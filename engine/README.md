# `Engine/`

### `camera.py`
Camera matrices, movement, projection.

### `constants.py`
Shared constants (tile size, etc.).

### `logic_thread.py`
Game logic - runs in separate thread

### `monster_ai.py`
Monster Behaviour, Movement, Pathfinding

### `physics.py`
Collision & physics simulation

### `player.py`
Player controller, noclip, strafe movement.

### `procedural_generator.py`
Procedural liminal map generator

### `qt_game_view.py`
Qt OpenGL widget that hosts the Renderer

### `renderer_core.py`
BaseRenderer class

### `renderer_F.py`
OpenGL FORWARD renderer

### `resource_manager.py`
Caches textures, models, shaders.

### `shaders.py`
Shader compilation & uniform binding.

### `terrain.py`
Chunked terrain mesh generation (perlin noise), texturing, collision

### `textures.py`
Texture loading & binding.

### `threaded_game_state.py`
Thread-safe wrapper for game state in Play mode.

### `xxx_loader.py`
Runtime OBJ and GLB loaders
