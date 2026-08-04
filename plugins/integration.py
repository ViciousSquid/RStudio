"""
Core integration shim for the Fio plugin system.

This module wires the plugin manager into the editor and engine **without
editing the large core source files**. It applies a handful of small, guarded
monkey-patches so the plugin system is effectively drop-in: adding the
``plugins/`` package plus a one-line hook in ``editor/__init__.py`` is all the
core needs.

``apply()`` is idempotent and defensive: any patch that cannot be installed
(e.g. a module that fails to import in a headless/tool context) is skipped with
a log line rather than breaking startup. It patches:

* ``engine.logic_thread.LogicThread``
    - ``__init__``            → attach plugin runtime I/O handlers
    - ``set_play_mode``       → dispatch on_play_start / on_play_stop
    - ``_handle_triggers``    → dispatch on_tick (runs last in the gameplay
                                sequence and carries the use-key edge)
* ``editor.view_2d.View2D``
    - ``contextMenuEvent``    → add a "Plugins ▸ <plugin>" placement submenu,
                                reusing the original menu handler unchanged

The equivalent hand-edits (for reference / an alternative to this shim) would
be three small insertions in those files; see ``plugins/README.md``.
"""

from __future__ import annotations

_applied = False


def _log(message: str):
    try:
        from editor.debug_console import debug_log
        debug_log("Plugins", message)
    except Exception:
        print(f"[Plugins] {message}")


def apply():
    """Install all plugin integration patches. Safe to call more than once."""
    global _applied
    if _applied:
        return
    _applied = True
    _patch_logic_thread()
    _patch_view_2d()


# ---------------------------------------------------------------------------
# engine.logic_thread.LogicThread
# ---------------------------------------------------------------------------

def _patch_logic_thread():
    try:
        from engine.logic_thread import LogicThread
    except Exception as exc:
        _log(f"logic-thread patch skipped ({exc})")
        return

    from plugins.manager import get_manager, load_plugins

    if getattr(LogicThread, "_fio_plugins_patched", False):
        return

    _orig_init = LogicThread.__init__
    _orig_set_play_mode = LogicThread.set_play_mode
    _orig_handle_triggers = LogicThread._handle_triggers

    def __init__(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        self.plugins = None
        try:
            load_plugins()
            mgr = get_manager()
            self.plugins = mgr
            if getattr(self, "io_manager", None) is not None:
                mgr.attach_runtime(self)
        except Exception as exc:
            _log(f"runtime attach failed: {exc}")

    def set_play_mode(self, enabled):
        _orig_set_play_mode(self, enabled)
        mgr = getattr(self, "plugins", None)
        if mgr is None:
            return
        try:
            if enabled:
                mgr.dispatch_play_start(self)
            else:
                mgr.dispatch_play_stop(self)
        except Exception as exc:
            _log(f"lifecycle dispatch failed: {exc}")

    def _handle_triggers(self, use_key_pressed):
        # Run the core trigger handling first, then let plugins tick. This runs
        # last in the play-tick gameplay sequence, so the use-key edge is intact
        # and any plugin HUD prompt is the final word for the frame.
        _orig_handle_triggers(self, use_key_pressed)
        mgr = getattr(self, "plugins", None)
        if mgr is None:
            return
        try:
            from plugins.api import TickContext
            ctx = TickContext(
                use_pressed=bool(use_key_pressed),
                interaction_consumed=bool(getattr(self, "current_hud_message", "")),
            )
            mgr.dispatch_tick(self, ctx)
        except Exception:
            pass

    LogicThread.__init__ = __init__
    LogicThread.set_play_mode = set_play_mode
    LogicThread._handle_triggers = _handle_triggers
    LogicThread._fio_plugins_patched = True


# ---------------------------------------------------------------------------
# editor.view_2d.View2D  — right-click "place entity" menu
# ---------------------------------------------------------------------------

def _patch_view_2d():
    try:
        from editor.view_2d import View2D
    except Exception as exc:
        _log(f"view-2d patch skipped ({exc})")
        return

    if getattr(View2D, "_fio_plugins_patched", False):
        return

    from plugins.manager import get_manager

    _orig_context_menu = View2D.contextMenuEvent

    def contextMenuEvent(self, event):
        try:
            entries = get_manager().menu_entries()
        except Exception:
            entries = []
        if not entries:
            return _orig_context_menu(self, event)

        from PyQt5.QtWidgets import QMenu

        click_pos = event.pos()
        orig_exec = QMenu.exec_
        captured = {}

        def exec_hook(menu_self, *args, **kwargs):
            # Restore the real exec_ immediately so this only fires for the top
            # menu and never re-enters.
            QMenu.exec_ = orig_exec
            action_map = {}
            try:
                menu_self.addSeparator()
                sub = menu_self.addMenu("Plugins")
                for plug, label, cls in entries:
                    action_map[sub.addAction(f"{plug.name} ▸ {label}")] = cls
            except Exception:
                action_map = {}
            chosen = orig_exec(menu_self, *args, **kwargs)
            if chosen in action_map:
                captured["cls"] = action_map[chosen]
                # Hide the choice from the original handler so it does nothing.
                return None
            return chosen

        QMenu.exec_ = exec_hook
        try:
            _orig_context_menu(self, event)
        finally:
            QMenu.exec_ = orig_exec

        cls = captured.get("cls")
        if cls is None:
            return

        # Place the plugin entity using the same world-position math the editor
        # uses for its built-in entities.
        try:
            world_pos = self.snap_to_grid(self.screen_to_world(click_pos))
            ax1, ax2 = self.get_axes()
            ax_map = {"x": 0, "y": 1, "z": 2}
            pos_3d = [0, 40, 0]
            pos_3d[ax_map[ax1]] = world_pos.x()
            pos_3d[ax_map[ax2]] = world_pos.y()
            if getattr(self, "view_type", None) == "top":
                pos_3d[1] = 40

            new_thing = cls(pos=pos_3d)
            self.main_window.save_state()
            self.editor.state.things.append(new_thing)
            self.editor.set_selected_object(new_thing)
            if (hasattr(self, "_focus_properties_tab")
                    and hasattr(self.main_window, "properties_tab_widget")):
                self._focus_properties_tab()
            self.update()
        except Exception as exc:
            _log(f"placement failed: {exc}")

    View2D.contextMenuEvent = contextMenuEvent
    View2D._fio_plugins_patched = True
