# `editor/`

### `asset_browser.py`		
"Texture & model browser with live thumbnails, “FIT / TILE / FACE” actions, drag-and-drop support

### `console_commands.py`
"Debug console command handler (noclip, map, fps, clear)."

### `debug_console.py`
"Full-featured Quake-style console with category filtering, entity-name hyperlinks, I/O tracing, font sizing, command history, singleton logger."

### `editor_state.py`
"Central model: stores brushes, things, terrain, undo/redo, serialisation (JSON v2 with I/O), lightmap dirty tracking, legacy migration."

### `io_editor_widget.py`
"“Output Connections” panel (Hammer-style) for adding/editing entity I/O (target, input, delay, fire-once)."

### `main_window.py`
"Main editor window – docks all UI components, menu, toolbar, play-mode toggle, toast notifications."

### `obj_loader.py`
OBJ file parser (shared between editor & engine).

### `property_editor.py`
"Per-object property panel (position, size, shader, colour, I/O, etc.)."

### `scene_hierarchy.py`
Tree view of all brushes + entities.

### `terrain_editor.py`
Dedicated terrain parameter editor.

### things.py
THINGS: Entity classes (playerstart, light, speaker, pickup, logic entities).

### `ui.py`
Shared UI helpers / widgets.

### `view_2d.py`
Orthographic 2D top-down / side editor view.
