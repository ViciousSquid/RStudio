# Engine

### `camera.py`
Camera matrices, movement, projection.

### `constants.py`
Shared constants (tile size, etc.).

### `logic_thread.py`
Game logic - runs in separate thread

### `obj_loader.py`
Runtime OBJ loader.

### `physics.py`
Collision & physics simulation

### `player.py`
Player controller, noclip, strafe movement.

### `qt_game_view.py`
Qt OpenGL widget that hosts the Renderer

### `renderer.py`
Core OpenGL renderer: brush drawing, terrain, water, lights, shadows, shader hot-reload prep, fog, etc.

### `resource_manager.py`
Caches textures, models, shaders.

### `shaders.py`
Shader compilation & uniform binding.

### `terrain.py`
Chunked terrain mesh generation, texturing, collision.

### `textures.py`
Texture loading & binding.

### `threaded_game_state.py`
Thread-safe wrapper for game state in Play mode.
