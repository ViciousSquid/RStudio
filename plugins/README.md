# Fio Plugin System

Plugins add new gameplay to Fio — new placeable entity types, their I/O, and
runtime behaviour — **without editing the core editor or engine**. Drop a
package into this `plugins/` directory and it is discovered automatically at
startup.

The system ships with one complete plugin, [`tidy`](tidy/), which powers
"pick up and put everything away" games (books back on the shelf, tidy the
museum, sort the warehouse).

---

## How it works

A plugin is a Python **sub-package of `plugins/`** that exposes a module-level
`PLUGIN` instance (a `FioPlugin` subclass) — or a `get_plugin()` factory — from
its `__init__.py`.

At startup the editor calls `plugins.manager.load_plugins()`. The
`PluginManager`:

1. **Discovers** every sub-package of `plugins/`.
2. **Loads** each one, calling `register(EditorAPI)` — where the plugin
   declares entity types, I/O definitions and editor palette entries. This
   runs in the editor *and* the engine, so it must be UI-free.
3. **Attaches** to each play session's logic thread via
   `register_runtime(RuntimeAPI)` — where the plugin registers the I/O *input
   handlers* that run when other entities fire outputs at it.
4. **Dispatches** the play lifecycle: `on_play_start`, `on_tick`,
   `on_play_stop`.

Every call into plugin code is wrapped: a plugin that raises logs an error to
the debug console instead of crashing the editor or a play session.

```
             load_plugins()                 (editor + engine, once)
                   │
                   ▼
        register(EditorAPI)  ── entity types, I/O defs, menu entries
                   │
   play ──►  register_runtime(RuntimeAPI)  ── I/O input handlers
                   │
             on_play_start(logic)
                   │
             on_tick(logic, ctx)  ── every tick, after core interactions
                   │
             on_play_stop(logic)
```

### Integration points in the core

The system is **drop-in**: the only edit to the core is a tiny bootstrap in
`editor/__init__.py` (which is otherwise empty). Everything else is installed at
startup by `plugins/integration.py` via small, guarded monkey-patches, so the
large editor/engine source files are left untouched.

| File | Role |
|------|------|
| `editor/__init__.py` | Bootstrap: `load_plugins()` + `integration.apply()`, run once when the editor package is first imported (before any map loads). |
| `plugins/integration.py` | Installs the hooks: attaches plugin runtime I/O + play lifecycle + per-tick dispatch onto `engine.logic_thread.LogicThread`, and a **Plugins ▸ <plugin>** submenu onto `editor.view_2d.View2D`'s right-click "place entity" menu. |

Everything else — the property panel, the I/O editor, serialization, and 3D
model rendering — works for plugin entities *for free*, because plugin entities
are ordinary `Thing` subclasses. (If you'd rather hand-wire the three hooks
directly into the core files instead of using the shim, `integration.py`'s
docstring says exactly where each one goes.)

---

## Writing a plugin

Create `plugins/myplugin/__init__.py` and `plugins/myplugin/plugin.py`:

```python
# plugins/myplugin/plugin.py
from plugins.api import FioPlugin, io_def
from editor.things import Thing

class Coin(Thing):
    pixmap_path = "assets/sprites/pickup.png"
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties['type'] = 'coin'          # I/O + serialization key
        self.properties.setdefault('value', 1)

class MyPlugin(FioPlugin):
    name = "myplugin"
    version = "1.0.0"
    category = "My Stuff"

    def register(self, api):
        api.register_entity(Coin, menu_label="Coin")
        api.register_io('coin',
            inputs=[io_def('Collect', "Force-collect this coin")],
            outputs=[io_def('OnCollected', "Fired when collected")])

    def register_runtime(self, api):
        def collect(entity, param, logic):
            entity.properties['collected'] = True
        api.register_input_handler('coin', 'collect', collect)

    def on_tick(self, logic, ctx):
        ...   # your per-tick gameplay
```

```python
# plugins/myplugin/__init__.py
from .plugin import MyPlugin
PLUGIN = MyPlugin()
```

That's it. Restart the editor and "Coin" appears under **Plugins ▸ myplugin**
in the right-click menu, with a Properties panel and an I/O tab.

### Rules of thumb

- **Entity `type` string is the contract.** `properties['type']` must match the
  keys you pass to `register_io` and `register_input_handler`. If you subclass
  `Thing` directly, the base class defaults `type` to the lowercased class
  name; set it explicitly to be safe.
- **Want 3D geometry in play mode?** Subclass the engine's `Model` (as
  `tidy`'s `TidyObject` does) or set a `model_path` property — any `Thing`
  with a `model_path` is rendered by the existing model pipeline. Things
  without one are editor-only sprites.
- **Keep `register()` UI-free.** It runs in headless/engine contexts too.
- **Do per-tick work in `on_tick`.** `ctx.use_pressed` is the edge-triggered
  interact key for that tick; `ctx.interaction_consumed` tells you whether the
  core already claimed the HUD/use this tick.
- **Restore what you mutate.** If you move entities during play, put them back
  in `on_play_stop` so the edited map is unchanged (see `TidySession.stop`).

### API reference

See [`plugins/api.py`](api.py) for the full, documented surface:
`FioPlugin`, `EditorAPI`, `RuntimeAPI`, `TickContext`, and the `io_def` helper.

---

## Enabling / disabling plugins

All discovered plugins load by default. To disable one, set the
`FIO_DISABLED_PLUGINS` environment variable to a comma-separated list of
package or plugin names:

```bash
FIO_DISABLED_PLUGINS=tidy python main.py
```

---

## Tests

A headless smoke test exercises discovery, registration, serialization and the
tidy runtime without a display or OpenGL:

```bash
QT_QPA_PLATFORM=offscreen python plugins/tidy/tests/test_smoke.py
```
