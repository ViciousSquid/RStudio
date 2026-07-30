# Fio Player (Android)

A standalone, **player-only** front end for the Fio engine. It loads and plays
exported `.fiopak` game packages on Android.
The heavy runtime systems in [`engine/`](../engine) (map loading, entity
system, physics, AI, audio, gameplay logic) are reused largely unchanged; only
the parts that touch the OS and the GPU are replaced:

| Concern            | Desktop (editor)                    | Player (Android)                          |
| ------------------ | ----------------------------------- | ----------------------------------------- |
| Windowing / events | PyQt5 (`editor/`, `qt_game_view.py`)| SDL2 via pygame (`player/platform/`)      |
| Graphics API       | OpenGL 3.3 core (`#version 330`)    | OpenGL ES 3.x (`#version 300 es`)         |
| Input              | Keyboard + mouse                    | Touch overlay + game controller           |
| Asset source       | Directory tree / extracted package  | Streamed straight from the `.fiopak` ZIP  |
| Lifecycle          | Always foreground                   | Suspend / resume, GL-surface loss         |

This is built **incrementally**, following the milestones in the project brief.
See [Status](#status) for exactly what is implemented versus scaffolded.

---

## Why this shape

The desktop renderer (`engine/renderer_core.py`) is coupled to a Qt
`QOpenGLWidget` context and to desktop GL. Rather than fork it, the player
introduces a thin host + GL-ES layer and reuses the engine's *logic* and *shader
sources* through well-defined seams. The two dialect differences that actually
matter — the windowing toolkit and the GLSL version — are isolated so the rest
of the engine can stay one codebase.

The **shaders are a single source of truth**: `player/gles_shaders.py` pulls the
canonical GLSL strings out of `engine/shaders.py` and re-dialects them to GLSL
ES 3.00 at load time, so a shader edit in the engine automatically flows to
mobile. GLSL ES 3.00 already supports everything the renderer needs — VBOs/VAOs,
`in`/`out` stage I/O, `layout(location=)`, custom fragment outputs, `texture()`
overloads, `sampler3D`/`samplerCube`, array constructors and `gl_FragDepth` — so
this is a translation, not a rewrite.

## Layout

```
player/
├── fiopak.py            # streaming .fiopak reader (metadata.json + maps + assets)
├── gles_shaders.py      # GLSL 3.30 -> GLSL ES 3.00 translation
├── app.py               # FioPlayerApp: composes loader + host + renderer
├── main.py              # entry point (desktop harness + Android)
├── buildozer.spec       # python-for-android build config (APK / AAB)
├── input/
│   ├── state.py         # normalized, source-agnostic InputState (edge-tracked)
│   ├── touch.py         # dual on-screen sticks + action buttons
│   └── gamepad.py       # SDL controller -> InputState mapping
├── platform/
│   ├── base.py          # PlatformHost interface + HostConfig + callbacks
│   ├── desktop.py       # pygame/SDL2 dev host (requests an ES context)
│   ├── android.py       # + Android lifecycle, native surface, immersive mode
│   ├── lifecycle.py     # suspend/resume + GL-surface-loss state machine
│   └── adaptive.py      # dynamic resolution controller
├── render/
│   ├── gles_context.py  # ES shader compile / link helpers (PyOpenGL, lazy)
│   └── renderer.py      # milestone-1 ES renderer + engine bridge seam
└── tests/               # stdlib unittest: loader, translator, input, platform
```

Everything except `render/renderer.py`, `render/gles_context.py`, and the
`run()` methods of the hosts is **pure Python with no GPU/pygame dependency**,
so it is unit-tested off-device (`python -m unittest discover -s player/tests`).

## Running the desktop dev harness

```bash
pip install pygame numpy pyopengl pyglm pillow
python -m player.main path/to/game.fiopak
# options: --width 1600 --height 900 --fps 60 --fullscreen --no-vsync
```

Controls in the harness: **WASD** move, **mouse-drag** look, **Space** jump,
**E** use, **left click** fire, **Esc** pause. Touchscreens and controllers work
through the same code paths the phone uses. Milestone 1 draws a rotating
reference triangle through the translated `simple` shader to confirm the ES
pipeline end-to-end.

## Building the Android APK / AAB

```bash
pip install buildozer
cd player
# put a game next to the app so it ships inside the APK:
cp ../packages/MyGame.fiopak game.fiopak
buildozer -v android debug         # -> player/bin/*.apk
# release (signed AAB for Google Play): configure signing, then
buildozer -v android release
```

`buildozer.spec` packages `player/` + `engine/` + `assets/` and excludes the
desktop-only `editor/` (and its PyQt5 dependency). `minapi = 24` (Android 7.0)
guarantees OpenGL ES 3.x, which the manifest also advertises so incompatible
devices are filtered on the Play Store.

### Native dependency strategy

`numpy`, `pyopengl` and `pillow` have maintained python-for-android recipes.
**PyGLM** (used by the engine for vector/matrix math) is C++ and has no upstream
p4a recipe yet — this is the one real packaging risk. Two supported paths:

1. **Local PyGLM recipe** — add a `python_for_android` recipe that cross-compiles
   PyGLM for `arm64-v8a`/`armeabi-v7a`. Best fidelity (byte-identical math with
   desktop) but more build setup.
2. **glm-on-numpy shim** — the player's own matrix needs (view/projection,
   uniforms) are small; the milestone renderer's use of `glm` can be swapped for
   a tiny numpy-backed helper, deferring PyGLM until the full engine simulation
   is wired. The engine's `player.py`/`monster_ai.py` still expect `glm`, so path
   1 is required before those are ported.

Keep `requirements` in `buildozer.spec` in sync with whichever path is active.

## Status

Implemented and tested (off-device):

- [x] **Streaming `.fiopak` loader** — reads `metadata.json`, resolves the start
      map, and streams maps/assets **directly from the ZIP** (no extraction),
      with editor-compatible path fallbacks (legacy `manifest.json`, `assets/`
      prefix toggling, bare-filename basename index). 16 tests.
- [x] **GLSL 3.30 → GLSL ES 3.00 translator** — version directive, mandatory
      fragment float precision, and `int`/`sampler3D`/`samplerCube` precision
      injection; validated against all 27 engine shader sources. 13 tests.
- [x] **Input model** — edge-tracked `InputState`, floating dual-stick touch
      overlay, and SDL controller mapping. 12 tests.
- [x] **Lifecycle + adaptive resolution** — suspend/resume + GL-surface-loss
      state machine, and a dynamic-resolution controller. 10 tests.
- [x] **Platform hosts** — pygame/SDL2 desktop harness and Android host
      (lifecycle events, native full-screen, immersive mode via pyjnius).
- [x] **Milestone-1 ES renderer** — context bring-up, shader-set compilation,
      reference-triangle proof-of-life; engine bridge seams in place.
- [x] **Build config** — `buildozer.spec` for debug APK and release AAB.

Next milestones (seams are marked `TODO(port)` in the code):

- [ ] **M3 — render maps**: port `engine/renderer_core.py` brush/mesh geometry
      upload and draw passes onto the ES context (`renderer.py:load_scene` /
      `render_scene`), using the already-translated shader programs.
- [ ] **M4 — player movement**: drive `engine/player.py` + `engine/physics.py`
      from `InputState` instead of the free-look camera (`app.py:_advance_simulation`).
- [ ] **M5 — entities, lighting, portals**: `logic_thread.py`, `monster_ai.py`,
      shadow cube-maps, stencil portals on ES (stencil buffer already requested).
- [ ] **M6 — audio**: back `engine/audio_manager.py` with `pygame.mixer`,
      streaming sounds from the package via `FioPackage.open_asset`.
- [ ] **M7 — polish for Play**: on-screen control theming, settings, safe-area
      insets, store assets, signing.

## Testing

```bash
python -m unittest discover -s player/tests -p "test_*.py" -v
```

The suite is stdlib-only (no pygame/numpy/GPU needed) and builds `.fiopak`
fixtures in memory, including one packaged from a real repository map when
`maps/` is present.
