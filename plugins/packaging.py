"""
Making ``.fiopak`` packages plugin-aware.

A ``.fiopak`` is a zip of maps + referenced assets. When a map uses entities
that come from a plugin, the package must also carry that plugin's code and
assets, or it won't load anywhere but the machine that built it. This module
provides :func:`augment_fiopak`, which the exporter calls after writing the
base package: it inspects the bundled maps, works out which plugins they need,
and injects those plugins (plus the plugin-system core) into the archive,
recording them in ``metadata.json`` under ``"plugins"``.

Archive layout after augmentation (only the plugin bits shown)::

    metadata.json            # gains  "plugins": ["tidy", ...]
    plugins/__init__.py      # plugin-system core, so the package is loadable
    plugins/api.py
    plugins/manager.py
    plugins/integration.py
    plugins/packaging.py
    plugins/tidy/…           # each required plugin, verbatim (code + assets)

Because plugin assets keep their original repo-relative paths
(``plugins/tidy/assets/book.obj``, ``.../covers/cover_03.png``), a map's
``model_path`` / ``texture`` referencing them resolves straight out of the
package with no rewriting.

:func:`load_package_plugins` is the counterpart for a consumer (a player or an
editor opening a foreign package): point it at an extracted package root and it
loads the bundled plugins.
"""

from __future__ import annotations

import json
import os
import zipfile
from typing import Dict, Iterable, List, Optional, Set


# Top-level plugin-system core files that must travel with any bundled plugin
# so the package can load itself. (Per-plugin packages are added separately.)
_CORE_FILES = ("__init__.py", "api.py", "manager.py", "integration.py",
               "packaging.py")

_SKIP_DIRS = {"__pycache__", ".git"}
_SKIP_SUFFIXES = (".pyc", ".pyo")


def _plugins_core_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def _repo_root() -> str:
    # plugins/ lives directly under the project root.
    return os.path.dirname(_plugins_core_dir())


def collect_entity_types(map_data: dict) -> Set[str]:
    """All entity ``type`` strings used by a map dict."""
    types: Set[str] = set()
    for thing in map_data.get("things", []):
        if isinstance(thing, dict):
            t = thing.get("type") or thing.get("properties", {}).get("type")
            if t:
                types.add(str(t))
    return types


def _iter_package_files(pkg_dir: str) -> Iterable[str]:
    """Yield absolute paths of files under *pkg_dir*, skipping caches/tests junk."""
    for root, dirs, files in os.walk(pkg_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name.endswith(_SKIP_SUFFIXES):
                continue
            yield os.path.join(root, name)


def _archive_name(abs_path: str) -> str:
    return os.path.relpath(abs_path, _repo_root()).replace("\\", "/")


def required_plugin_files(type_names: Iterable[str]) -> Dict[str, str]:
    """Map archive-path -> source-path for every file needed by *type_names*.

    Returns ``{}`` when the maps use no plugin entities. Includes the plugin
    core files only when at least one plugin is actually required.
    """
    try:
        from plugins.manager import get_manager
    except Exception:
        return {}

    mgr = get_manager()
    plugins = mgr.required_plugins_for_types(type_names)
    if not plugins:
        return {}

    files: Dict[str, str] = {}

    # Plugin-system core.
    core = _plugins_core_dir()
    for name in _CORE_FILES:
        src = os.path.join(core, name)
        if os.path.isfile(src):
            files[_archive_name(src)] = src

    # Each required plugin package, verbatim.
    for plugin in plugins:
        pkg_dir = mgr.plugin_package_dir(plugin)
        if not pkg_dir or not os.path.isdir(pkg_dir):
            continue
        for src in _iter_package_files(pkg_dir):
            files[_archive_name(src)] = src

    return files


def augment_fiopak(pak_path: str, log=None) -> dict:
    """Inject the plugins a package's maps depend on into an existing ``.fiopak``.

    Reads the archive at *pak_path*, works out required plugins from the bundled
    maps, and rewrites the archive with the plugin code/assets added and
    ``metadata.json`` updated. A no-op (leaving the file untouched) when the maps
    use no plugin entities.

    Returns a summary dict: ``{"plugins": [names], "added_paths": {archive…}}``.
    """
    def _say(msg):
        if log:
            log(msg)

    with zipfile.ZipFile(pak_path, "r") as zin:
        names = list(zin.namelist())
        entries: Dict[str, bytes] = {n: zin.read(n) for n in names}

    # Collect entity types from all bundled maps.
    types: Set[str] = set()
    for name, raw in entries.items():
        if name.startswith("maps/") and name.endswith(".json"):
            try:
                types |= collect_entity_types(json.loads(raw.decode("utf-8")))
            except Exception:
                continue

    plugin_files = required_plugin_files(types)
    if not plugin_files:
        return {"plugins": [], "added_paths": set()}

    # Resolve the human-readable plugin names for the manifest.
    try:
        from plugins.manager import get_manager
        mgr = get_manager()
        plugin_names = [mgr.plugin_package_name(p)
                        for p in mgr.required_plugins_for_types(types)]
    except Exception:
        plugin_names = []

    # Update metadata.
    meta: dict = {}
    if "metadata.json" in entries:
        try:
            meta = json.loads(entries["metadata.json"].decode("utf-8"))
        except Exception:
            meta = {}
    meta["plugins"] = plugin_names
    meta["requires_plugins"] = bool(plugin_names)
    entries["metadata.json"] = json.dumps(meta, indent=2).encode("utf-8")

    # Add plugin files (dict de-dups against anything already present).
    added_paths: Set[str] = set()
    for arc, src in plugin_files.items():
        if arc in entries:
            continue
        try:
            with open(src, "rb") as f:
                entries[arc] = f.read()
            added_paths.add(arc)
        except Exception as exc:
            _say(f"[Plugins] could not bundle {arc}: {exc}")

    # Rewrite the archive.
    with zipfile.ZipFile(pak_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data in entries.items():
            zout.writestr(name, data)

    _say(f"[Plugins] packaged {len(added_paths)} plugin file(s): "
         f"{', '.join(plugin_names) or '(none)'}")
    return {"plugins": plugin_names, "added_paths": added_paths}


def load_package_plugins(package_root: str, log=None) -> List[str]:
    """Load plugins bundled inside an extracted package at *package_root*.

    Adds *package_root* to ``sys.path`` (so the bundled ``plugins`` package is
    importable) and runs discovery. Intended for a player/editor opening a
    package built elsewhere. Returns the names of plugins now loaded.

    Note: this makes the plugins' entity types and I/O available. Executing a
    plugin's *gameplay* additionally requires the host to dispatch the play
    lifecycle (as the editor's play mode does via ``plugins.integration``).
    """
    import sys

    def _say(msg):
        if log:
            log(msg)

    plugins_dir = os.path.join(package_root, "plugins")
    if not os.path.isdir(plugins_dir):
        return []

    if package_root not in sys.path:
        sys.path.insert(0, package_root)

    try:
        from plugins.manager import get_manager, load_plugins
        load_plugins()
        mgr = get_manager()
        names = [p.name for p in mgr.plugins]
        _say(f"[Plugins] loaded from package: {', '.join(names) or '(none)'}")
        return names
    except Exception as exc:
        _say(f"[Plugins] failed to load package plugins: {exc}")
        return []


def package_plugin_names(pak_path: str) -> List[str]:
    """Read the ``plugins`` list declared in a package's ``metadata.json``."""
    try:
        with zipfile.ZipFile(pak_path, "r") as zf:
            for name in ("metadata.json", "manifest.json"):
                if name in zf.namelist():
                    meta = json.loads(zf.read(name).decode("utf-8"))
                    return list(meta.get("plugins", []) or [])
    except Exception:
        pass
    return []
