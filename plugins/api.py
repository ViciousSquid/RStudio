"""
Public API surface for Fio plugins.

Everything a plugin author needs is here: the :class:`FioPlugin` base class to
subclass, and the two "API" objects the manager hands to a plugin at the right
moments (:class:`EditorAPI` at load time, :class:`RuntimeAPI` when a play
session's logic thread spins up).

Design goals
------------
* **Loose coupling.** The core editor/engine call *into* the manager; plugins
  never import editor internals except through helpers exposed here. The
  editor/engine modules are imported lazily inside methods so that importing
  this module never drags in PyQt or OpenGL (it is imported in headless tools
  and tests too).
* **Fail safe.** A plugin that raises during registration or a hook must never
  crash the host. The manager wraps every call; this module keeps the surface
  small and defensive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple, Type


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def io_def(name: str, description: str = "", param_type: str = ""):
    """Build an :class:`editor.io_system.IODef`.

    Provided as a convenience so plugins can describe inputs/outputs with plain
    tuples/args and not import ``io_system`` themselves. Returns ``None`` if the
    I/O system is unavailable (headless contexts), which the manager tolerates.
    """
    try:
        from editor.io_system import IODef
    except Exception:
        return None
    return IODef(name, description, param_type)


# ---------------------------------------------------------------------------
# Editor-time API (passed to FioPlugin.register)
# ---------------------------------------------------------------------------

class EditorAPI:
    """Handed to :meth:`FioPlugin.register` exactly once when the plugin loads.

    This phase runs in *both* the editor process and any process that imports
    the engine, so it must be UI-free. Use it to declare entity types, their
    I/O, and editor palette entries.
    """

    def __init__(self, manager, plugin: "FioPlugin"):
        self._manager = manager
        self._plugin = plugin

    # -- entity registration ------------------------------------------------
    def register_entity(
        self,
        cls: type,
        category: Optional[str] = None,
        menu_label: Optional[str] = None,
        placeable: bool = True,
    ) -> type:
        """Register a ``Thing`` subclass as a placeable editor entity.

        * Adds ``cls`` to ``editor.things.ENTITY_TYPES`` (keyed by class name),
          so the property editor, spawner and serializer can find it.
        * Adds it to ``ENTITY_CATEGORIES`` under *category* (default: the
          plugin's :attr:`~FioPlugin.category`).
        * If *placeable*, records a right-click menu entry the editor's 2D view
          exposes under a "Plugins ▸ <plugin>" submenu.

        Returns *cls* unchanged so it can be used as a decorator.
        """
        cat = category or self._plugin.category
        label = menu_label or cls.__name__

        # Record ownership first — this has no dependencies and must work even
        # in the PyQt-free player (where the editor palette below is skipped),
        # so the package exporter and the player host can map map entity 'type'
        # strings back to the owning plugin and its class.
        self._manager._record_entity_owner(cls, self._plugin)

        # Editor palette registration (needs editor.things → PyQt). Absent in
        # the standalone player; skip quietly there.
        try:
            from editor.things import ENTITY_TYPES, ENTITY_CATEGORIES
            ENTITY_TYPES[cls.__name__] = cls
            ENTITY_CATEGORIES.setdefault(cat, [])
            if cls.__name__ not in ENTITY_CATEGORIES[cat]:
                ENTITY_CATEGORIES[cat].append(cls.__name__)
        except Exception:
            pass

        if placeable:
            self._manager._add_menu_entry(self._plugin, label, cls)
        return cls

    # -- I/O registration ---------------------------------------------------
    def register_io(self, entity_type: str, inputs: List[Any], outputs: List[Any]):
        """Register input/output definitions for *entity_type*.

        *entity_type* must equal the entity's ``properties['type']`` string.
        *inputs*/*outputs* are lists of :func:`io_def` results (``IODef``);
        ``None`` entries (produced when I/O is unavailable) are filtered out.
        """
        try:
            from editor.io_system import register_io
        except Exception:
            return
        register_io(
            entity_type,
            [d for d in inputs if d is not None],
            [d for d in outputs if d is not None],
        )

    def log(self, message: str):
        # Informational by default (silent unless FIO_PLUGIN_DEBUG); plugins
        # should not spam the console on a normal launch.
        self._manager._debug(f"[{self._plugin.name}] {message}")


# ---------------------------------------------------------------------------
# Runtime API (passed to FioPlugin.register_runtime)
# ---------------------------------------------------------------------------

class RuntimeAPI:
    """Handed to :meth:`FioPlugin.register_runtime` when a logic thread starts.

    Use it to register I/O *input handlers* (the functions that actually run
    when another entity fires an output at yours) against the play session's
    ``IOManager``.
    """

    def __init__(self, manager, logic, plugin: "FioPlugin"):
        self._manager = manager
        self._plugin = plugin
        self.logic = logic
        self.io_manager = getattr(logic, "io_manager", None)

    def register_input_handler(self, entity_type: str, input_name: str, handler: Callable):
        """Register ``handler(entity, parameter, logic)`` for an entity input.

        The handler is registered once, when the logic thread attaches, but is
        gated by the plugin's *live* ``enabled`` state: it runs only while the
        plugin is on. That lets the manager attach every loaded plugin up front
        (so a plugin enabled later — e.g. a disabled-by-default one auto-enabled
        when its level loads — has working inputs immediately) while a disabled
        plugin's inputs stay inert without needing to re-attach.
        """
        if self.io_manager is None:
            return
        plugin = self._plugin

        def gated(entity, parameter, logic):
            if getattr(plugin, "enabled", True):
                return handler(entity, parameter, logic)

        self.io_manager.register_input_handler(entity_type, input_name, gated)

    def fire_output(self, entity, output_name: str, value: Optional[str] = None):
        """Fire an output from *entity* through the I/O system (if available)."""
        if self.io_manager is not None:
            self.io_manager.fire_output(entity, output_name, value)

    def log(self, message: str):
        self._manager._debug(f"[{self._plugin.name}] {message}")


# ---------------------------------------------------------------------------
# Per-tick context
# ---------------------------------------------------------------------------

@dataclass
class TickContext:
    """State passed to :meth:`FioPlugin.on_tick`, once per play-mode tick.

    ``use_pressed`` is the edge-triggered "use/interact" key for this tick
    (already consumed by the logic thread), so a plugin can treat a ``True``
    value as a single press. ``keys`` is the raw held-key set.
    """
    delta: float = 0.0
    use_pressed: bool = False
    keys: Any = field(default_factory=set)
    # True if the core interaction code already set a HUD prompt / consumed the
    # use press this tick (door, pickup, level-changer). Plugins should avoid
    # clobbering it unless they own a target under the crosshair.
    interaction_consumed: bool = False


# ---------------------------------------------------------------------------
# Plugin base class
# ---------------------------------------------------------------------------

class FioPlugin:
    """Base class for all Fio plugins.

    Subclass this, set the metadata attributes, and override the lifecycle
    methods you need. Expose an instance as the module-level ``PLUGIN`` of your
    package's ``__init__`` (or a ``get_plugin()`` factory) so the manager can
    find it.
    """

    #: Short unique identifier (used in logs and the menu).
    name: str = "unnamed"
    #: Human-readable version string.
    version: str = "0.0.0"
    #: One-line description shown in tooling.
    description: str = ""
    #: Default editor category / menu grouping for this plugin's entities.
    category: str = "Plugins"
    #: Whether the plugin is active. Toggled from the editor's Plugins menu;
    #: the manager skips a disabled plugin's runtime attach and lifecycle/tick
    #: dispatch, so it becomes inert without being unloaded. A plugin may set
    #: this to ``False`` to ship disabled-by-default; the manager then
    #: auto-enables it when a level referencing its entities is loaded (see
    #: :meth:`PluginManager.auto_enable_for_map`).
    enabled: bool = True

    # -- load-time (editor + engine) ---------------------------------------
    def register(self, api: EditorAPI) -> None:
        """Register entities, I/O definitions and palette entries.

        Runs once, UI-free, in every process that loads plugins. Do not touch
        Qt/OpenGL here.
        """

    # -- runtime attach (per logic thread) ---------------------------------
    def register_runtime(self, api: RuntimeAPI) -> None:
        """Register I/O input handlers against a play session's IOManager."""

    # -- play lifecycle -----------------------------------------------------
    def on_play_start(self, logic) -> None:
        """Called when the user enters play mode. Initialise per-session state."""

    def on_play_stop(self, logic) -> None:
        """Called when leaving play mode. Restore any edited entity state."""

    def on_tick(self, logic, ctx: TickContext) -> None:
        """Called every play-mode tick after core gameplay handling."""

    # -- optional editor menu customisation --------------------------------
    def menu_entries(self) -> List[Tuple[str, type]]:
        """Extra ``(label, ThingClass)`` placement entries.

        Most plugins rely on :meth:`EditorAPI.register_entity` instead; override
        only for bespoke menu layouts. Returning an empty list is fine.
        """
        return []

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<FioPlugin {self.name} v{self.version}>"
