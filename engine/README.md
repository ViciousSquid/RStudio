# `engine/`
### `camera.py`
Camera matrices, movement, projection.
### `constants.py`
Shared constants (tile size, etc.).
### `logic_thread.py`
Game logic loop (separate thread) — I/O event dispatching _with dual ID/name entity resolution_
### `monster_constants.py`
Monster type definitions and stat tables.
### `obj_loader.py`
Runtime OBJ loader.
### `physics.py`
Collision & physics simulation.
### `player.py`
Player controller, noclip, strafe movement.
### `qt_game_view.py`
Qt OpenGL widget that hosts the Renderer.
### `renderer.py`
Core OpenGL renderer with frustum culling.
### `resource_manager.py`
Caches textures, models, shaders.
### `shaders.py`
Shader compilation & uniform binding.
### `terrain.py`
Chunked terrain mesh generation (perlin noise), texturing, collision.
### `textures.py`
Texture loading & binding.
### `threaded_game_state.py`
Thread-safe wrapper for game state in Play mode.
