import time
import os
import numpy as np
import ctypes
from collections import deque
from typing import Optional
from PyQt5.QtWidgets import QOpenGLWidget, QApplication, QLineEdit
from PyQt5.QtCore import Qt, QTimer, QPoint, QUrl, QRect, QEvent
from PyQt5.QtGui import QPainter, QColor, QFont, QCursor, QFontDatabase, QPen, QBrush, QPolygon, QKeySequence, QPixmap
from PyQt5.QtMultimedia import QSoundEffect
import OpenGL.GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
import glm
from engine.camera import Camera
from editor.things import (
    Thing, Light, PlayerStart, Monster, Pickup, Speaker,
    LogicGate, LogicRelay, LogicTimer, LevelChanger
)
from engine.player import Player
from PIL import Image
from .renderer import Renderer
from engine import shaders
from engine.threaded_game_state import ThreadedGameState, RenderState
from engine.logic_thread import LogicThread
from engine.constants import RENDER_MODE_LIT, RENDER_MODE_UNLIT, RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX
from editor.debug_console import DebugConsole, get_debug_logger


def perspective_projection(fov, aspect, near, far):
    if aspect == 0:
        return glm.mat4(1.0)
    return glm.perspective(glm.radians(fov), aspect, near, far)


class QtGameView(QOpenGLWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

        # Rendering and view state
        self.brush_display_mode = "Solid Lit"
        self.show_triggers_as_solid = False
        self.camera = Camera()
        self.camera.pos = glm.vec3(0, 150, 400)
        self.debug_console_window = DebugConsole.get_instance()
        self.grid_size, self.world_size = 16, 2048
        self.grid_dirty = True
        self.culling_enabled = True
        self.selected_object = None
        self.show_sprites_in_play_mode = False
        self.visibility_system = None
        self.show_visibility_debug = False
        self.grid_visible = True
        self.dragging_sysmon = False
        self.sysmon_drag_offset = QPoint(0, 0)

        # Audio setup: Initialize Sound Pool
        self.sound_pool = {}  # Map of filename -> list of QSoundEffect
        self._init_sound_system()

        # Initialize render mode names mapping for notifications
        self.render_mode_names = {
            RENDER_MODE_LIT: "Lit",
            RENDER_MODE_UNLIT: "Unlit",
            RENDER_MODE_WIREFRAME: "Wireframe",
            RENDER_MODE_VERTEX: "Vertex"
        }

        self.sysmon_expanded = False
        self.sysmon_stats = {
            'visible_brushes': 0,
            'visible_tris': 0,
            'visible_surfaces': 0,
            'culled_brushes': 0,
            'culled_tris': 0,
            'culled_surfaces': 0
        }

        # Threading Initialization
        self.game_state = ThreadedGameState()

        self.logic_thread: Optional[LogicThread] = None
        self.use_threading = True
        self._thread_started = False

        # Face Mode Initialization
        self.face_mode_active = False
        self.hovered_face_info = None

        # Input state
        self.mouselook_active = False
        self.last_mouse_pos = QPoint()

        # Debug Window Manager State
        self.debug_mode_active = False
        self.debug_window_rect = QRect(20, 20, 400, 200)
        self.frame_times = deque(maxlen=100)
        self.console_font = QFont("Arial", 9)
        self.console_font.setStyleHint(QFont.Monospace)

        self.texture_manager = {}
        self.sprite_textures = {}
        self.gun_hud_pixmaps = {}
        self.gun_flash_pixmaps = {}  # gunxHUD_flash.png muzzle flash overlays
        self.monster_debug_active = False  # F7 toggle
        self.show_spatial_grid = False     # 'sg' console command toggle
        self.renderer = None

        # Debug Rendering Resources
        self.debug_shader = None
        self.debug_vao = None
        self.debug_vbo = None

        self.show_render_menu = False
        self.current_render_mode = RENDER_MODE_LIT

        self.play_mode = False
        self.player = None

        # Stored spawn point so death-screen Escape can cleanly exit play mode
        self._last_player_start_pos = [0, 0, 0]
        self._last_player_start_angle = 0

        self.fps = 0
        self.frame_count = 0
        self.last_time = time.perf_counter()
        self.last_fps_time = time.perf_counter()
        self.start_time = time.perf_counter()

        # Pre-allocated render config
        self._render_config = {
            "culling_enabled": True,
            "brush_display_mode": "Textured",
            "render_mode": 0,
            "show_triggers_as_solid": False,
            "show_caulk": True,
            "play_mode": False,
            "selected_object": None,
            "time": 0.0,
            "show_sprites_in_play_mode": False,
            "grid_visible": True,
        }

        self.is_dragging_gizmo = False
        self.gizmo_drag_axis = None
        self.gizmo_object_start_pos = None
        self.drag_start_on_axis = None
        # Terrain sculpt painting mode
        self.terrain_sculpt_active = False
        self.terrain_sculpt_painting = False  # True while mouse is held down
        self.terrain_sculpt_mode = 'raise'    # raise / lower / smooth / flatten
        self.terrain_sculpt_radius = 50.0
        self.terrain_sculpt_strength = 20.0
        self.projection_matrix = glm.mat4(1.0)
        self.view_matrix = glm.mat4(1.0)
        self._cached_aspect_ratio = 1.0
        self.cull_distance = 4096

        # Matrix pointers for raw OpenGL calls
        self._proj_ptr = None
        self._view_ptr = None

        # ---- In-game console overlay ----------------------------------------
        # A floating QLineEdit that appears at the bottom of the viewport when
        # the player presses the console key (default: backtick).  While it is
        # visible, camera rotation and game input are frozen so the player can
        # type freely.
        self.console_overlay_active = False
        self._console_input = QLineEdit(self)
        self._console_input.setPlaceholderText("Enter command…   Esc to close")
        self._console_input.setFont(QFont("Consolas", 11))
        self._console_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(10, 10, 10, 220);
                color: #F08000;
                border: none;
                border-top: 2px solid #F08000;
                padding: 6px 10px;
                font-family: Consolas, monospace;
                font-size: 11pt;
            }
        """)
        self._console_input.returnPressed.connect(self._submit_console_command)
        self._console_input.installEventFilter(self)
        self._console_input.hide()
        # ---------------------------------------------------------------------

        timer = QTimer(self)
        timer.setInterval(16)
        timer.timeout.connect(self.update_loop)
        timer.start()

        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)

    def _init_sound_system(self):
        """Preload all sounds in assets/sounds to avoid lag during playback."""
        sound_dir = os.path.join(os.getcwd(), 'assets', 'sounds')
        if not os.path.exists(sound_dir):
            print("Warning: assets/sounds directory not found.")
            return

        print("Preloading sounds...")
        count = 0
        for f in os.listdir(sound_dir):
            if f.lower().endswith(('.wav', '.mp3')):
                full_path = os.path.join(sound_dir, f)
                self._preload_sound_file(f, full_path)
                count += 1
        print(f"Preloaded {count} sound files.")

    def _preload_sound_file(self, name, path, pool_size=4):
        """Creates a pool of QSoundEffects for a specific file to allow polyphony.

        After setting the source we play once at zero volume and immediately
        stop.  This forces the audio backend to decode and buffer the sample
        so the very first *real* play() has no start-up latency.
        """
        if name in self.sound_pool:
            return

        self.sound_pool[name] = []
        url = QUrl.fromLocalFile(path)

        for _ in range(pool_size):
            effect = QSoundEffect(self)
            effect.setSource(url)
            # Prime the audio pipeline: play silent then stop
            effect.setVolume(0.0)
            effect.play()
            effect.stop()
            effect.setVolume(1.0)
            self.sound_pool[name].append(effect)

    def _get_sound_instance(self, name):
        """Retrieve an available sound instance from the pool."""
        clean_name = os.path.basename(name)

        if clean_name not in self.sound_pool:
            path = os.path.join(os.getcwd(), 'assets', 'sounds', clean_name)
            if os.path.exists(path):
                self._preload_sound_file(clean_name, path)
            else:
                return None

        pool = self.sound_pool[clean_name]

        # Find an instance that isn't playing
        for effect in pool:
            if not effect.isPlaying():
                return effect

        # All are playing — grow the pool
        if pool:
            source_url = pool[0].source()
            new_effect = QSoundEffect(self)
            new_effect.setSource(source_url)
            pool.append(new_effect)
            return new_effect

        return None

    def initializeGL(self):
        gl.glClearColor(0.1, 0.1, 0.15, 1.0)
        try:
            pass
        except: pass

        config = getattr(self.editor, 'config', None)
        self.renderer = Renderer(self.load_texture, self.grid_size, self.world_size, config)
        self.set_cull_distance(self.cull_distance)

        self._preload_assets()
        self.load_all_sprite_textures()
        if hasattr(self.editor, 'state') and hasattr(self.editor.state, 'brushes'):
            self.preload_level_textures()

        self._start_logic_thread()
        self._init_debug_resources()

        if hasattr(self, 'debug_console_window'):
            QTimer.singleShot(1000, self.debug_console_window.show)

    def _init_debug_resources(self):
        try:
            vs_src = """
            #version 330 core
            layout (location = 0) in vec3 aPos;
            uniform mat4 view;
            uniform mat4 projection;
            void main() { gl_Position = projection * view * vec4(aPos, 1.0); }
            """
            fs_src = """
            #version 330 core
            out vec4 FragColor;
            uniform vec3 color;
            void main() { FragColor = vec4(color, 1.0); }
            """
            self.debug_shader = compileProgram(
                compileShader(vs_src, gl.GL_VERTEX_SHADER),
                compileShader(fs_src, gl.GL_FRAGMENT_SHADER),
                validate=False
            )
            self.debug_vao = gl.glGenVertexArrays(1)
            self.debug_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self.debug_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.debug_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 1024 * 1024, None, gl.GL_DYNAMIC_DRAW)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
            gl.glEnableVertexAttribArray(0)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
            gl.glBindVertexArray(0)
        except Exception as e:
            print(f"Debug Renderer Init Failed: {e}")

    def _preload_assets(self):
        tex_dir = os.path.join('assets', 'textures')
        if os.path.exists(tex_dir):
            for f in os.listdir(tex_dir):
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tga')):
                    self.renderer.load_texture(f, 'textures')
        terrain_dir = os.path.join('assets', 'textures', 'terrain')
        if os.path.exists(terrain_dir):
            for f in os.listdir(terrain_dir):
                if f.lower().endswith(('.jpg', '.png')):
                    self.renderer.load_texture(os.path.join('terrain', f), 'textures')

    def _start_logic_thread(self):
        if self._thread_started: return
        self.logic_thread = LogicThread(self.game_state, self.editor.state, self.visibility_system)
        self.logic_thread.set_editor_camera(self.camera.pos, self.camera.yaw, self.camera.pitch, self.camera.fov)
        self.logic_thread.set_play_mode(False)
        self.logic_thread.start()
        self._thread_started = True

    def _stop_logic_thread(self):
        if self.logic_thread:
            self.logic_thread.stop()
            self.logic_thread.join(timeout=1.0)
            self.logic_thread = None
            self._thread_started = False

    def closeEvent(self, event):
        self._stop_logic_thread()
        super().closeEvent(event)

    def preload_level_textures(self):
        if self.renderer:
            self.renderer.preload_level_textures(self.editor.state.brushes)

    def update_grid(self):
        self.grid_dirty = True

    def resizeGL(self, width, height):
        super().resizeGL(width, height)
        if height > 0: self._cached_aspect_ratio = width / height
        else: self._cached_aspect_ratio = 1.0
        if self.logic_thread: self.logic_thread.set_frustum_aspect(self._cached_aspect_ratio)
        # Keep console overlay pinned to the bottom edge when the window resizes
        if self.console_overlay_active:
            self._console_input.setGeometry(0, height - 36, width, 36)

    def update_loop(self):
        current_time = time.perf_counter()
        delta = current_time - self.last_time
        self.last_time = current_time
        self.frame_count += 1
        fps_elapsed = current_time - self.last_fps_time
        if fps_elapsed > 1.0:
            self.fps = self.frame_count / fps_elapsed
            self.frame_count = 0
            self.last_fps_time = current_time

        self.frame_times.append(delta * 1000.0)
        self._process_sound_queue()

        if self.use_threading and self.logic_thread:
            keys = set() if self.console_overlay_active else self.editor.keys_pressed
            self.game_state.set_keys(keys)

            # Consume new-frame flag so the logic thread can write again.
            # try_swap() both checks AND consumes in a single atomic call.
            has_new = self.game_state.try_swap()

            # Always request a repaint.  Previously this was conditional on
            # has_new, which meant Qt's QOpenGLWidget FBO could go stale when
            # the logic thread was between frames — the compositor would then
            # present uninitialised / previous-frame FBO content, visible as
            # per-frame brightness flicker (especially with an empty scene
            # where the render completes almost instantly).
            self.update()

            # Also update the 2D views in play mode so monster positions are shown moving
            if has_new and self.play_mode:
                self.editor.update_views()
        else:
            self.update()

    def _process_sound_queue(self):
        """Checks the game state for new sound requests and plays them using pooled objects."""
        for request in self.game_state.consume_sounds():
            sound_file = request.get('file')
            volume = request.get('volume', 1.0)

            if not sound_file:
                continue

            effect = self._get_sound_instance(sound_file)

            if effect:
                effect.setVolume(volume)
                effect.play()

    def _gather_io_connections(self):
        """Collect all connection lines for 3D rendering.

        Gathers three kinds of link:
          1. I/O system connections  (yellow = logic, cyan = standard)
          2. PathNode → next_node chains  (teal)
          3. Monster → patrol_target  (teal)

        Returns a list of dicts with 'src', 'dst', 'color' keys suitable
        for Renderer.draw_connection_lines().
        """
        COLOR_LOGIC   = (1.0, 1.0, 0.0)            # yellow
        COLOR_IO      = (0.0, 1.0, 1.0)            # cyan
        COLOR_PATROL  = (0.15, 0.65, 0.60)         # teal (matches 2D view)

        try:
            from editor.io_system import get_connections
            io_available = True
        except ImportError:
            io_available = False

        try:
            from editor.things import PathNode, Monster
        except ImportError:
            PathNode = None
            Monster = None

        def find_pos_by_name(name):
            for b in self.editor.state.brushes:
                if b.get('name') == name:
                    return b['pos']
            for t in self.editor.state.things:
                t_name = getattr(t, 'name', t.properties.get('name', ''))
                if t_name == name:
                    return t.pos
            return None

        lines = []

        # --- 1. I/O system connections ---
        if io_available:
            for brush in self.editor.state.brushes:
                for conn in get_connections(brush):
                    dst = find_pos_by_name(conn.target_name)
                    if dst:
                        is_logic = brush.get('is_trigger') or brush.get('is_mover') or brush.get('is_door')
                        color = COLOR_LOGIC if is_logic else COLOR_IO
                        lines.append({'src': brush['pos'], 'dst': dst, 'color': color})
            for thing in self.editor.state.things:
                for conn in get_connections(thing):
                    dst = find_pos_by_name(conn.target_name)
                    if dst:
                        is_logic = thing.properties.get('type') == 'logic_gate'
                        color = COLOR_LOGIC if is_logic else COLOR_IO
                        lines.append({'src': thing.pos, 'dst': dst, 'color': color})

        # --- 2. PathNode → next_node chains ---
        if PathNode is not None:
            node_lookup = {}
            for t in self.editor.state.things:
                if isinstance(t, PathNode):
                    n = t.properties.get('name', '') or ''
                    if n:
                        node_lookup[n] = t

            for name, node in node_lookup.items():
                next_name = node.get_next_node_name()
                if not next_name:
                    continue
                next_node = node_lookup.get(next_name)
                if next_node is None:
                    continue
                lines.append({'src': node.pos, 'dst': next_node.pos, 'color': COLOR_PATROL})

        # --- 3. Monster → patrol_target ---
        if Monster is not None and PathNode is not None:
            for t in self.editor.state.things:
                if not isinstance(t, Monster):
                    continue
                if not t.properties.get('patrol', False):
                    continue
                target_name = t.properties.get('patrol_target', '') or ''
                if not target_name:
                    continue
                dst = find_pos_by_name(target_name)
                if dst:
                    lines.append({'src': t.pos, 'dst': dst, 'color': COLOR_PATROL})

        # --- 4. Teleporter connections (Action=teleport with target_node) ---
        COLOR_TELEPORT = (0.78, 0.39, 1.0)  # Purple-ish (RGB 200,100,255)
        try:
            from editor.things import PathNode
            # Build node lookup by name
            node_lookup = {}
            for t in self.editor.state.things:
                if isinstance(t, PathNode):
                    n = t.properties.get('name', '') or ''
                    if n:
                        node_lookup[n] = t

            for brush in self.editor.state.brushes:
                if not brush.get('is_trigger', False):
                    continue
                if brush.get('trigger_action') != 'teleport':
                    continue
                target_name = brush.get('target_node', '')
                if not target_name:
                    continue
                dst_node = node_lookup.get(target_name)
                if dst_node:
                    lines.append({
                        'src': brush['pos'],
                        'dst': dst_node.pos,
                        'color': COLOR_TELEPORT
                    })
        except ImportError:
            pass

        return lines

    def paintGL(self):
        if not self.renderer or getattr(self.renderer, '_shader_init_failed', False):
            return

        # Rebuild 3D grid VBO when grid/world size changed
        if self.grid_dirty:
            self.renderer.update_grid_buffers(self.world_size, self.grid_size)
            self.grid_dirty = False

        # === THREADED RENDER PATH ===
        render_state: Optional[RenderState] = None

        if self.use_threading and self.logic_thread:
            # The swap is already handled by update_loop.  Here we just read
            # whatever the current read-side state is — it is always valid
            # (initialised to a sensible default RenderState, then replaced
            # atomically by request_swap each time the logic thread finishes).
            render_state = self.game_state.get_render_state()

            self.view_matrix = render_state.camera_view_matrix

            if render_state.is_play_mode:
                camera_pos = render_state.player_pos
            else:
                camera_pos = render_state.editor_camera_pos

            brushes_to_render = render_state.visible_brushes
            things_to_render = render_state.visible_things

            if not self.play_mode:
                self.camera.pos = glm.vec3(render_state.editor_camera_pos)
                self.camera.yaw = render_state.editor_camera_yaw
                self.camera.pitch = render_state.editor_camera_pitch
                self.camera.fov = render_state.editor_camera_fov
        else:
            # Non-threaded fallback (editor only)
            self.view_matrix = self.camera.get_view_matrix()
            camera_pos = self.camera.pos
            brushes_to_render = self.editor.state.brushes
            things_to_render = self.editor.state.things

        self.projection_matrix = perspective_projection(self.camera.fov, self._cached_aspect_ratio, 0.1, 10000.0)

        self._proj_ptr = glm.value_ptr(self.projection_matrix)
        self._view_ptr = glm.value_ptr(self.view_matrix)

        self._render_config["culling_enabled"] = self.culling_enabled
        self._render_config["brush_display_mode"] = self.brush_display_mode
        self._render_config["show_triggers_as_solid"] = self.show_triggers_as_solid
        self._render_config["render_mode"] = getattr(self, 'current_render_mode', 0)
        self._render_config["play_mode"] = self.play_mode
        self._render_config["selected_object"] = self.selected_object
        self._render_config["time"] = time.perf_counter() - self.start_time
        self._render_config["show_sprites_in_play_mode"] = self.show_sprites_in_play_mode
        self._render_config["grid_visible"] = getattr(self, 'grid_visible', True) and not self.play_mode
        self._render_config["terrain"] = getattr(self.editor, 'terrain', None)

        if render_state and hasattr(render_state, 'all_brushes'):
            self._render_config["all_brushes"] = render_state.all_brushes
        else:
            self._render_config["all_brushes"] = self.editor.state.brushes

        self.update_instance_textures(things_to_render)

        self.renderer.render_scene(
            self.projection_matrix, self.view_matrix, camera_pos,
            brushes_to_render, things_to_render,
            self.selected_object, self._render_config
        )

        # Render Bullet Marks
        if render_state and hasattr(render_state, 'bullet_marks'):
            self._render_bullet_marks(render_state.bullet_marks)

        # Render flying-monster projectiles
        if render_state and hasattr(render_state, 'projectiles') and render_state.projectiles:
            self._render_projectiles(render_state.projectiles)

        # Render monster debug rays (F7 toggle)
        if render_state and getattr(render_state, 'monster_debug_active', False):
            self._render_monster_debug_rays(getattr(render_state, 'monster_debug_rays', []))

        # Render spatial grid cells ('sg' console command)
        if self.play_mode and getattr(self, 'show_spatial_grid', False):
            self._render_spatial_grid()

        # 3D I/O connection lines (editor only — never in play mode)
        if not self.play_mode and getattr(self.editor, 'show_logic_links', False):
            conn_lines = self._gather_io_connections()
            if conn_lines:
                self.renderer.draw_connection_lines(
                    self.projection_matrix, self.view_matrix, conn_lines)

        # Face Mode Highlight
        if self.face_mode_active and self.hovered_face_info:
            brush, face_name = self.hovered_face_info
            if hasattr(self.renderer, 'draw_face_highlight'):
                self.renderer.draw_face_highlight(self.projection_matrix, self.view_matrix, brush, face_name)

        if render_state:
            self.sysmon_stats['visible_brushes'] = len(render_state.visible_brushes)
            self.sysmon_stats['culled_brushes'] = render_state.culled_brushes
            self.sysmon_stats['total_brushes'] = render_state.total_brushes

        # FIX: glFinish() instead of glFlush() — guarantees all GL commands have
        # completed before QPainter starts modifying the framebuffer.  glFlush()
        # only *initiates* execution; on Adreno and some Intel/Mesa drivers the
        # GPU may still be writing when QPainter begins, causing intermittent
        # framebuffer corruption that manifests as per-frame brightness flicker.
        gl.glFinish()

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.editor.config.getboolean('Display', 'show_fps', fallback=False):
            self._draw_fps_counter(painter)
        if self.play_mode and self.show_sprites_in_play_mode:
            self._draw_sprites_text(painter)
        if self.play_mode and getattr(self, 'show_render_menu', False):
            self._draw_render_menu(painter)
        if self.play_mode and self.editor.config.getboolean('Display', 'show_hud', fallback=True):
            self._draw_hud(painter, render_state)

        # ---- Death screen overlay ----
        if self.play_mode and render_state and getattr(render_state, 'player_dead', False):
            self._draw_death_screen(painter)

        if self.debug_mode_active:
            self._draw_window_manager(painter)

        if not self.play_mode and getattr(self.editor, 'show_logic_links', False):
            painter.setPen(QColor(255, 255, 0))
            painter.setFont(QFont("Arial", 10, QFont.Bold))
            #painter.drawText(10, self.height() - 40, "LINKS VISIBLE [F1]")

        # Draw Face Mode UI Text
        if self.face_mode_active:
            font_top = QFont("Arial", 14, QFont.Bold)
            font_bot = QFont("Arial", 10, QFont.Bold)

            msg_top = "Select a FACE for texturing"
            msg_bot = "Press ESC to cancel"

            painter.setFont(font_top)
            mt = painter.fontMetrics()
            wt = mt.horizontalAdvance(msg_top)
            ht = mt.height()

            painter.setFont(font_bot)
            mb = painter.fontMetrics()
            wb = mb.horizontalAdvance(msg_bot)
            hb = mb.height()

            cx = self.width() // 2
            margin_bottom = 30
            spacing = 5
            padding_x = 20
            padding_y = 10

            total_text_h = ht + hb + spacing
            box_w = max(wt, wb) + (padding_x * 2)
            box_h = total_text_h + (padding_y * 2)

        painter.end()

    def _render_bullet_marks(self, marks):
        """Draw simple black dots at hit locations."""
        if not marks or 'simple' not in self.renderer.shaders: return

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        shader = self.renderer.shaders['simple']
        uniforms = self.renderer.uniforms['simple']
        gl.glUseProgram(shader)

        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)

        gl.glBindVertexArray(self.renderer.vaos['cube'])

        for mark in marks:
            pos = mark['pos']
            alpha = mark['alpha']

            gl.glUniform3f(uniforms['color'], 0.0, 0.0, 0.0)

            mat = glm.translate(glm.mat4(1.0), glm.vec3(pos[0], pos[1], pos[2]))
            mat = glm.scale(mat, glm.vec3(2.0, 2.0, 2.0))

            gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(mat))
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)

        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_BLEND)

    def _render_projectiles(self, projectiles):
        """Render flying-monster projectiles as camera-facing billboards."""
        if not projectiles or 'sprite' not in self.renderer.shaders:
            return

        # Use dedicated projectile texture, falling back to the generic monster sprite
        tex_id = (self.sprite_textures.get('projectile') or
                  self.sprite_textures.get('Monster'))
        if not tex_id:
            return

        from engine.monster_constants import MONSTER_PROJECTILE_SPRITE_SIZE
        pw, ph = MONSTER_PROJECTILE_SPRITE_SIZE

        shader   = self.renderer.shaders['sprite']
        uniforms = self.renderer.uniforms['sprite']

        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'],       1, gl.GL_FALSE, self._view_ptr)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(uniforms['sprite_texture'], 0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
        gl.glBindVertexArray(self.renderer.vaos['sprite'])

        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        pos_loc  = uniforms['sprite_pos_world']
        size_loc = uniforms['sprite_size']
        for proj in projectiles:
            pos = proj['pos']
            gl.glUniform3f(pos_loc,  pos[0], pos[1], pos[2])
            gl.glUniform2f(size_loc, pw, ph)
            gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)

        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_BLEND)

    def _render_monster_debug_rays(self, rays):
        """Draw LOS debug lines from monsters to player (F7 toggle).

        Green = has line-of-sight, Red = blocked by wall brush.
        Uses the debug_shader / debug_vao already initialised for
        the editor debug renderer.
        """
        if not rays or not self.debug_shader:
            return

        gl.glUseProgram(self.debug_shader)
        proj_loc  = gl.glGetUniformLocation(self.debug_shader, 'projection')
        view_loc  = gl.glGetUniformLocation(self.debug_shader, 'view')
        color_loc = gl.glGetUniformLocation(self.debug_shader, 'color')
        gl.glUniformMatrix4fv(proj_loc, 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(view_loc, 1, gl.GL_FALSE, self._view_ptr)

        gl.glBindVertexArray(self.debug_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.debug_vbo)

        for ray in rays:
            s, e = ray['start'], ray['end']
            if ray.get('color') == 'green':
                gl.glUniform3f(color_loc, 0.0, 1.0, 0.0)
            else:
                gl.glUniform3f(color_loc, 1.0, 0.0, 0.0)
            data = np.array([s[0], s[1], s[2], e[0], e[1], e[2]], dtype=np.float32)
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, data.nbytes, data)
            gl.glDrawArrays(gl.GL_LINES, 0, 2)

        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)

    def _render_spatial_grid(self):
        """Draw the spatial grid cell boundaries as wireframe quads.

        Each populated cell in the SpatialGrid is drawn as a rectangle
        at Y=0 using the debug shader so the player can see the
        partitioning structure used by monster AI and physics.
        """
        if not self.debug_shader or not self.logic_thread:
            return
        grid = getattr(self.logic_thread, '_spatial_grid', None)
        if grid is None:
            return

        gl.glUseProgram(self.debug_shader)
        proj_loc  = gl.glGetUniformLocation(self.debug_shader, 'projection')
        view_loc  = gl.glGetUniformLocation(self.debug_shader, 'view')
        color_loc = gl.glGetUniformLocation(self.debug_shader, 'color')
        gl.glUniformMatrix4fv(proj_loc, 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(view_loc, 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniform3f(color_loc, 0.0, 0.8, 1.0)  # cyan

        gl.glBindVertexArray(self.debug_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.debug_vbo)

        cs = grid.cell_size
        draw_y = 1.0  # slightly above ground to avoid z-fight

        for (cx, cz) in grid.cells:
            x0 = cx * cs
            z0 = cz * cs
            x1 = x0 + cs
            z1 = z0 + cs
            # Four edges of the cell
            edges = [
                (x0, draw_y, z0, x1, draw_y, z0),
                (x1, draw_y, z0, x1, draw_y, z1),
                (x1, draw_y, z1, x0, draw_y, z1),
                (x0, draw_y, z1, x0, draw_y, z0),
            ]
            for e in edges:
                data = np.array(e, dtype=np.float32)
                gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, data.nbytes, data)
                gl.glDrawArrays(gl.GL_LINES, 0, 2)

        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)

    def keyPressEvent(self, event):
        def check_key(cfg_key, default):
            key_str = self.editor.config.get('Shortcuts', cfg_key, fallback=default)
            seq = QKeySequence(key_str)
            return QKeySequence(event.key() | int(event.modifiers())) == seq

        # ---- In-game console overlay ----------------------------------------
        if self.play_mode and check_key('key_console', '`'):
            if self.console_overlay_active:
                self._close_console_overlay()
            else:
                self._open_console_overlay()
            return

        if self.console_overlay_active:
            return

        if check_key('key_show_connections', 'F1'):
            current_state = getattr(self.editor, 'show_logic_links', False)
            self.editor.show_logic_links = not current_state
            self.editor.update_views()
            if hasattr(self.editor, 'show_toast'):
                status = "ON" if self.editor.show_logic_links else "OFF"
                self.editor.show_toast(f"Logic Links: {status}")
            return

        if check_key('key_toggle_wireframe', 'F2'):
            if self.current_render_mode == RENDER_MODE_WIREFRAME:
                self.current_render_mode = RENDER_MODE_LIT
            else:
                self.current_render_mode = RENDER_MODE_WIREFRAME
            mode_name = self.render_mode_names.get(self.current_render_mode, "Unknown")
            if hasattr(self.editor, 'show_toast'):
                self.editor.show_toast(f"Render Mode: {mode_name}")
            self.update()
            return

        if check_key('key_sysmon', 'F3'):
            self.debug_mode_active = not self.debug_mode_active
            # In play mode, never change cursor behaviour – keep mouse captured.
            # Only update the view so the overlay appears/disappears.
            self.update()
            return

        # ---- F7: Monster debug visualisation toggle ----
        if self.play_mode and event.key() == Qt.Key_F7:
            self.monster_debug_active = not self.monster_debug_active
            if self.logic_thread:
                self.logic_thread.monster_debug_active = self.monster_debug_active
            if hasattr(self.editor, 'show_toast'):
                status = "ON" if self.monster_debug_active else "OFF"
                self.editor.show_toast(f"Monster Debug: {status}")
            self.update()
            return

        # ---- Death screen: any key press exits play mode ----
        if self.play_mode:
            render_state = self.game_state.get_render_state()
            if getattr(render_state, 'player_dead', False):
                if event.key() == Qt.Key_Escape:
                    self._exit_play_mode()
                    return
                return

        if not self.play_mode:
            if event.key() == Qt.Key_BracketLeft:
                if hasattr(self.editor, 'set_grid_size'):
                    new_size = max(2, self.grid_size // 2)
                    self.editor.set_grid_size(new_size)
                    if hasattr(self.editor, 'show_toast'):
                        self.editor.show_toast(f"Grid Size: {new_size}")
                return
            elif event.key() == Qt.Key_BracketRight:
                if hasattr(self.editor, 'set_grid_size'):
                    new_size = min(128, self.grid_size * 2)
                    self.editor.set_grid_size(new_size)
                    if hasattr(self.editor, 'show_toast'):
                        self.editor.show_toast(f"Grid Size: {new_size}")
                return

        if self.play_mode:
            if getattr(self, 'show_render_menu', False):
                if event.key() == Qt.Key_1:
                    self.current_render_mode = RENDER_MODE_LIT
                    self.update()
                elif event.key() == Qt.Key_2:
                    self.current_render_mode = RENDER_MODE_UNLIT
                    self.update()
                elif event.key() == Qt.Key_3:
                    self.current_render_mode = RENDER_MODE_WIREFRAME
                    self.update()
                elif event.key() == Qt.Key_4:
                    self.current_render_mode = RENDER_MODE_VERTEX
                    self.update()
                elif event.key() == Qt.Key_Escape:
                    self.show_render_menu = False
                    self.update()
                return

        super().keyPressEvent(event)

    def _draw_sprites_text(self, painter):
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 105, 180))
        painter.fillRect(5, 5, 80, 25, QColor(0, 0, 0, 128))
        painter.drawText(10, 20, "Sprites")

    def _draw_fps_counter(self, painter):
        font = QFont()
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        rect_width = 100
        rect_x = self.width() - rect_width - 5
        painter.fillRect(rect_x, 5, rect_width, 20, QColor(0, 0, 0, 128))
        painter.drawText(rect_x + 5, 20, f"FPS: {self.fps:.0f}")

    def _draw_hud(self, painter, render_state):
        if not render_state: return
        health = render_state.player_health
        max_health = render_state.player_max_health
        health_ratio = health / max_health if max_health > 0 else 0
        hud_margin = 20
        bar_width = 200
        bar_height = 20
        bar_x = hud_margin
        bar_y = self.height() - hud_margin - bar_height
        painter.setPen(QPen(QColor(60, 60, 60), 2))
        painter.setBrush(QBrush(QColor(40, 40, 40, 200)))
        painter.drawRect(bar_x, bar_y, bar_width, bar_height)
        if health_ratio > 0.6: fill_color = QColor(50, 200, 50)
        elif health_ratio > 0.3: fill_color = QColor(255, 200, 50)
        else: fill_color = QColor(200, 50, 50)
        fill_width = int(bar_width * health_ratio)
        if fill_width > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(fill_color))
            painter.drawRect(bar_x, bar_y, fill_width, bar_height)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(bar_x, bar_y - 5, f"HEALTH: {health}/{max_health}")
        active_weapon = getattr(render_state, 'active_weapon', None)
        if active_weapon:
            cx, cy = self.width() // 2, self.height() // 2
            size = 10
            painter.setPen(QPen(QColor(0, 255, 0, 200), 2))
            painter.drawLine(cx - size, cy, cx + size, cy)
            painter.drawLine(cx, cy - size, cx, cy + size)
        if hasattr(render_state, 'hud_message') and render_state.hud_message:
            msg = render_state.hud_message
            msg_font = QFont()
            msg_font.setPointSize(14)
            msg_font.setBold(True)
            painter.setFont(msg_font)
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(msg)
            cx = self.width() // 2
            cy = self.height() // 2 + 50
            painter.setPen(QColor(0, 0, 0))
            painter.drawText(cx - text_width//2 + 2, cy + 2, msg)
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(cx - text_width//2, cy, msg)
        if active_weapon:
            hud_pixmap = self._load_gun_hud_pixmap(active_weapon)
            if hud_pixmap and not hud_pixmap.isNull():
                scale_factor = self.height() / 600.0
                target_h = int(200 * scale_factor)
                if hud_pixmap.height() > 0: target_w = int(hud_pixmap.width() * (target_h / hud_pixmap.height()))
                else: target_w = target_h
                x = self.width() - target_w - 20
                y = self.height() - target_h
                painter.drawPixmap(x, y, target_w, target_h, hud_pixmap)
                # Muzzle flash overlay — drawn on top of gun sprite for one frame
                if getattr(render_state, 'muzzle_flash_active', False):
                    flash_pixmap = self._load_gun_flash_pixmap(active_weapon)
                    if flash_pixmap and not flash_pixmap.isNull():
                        painter.drawPixmap(x, y, target_w, target_h, flash_pixmap)
        collected_keys = getattr(render_state, 'collected_keys', set())
        if collected_keys:
            key_x = self.width() - hud_margin - 100
            key_y = self.height() - hud_margin - 100
            key_size = 100
            key_spacing = 40
            for i, key_name in enumerate(sorted(collected_keys)):
                icon_x = key_x - i * key_spacing
                try:
                    pixmap = Pickup.get_key_pixmap(key_name)
                    if pixmap and not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(key_size, key_size)
                        painter.drawPixmap(icon_x, key_y, scaled_pixmap)
                    else: self._draw_key_fallback(painter, key_name, icon_x, key_y, key_size)
                except: self._draw_key_fallback(painter, key_name, icon_x, key_y, key_size)

    def _draw_death_screen(self, painter):
        """Full-screen death overlay — drawn on top of HUD after player_dead is set."""
        w, h = self.width(), self.height()

        # Dark red vignette overlay
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(120, 0, 0, 160)))
        painter.drawRect(0, 0, w, h)

        # "YOU DIED" title
        title_font = QFont("Arial", 64, QFont.Bold)
        painter.setFont(title_font)
        fm = painter.fontMetrics()
        title_text = "YOU DIED"
        title_w = fm.horizontalAdvance(title_text)
        title_x = (w - title_w) // 2
        title_y = h // 2 - 20

        # Shadow
        painter.setPen(QColor(60, 0, 0, 220))
        painter.drawText(title_x + 3, title_y + 3, title_text)
        # Main text
        painter.setPen(QColor(255, 60, 60))
        painter.drawText(title_x, title_y, title_text)

        # Sub-prompt
        sub_font = QFont("Arial", 18)
        painter.setFont(sub_font)
        fm2 = painter.fontMetrics()
        sub_text = "Press Escape to return to the editor"
        sub_w = fm2.horizontalAdvance(sub_text)
        sub_x = (w - sub_w) // 2
        sub_y = title_y + 60

        painter.setPen(QColor(0, 0, 0, 180))
        painter.drawText(sub_x + 2, sub_y + 2, sub_text)
        painter.setPen(QColor(220, 180, 180))
        painter.drawText(sub_x, sub_y, sub_text)

    def _draw_key_fallback(self, painter, key_name, x, y, size):
        key_colors = {'blue_key': QColor(50, 100, 200), 'red_key': QColor(200, 50, 50), 'yellow_key': QColor(200, 200, 50), 'green_key': QColor(50, 200, 50)}
        color = key_colors.get(key_name, QColor(150, 150, 150))
        painter.setPen(QPen(color.darker(120), 2))
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(x, y, size, size, 4, 4)
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.drawLine(x + 8, y + size//2, x + size - 8, y + size//2)
        painter.drawEllipse(x + 4, y + size//2 - 6, 12, 12)
        painter.drawLine(x + size - 10, y + size//2, x + size - 10, y + size//2 + 6)
        painter.drawLine(x + size - 14, y + size//2, x + size - 14, y + size//2 + 4)

    def _draw_window_manager(self, painter):
        bg_color = QColor(20, 20, 25, 235)
        border_color = QColor(80, 80, 90)
        header_color = QColor(66, 95, 93)
        text_color = QColor(220, 220, 220)
        graph_bg_color = QColor(10, 10, 15, 200)
        target_height = 240 if self.sysmon_expanded else 30
        rect = QRect(self.debug_window_rect.x(), self.debug_window_rect.y(), self.debug_window_rect.width(), target_height)
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(bg_color))
        painter.drawRect(rect)
        header_rect = QRect(rect.x(), rect.y(), rect.width(), 25)
        painter.fillRect(header_rect, header_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawLine(rect.x(), rect.y() + 25, rect.right(), rect.y() + 25)
        painter.setFont(self.console_font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(header_rect.adjusted(10, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "SysMon [F3]")
        painter.drawText(QRect(rect.right() - 50, rect.y(), 25, 25), Qt.AlignCenter, "▼" if self.sysmon_expanded else "▶")
        painter.drawText(QRect(rect.right() - 25, rect.y(), 25, 25), Qt.AlignCenter, "[X]")
        if not self.sysmon_expanded: return
        graph_x, graph_y = rect.x() + 5, rect.y() + 30
        graph_width, graph_height = rect.width() - 10, 50
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(graph_bg_color))
        painter.drawRect(graph_x, graph_y, graph_width, graph_height)
        if len(self.frame_times) > 1:
            max_ft = max(max(self.frame_times), 16.67)
            step = graph_width / max(len(self.frame_times) - 1, 1)
            points = [QPoint(int(graph_x + i * step), int(graph_y + graph_height - (ft / max_ft) * graph_height)) for i, ft in enumerate(self.frame_times)]
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(100, 200, 100, 40)))
            poly = QPolygon([QPoint(graph_x, graph_y + graph_height)] + points + [QPoint(points[-1].x(), graph_y + graph_height)])
            painter.drawPolygon(poly)
            painter.setPen(QPen(QColor(100, 255, 100), 1))
            painter.drawPolyline(QPolygon(points))
        brush_tris = len(self.editor.state.brushes) * 12
        terrain_total_tris = 0
        terrain_visible_tris = 0
        if hasattr(self.editor, 'terrain') and self.editor.terrain is not None:
            terrain_total_tris = self.editor.terrain.get_tri_count()
            terrain_visible_tris = self.editor.terrain.total_triangles
        total_tris = brush_tris + terrain_total_tris
        visible_tris = (self.renderer.render_stats.visible_tris if self.renderer else 0) + terrain_visible_tris
        left_margin = rect.x() + 10
        stats_start_y = graph_y + graph_height + 25
        line_height = 18
        current_ft = self.frame_times[-1] if self.frame_times else 0
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(left_margin, stats_start_y, f"Frame: {current_ft:.1f}ms  FPS: {self.fps:.0f}")
        painter.setPen(text_color)
        painter.drawText(left_margin, stats_start_y + line_height * 2, f"Things:   {len(self.editor.state.things)}")
        painter.drawText(left_margin, stats_start_y + line_height * 3, f"Draws:    {self.renderer.render_stats.draw_calls if self.renderer else 0}")
        brush_text = f"Brushes:  {self.sysmon_stats.get('total_brushes', 0)} "
        painter.drawText(left_margin, stats_start_y + line_height * 4, brush_text)
        tri_text = f"Tris:     {total_tris} "
        painter.drawText(left_margin, stats_start_y + line_height * 5, tri_text)
        fm = painter.fontMetrics()
        painter.setPen(QColor(50, 200, 50))
        painter.drawText(left_margin + fm.horizontalAdvance(brush_text), stats_start_y + line_height * 4, f"(Visible: {self.sysmon_stats.get('visible_brushes', 0)})")
        painter.drawText(left_margin + fm.horizontalAdvance(tri_text), stats_start_y + line_height * 5, f"(Visible: {visible_tris})")
        painter.setPen(QColor(180, 180, 180))
        culled_brushes = self.sysmon_stats.get('culled_brushes', 0)
        total_brushes = self.sysmon_stats.get('total_brushes', 0)
        cull_pct = (culled_brushes / total_brushes * 100) if total_brushes > 0 else 0
        painter.drawText(left_margin, rect.bottom() - 10, f"Culled: {cull_pct:.1f}%")
        tps_text = f"TPS: {getattr(self.logic_thread, 'actual_tps', 0.0):.1f}"
        painter.drawText(rect.right() - fm.horizontalAdvance(tps_text) - 10, rect.bottom() - 10, tps_text)

    def _draw_render_menu(self, painter):
        width, height = 200, 120
        x, y = (self.width() - width) // 2, (self.height() - height) // 2
        painter.fillRect(x, y, width, height, QColor(20, 20, 20, 230))
        painter.setPen(QPen(QColor(100, 100, 100), 1))
        painter.drawRect(x, y, width, height)
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(x + 10, y + 25, "Render Mode")
        font.setBold(False)
        font.setPointSize(10)
        painter.setFont(font)
        options = [(RENDER_MODE_LIT, "[1] Lit"), (RENDER_MODE_UNLIT, "[2] Unlit"), (RENDER_MODE_WIREFRAME, "[3] Wire"), (RENDER_MODE_VERTEX, "[4] Vert")]
        cy = y + 55
        for mid, txt in options:
            if getattr(self, 'current_render_mode', 0) == mid:
                painter.setPen(QColor(100, 255, 100))
                painter.drawText(x + 20, cy, "> " + txt)
            else:
                painter.setPen(QColor(200, 200, 200))
                painter.drawText(x + 20, cy, "  " + txt)
            cy += 20

    def load_texture(self, texture_name, subfolder):
        return self.renderer.load_texture(texture_name, subfolder) if self.renderer else 0

    def load_all_sprite_textures(self):
        things = {
            'PlayerStart': 'player.png',
            'Light': 'light.png',
            'Monster': 'monster.png',
            'Pickup': 'pickup.png',
            'Speaker': 'speaker.png',
            'LevelChanger': 'levelchanger.png'
        }
        for cls, fname in things.items():
            tid = self.load_texture(fname, 'sprites')
            if tid: self.sprite_textures[cls] = tid
        key_textures = {'blue_key': 'bluekey.png', 'red_key': 'redkey.png', 'yellow_key': 'yellowkey.png', 'green_key': 'greenkey.png'}
        for key_name, fname in key_textures.items():
            tid = self.load_texture(fname, 'sprites')
            if tid: self.sprite_textures[f'key_{key_name}'] = tid
        # Try to load dedicated projectile sprite (optional)
        proj_tid = self.load_texture('projectile.png', 'sprites')
        if proj_tid:
            self.sprite_textures['projectile'] = proj_tid
        if self.renderer:
            self.renderer.set_sprite_textures(self.sprite_textures)

    def _pixmap_to_texture(self, pixmap):
        """Convert QPixmap to OpenGL texture ID."""
        from PyQt5.QtGui import QImage
        image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)
        width, height = image.width(), image.height()
        # FIX#10: Use constBits + sizeInBytes (Qt 5.10+) with fallback
        ptr = image.constBits()
        try:
            nbytes = image.sizeInBytes()
        except AttributeError:
            nbytes = image.byteCount()
        data = ptr.asstring(nbytes)
        tex_id = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, width, height, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, data)
        return tex_id

    def update_instance_textures(self, things):
        """Update per-instance textures for special entities (Monster, LogicGate, Pickup, LevelChanger)."""
        if not self.renderer:
            return

        instance_textures = {}

        for thing in things:
            # === MONSTER ===
            # Three possible states: alive (idle), shooting, dead.
            # The tex_key encodes all three so each sprite is cached independently.
            if isinstance(thing, Monster):
                mtype       = thing.properties.get('monster_type', 'human')
                is_dead     = thing.properties.get('dead',        False)
                is_shooting = thing.properties.get('is_shooting', False)

                if is_dead:
                    state_key = 'dead'
                elif is_shooting:
                    state_key = 'shooting'
                else:
                    state_key = 'alive'

                # Key by the actual sprite path so per-instance custom sprites
                # are cached independently from same-type default sprites.
                sprite_path = thing.get_sprite_path()
                tex_key = f"msprite__{sprite_path.replace('/', '__').replace('.', '_')}"

                if tex_key not in self.sprite_textures:
                    rel_path = sprite_path.replace('assets/', '')
                    dirname  = os.path.dirname(rel_path)   # e.g. "sprites/monsters/human"
                    filename = os.path.basename(rel_path)  # e.g. "shoot.png"
                    tid = self.load_texture(filename, dirname)
                    if tid:
                        self.sprite_textures[tex_key] = tid

                if tex_key in self.sprite_textures:
                    instance_textures[id(thing)] = self.sprite_textures[tex_key]
                continue

            # === LOGIC GATE ===
            if isinstance(thing, LogicGate):
                l_type = thing.properties.get('logic_type', 'and').lower()
                filename = f"logic_{l_type}.png"
                tex_key = f"logic_{l_type}"
                if tex_key not in self.sprite_textures:
                    tid = self.load_texture(filename, 'sprites')
                    if tid:
                        self.sprite_textures[tex_key] = tid
                if tex_key in self.sprite_textures:
                    instance_textures[id(thing)] = self.sprite_textures[tex_key]

            # === PICKUP (keys, custom sprites, guns) ===
            elif isinstance(thing, Pickup):
                if thing.is_key():
                    key_name = thing.get_key_name()
                    tex_key = f'key_{key_name}'
                    if tex_key in self.sprite_textures:
                        instance_textures[id(thing)] = self.sprite_textures[tex_key]
                elif thing.properties.get('custom_sprite'):
                    sprite_path = thing.properties.get('custom_sprite')
                    filename = os.path.basename(sprite_path.replace('\\', '/'))
                    tex_id = self.load_texture(filename, 'sprites')
                    if tex_id:
                        instance_textures[id(thing)] = tex_id

            # === LEVEL CHANGER ===
            elif isinstance(thing, LevelChanger):
                tex_key = 'LevelChanger'
                if tex_key in self.sprite_textures:
                    instance_textures[id(thing)] = self.sprite_textures[tex_key]
                else:
                    fallback_key = 'logic_relay'
                    if fallback_key in self.sprite_textures:
                        instance_textures[id(thing)] = self.sprite_textures[fallback_key]

        self.renderer.set_instance_textures(instance_textures)

    def toggle_play_mode(self, player_start_pos, player_start_angle, physics_enabled=True):
        self.play_mode = not self.play_mode

        # Store the previous state of debug_mode_active so we can restore it later
        # but we don't change it when entering or exiting play mode.
        # The sysmon overlay will remain visible if it was on before.

        if self.play_mode:
            # Store spawn info
            self._last_player_start_pos = player_start_pos
            self._last_player_start_angle = player_start_angle

            # Capture mouse for mouselook
            center_pos = self.mapToGlobal(self.rect().center())
            QCursor.setPos(center_pos)
            self.last_mouse_pos = self.mapFromGlobal(center_pos)
            QApplication.setOverrideCursor(Qt.BlankCursor)

            # Create player
            self.player = Player(
                player_start_pos[0], player_start_pos[2],
                np.radians(90.0 - player_start_angle),
                physics_enabled=physics_enabled
            )
            self.player.pos.y = player_start_pos[1]

            if self.logic_thread:
                self.logic_thread.set_player(self.player)
                self.logic_thread.set_play_mode(True)

            # Do NOT change debug_mode_active – keep whatever it was
            # The overlay will be drawn if debug_mode_active is True

        else:
            # Exiting play mode
            # Close console overlay if open
            if self.console_overlay_active:
                self._console_input.hide()
                self.console_overlay_active = False

            # Reset monster debug overlay
            self.monster_debug_active = False
            self.show_spatial_grid = False
            if self.logic_thread:
                self.logic_thread.monster_debug_active = False

            # Restore cursor
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            self.setCursor(Qt.ArrowCursor)

            if self.logic_thread:
                self.logic_thread.set_play_mode(False)
                self.logic_thread.set_player(None)

            self.player = None
            self.update()


    def _exit_play_mode(self):
        """
        Exit play mode cleanly from within the view (e.g. death screen Escape).
        Calls toggle_play_mode with the stored spawn info so the editor's state
        stays consistent.  Falls back to direct teardown if nothing is stored.
        """
        if not self.play_mode:
            return
        pos   = getattr(self, '_last_player_start_pos',   [0, 0, 0])
        angle = getattr(self, '_last_player_start_angle', 0)
        self.toggle_play_mode(pos, angle)

    def set_culling(self, enabled):
        self.culling_enabled = enabled
        self.update()

    def set_cull_distance(self, distance):
        self.cull_distance = distance
        if self.renderer:
            self.renderer.lod_manager.cull_dist_sq = distance * distance
            self.renderer.lod_manager.full_dist_sq = (distance * 0.25) ** 2
        self.update()

    def get_selected_object_pos(self):
        if not self.editor.state.selected_object: return None
        if isinstance(self.editor.state.selected_object, dict): 
            return glm.vec3(self.editor.state.selected_object.get('pos', [0, 0, 0]))
        return glm.vec3(self.editor.state.selected_object.pos)

    def set_selected_object_pos(self, new_pos_vec):
        if not self.editor.state.selected_object: return
        grid = self.editor.grid_size_spinbox.value()
        snapped = [round(c / grid) * grid for c in new_pos_vec]
        if isinstance(self.editor.state.selected_object, dict):
            self.editor.state.selected_object['pos'] = snapped
        else:
            self.editor.state.selected_object.pos = snapped
        self.update()

    # =========================================================================
    # TERRAIN SCULPT PAINTING
    # =========================================================================

    def set_terrain_sculpt_active(self, active: bool):
        """Enable or disable terrain sculpt painting mode."""
        self.terrain_sculpt_active = active
        if active:
            self.setCursor(Qt.CrossCursor)
        else:
            self.terrain_sculpt_painting = False
            self.setCursor(Qt.ArrowCursor)

    def raycast_terrain(self, mx: int, my: int):
        """Cast a ray from the mouse position and find where it hits the terrain.
        Returns (world_x, world_y, world_z) or None."""
        terrain = getattr(self.editor, 'terrain', None)
        if terrain is None or not terrain.enabled:
            return None
        ray_o, ray_d = self.get_ray_from_mouse(mx, my)
        # March along the ray testing against the terrain heightfield
        step = 4.0
        max_dist = 5000.0
        t = 1.0
        prev_above = True
        while t < max_dist:
            px = ray_o.x + ray_d.x * t
            py = ray_o.y + ray_d.y * t
            pz = ray_o.z + ray_d.z * t
            h = terrain.get_height_at_safe(px, pz)
            if h is not None:
                above = py >= h
                if not above and prev_above:
                    # Refine with binary search
                    lo, hi = t - step, t
                    for _ in range(12):
                        mid = (lo + hi) * 0.5
                        mpx = ray_o.x + ray_d.x * mid
                        mpy = ray_o.y + ray_d.y * mid
                        mpz = ray_o.z + ray_d.z * mid
                        mh = terrain.get_height_at_safe(mpx, mpz)
                        if mh is not None and mpy < mh:
                            hi = mid
                        else:
                            lo = mid
                    mid = (lo + hi) * 0.5
                    fx = ray_o.x + ray_d.x * mid
                    fy = ray_o.y + ray_d.y * mid
                    fz = ray_o.z + ray_d.z * mid
                    return (fx, fy, fz)
                prev_above = above
            t += step
            # Increase step size further from camera
            if t > 500:
                step = 16.0
            elif t > 200:
                step = 8.0
        return None

    def _apply_sculpt_at_mouse(self, mx: int, my: int):
        """Apply a single sculpt stroke at the mouse position."""
        hit = self.raycast_terrain(mx, my)
        if hit is None:
            return
        wx, wy, wz = hit
        terrain = self.editor.terrain
        mode = self.terrain_sculpt_mode
        radius = self.terrain_sculpt_radius
        strength = self.terrain_sculpt_strength
        if mode == 'raise':
            terrain.apply_sculpt_at(wx, wz, radius, strength)
        elif mode == 'lower':
            terrain.apply_sculpt_at(wx, wz, radius, -strength)
        elif mode == 'smooth':
            terrain.smooth_sculpt_at(wx, wz, radius, min(strength / 20.0, 1.0))
        elif mode == 'flatten':
            terrain.flatten_sculpt_at(wx, wz, radius, min(strength / 20.0, 1.0))
        # Persist to state
        if hasattr(self.editor, 'state') and hasattr(self.editor.state, 'terrain_data'):
            self.editor.state.terrain_data = terrain.to_dict()
        self.update()

    def get_ray_from_mouse(self, mx, my):
        w, h = self.width(), self.height()
        if w == 0 or h == 0: return glm.vec3(0), glm.vec3(0, 0, 1)
        ndc_x = (2.0 * mx / w) - 1.0
        ndc_y = 1.0 - (2.0 * my / h)
        clip = glm.vec4(ndc_x, ndc_y, -1.0, 1.0)
        inv_proj = glm.inverse(self.projection_matrix)
        eye = inv_proj * clip
        eye = glm.vec4(eye.x, eye.y, -1.0, 0.0)
        inv_view = glm.inverse(self.view_matrix)
        world = inv_view * eye
        ray_dir = glm.normalize(glm.vec3(world))
        if self.use_threading and self.logic_thread:
            ec = self.logic_thread.get_editor_camera()
            ray_origin = ec.pos
        else:
            ray_origin = self.camera.pos
        return ray_origin, ray_dir

    def get_object_at_3d(self, mx, my):
        ray_o, ray_d = self.get_ray_from_mouse(mx, my)
        best_obj, best_t = None, float('inf')
        for brush in self.editor.state.brushes:
            pos = glm.vec3(brush.get('pos', [0, 0, 0]))
            size = glm.vec3(brush.get('size', [64, 64, 64]))
            bmin, bmax = pos - size/2, pos + size/2
            tmin, tmax = 0.0, float('inf')
            hit = True
            for i in range(3):
                if abs(ray_d[i]) < 1e-6:
                    if ray_o[i] < bmin[i] or ray_o[i] > bmax[i]: hit = False; break
                else:
                    t1 = (bmin[i] - ray_o[i]) / ray_d[i]
                    t2 = (bmax[i] - ray_o[i]) / ray_d[i]
                    if t1 > t2: t1, t2 = t2, t1
                    tmin = max(tmin, t1)
                    tmax = min(tmax, t2)
                    if tmin > tmax: hit = False; break
            if hit and tmin < best_t: best_t = tmin; best_obj = brush
        for thing in self.editor.state.things:
            tp = glm.vec3(thing.pos)
            radius = 32.0
            oc = ray_o - tp
            a = glm.dot(ray_d, ray_d)
            b = 2.0 * glm.dot(oc, ray_d)
            c = glm.dot(oc, oc) - radius * radius
            disc = b * b - 4 * a * c
            if disc >= 0:
                t = (-b - disc**0.5) / (2.0 * a)
                if 0 < t < best_t: best_t = t; best_obj = thing
        return best_obj

    def intersect_ray_with_axis(self, ray_o, ray_d, obj_pos, axis_vec):
        perp = glm.cross(ray_d, axis_vec)
        denom = glm.dot(perp, perp)
        if denom < 1e-6: return None, float('inf')
        diff = obj_pos - ray_o
        t = glm.dot(glm.cross(diff, axis_vec), perp) / denom
        closest = ray_o + ray_d * t
        dist = glm.distance(closest, obj_pos + axis_vec * glm.dot(closest - obj_pos, axis_vec))
        return closest, dist

    def get_brush_face_at_coords(self, mx, my):
        ray_o, ray_d = self.get_ray_from_mouse(mx, my)
        best_t = float('inf')
        best_hit = None
        for brush in self.editor.state.brushes:
            if brush.get('hidden', False): continue
            pos = glm.vec3(brush.get('pos', [0, 0, 0]))
            size = glm.vec3(brush.get('size', [64, 64, 64]))
            bmin, bmax = pos - size/2, pos + size/2
            tmin_b, tmax_b = 0.0, float('inf')
            hit = True
            for i in range(3):
                if abs(ray_d[i]) < 1e-6:
                    if ray_o[i] < bmin[i] or ray_o[i] > bmax[i]: hit = False; break
                else:
                    t1 = (bmin[i] - ray_o[i]) / ray_d[i]
                    t2 = (bmax[i] - ray_o[i]) / ray_d[i]
                    if t1 > t2: t1, t2 = t2, t1
                    tmin_b = max(tmin_b, t1)
                    tmax_b = min(tmax_b, t2)
                    if tmin_b > tmax_b: hit = False; break
            if not hit or tmin_b >= best_t: continue
            t_box = tmin_b
            hit_pt = ray_o + ray_d * t_box
            local = hit_pt - pos
            rel = glm.abs(local) / size
            face = 'north'
            if rel.x > rel.y and rel.x > rel.z:
                face = 'east' if local.x > 0 else 'west'
            elif rel.y > rel.x and rel.y > rel.z:
                face = 'top' if local.y > 0 else 'down'
            else:
                face = 'north' if local.z > 0 else 'south'
            best_t = t_box
            best_hit = (brush, face)
        return best_hit

    def mousePressEvent(self, event):
        # Terrain sculpt painting
        if self.terrain_sculpt_active and not self.play_mode and event.button() == Qt.LeftButton:
            self.terrain_sculpt_painting = True
            self._apply_sculpt_at_mouse(event.x(), event.y())
            return

        # System monitor interaction – only allowed in editor mode
        if not self.play_mode and self.debug_mode_active and event.button() == Qt.LeftButton:
            if self.debug_window_rect.contains(event.pos()):
                # Close button (top-right X)
                if event.x() > self.debug_window_rect.right() - 25 and event.y() < self.debug_window_rect.y() + 25:
                    self.debug_mode_active = False
                    if self.play_mode:
                        QApplication.setOverrideCursor(Qt.BlankCursor)
                    return

                # Title bar drag (top 25 px)
                title_bar_rect = QRect(self.debug_window_rect.x(), self.debug_window_rect.y(),
                                    self.debug_window_rect.width(), 25)
                if title_bar_rect.contains(event.pos()):
                    self.dragging_sysmon = True
                    self.sysmon_drag_offset = event.pos() - QPoint(self.debug_window_rect.x(), self.debug_window_rect.y())
                    self.setCursor(Qt.ClosedHandCursor)
                    return

        # Face Mode Click - Apply Texture (Left Click Only)
        if self.face_mode_active and event.button() == Qt.LeftButton:
            if self.hovered_face_info:
                brush, face = self.hovered_face_info
                self.editor.apply_texture_to_specific_face(brush, face)
            return

        # Legacy Face Selection (Ctrl+Click)
        if event.button() == Qt.LeftButton and QApplication.keyboardModifiers() == Qt.ControlModifier and not self.play_mode:
            face = self.get_face_at(event.pos())
            if face:
                self.editor.selected_face = face
                self.update()
            return

        if self.play_mode and event.button() == Qt.LeftButton:
            if self.console_overlay_active:
                return
            render_state = self.game_state.get_render_state()
            if getattr(render_state, 'player_dead', False):
                return
            active_weapon = getattr(render_state, 'active_weapon', None)
            if active_weapon:
                self.game_state.queue_shot()
                # Play weapon-specific sound immediately (zero latency)
                from engine.monster_constants import WEAPON_SHOOT_SOUND
                sound_file = WEAPON_SHOOT_SOUND.get(active_weapon, 'shoot.wav')
                effect = self._get_sound_instance(sound_file)
                if effect:
                    effect.play()
                return

        if event.button() == Qt.LeftButton and QApplication.keyboardModifiers() == Qt.ShiftModifier and not self.play_mode:
            obj = self.get_object_at_3d(event.x(), event.y())
            if obj:
                self.editor.save_state()
                self.editor.set_selected_object(obj)
                self.update()
            return

        if event.button() == Qt.LeftButton and self.editor.state.selected_object and not self.play_mode:
            obj_pos = self.get_selected_object_pos()
            if obj_pos:
                ray_o, ray_d = self.get_ray_from_mouse(event.x(), event.y())
                best_dist = float('inf')
                hit_axis = None
                start_pt = None
                for axis, vec in [('x', glm.vec3(1,0,0)), ('y', glm.vec3(0,1,0)), ('z', glm.vec3(0,0,1))]:
                    pt, dist = self.intersect_ray_with_axis(ray_o, ray_d, obj_pos, vec)
                    if pt and dist < 1.5 and glm.distance(pt, obj_pos) < 40.0:
                        if dist < best_dist:
                            best_dist = dist
                            hit_axis = axis
                            start_pt = pt
                if hit_axis:
                    self.editor.save_state()
                    self.is_dragging_gizmo = True
                    self.gizmo_drag_axis = hit_axis
                    self.gizmo_object_start_pos = obj_pos
                    self.drag_start_on_axis = start_pt
                    self.setCursor(Qt.ClosedHandCursor)
                    return

        if not self.play_mode and event.button() == Qt.RightButton:
            self.mouselook_active = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.BlankCursor)

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # SysMon title-bar dragging – only in editor mode
        if not self.play_mode and self.dragging_sysmon:
            new_pos = event.pos() - self.sysmon_drag_offset
            new_x = max(5, min(new_pos.x(), self.width() - self.debug_window_rect.width() - 5))
            new_y = max(5, min(new_pos.y(), self.height() - 120))
            self.debug_window_rect.moveTo(new_x, new_y)
            self.update()
            return

        # Mouselook (priority over face hover)
        if self.mouselook_active:
            dx, dy = event.x() - self.last_mouse_pos.x(), event.y() - self.last_mouse_pos.y()
            if self.use_threading and self.logic_thread:
                self.game_state.set_mouse_delta(float(dx), float(dy))
            else:
                self.camera.rotate(dx, dy)
            center = self.mapToGlobal(self.rect().center())
            QCursor.setPos(center)
            self.last_mouse_pos = self.mapFromGlobal(center)
            self.editor.update_views()
            return

        # Play Mode Mouse – only skip if console overlay is capturing input.
        # Sysmon (debug_mode_active) should NOT block mouselook.
        if self.play_mode:
            if self.console_overlay_active:
                return
            cp = event.pos()
            dx, dy = cp.x() - self.last_mouse_pos.x(), cp.y() - self.last_mouse_pos.y()
            if dx == 0 and dy == 0:
                return
            self.game_state.set_mouse_delta(float(dx), float(dy))
            center = self.mapToGlobal(self.rect().center())
            QCursor.setPos(center)
            self.last_mouse_pos = self.mapFromGlobal(center)
            return

        # Terrain sculpt drag painting
        if self.terrain_sculpt_painting and self.terrain_sculpt_active:
            self._apply_sculpt_at_mouse(event.x(), event.y())
            return

        # Gizmo Drag
        if self.is_dragging_gizmo:
            ray_o, ray_d = self.get_ray_from_mouse(event.x(), event.y())
            axis_vec = {'x': glm.vec3(1,0,0), 'y': glm.vec3(0,1,0), 'z': glm.vec3(0,0,1)}[self.gizmo_drag_axis]
            pt, _ = self.intersect_ray_with_axis(ray_o, ray_d, self.gizmo_object_start_pos, axis_vec)
            if pt:
                diff = pt - self.drag_start_on_axis
                self.set_selected_object_pos(self.gizmo_object_start_pos + diff)
            return

        # Face Mode Hover
        if self.face_mode_active:
            self.hovered_face_info = self.get_brush_face_at_coords(event.x(), event.y())
            self.update()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.terrain_sculpt_painting and event.button() == Qt.LeftButton:
            self.terrain_sculpt_painting = False
            return

        # SysMon dragging end – only in editor mode
        if not self.play_mode and self.dragging_sysmon and event.button() == Qt.LeftButton:
            self.dragging_sysmon = False
            self.setCursor(Qt.ArrowCursor)
            return

        if self.is_dragging_gizmo:
            self.is_dragging_gizmo = False
            self.setCursor(Qt.ArrowCursor)
            self.editor.save_state()

        if self.mouselook_active and event.button() == Qt.RightButton:
            self.mouselook_active = False
            self.setCursor(Qt.ArrowCursor)

        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if not self.play_mode:
            self.camera.fov = np.clip(self.camera.fov - event.angleDelta().y() * 0.05, 30, 120)
            self.editor.update_views()

    def get_face_at(self, mouse_pos):
        if not isinstance(self.editor.state.selected_object, dict): return None
        brush = self.editor.state.selected_object
        ray_o, ray_d = self.get_ray_from_mouse(mouse_pos.x(), mouse_pos.y())
        pos = glm.vec3(brush.get('pos', [0, 0, 0]))
        size = glm.vec3(brush.get('size', [64, 64, 64]))
        bmin, bmax = pos - size/2, pos + size/2
        tmin, tmax = 0.0, float('inf')
        for i in range(3):
            if abs(ray_d[i]) < 1e-6:
                if ray_o[i] < bmin[i] or ray_o[i] > bmax[i]: return None
            else:
                t1 = (bmin[i] - ray_o[i]) / ray_d[i]
                t2 = (bmax[i] - ray_o[i]) / ray_d[i]
                if t1 > t2: t1, t2 = t2, t1
                tmin = max(tmin, t1)
                tmax = min(tmax, t2)
        if tmin > tmax: return None
        hit = ray_o + ray_d * tmin
        local = hit - pos
        rel = abs(local) / size
        if rel.x > rel.y and rel.x > rel.z: return 'east' if local.x > 0 else 'west'
        if rel.y > rel.x and rel.y > rel.z: return 'top' if local.y > 0 else 'bottom'
        return 'north' if local.z > 0 else 'south'

    def _load_gun_hud_pixmap(self, gun_type):
        """Lazy load HUD pixmaps for guns."""
        if gun_type in self.gun_hud_pixmaps:
            return self.gun_hud_pixmaps[gun_type]
        path = os.path.join('assets', 'sprites', f'{gun_type}HUD.png')
        if os.path.exists(path):
            pixmap = QPixmap(path)
            self.gun_hud_pixmaps[gun_type] = pixmap
            return pixmap
        return None

    def _load_gun_flash_pixmap(self, gun_type):
        """Lazy load muzzle flash pixmap for guns (gunxHUD_flash.png)."""
        if gun_type in self.gun_flash_pixmaps:
            return self.gun_flash_pixmaps[gun_type]
        path = os.path.join('assets', 'sprites', f'{gun_type}HUD_flash.png')
        if os.path.exists(path):
            pixmap = QPixmap(path)
            self.gun_flash_pixmaps[gun_type] = pixmap
            return pixmap
        return None

    # =========================================================================
    # IN-GAME CONSOLE OVERLAY
    # =========================================================================

    def eventFilter(self, obj, event):
        """Catch Escape inside the console QLineEdit to close the overlay."""
        if obj is self._console_input and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._close_console_overlay()
                return True   # consumed — do not propagate
        return super().eventFilter(obj, event)

    def _open_console_overlay(self):
        """
        Show the floating command bar at the bottom of the viewport.
        Restores a visible cursor and freezes game input until dismissed.
        """
        self.console_overlay_active = True
        # Restore a visible cursor so the player can see they are typing
        QApplication.setOverrideCursor(Qt.ArrowCursor)
        w, h = self.width(), self.height()
        self._console_input.setGeometry(0, h - 36, w, 36)
        self._console_input.show()
        self._console_input.raise_()
        self._console_input.setFocus()
        self._console_input.clear()

    def _close_console_overlay(self):
        """
        Hide the command bar and restore play-mode mouselook.
        """
        self.console_overlay_active = False
        self._console_input.hide()
        self._console_input.clearFocus()
        self.setFocus()
        if self.play_mode:
            # Restore blank cursor and re-centre the mouse for mouselook
            while QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
            QApplication.setOverrideCursor(Qt.BlankCursor)
            center = self.mapToGlobal(self.rect().center())
            QCursor.setPos(center)
            self.last_mouse_pos = self.mapFromGlobal(center)

    def _submit_console_command(self):
        """
        Forward whatever is in the overlay input to the DebugConsole and close.
        Routing through DebugConsole._on_command_entered means the command is
        echoed in orange, added to history, and dispatched to the handler — the
        same behaviour as typing in the standalone console window.
        """
        cmd = self._console_input.text().strip()
        if cmd and self.debug_console_window:
            self.debug_console_window.command_input.setText(cmd)
            self.debug_console_window._on_command_entered()
        self._close_console_overlay()



