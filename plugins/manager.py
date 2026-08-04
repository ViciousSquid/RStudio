"""
Plugin discovery, loading and hook dispatch.

The :class:`PluginManager` is a process-wide singleton. It:

  1. **Discovers** plugins by scanning this package's directory for
     sub-packages that expose a ``PLUGIN`` instance or ``get_plugin()``
     factory.
  2. **Loads** each plugin once, calling ``register(EditorAPI)``. This is
     idempotent — :func:`load_plugins` may be called from several entry points
     (editor window, logic thread, headless tools) and only acts the first
     time.
  3. **Attaches** to each play session's logic thread via
     :meth:`attach_runtime`, calling ``register_runtime(RuntimeAPI)``.
  4. **Dispatches** the ``on_play_start`` / ``on_tick`` / ``on_play_stop``
     lifecycle hooks.

Every call into plugin code is wrapped so a misbehaving plugin logs an error
instead of taking down the editor or a play session.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import traceback
from typing import List, Optional, Tuple

from .api import EditorAPI, FioPlugin, RuntimeAPI, TickContext


def _log(message: str):
    """Route through the editor debug console when present, else print."""
    try:
        from editor.debug_console import debug_log
        debug_log("Plugins", message)
    except Exception:
        print(f"[Plugins] {message}")


class PluginManager:
    def __init__(self):
        self.plugins: List[FioPlugin] = []
        self._loaded = False
        self._loading = False
        # (plugin, label, ThingClass) placement entries for the editor menu.
        self._menu_entries: List[Tuple[FioPlugin, str, type]] = []
        # Disabled plugin names (by directory or plugin.name). Populated from
        # the FIO_DISABLED_PLUGINS env var, comma-separated.
        self._disabled = {
            n.strip().lower()
            for n in os.environ.get("FIO_DISABLED_PLUGINS", "").split(",")
            if n.strip()
        }

    # -- logging ------------------------------------------------------------
    def _log(self, message: str):
        _log(message)

    # -- discovery + load ---------------------------------------------------
    def discover_and_load(self):
        """Find and load all plugins. Safe to call repeatedly."""
        if self._loaded or self._loading:
            return
        self._loading = True

        package_dir = os.path.dirname(os.path.abspath(__file__))
        found = 0
        for entry in sorted(pkgutil.iter_modules([package_dir])):
            mod_name = entry.name
            if not entry.ispkg:
                continue
            if mod_name.startswith("_"):
                continue
            if mod_name.lower() in self._disabled:
                self._log(f"Skipping disabled plugin package '{mod_name}'")
                continue
            self._load_one(mod_name)
            found += 1

        self._loaded = True
        self._loading = False

        if self.plugins:
            names = ", ".join(f"{p.name} v{p.version}" for p in self.plugins)
            self._log(f"Loaded {len(self.plugins)} plugin(s): {names}")
        elif found == 0:
            self._log("No plugins found.")

    def _load_one(self, mod_name: str):
        try:
            module = importlib.import_module(f"plugins.{mod_name}")
        except Exception:
            self._log(f"Failed to import plugin '{mod_name}':\n{traceback.format_exc()}")
            return

        plugin = getattr(module, "PLUGIN", None)
        if plugin is None:
            factory = getattr(module, "get_plugin", None)
            if callable(factory):
                try:
                    plugin = factory()
                except Exception:
                    self._log(f"get_plugin() failed for '{mod_name}':\n{traceback.format_exc()}")
                    return

        if plugin is None:
            self._log(f"Plugin package '{mod_name}' exposes no PLUGIN or get_plugin(); skipping.")
            return
        if not isinstance(plugin, FioPlugin):
            self._log(f"Plugin '{mod_name}' PLUGIN is not a FioPlugin; skipping.")
            return
        if plugin.name.lower() in self._disabled:
            self._log(f"Skipping disabled plugin '{plugin.name}'")
            return

        try:
            plugin.register(EditorAPI(self, plugin))
        except Exception:
            self._log(f"register() failed for '{plugin.name}':\n{traceback.format_exc()}")
            return

        # Pick up any bespoke menu entries the plugin declares directly.
        try:
            for label, cls in (plugin.menu_entries() or []):
                self._add_menu_entry(plugin, label, cls)
        except Exception:
            self._log(f"menu_entries() failed for '{plugin.name}':\n{traceback.format_exc()}")

        self.plugins.append(plugin)

    # -- editor menu --------------------------------------------------------
    def _add_menu_entry(self, plugin: FioPlugin, label: str, cls: type):
        self._menu_entries.append((plugin, label, cls))

    def menu_entries(self) -> List[Tuple[FioPlugin, str, type]]:
        """All placement entries as ``(plugin, label, ThingClass)`` tuples."""
        return list(self._menu_entries)

    def has_plugins(self) -> bool:
        return bool(self.plugins)

    # -- runtime attach -----------------------------------------------------
    def attach_runtime(self, logic):
        """Let every plugin register I/O handlers for this logic thread."""
        for plugin in self.plugins:
            try:
                plugin.register_runtime(RuntimeAPI(self, logic, plugin))
            except Exception:
                self._log(f"register_runtime() failed for '{plugin.name}':\n{traceback.format_exc()}")

    # -- lifecycle dispatch -------------------------------------------------
    def dispatch_play_start(self, logic):
        for plugin in self.plugins:
            try:
                plugin.on_play_start(logic)
            except Exception:
                self._log(f"on_play_start() failed for '{plugin.name}':\n{traceback.format_exc()}")

    def dispatch_play_stop(self, logic):
        for plugin in self.plugins:
            try:
                plugin.on_play_stop(logic)
            except Exception:
                self._log(f"on_play_stop() failed for '{plugin.name}':\n{traceback.format_exc()}")

    def dispatch_tick(self, logic, ctx: TickContext):
        for plugin in self.plugins:
            try:
                plugin.on_tick(logic, ctx)
            except Exception:
                self._log(f"on_tick() failed for '{plugin.name}':\n{traceback.format_exc()}")


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------

_MANAGER: Optional[PluginManager] = None


def get_manager() -> PluginManager:
    """Return the process-wide :class:`PluginManager`, creating it on first use."""
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = PluginManager()
    return _MANAGER


def load_plugins():
    """Discover and load all plugins (idempotent). Call this early at startup."""
    get_manager().discover_and_load()
