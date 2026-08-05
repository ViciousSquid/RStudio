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

The **engine** play lifecycle is wired **natively**: `engine.logic_thread.LogicThread`
calls the plugin manager directly — `attach_runtime` in `__init__`,
`dispatch_play_start`/`dispatch_play_stop` in `set_play_mode`, and the cached,
early-out `tick()` in `_tick_play_mode`. Each call is guarded, so a build without
the `plugins/` package runs unchanged. The **editor** integrations stay as small,
guarded monkey-patches in `plugins/integration.py` (cold paths — menus, load
hooks, export), so the large editor source files are left untouched. The only
editor edit is a tiny bootstrap in `editor/__init__.py`.

| File | Role |
|------|------|
| `engine/logic_thread.py` | **Native** plugin hooks: `attach_runtime` (`__init__`), play-start/stop (`set_play_mode`), per-tick dispatch (`_tick_play_mode`). All guarded and optional. |
| `editor/__init__.py` | Bootstrap: `load_plugins()` + `integration.apply()`, run once when the editor package is first imported (before any map loads). |
| `plugins/integration.py` | Installs the editor hooks: auto-enable/disable of a disabled-by-default plugin onto `editor.editor_state.EditorState` (`load_from_data` enables for a level's entities, `clear_scene` reverts on File ▸ New); a **Plugins ▸ <plugin>** submenu onto `editor.view_2d.View2D`'s right-click menu; a top-level **Plugins** menu onto `editor.ui.Ui_MainWindow`; and plugin bundling onto `editor.package_exporter.PackageExporter.export`. |
| `plugins/packaging.py` | Bundles the plugins a `.fiopak`'s maps depend on (code + assets + manifest) so exported packages are self-contained. |

Everything else — the property panel, the I/O editor, serialization, and 3D
model rendering — works for plugin entities *for free*, because plugin entities
are ordinary `Thing` subclasses.

**Runtime attach + enable gating.** Every loaded plugin's I/O input handlers are
registered once when the logic thread is built, but each handler self-gates on
its plugin's live `enabled` flag — so a plugin enabled *after* startup (e.g. a
disabled-by-default one auto-enabled when its level loads) has working inputs
with no re-attach, while a disabled plugin's inputs stay inert. Play-start/tick/stop
dispatch is likewise gated and, on the hot per-tick path, served from a cache
that only rebuilds when the enabled set changes — a map whose active plugins
don't tick pays almost nothing per frame.

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

## Finding plugins in the editor

Loaded plugins appear two ways:

- **Menu bar → Plugins** — a submenu per plugin with an **Enabled** checkbox to
  toggle it on/off, its placeable entities (click one to drop it at the origin,
  then drag it into place), and an *About* entry. The base of the menu has an
  *About the plugin system* summary.
- **2D view right-click → Plugins ▸ <plugin>** — place an entity exactly where
  you click (only shown for enabled plugins).

Plugin entities also get a Properties panel and an I/O tab automatically, and
the `LogicSpawner` can spawn them at runtime.

Loading is **silent** by default — nothing about plugins appears in the console.
Set `FIO_PLUGIN_DEBUG=1` to see informational load/registration messages
(errors are always shown).

## Packaging plugins into a `.fiopak`

`.fiopak` exports are **plugin-aware**. When you export a package
(File → Export…), the exporter scans the maps it bundles, works out which
plugins their entities come from, and injects those plugins — **code and
assets** — plus the plugin-system core into the archive, recording them in
`metadata.json` under `"plugins"`. The package is then self-contained and loads
on another machine.

- Plugin assets keep their repo-relative paths (e.g.
  `plugins/tidy/assets/tidy_object.obj`), so a map's `model_path` resolves
  straight out of the package — no rewriting.
- Packages that use no plugin entities are unaffected (the step is a no-op).
- The player side exposes the dependency: `FioPackage.required_plugins` reads
  the manifest list, and `plugins.packaging.load_package_plugins(root)` loads
  the bundled plugins from an extracted package.

The mechanics live in [`plugins/packaging.py`](packaging.py)
(`augment_fiopak`, `load_package_plugins`) and are wired onto the exporter by
`integration.py`.

## Running plugins outside the editor (the `.fiopak` player)

Plugin gameplay runs in **both** hosts:

- **Editor Play mode** — the logic thread dispatches the plugin lifecycle/tick
  (via `plugins.integration`).
- **Standalone `.fiopak` player** (`player/`, incl. the Android build) — the
  `player.plugin_host.PlayerPluginHost` loads the package's plugins, builds
  entity instances from the map, and drives the same lifecycle/tick from the
  player's frame loop against a camera→player bridge (USE = interact).

To make this work everywhere, the plugin runtime is **dependency-free**: no
PyGLM (plain-Python vector math) and no PyQt. Plugin entities normally subclass
the editor's `Thing`/`Model`, but when the editor package is absent (the player)
they fall back to `plugins/entitybase.py`, a tiny PyQt-free base. So the same
plugin loads in the editor, the desktop player, and the APK.

> Note: the player's renderer is still bringing up map-model drawing, so plugin
> gameplay *runs* (state, HUD text via `render_state["hud"]`) ahead of the
> models being visible on screen. The host exposes `things` and `hud_message`
> for the renderer to consume once it draws dynamic models.

## Android APK

`player/buildozer.spec` includes `plugins/*`, so the plugin system + bundled
plugins (code and `.obj`/`.mtl` assets) ship inside the APK. The
**Android Player Build** workflow (`.github/workflows/android-build.yml`)
bundles `maps/Tidy_Test.json` as the sample `game.fiopak` (self-contained — the
plugin travels with it), so the on-device build exercises the plugin loader and
runtime. Trigger it from **Actions → Android Player Build → Run workflow**; the
APK is uploaded as the `fio-player-debug-apk` artifact.

## Enabling / disabling plugins

- **Disabled by default + auto-enable on load:** a plugin can set
  `enabled = False` on its class to ship inert — ordinary maps never pay for
  gameplay they don't use. When a level whose `things` reference the plugin's
  entity types is loaded, the manager turns it on automatically
  (`PluginManager.auto_enable_for_map`, wired into level loading in the editor
  and the standalone player). The Tidy plugin ships this way: it stays off until
  you open a map like `maps/Tidy_Test.json`. The flip is symmetric — clearing
  the scene (**File ▸ New**, or loading a map that doesn't use the plugin)
  reverts a level-driven auto-enable via `PluginManager.disable_auto_enabled`,
  so an empty map starts clean. This is a runtime, per-session flip: it never
  rewrites the persisted `[Plugins] disabled` list, and a plugin you enabled by
  hand from the menu is never auto-disabled underneath you.
- **Per plugin, in the editor:** toggle **Enabled** in the Plugins menu. A
  disabled plugin stops its gameplay and greys out placement; the choice is
  saved to `settings.ini` (`[Plugins] disabled`) and restored next launch.
  (Entity *registration* isn't undone live, so a re-enable is instant while a
  full unload happens on restart.)
- **At startup, globally:** set `FIO_DISABLED_PLUGINS` to a comma-separated list
  of plugin/package names so they never load:

  ```bash
  FIO_DISABLED_PLUGINS=tidy python main.py
  ```

---

## Tests

Headless, no display / OpenGL required:

```bash
QT_QPA_PLATFORM=offscreen python plugins/tidy/tests/test_smoke.py       # runtime + integration
QT_QPA_PLATFORM=offscreen python plugins/tidy/tests/test_packaging.py   # .fiopak bundling
python plugins/tidy/tests/test_player.py                                # player path (editor/PyQt/glm blocked)
```
