"""
Persistence helpers for Big World.

Big World adds almost nothing new to persist, and by design:

* **UUIDs** are already Fio's stable identity for brushes (``brush['id']``) and
  entities (``thing.properties['id']``). Big World *reads* them and never writes
  them, so an object keeps the same UUID across load → activate → deactivate →
  save → reload → stream. Streaming is a runtime state change, not an identity
  change.
* **Cell assignment** is derived purely from an object's position and the shared
  512-unit grid. It is therefore recomputed on load and never needs to be stored
  — a brush cannot get "lost" from its cell because its cell *is* its position.
* **Everything else** (names, transforms, properties, custom key/values, I/O)
  is the object's own data, saved by Fio's existing serializer unchanged.

The only genuinely new datum is the map's Big World *config* (whether streaming
is on and the two radii). That travels as an ordinary :class:`BigWorldSettings`
entity, so it round-trips through Fio's normal save/load with no core change —
see :mod:`plugins.bigworld.entities`.

This module provides small, pure functions for reading that config out of a
loaded map dict (or a live ``things`` list), plus verification helpers the tests
and tools use to *prove* UUID stability across a streaming round-trip. Nothing
here imports the editor or engine, so it runs headless.
"""

from __future__ import annotations

from typing import Dict, List, Optional

_SETTINGS_TYPE = "bigworldsettings"

#: The runtime marker keys the session writes onto objects while they are parked.
#: They must never be persisted — they are transient streaming state, not map
#: data. :func:`strip_runtime_keys` removes them before a save.
RUNTIME_KEYS = ("_bw_parked_hidden", "_bw_parked_disabled", "bw_active")


def _normalise_type(type_name) -> str:
    return str(type_name or "").replace("_", "").lower()


# ---------------------------------------------------------------------------
# Config extraction
# ---------------------------------------------------------------------------

def find_settings_dict(map_data: dict) -> Optional[dict]:
    """Return the ``BigWorldSettings`` entity dict in a loaded map, or None.

    Absent ⇒ no Big World metadata ⇒ the caller should behave as ordinary Fio
    (the §20 backwards-compatibility contract).
    """
    if not isinstance(map_data, dict):
        return None
    for t in map_data.get("things", []) or ():
        if not isinstance(t, dict):
            continue
        typ = t.get("type") or (t.get("properties", {}) or {}).get("type")
        if _normalise_type(typ) == _SETTINGS_TYPE:
            return t
    return None


def find_settings_thing(things) -> Optional[object]:
    """Return the live ``BigWorldSettings`` entity in a ``things`` list, or None."""
    for t in things or ():
        props = getattr(t, "properties", None)
        if isinstance(props, dict) and _normalise_type(props.get("type")) == _SETTINGS_TYPE:
            return t
    return None


def config_from_settings(settings) -> Dict:
    """Normalise a settings entity/dict into a plain config dict.

    Accepts either a live :class:`BigWorldSettings` (or any object with a
    ``properties`` dict) or a raw map-thing dict. Returns defaults for anything
    missing so a hand-edited or partial map never raises.
    """
    if settings is None:
        props = {}
    elif isinstance(settings, dict):
        props = settings.get("properties", settings) or {}
    else:
        props = getattr(settings, "properties", {}) or {}

    def _f(key, default):
        try:
            return float(props.get(key, default))
        except (TypeError, ValueError):
            return default

    def _b(key, default):
        val = props.get(key, default)
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes", "on")

    act = _f("activation_radius", 2048.0)
    deact = max(_f("deactivation_radius", 2304.0), act)
    return {
        "enabled": _b("enabled", True),
        "activation_radius": act,
        "deactivation_radius": deact,
        "show_cell_debug": _b("show_cell_debug", True),
        "terrain_fill": _b("terrain_fill", False),
        "terrain_infinite": _b("terrain_infinite", False),
        "terrain_stream_radius": _f("terrain_stream_radius", 0.0),
    }


def map_has_bigworld(map_data: dict) -> bool:
    """True if the map carries Big World metadata (a settings entity)."""
    return find_settings_dict(map_data) is not None


# ---------------------------------------------------------------------------
# Save hygiene + UUID-stability verification
# ---------------------------------------------------------------------------

def strip_runtime_keys(map_data: dict) -> dict:
    """Remove transient Big World runtime markers from a map dict before saving.

    Streaming state (a parked brush's remembered ``hidden`` value, the live
    ``bw_active`` flag) must not leak into the saved file. Cell assignment and
    UUIDs are untouched — they are legitimate map data / derived state. Mutates
    and returns *map_data*.
    """
    for brush in map_data.get("brushes", []) or ():
        if isinstance(brush, dict):
            for k in RUNTIME_KEYS:
                brush.pop(k, None)
    for t in map_data.get("things", []) or ():
        if isinstance(t, dict):
            props = t.get("properties")
            if isinstance(props, dict):
                for k in RUNTIME_KEYS:
                    props.pop(k, None)
    return map_data


def collect_uuids(brushes, things) -> Dict[str, set]:
    """Gather the UUID sets of a world, for before/after stability checks."""
    b = {str(br.get("id", "")) for br in (brushes or ()) if isinstance(br, dict)}
    t = set()
    for th in things or ():
        props = getattr(th, "properties", None)
        if isinstance(props, dict):
            t.add(str(props.get("id", "")))
    b.discard("")
    t.discard("")
    return {"brushes": b, "things": t}


def uuids_stable(before: Dict[str, set], after: Dict[str, set]) -> bool:
    """True if every UUID present before is still present after (none regenerated)."""
    return (before["brushes"] == after["brushes"]
            and before["things"] == after["things"])
