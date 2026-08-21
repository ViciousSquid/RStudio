"""
Native play-session save / load for Fio.

Fio already knows how to *serialize a level* — :meth:`EditorState.get_level_data`
turns the live brush/thing scene (with every entity's current properties and
position) into a plain JSON-able dict, and :meth:`EditorState.load_from_data`
rebuilds it. That is the editor's document format, not a saved game: it captures
the map, but none of the *live* play-session state that only exists once you hit
Play — where the player is standing, how much health is left, which keys have
been picked up, which doors are open, which monsters are dead, and the active
cheat flags.

This module builds a *saved game* on top of that existing capability. A snapshot
is the serialized level (so entity health/dead/collected/hidden and positions
come along for free) plus a ``runtime`` block for the things the level format
never stores: the player transform and stats, the cheat flags, the collected-key
set, and the door / mover / monster animation state.

It is deliberately engine-native: no plugin, no bump to the plugin API
(:data:`plugins.api.API_VERSION` stays ``1.3.0``). :class:`~engine.logic_thread.LogicThread`
exposes :meth:`~engine.logic_thread.LogicThread.save_session` /
:meth:`~engine.logic_thread.LogicThread.load_session`, and the editor console
grows ``save`` / ``load`` / ``quicksave`` / ``quickload`` commands over them.

Snapshot shape::

    {
      "fio_savegame": true,
      "save_version": 1,
      "saved_at": "2026-08-21T18:44:00",
      "map": "Simple_Map_Test.json",
      "level": { ... EditorState.get_level_data() ... },
      "player": { pos, angle, pitch, velocity, camera_height,
                  physics_enabled, on_ground, in_water, swimming },
      "player2": { ... } | null,
      "runtime": {
        "god_mode", "buddha_mode", "notarget",
        "camera_mode", "overhead_height", "overhead_tilt", "overhead_orientation",
        "active_weapon", "current_hud_message",
        "player_health", "player_max_health", "player_dead",
        "player2_health", "player2_max_health", "player2_dead",
        "collected_keys": [ ... ],
        "door_states":   { "<index>": {"state", "progress"} },
        "mover_states":  { "<index>": {"progress", "forward"} },
        "monster_states": { "<entity id>": { ... } }
      }
    }

Restore is applied as an *overlay* onto a live, already-playing session, so it
never rebuilds the scene mid-flight (which would invalidate the logic thread's
caches, spatial grid and object identities). Entity live state is matched back
by the stable UUID every brush and thing carries.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

#: Bump only when the snapshot layout changes incompatibly. This is the *save
#: file* format version and is unrelated to the plugin API version.
SAVE_VERSION = 1

#: Marker key so a stray JSON file is never mistaken for a Fio save.
_MAGIC = "fio_savegame"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _vec3(v) -> list:
    """A glm.vec3 / sequence as a plain ``[x, y, z]`` list of floats."""
    try:
        return [float(v.x), float(v.y), float(v.z)]
    except AttributeError:
        return [float(v[0]), float(v[1]), float(v[2])]


def _set_vec3(target, value) -> None:
    """Write ``[x, y, z]`` back into a glm.vec3 (in place) or a list."""
    if value is None:
        return
    x, y, z = float(value[0]), float(value[1]), float(value[2])
    try:
        target.x, target.y, target.z = x, y, z
    except AttributeError:
        target[0], target[1], target[2] = x, y, z


#: Brush dict keys the overlay is allowed to write back onto a live brush.
#: Everything else (geometry, positions, direction vectors, flags) comes from the
#: freshly-loaded map and must keep its runtime type — overwriting it with the
#: JSON-degraded (list) form breaks typed math in the engine. Only genuinely
#: gameplay-mutable brush state belongs here; door/mover animation is restored
#: separately via door_states/mover_states.
_BRUSH_OVERLAY_KEYS = frozenset({"hidden", "tint"})


def _public_state(state: dict) -> dict:
    """A state dict without its cached, underscore-prefixed runtime fields.

    Animation state dicts stash caches the engine recomputes lazily — e.g. a
    mover's ``_direction_np`` (a NumPy array). Those must never round-trip
    through JSON: the array would come back a plain list and the engine would
    then try to multiply a list by a float. Persist only the real state; the
    caches rebuild on the next tick.
    """
    return {k: v for k, v in state.items() if not str(k).startswith("_")}


def _thing_id(thing) -> str:
    try:
        return thing.properties.get("id", "")
    except AttributeError:
        return ""


def _capture_player(player) -> Optional[dict]:
    if player is None:
        return None
    return {
        "pos": _vec3(player.pos),
        "angle": float(getattr(player, "angle", 0.0)),
        "pitch": float(getattr(player, "pitch", 0.0)),
        "velocity": _vec3(getattr(player, "velocity", (0.0, 0.0, 0.0))),
        "camera_height": float(getattr(player, "camera_height", 40.0)),
        "physics_enabled": bool(getattr(player, "physics_enabled", True)),
        "on_ground": bool(getattr(player, "on_ground", False)),
        "in_water": bool(getattr(player, "in_water", False)),
        "swimming": bool(getattr(player, "swimming", False)),
    }


def _apply_player(player, data: Optional[dict]) -> None:
    if player is None or not data:
        return
    _set_vec3(player.pos, data.get("pos"))
    _set_vec3(getattr(player, "velocity", None), data.get("velocity"))
    if "angle" in data:
        player.angle = float(data["angle"])
    if "pitch" in data:
        player.pitch = float(data["pitch"])
    if "camera_height" in data:
        player.camera_height = float(data["camera_height"])
    if "physics_enabled" in data:
        player.physics_enabled = bool(data["physics_enabled"])
    if "on_ground" in data:
        player.on_ground = bool(data["on_ground"])
    if "in_water" in data:
        player.in_water = bool(data["in_water"])
    if "swimming" in data:
        player.swimming = bool(data["swimming"])


# ---------------------------------------------------------------------------
# snapshot build / restore
# ---------------------------------------------------------------------------

def build_snapshot(logic, *, map_name: str = "") -> dict:
    """Capture the live play session on *logic* (a ``LogicThread``) as a dict.

    Call while a play session is active. The returned dict is JSON-serialisable
    and self-contained (it embeds the whole level), so it can be written to disk
    and loaded in a fresh session, or applied back in the same one.
    """
    level = {}
    try:
        level = logic.editor_state.get_level_data()
    except Exception:
        level = {}

    monster_states: Dict[str, Any] = {}
    try:
        raw = getattr(logic.monster_ai, "monster_states", {}) or {}
        by_obj_id = {id(t): t for t in getattr(logic, "_monster_things", [])}
        for obj_id, state in raw.items():
            mon = by_obj_id.get(obj_id)
            sid = _thing_id(mon) if mon is not None else ""
            if sid:
                # investigating_sound holds a transient (pos, expiry) tuple tied
                # to wall-clock time; drop it rather than persist a stale timer.
                # _public_state also strips any cached _-prefixed runtime fields.
                clean = _public_state(state)
                clean.pop("investigating_sound", None)
                monster_states[sid] = clean
    except Exception:
        monster_states = {}

    runtime = {
        "god_mode": bool(getattr(logic, "god_mode", False)),
        "buddha_mode": bool(getattr(logic, "buddha_mode", False)),
        "notarget": bool(getattr(logic, "notarget", False)),
        "camera_mode": getattr(logic, "camera_mode", "First Person"),
        "overhead_height": float(getattr(logic, "overhead_height", 800.0)),
        "overhead_tilt": float(getattr(logic, "overhead_tilt", 0.0)),
        "overhead_orientation": getattr(logic, "overhead_orientation", "north"),
        "active_weapon": getattr(logic, "active_weapon", None),
        "current_hud_message": getattr(logic, "current_hud_message", ""),
        "player_health": getattr(logic, "player_health", 100),
        "player_max_health": getattr(logic, "player_max_health", 100),
        "player_dead": bool(getattr(logic, "player_dead", False)),
        "player2_health": getattr(logic, "player2_health", 100),
        "player2_max_health": getattr(logic, "player2_max_health", 100),
        "player2_dead": bool(getattr(logic, "player2_dead", False)),
        "collected_keys": sorted(str(k) for k in getattr(logic, "collected_keys", set())),
        "door_states": {str(i): _public_state(s) for i, s in getattr(logic, "door_states", {}).items()},
        "mover_states": {str(i): _public_state(s) for i, s in getattr(logic, "mover_states", {}).items()},
        "monster_states": monster_states,
    }

    return {
        _MAGIC: True,
        "save_version": SAVE_VERSION,
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "map": map_name or "",
        "level": level,
        "player": _capture_player(getattr(logic, "player", None)),
        "player2": _capture_player(getattr(logic, "player2", None)),
        "runtime": runtime,
    }


def _overlay_entities(logic, level: dict) -> None:
    """Restore live entity state (position + properties) from a saved level.

    Matches by stable UUID so it survives a full scene reload; entities present
    in the save but not the live scene (or vice-versa) are skipped quietly.
    """
    if not level:
        return

    # -- things: restore pos + mutable properties by id --------------------
    live_things = {}
    for t in getattr(logic, "things", []) or []:
        tid = _thing_id(t)
        if tid:
            live_things[tid] = t
    for t_data in level.get("things", []):
        props = t_data.get("properties", {}) or {}
        tid = props.get("id", "")
        live = live_things.get(tid)
        if live is None:
            continue
        try:
            if "pos" in t_data and t_data["pos"] is not None:
                live.pos = list(t_data["pos"])
            for k, v in props.items():
                if k == "_io_connections":
                    continue
                live.properties[k] = v
        except Exception:
            continue

    # -- brushes: restore only genuinely gameplay-mutable state by id ------
    # Static geometry (pos/size/direction/…) comes from the freshly-loaded map
    # and must keep its runtime type; door/mover animation is restored via the
    # door_states/mover_states dicts, not from the brush record.
    live_brushes = {b.get("id"): b for b in (getattr(logic, "brushes", []) or []) if b.get("id")}
    for b_data in level.get("brushes", []):
        live = live_brushes.get(b_data.get("id"))
        if live is None:
            continue
        for k in _BRUSH_OVERLAY_KEYS:
            if k in b_data:
                live[k] = b_data[k]
            else:
                live.pop(k, None)


def restore_snapshot(logic, data: dict) -> None:
    """Apply a snapshot from :func:`build_snapshot` onto a live play session.

    *logic* must be an active (play-mode) ``LogicThread`` whose loaded map
    matches the save. Restore is an overlay — the scene is not rebuilt — so
    object identities, caches and the spatial grid stay valid.
    """
    if not isinstance(data, dict) or not data.get(_MAGIC):
        raise ValueError("not a Fio save file")

    runtime = data.get("runtime", {}) or {}

    # Live entity state first, so anything derived from it below is consistent.
    _overlay_entities(logic, data.get("level", {}) or {})

    # Player(s)
    _apply_player(getattr(logic, "player", None), data.get("player"))
    _apply_player(getattr(logic, "player2", None), data.get("player2"))

    # Player stats / cheat flags
    for attr in (
        "god_mode", "buddha_mode", "notarget",
        "camera_mode", "overhead_height", "overhead_tilt", "overhead_orientation",
        "active_weapon", "current_hud_message",
        "player_health", "player_max_health", "player_dead",
        "player2_health", "player2_max_health", "player2_dead",
    ):
        if attr in runtime:
            setattr(logic, attr, runtime[attr])

    # Collected keys — rebuild the set from the saved list.
    try:
        logic.collected_keys = set(runtime.get("collected_keys", []) or [])
    except Exception:
        pass

    # Collected-pickup set is keyed by id(thing) and can't be persisted across a
    # reload; rebuild it from the entity 'collected' flags we just overlaid.
    try:
        collected = set()
        for t in getattr(logic, "things", []) or []:
            if t.properties.get("collected"):
                collected.add(id(t))
        logic.collected_pickups = collected
    except Exception:
        pass

    # Door / mover animation state (keys serialize as strings → back to int).
    # _public_state drops any cached _-prefixed fields (e.g. a mover's
    # _direction_np NumPy cache) that an older save may still carry, so the
    # engine rebuilds them with the right type on the next tick.
    try:
        logic.door_states = {int(i): _public_state(s) for i, s in runtime.get("door_states", {}).items()}
    except Exception:
        pass
    try:
        logic.mover_states = {int(i): _public_state(s) for i, s in runtime.get("mover_states", {}).items()}
    except Exception:
        pass

    # Monster combat state, remapped from stable id back to the live object id.
    try:
        saved_ms = runtime.get("monster_states", {}) or {}
        if saved_ms and getattr(logic, "monster_ai", None) is not None:
            by_sid = {}
            for t in getattr(logic, "_monster_things", []) or []:
                sid = _thing_id(t)
                if sid:
                    by_sid[sid] = t
            remapped = {}
            for sid, state in saved_ms.items():
                mon = by_sid.get(sid)
                if mon is not None:
                    remapped[id(mon)] = _public_state(state)
            logic.monster_ai.monster_states = remapped
    except Exception:
        pass

    # Rebuild the I/O entity lookup caches, since we mutated properties, and
    # refresh the monster sprite cache so dead/alive billboards match the
    # restored health immediately.
    try:
        logic._build_entity_caches()
    except Exception:
        pass
    try:
        from editor.things import Monster
        Monster.clear_sprite_cache()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# file IO
# ---------------------------------------------------------------------------

def _json_default(o):
    """Coerce values the stock JSON encoder rejects into plain JSON.

    The embedded level can carry runtime-typed values that aren't JSON-native —
    NumPy arrays/scalars written by the geometry and terrain layers, glm vectors,
    Python sets. Rather than hunt down every field, this makes the whole snapshot
    safe: arrays/vectors become lists, NumPy scalars become Python numbers, sets
    become lists, and anything else falls back to its string form.
    """
    # NumPy arrays and scalars both expose tolist() (scalars → a Python scalar).
    tolist = getattr(o, "tolist", None)
    if callable(tolist):
        try:
            return tolist()
        except Exception:
            pass
    if isinstance(o, (set, frozenset)):
        return list(o)
    # glm vectors and other iterable sequence-likes.
    try:
        return list(o)
    except TypeError:
        return str(o)


def write(path: str, snapshot: dict) -> None:
    """Write *snapshot* to *path* as JSON (creating parent dirs as needed)."""
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, default=_json_default)


def read(path: str) -> dict:
    """Read and validate a Fio save file at *path*; returns the snapshot dict."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict) or not data.get(_MAGIC):
        raise ValueError(f"'{path}' is not a Fio save file")
    ver = data.get("save_version", 0)
    if ver > SAVE_VERSION:
        raise ValueError(
            f"save '{path}' is version {ver}, newer than this build supports "
            f"(v{SAVE_VERSION})"
        )
    return data
