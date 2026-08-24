# `engine/`

### `audio_manager.py`
Sound effect loading and playback via pygame. Routes through `ResourceManager` for `.fiopak` package compatibility (streams from ZIP in package mode, reads from filesystem otherwise). Caches loaded sounds.

### `brush_geometry.py`
Convex brush geometry module for angled/clipped brushes. Represents brushes as intersections of half-space planes (Quake/Radiant-style), computes surface polygons, builds collision meshes, and provides 2D silhouette and bounds derivation. Dependency-light (NumPy only) for headless testing and use from the logic thread.

### `camera.py`
Camera class managing position, yaw, pitch, FOV, and view/projection matrix computation. Provides the view matrix for the renderer and the projection matrix for 3D perspective.

### `constants.py`
Shared engine constants: window defaults, tile/wall dimensions, render mode enums (lit, unlit, wireframe, vertex), physics tuning (gravity, jump strength, terminal velocity), and water physics parameters (swim speed, drag, waterjump limits).

### `glb_loader.py`
GLB/glTF 2.0 binary model loader. Parses the GLB container, extracts mesh geometry (vertices, normals, UVs, indices), PBR materials, embedded textures, and node hierarchies. The `GLB` class provides an OpenGL-ready interface (VAO, VBO, vertex count, material groups) matching the `OBJ` class for renderer compatibility.

### `logic_thread.py`
Game logic thread running at a fixed 60 Hz timestep. Handles player movement and physics, entity interactions and trigger evaluation, I/O event dispatching, mover/door animations, pickup collection, player death, portal transit, and monster AI ticking. Also drives the play-mode camera.

### `monster_ai.py`
Monster behaviour, movement, and pathfinding. Implements sight-range detection, pursuit, attack cooldowns, shoot animations, projectile spawning, death handling, and pathfinding using the spatial grid.

### `monster_constants.py`
Monster AI constants. Defines sight range, shoot interval, move speed, stop distance, sprite frame filenames, per-type billboard sizes, variant folder names, projectile speed/range/size, and physics/collision parameters.

### `obj_loader.py`
Wavefront OBJ/MTL model loader. Parses vertex positions, texture coordinates, normals, face indices, and material references. The `OBJ` class builds OpenGL buffers (VAO/VBO) and provides material groups for the renderer. Falls back to `ResourceManager` for package mode.

### `overhead_sprite.py`
Top-down player sprite for the Overhead camera mode. Split into `SpriteController` (pure animation state machine: idle, walk cycle, armed/shoot poses, facing) and `OverheadSpriteRenderer` (draws the chosen frame as a textured ground quad rotated to the player's heading). Assets live under `assets/sprites/topdown/`.

### `physics.py`
Collision detection and spatial partitioning. Implements `SpatialGrid` for O(1) cell-based brush lookup (used by player physics and monster AI), AABB-vs-brush collision, raycast, line-of-sight checks, and water volume overlap queries.

### `player.py`
Player controller. Handles first-person movement (walk, strafe, sprint), noclip mode, gravity and jump physics, water swimming and waterjump, mesh-based collision with angled brushes, step climbing, and input key mapping.

### `qt_game_view.py`
Qt `QOpenGLWidget` that hosts the renderer and drives the game loop. Manages the paint/update cycle, keyboard and mouse input dispatch, play-mode toggling, HUD drawing, split-screen viewport layout, and swappable renderer registration.

### `renderer_core.py`
`BaseRenderer` class with shared rendering logic inherited by all renderer backends. Provides texture management, grid drawing, sprite rendering, model loading and drawing, water/glass/fog volume rendering, terrain rendering, editor helpers (gizmo, selection outline, face highlight, connection lines, path nodes, portal wireframes), projected shadows, VAO creation, and shader compilation with hot-reload.

### `renderer_F.py`
Forward renderer (`Renderer_F`), inheriting from `BaseRenderer`. Implements the forward lighting pass with per-face texture batching, omnidirectional point-light shadow mapping (depth cube-maps), portal virtual-view rendering with distance culling, and render-mode switching (lit, unlit, wireframe, vertex).

### `savegame.py`
Native play-session save/load. The editor already serializes a *level* (`EditorState.get_level_data`); this builds a *saved game* on top of it — the serialized level (so entity health/dead/collected/hidden state and positions come along for free) plus a `runtime` block for what the level format never stores: the player transform and stats, cheat flags (`god`/`buddha`/`notarget`), collected keys, and door/mover/monster animation state. `build_snapshot`/`restore_snapshot` capture and re-apply a session; `write`/`read` handle the JSON `.fiosave` files. Restore is an *overlay* onto a live, already-playing session (entities matched back by stable UUID) so it never rebuilds the scene mid-flight. Exposed through `LogicThread.save_session`/`load_session` and the editor console's `save`/`load`/`quicksave`/`quickload` commands — no plugin, and the plugin API stays at v1.3.0.

**Save modes (`save_version` 2).** A `save_mode` metadata key selects one of three strategies, chosen by the *Play-session Save Mode* setting (Settings → Play Modes; persisted as `[Settings] save_mode`, default `full`):
- **`full`** — the original self-contained snapshot (whole level + player/runtime). Largest; needs no base map.
- **`delta`** — only the entities/brushes that differ from the base map (matched by UUID) plus player/runtime state, with a `base_map` identity block (name + a UUID fingerprint + counts). Smallest, but the base map must be present to load. It restores by feeding just those changed records to the *same* `_overlay_entities` UUID overlay a full save uses (`compute_delta_level`/`restore_delta`).
- **`both`** — the compact delta *and* a complete fallback snapshot in one file.

Loading is automatic: `restore_auto` reads `save_mode` (a legacy v1 file with no `save_mode` is treated as `full`), and for delta/both `classify_base_map` grades the current map against the stored identity as *exact* (apply the delta), *related* (apply by UUID, skipping entities that no longer exist, with a warning) or *incompatible*. An incompatible `both` save falls back to its full snapshot automatically; an incompatible delta-only save is the sole case that surfaces a prompt. `read` still rejects a `save_version` newer than the build understands, so future saves fail safely.

An optional `world_mode` metadata key extends this for streaming maps. A **Big World** map forces a delta save (`world_mode: "bigworld"`, `save_mode: "delta"`, never a full world snapshot): the changes are stored as a per-cell registry (`cell_deltas`) keyed by cell id and UUID, produced by the plugin's [`persistence.build_cell_delta_registry`](../plugins/bigworld/persistence.py) and restored via `_flatten_cell_deltas` + the same UUID overlay. `restore_auto` auto-detects and validates it. This forcing lives in `LogicThread.save_session` (when a live `_bigworld` session exists); ordinary maps are unaffected. See the [Big World README](../plugins/bigworld/README.md#play-session-saves-are-forced-deltas).

### `resource_manager.py`
Singleton asset provider that transparently serves files from either a standard directory tree or a mounted `.fiopak` ZIP archive. Handles path resolution, byte/text asset loading, stream access for audio, asset caching, and manifest reading in package mode.

### `shaders.py`
Shader source management, compilation, and uniform binding. Loads GLSL files from the `shaders/` directory, defines shadow mapping GLSL snippets (omnidirectional point-light depth cube-maps), and provides the `DEFAULT_SHADERS` dict used by the renderer and terrain system.

### `sysmon.py`
System monitor overlay widget. Displays a draggable, expandable HUD with real-time FPS graph (pre-allocated ring buffer), frame time tracking, visible/culled brush and triangle counts, GPU memory queries (NVX/ATI extensions), and per-second stats text caching.

### `terrain.py`
Chunked terrain mesh generation and rendering. Implements Perlin noise heightmap generation, chunk-based LOD mesh building with per-vertex normals, multi-texture blending, and terrain collision queries.

### `textures.py`
`TextureManager` for OpenGL texture loading and binding. Loads images via `QImage`, converts to RGBA, uploads to GPU, and caches texture IDs. Supports `ResourceManager` for package-mode asset streaming.

### `threaded_game_state.py`
Thread-safe bridge between the logic thread and the renderer. `ThreadedGameState` synchronises game state updates behind locks; `RenderState` is a per-frame snapshot (camera matrices, player state, visible brushes/things, HUD data, split-screen state) copied atomically for the render thread.
