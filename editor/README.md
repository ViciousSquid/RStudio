# `editor/`
### `asset_browser.py`
Texture & model browser with live thumbnails, FIT/TILE/FACE actions, drag-and-drop support.
### `console_commands.py`
Debug console command handler (noclip, map, fps, clear).
### `debug_console.py`
Quake-style console with category filtering, entity-name hyperlinks, I/O tracing, font sizing, command history, singleton logger.
### `editor_state.py`
Central model: stores brushes, things, terrain, undo/redo, serialisation (JSON v3 with I/O + stable entity UUIDs), logic graph layout persistence, lightmap dirty tracking, legacy migration.
### `io_editor_widget.py`
"Output Connections" panel (Hammer-style) for adding/editing entity I/O (target, input, delay, fire-once).
### `io_handlers.py`
Input handler registrations for the I/O system — maps (entity_type, input_name) pairs to handler functions.
### `io_system.py`
Half-Life 2-style entity I/O engine: OutputConnection dataclass, IOManager event dispatcher, delayed firing queue, ID-and-name-based entity resolution.
### `logic_graph_widget.py`
Visual node-graph editor for I/O connections — drag-to-connect pins, right-click editing, persistent node positions keyed by entity UUID.
### `logic_wizard.py`
Guided wizard for creating common I/O setups (button→door, trigger→event, etc.).
### `main_window.py`
Main editor window — docks all UI components, menu, toolbar, play-mode toggle, toast notifications.
### `monster_customise_dialog.py`
Dialog for editing monster entity properties (health, speed, behaviour).
### `obj_loader.py`
OBJ file parser (shared between editor & engine).
### `property_editor.py`
Per-object property panel (position, size, shader, colour, I/O, etc.).
### `rand_map_gen.py`
Random map generation algorithm.
### `rand_map_gen_dial.py`
Random map generation settings dialog.
### `scene_hierarchy.py`
Tree view of all brushes + entities.
### `SettingsWindow.py`
Editor preferences/settings dialog.
### `terrain_editor.py`
Dedicated terrain parameter editor.
### `things.py`
Entity classes (playerstart, light, speaker, pickup, logic entities) with stable UUID assignment and type-preserving serialisation.
### `ui.py`
Shared UI helpers / widgets.
### `view_2d.py`
Orthographic 2D top-down / side editor view.
