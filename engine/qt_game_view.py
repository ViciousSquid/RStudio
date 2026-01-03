import time
import os
import numpy as np
import ctypes
from collections import deque
from typing import Optional
from PyQt5.QtWidgets import QOpenGLWidget, QApplication
from PyQt5.QtCore import Qt, QTimer, QPoint, QUrl, QRect
from PyQt5.QtGui import QPainter, QColor, QFont, QCursor, QFontDatabase, QPen, QBrush, QPolygon
from PyQt5.QtMultimedia import QSoundEffect
import OpenGL.GL as gl
import glm
from engine.camera import Camera
from editor.things import Thing, Light, PlayerStart, Monster, Pickup, Speaker
from engine.player import Player
from PIL import Image
from .renderer import Renderer
from engine import shaders
from engine.threaded_game_state import ThreadedGameState, RenderState
from engine.logic_thread import LogicThread
from engine.constants import RENDER_MODE_LIT, RENDER_MODE_UNLIT, RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX


def perspective_projection(fov, aspect, near, far):
    if aspect == 0:
        return glm.mat4(1.0)
    return glm.perspective(glm.radians(fov), aspect, near, far)


class QtGameView(QOpenGLWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        
        # Rendering and view state
        self.brush_display_mode = "Textured"
        self.show_triggers_as_solid = False
        self.camera = Camera()
        self.camera.pos = glm.vec3(0, 150, 400)
        self.grid_size, self.world_size = 16, 1024
        self.grid_dirty = True
        self.culling_enabled = True # Default true for perf
        self.selected_object = None
        self.show_sprites_in_play_mode = False
        self.visibility_system = None
        self.show_visibility_debug = False
        self.grid_visible = True  # Grid visibility toggle

        self.sysmon_expanded = False
        self.sysmon_stats = {
            'visible_brushes': 0,
            'visible_tris': 0,
            'visible_surfaces': 0,
            'culled_brushes': 0,
            'culled_tris': 0,
            'culled_surfaces': 0
        }

        # Threading
        self.game_state = ThreadedGameState()
        self.logic_thread: Optional[LogicThread] = None
        self.use_threading = True 
        self._thread_started = False

        # Input state
        self.mouselook_active = False
        self.last_mouse_pos = QPoint()
        
        # Debug Window Manager State
        self.debug_mode_active = False
        self.debug_window_rect = QRect(20, 20, 400, 200)
        self.debug_drag_active = False
        self.debug_drag_offset = QPoint()
        self.frame_times = deque(maxlen=100)
        self.console_font = QFont("Arial", 9)
        self.console_font.setStyleHint(QFont.Monospace)
        
        self.texture_manager = {}
        self.sprite_textures = {}
        self.noise_texture_id = 0

        self.renderer = None

        self.show_render_menu = False
        self.current_render_mode = RENDER_MODE_LIT
        self.render_mode_names = {
            RENDER_MODE_LIT: "Lit (Phong)",
            RENDER_MODE_UNLIT: "Unlit (Fullbright)",
            RENDER_MODE_WIREFRAME: "Wireframe",
            RENDER_MODE_VERTEX: "Vertex"
        }
        
        self.play_mode = False
        self.player = None
        self.tile_map = None
        self.player_in_triggers = set()
        self.fired_once_triggers = set()
        self.active_sounds = {}
        self.played_once_sounds = set()
        
        self.mover_states = {}
        
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
        self.projection_matrix = glm.mat4(1.0)
        self.view_matrix = glm.mat4(1.0)
        
        self._cached_aspect_ratio = 1.0
        self.cull_distance = 4096

        timer = QTimer(self)
        timer.setInterval(16)
        timer.timeout.connect(self.update_loop)
        timer.start()
        
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)

    def initializeGL(self):
        gl.glClearColor(0.1, 0.1, 0.15, 1.0)
        # Disable VSync for max FPS testing (enable in production if needed)
        try:
            # WGL_EXT_swap_control
            # This is platform specific, skipping for safety or check OS
            pass
        except: pass

        self.renderer = Renderer(self.load_texture, self.grid_size, self.world_size)
        self.set_cull_distance(self.cull_distance)
        
        # PRELOAD OPTIMIZATION
        self._preload_assets()
        
        self.load_all_sprite_textures()
        if hasattr(self.editor, 'state') and hasattr(self.editor.state, 'brushes'):
            self.preload_level_textures()
        
        self._start_logic_thread()

    def _preload_assets(self):
        """Preloads all textures in the assets/textures folder to VRAM."""
        print("Preloading assets...")
        tex_dir = os.path.join('assets', 'textures')
        if os.path.exists(tex_dir):
            for f in os.listdir(tex_dir):
                if f.lower().endswith(('.png', '.jpg', '.jpeg', '.tga')):
                    self.renderer.load_texture(f, 'textures')
        print("Assets loaded.")

    def _start_logic_thread(self):
        if self._thread_started:
            return
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
        """Signals that the grid mesh needs to be rebuilt."""
        self.grid_dirty = True

    def resizeGL(self, width, height):
        super().resizeGL(width, height)
        if height > 0:
            self._cached_aspect_ratio = width / height
        else:
            self._cached_aspect_ratio = 1.0
        if self.logic_thread:
            self.logic_thread.set_frustum_aspect(self._cached_aspect_ratio)

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

        if self.use_threading and self.logic_thread:
            self.game_state.set_keys(self.editor.keys_pressed)
            if self.game_state.try_swap():
                self.update()
        else:
            self.update()

    def paintGL(self):
        if not self.renderer: return

        if self.grid_dirty:
            self.renderer.update_grid_buffers(self.world_size, self.grid_size)
            self.grid_dirty = False

        start_total = time.perf_counter()

        camera_pos = glm.vec3(0, 0, 0)
        render_state: Optional[RenderState] = None

        if self.use_threading and self.logic_thread:
            render_state = self.game_state.get_render_state()
            self.view_matrix = render_state.camera_view_matrix
            if render_state.is_play_mode:
                camera_pos = render_state.player_pos
            else:
                camera_pos = render_state.editor_camera_pos
            
            # Logic thread does culling, just grab results
            brushes_to_render = render_state.visible_brushes
            things_to_render = render_state.visible_things
            
            if not self.play_mode:
                self.camera.pos = glm.vec3(render_state.editor_camera_pos)
                self.camera.yaw = render_state.editor_camera_yaw
                self.camera.pitch = render_state.editor_camera_pitch
                self.camera.fov = render_state.editor_camera_fov
        else:
            self.view_matrix = self.camera.get_view_matrix()
            camera_pos = self.camera.pos
            brushes_to_render = self.editor.state.brushes
            things_to_render = self.editor.state.things
        
        self.projection_matrix = perspective_projection(self.camera.fov, self._cached_aspect_ratio, 0.1, 10000.0)

        self._render_config["culling_enabled"] = self.culling_enabled
        self._render_config["brush_display_mode"] = self.brush_display_mode
        self._render_config["show_triggers_as_solid"] = self.show_triggers_as_solid
        self._render_config["render_mode"] = getattr(self, 'current_render_mode', 0)
        self._render_config["play_mode"] = self.play_mode
        self._render_config["selected_object"] = self.selected_object
        self._render_config["time"] = time.perf_counter() - self.start_time
        self._render_config["show_sprites_in_play_mode"] = self.show_sprites_in_play_mode
        self._render_config["grid_visible"] = getattr(self, 'grid_visible', True) and not self.play_mode
        
        # Pass unculled brushes for shadow rendering (shadows visible even when caster is off-screen)
        if render_state and hasattr(render_state, 'all_brushes'):
            self._render_config["all_brushes"] = render_state.all_brushes
        else:
            self._render_config["all_brushes"] = self.editor.state.brushes

        # Update per-instance textures for things like key pickups
        self.update_instance_textures(things_to_render)

        self.renderer.render_scene(
            self.projection_matrix, self.view_matrix, camera_pos,
            brushes_to_render, things_to_render,
            self.selected_object, self._render_config
        )

        # Update stats
        if render_state:
            self.sysmon_stats['visible_brushes'] = len(render_state.visible_brushes)
            self.sysmon_stats['culled_brushes'] = render_state.culled_brushes
            self.sysmon_stats['total_brushes'] = render_state.total_brushes

        # 2D Overlay
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
        if self.debug_mode_active:
            self._draw_window_manager(painter)
        painter.end()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_F3:
            self.debug_mode_active = not self.debug_mode_active
            if self.play_mode:
                if self.debug_mode_active:
                    QApplication.restoreOverrideCursor()
                    self.setCursor(Qt.ArrowCursor)
                else:
                    center_pos = self.mapToGlobal(self.rect().center())
                    QCursor.setPos(center_pos)
                    self.last_mouse_pos = self.mapFromGlobal(center_pos)
                    QApplication.setOverrideCursor(Qt.BlankCursor)
            self.update()
            return

        # Grid resizing (Non-play mode only)
        if not self.play_mode:
            if event.key() == Qt.Key_BracketLeft:
                if hasattr(self.editor, 'set_grid_size'):
                    new_size = max(1, self.grid_size // 2)
                    self.editor.set_grid_size(new_size)
                    self.editor.show_toast(f"Grid Size: {new_size}")
                return
            elif event.key() == Qt.Key_BracketRight:
                if hasattr(self.editor, 'set_grid_size'):
                    new_size = min(2048, self.grid_size * 2)
                    self.editor.set_grid_size(new_size)
                    self.editor.show_toast(f"Grid Size: {new_size}")
                return

        if self.play_mode:
            if getattr(self, 'show_render_menu', False):
                if event.key() == Qt.Key_1: self.current_render_mode = RENDER_MODE_LIT
                elif event.key() == Qt.Key_2: self.current_render_mode = RENDER_MODE_UNLIT
                elif event.key() == Qt.Key_3: self.current_render_mode = RENDER_MODE_WIREFRAME
                elif event.key() == Qt.Key_4: self.current_render_mode = RENDER_MODE_VERTEX
                elif event.key() == Qt.Key_Escape: self.show_render_menu = False
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
        
        # --- Health Bar ---
        health = render_state.player_health
        max_health = render_state.player_max_health
        health_ratio = health / max_health if max_health > 0 else 0
        hud_margin = 20
        bar_width = 200
        bar_height = 20
        bar_x = hud_margin
        bar_y = self.height() - hud_margin - bar_height
        
        # Draw Health Background
        painter.setPen(QPen(QColor(60, 60, 60), 2))
        painter.setBrush(QBrush(QColor(40, 40, 40, 200)))
        painter.drawRect(bar_x, bar_y, bar_width, bar_height)
        
        # Color Logic
        if health_ratio > 0.6: fill_color = QColor(50, 200, 50)
        elif health_ratio > 0.3: fill_color = QColor(255, 200, 50)
        else: fill_color = QColor(200, 50, 50)
        
        # Draw Health Fill
        fill_width = int(bar_width * health_ratio)
        if fill_width > 0:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(fill_color))
            painter.drawRect(bar_x, bar_y, fill_width, bar_height)
            
        # Draw Text
        font = QFont()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(bar_x, bar_y - 5, f"HEALTH: {health}/{max_health}")
        # REMOVED: painter.drawText(bar_x + bar_width + 20, bar_y + bar_height - 5, "[E] Use")

        # --- Context Sensitive Interaction Message ---
        if hasattr(render_state, 'hud_message') and render_state.hud_message:
            msg = render_state.hud_message
            
            # Font settings for message
            msg_font = QFont()
            msg_font.setPointSize(14)
            msg_font.setBold(True)
            painter.setFont(msg_font)
            
            # Calculate text size to center it
            fm = painter.fontMetrics()
            text_width = fm.horizontalAdvance(msg) 
            
            cx = self.width() // 2
            cy = self.height() // 2 + 50 # Render slightly below center crosshair
            
            # Draw Shadow
            painter.setPen(QColor(0, 0, 0))
            painter.drawText(cx - text_width//2 + 2, cy + 2, msg)
            
            # Draw Text
            painter.setPen(QColor(200, 200, 200))
            painter.drawText(cx - text_width//2, cy, msg)
        
        # --- Collected Keys (Clean Look) ---
        collected_keys = getattr(render_state, 'collected_keys', set())
        if collected_keys:
            key_x = self.width() - hud_margin - 100
            key_y = self.height() - hud_margin - 100
            key_size = 75
            key_spacing = 40
            
            # REMOVED: Background Rectangle logic
            
            # Draw each key icon directly
            for i, key_name in enumerate(sorted(collected_keys)):
                icon_x = key_x - i * key_spacing
                
                try:
                    pixmap = Pickup.get_key_pixmap(key_name)
                    if pixmap and not pixmap.isNull():
                        scaled_pixmap = pixmap.scaled(key_size, key_size)
                        painter.drawPixmap(icon_x, key_y, scaled_pixmap)
                    else:
                        self._draw_key_fallback(painter, key_name, icon_x, key_y, key_size)
                except:
                    self._draw_key_fallback(painter, key_name, icon_x, key_y, key_size)
    
    def _draw_key_fallback(self, painter, key_name, x, y, size):
        """Draw a colored key icon as fallback when pixmap not available."""
        key_colors = {
            'blue_key': QColor(50, 100, 200),
            'red_key': QColor(200, 50, 50),
            'yellow_key': QColor(200, 200, 50),
            'green_key': QColor(50, 200, 50),
        }
        color = key_colors.get(key_name, QColor(150, 150, 150))
        
        painter.setPen(QPen(color.darker(120), 2))
        painter.setBrush(QBrush(color))
        painter.drawRoundedRect(x, y, size, size, 4, 4)
        
        # Draw key symbol
        painter.setPen(QPen(QColor(255, 255, 255), 2))
        # Key body
        painter.drawLine(x + 8, y + size//2, x + size - 8, y + size//2)
        # Key head
        painter.drawEllipse(x + 4, y + size//2 - 6, 12, 12)
        # Key teeth
        painter.drawLine(x + size - 10, y + size//2, x + size - 10, y + size//2 + 6)
        painter.drawLine(x + size - 14, y + size//2, x + size - 14, y + size//2 + 4)

    def _draw_window_manager(self, painter):
        bg_color = QColor(20, 20, 25, 240)
        border_color = QColor(80, 80, 90)
        header_color = QColor(66, 95, 93)
        text_color = QColor(220, 220, 220)
        graph_bg_color = QColor(10, 10, 15, 200)
        
        # Target height approx 210px when expanded
        target_height = 210 if self.sysmon_expanded else 30
        
        rect = QRect(self.debug_window_rect.x(), self.debug_window_rect.y(), self.debug_window_rect.width(), target_height)
        
        # Draw Window Background
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(bg_color))
        painter.drawRect(rect)
        
        # Draw Header
        header_rect = QRect(rect.x(), rect.y(), rect.width(), 25)
        painter.fillRect(header_rect, header_color)
        painter.setPen(QPen(border_color, 1))
        painter.drawLine(rect.x(), rect.y() + 25, rect.right(), rect.y() + 25)
        
        # Header Text
        painter.setFont(self.console_font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(header_rect.adjusted(10, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "SysMon [F3]")
        
        # Header Controls
        painter.drawText(QRect(rect.right() - 50, rect.y(), 25, 25), Qt.AlignCenter, "▼" if self.sysmon_expanded else "▶")
        painter.drawText(QRect(rect.right() - 25, rect.y(), 25, 25), Qt.AlignCenter, "[X]")
        
        if not self.sysmon_expanded:
            return

        left_margin = rect.x() + 10
        line_height = 18
        graph_x = rect.x() + 5
        graph_y = rect.y() + 30
        graph_width = rect.width() - 10
        graph_height = 50
        
        painter.setPen(QPen(border_color, 1))
        painter.setBrush(QBrush(graph_bg_color))
        painter.drawRect(graph_x, graph_y, graph_width, graph_height)
        
        max_frame_time = max(self.frame_times) if self.frame_times else 16.67
        max_frame_time = max(max_frame_time, 16.67)
        
        if len(self.frame_times) > 1:
            points = []
            step = graph_width / max(len(self.frame_times) - 1, 1)
            
            for i, ft in enumerate(self.frame_times):
                x = graph_x + i * step
                # Invert Y so higher time = higher spike
                y = graph_y + graph_height - (ft / max_frame_time) * graph_height
                y = max(graph_y, min(graph_y + graph_height, y))
                points.append(QPoint(int(x), int(y)))
            
            # Fill area
            if points:
                poly_points = [QPoint(graph_x, graph_y + graph_height)]
                poly_points.extend(points)
                poly_points.append(QPoint(int(graph_x + (len(self.frame_times)-1)*step), graph_y + graph_height))
                
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(100, 200, 100, 40)))
                painter.drawPolygon(QPolygon(poly_points))
                
                # Draw Line
                painter.setPen(QPen(QColor(100, 255, 100), 1))
                painter.drawPolyline(QPolygon(points))

        frame_stats_y = graph_y + graph_height + 26
        
        current_ft = self.frame_times[-1] if self.frame_times else 0
        avg_ft = sum(self.frame_times) / len(self.frame_times) if self.frame_times else 0
        
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(left_margin, int(frame_stats_y), f"Frame: {current_ft:.1f}ms  Avg: {avg_ft:.1f}ms")
        stats_start_y = frame_stats_y + 24
        
        visible = self.sysmon_stats.get('visible_brushes', 0)
        total_brushes = self.sysmon_stats.get('total_brushes', 0)
        culled_brushes = self.sysmon_stats.get('culled_brushes', 0)
        total_things = len(self.editor.state.things)
        draws = self.renderer.render_stats.draw_calls if self.renderer else 0

        painter.setPen(text_color)
        painter.drawText(left_margin, int(stats_start_y), f"Things:   {total_things}")
        painter.drawText(left_margin, int(stats_start_y + line_height), f"Draws:    {draws}")
        brush_text = f"Brushes:  {total_brushes} "
        painter.drawText(left_margin, int(stats_start_y + line_height * 2), brush_text)
        
        # Visible count in green
        fm = painter.fontMetrics()
        offset = fm.horizontalAdvance(brush_text)
        painter.setPen(QColor(50, 200, 50))
        painter.drawText(left_margin + offset, int(stats_start_y + line_height * 2), f"(Visible: {visible})")

        cull_pct = 0.0
        if total_brushes > 0:
            cull_pct = (culled_brushes / total_brushes) * 100.0

        footer_font = QFont(font)
        footer_font.setPointSize(11) # Reduced size
        footer_font.setBold(True)
        painter.setFont(footer_font)
        
        painter.setPen(QColor(180, 180, 180)) 
        painter.drawText(left_margin, rect.bottom() - 10, f"Culled: {cull_pct:.1f}%")
        tps = getattr(self.logic_thread, 'actual_tps', 0.0) if self.logic_thread else 0.0
        
        tps_text = f"TPS: {tps:.1f}"
        tps_width = painter.fontMetrics().horizontalAdvance(tps_text)
        painter.setPen(QColor(220, 220, 220))
        painter.drawText(rect.right() - tps_width - 10, rect.bottom() - 10, tps_text)
    
        painter.setFont(self.console_font)

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
        options = [(RENDER_MODE_LIT, "[1] Lit"), (RENDER_MODE_UNLIT, "[2] Unlit"), 
                   (RENDER_MODE_WIREFRAME, "[3] Wire"), (RENDER_MODE_VERTEX, "[4] Vert")]
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
        things = {'PlayerStart': 'player.png', 'Light': 'light.png', 'Monster': 'monster.png', 'Pickup': 'pickup.png', 'Speaker': 'speaker.png'}
        for cls, fname in things.items():
            tid = self.load_texture(fname, 'sprites')
            if tid: self.sprite_textures[cls] = tid
        
        # Load key-specific textures
        key_textures = {
            'blue_key': 'bluekey.png',
            'red_key': 'redkey.png', 
            'yellow_key': 'yellowkey.png',
            'green_key': 'greenkey.png',
        }
        for key_name, fname in key_textures.items():
            tid = self.load_texture(fname, 'sprites')
            if tid: 
                self.sprite_textures[f'key_{key_name}'] = tid
        
        if self.renderer:
            self.renderer.set_sprite_textures(self.sprite_textures)
    
    def update_instance_textures(self, things):
        """Build per-instance texture mapping for things like Pickups with custom sprites."""
        if not self.renderer:
            return
        
        instance_textures = {}
        
        for thing in things:
            if isinstance(thing, Pickup):
                # Check if it's a key
                if thing.is_key():
                    key_name = thing.get_key_name()
                    tex_key = f'key_{key_name}'
                    if tex_key in self.sprite_textures:
                        instance_textures[id(thing)] = self.sprite_textures[tex_key]
                # Check for custom sprite
                elif thing.properties.get('custom_sprite'):
                    sprite_path = thing.properties.get('custom_sprite')
                    
                    # STRICT: Enforce loading from assets/sprites folder only
                    # We extract just the filename and force the 'sprites' subfolder
                    filename = os.path.basename(sprite_path.replace('\\', '/'))
                        
                    # Load custom sprite texture if not already loaded
                    tex_id = self.load_texture(filename, 'sprites')
                    if tex_id:
                        instance_textures[id(thing)] = tex_id
        
        self.renderer.set_instance_textures(instance_textures)

    def toggle_play_mode(self, player_start_pos, player_start_angle, physics_enabled=True):
        self.play_mode = not self.play_mode
        self.debug_mode_active = False
        if self.play_mode:
            center_pos = self.mapToGlobal(self.rect().center())
            QCursor.setPos(center_pos)
            self.last_mouse_pos = self.mapFromGlobal(center_pos)
            QApplication.setOverrideCursor(Qt.BlankCursor)
            
            # Setup player for logic thread
            self.player = Player(player_start_pos[0], player_start_pos[2], np.radians(player_start_angle), physics_enabled=physics_enabled)
            self.player.pos.y = player_start_pos[1]
            if self.logic_thread:
                self.logic_thread.set_player(self.player)
                self.logic_thread.set_play_mode(True)
        else:
            QApplication.restoreOverrideCursor()
            if self.logic_thread:
                self.logic_thread.set_play_mode(False)
                self.logic_thread.set_player(None)
            self.player = None
            self.update()

    def set_culling(self, enabled):
        self.culling_enabled = enabled
        self.update()

    def set_cull_distance(self, distance):
        self.cull_distance = distance
        if self.renderer:
            self.renderer.lod_manager.cull_dist_sq = distance * distance
            # Scale full detail distance relative to cull distance (e.g., 25%)
            self.renderer.lod_manager.full_dist_sq = (distance * 0.25) ** 2
        self.update()

    def get_selected_object_pos(self):
        if not self.editor.state.selected_object: return None
        if isinstance(self.editor.state.selected_object, dict): return glm.vec3(self.editor.state.selected_object['pos'])
        return glm.vec3(self.editor.state.selected_object.pos)

    def set_selected_object_pos(self, new_pos_vec):
        if not self.editor.state.selected_object: return
        grid = self.editor.grid_size_spinbox.value()
        snapped = [round(c / grid) * grid for c in new_pos_vec]
        if isinstance(self.editor.state.selected_object, dict):
            self.editor.state.selected_object['pos'] = snapped
        else:
            obj = self.editor.state.selected_object
            if hasattr(obj, 'pos'): obj.pos = snapped
        if self.logic_thread and self.logic_thread.is_alive() and type(self.editor.state.selected_object).__name__ == 'Light':
            self.game_state.request_swap()
        self.editor.update_all_ui()

    def get_ray_from_mouse(self, x, y):
        win_x, win_y = float(x), float(self.height() - y)
        vp = glm.vec4(0, 0, self.width(), self.height())
        near = glm.unProject(glm.vec3(win_x, win_y, 0.0), self.view_matrix, self.projection_matrix, vp)
        far = glm.unProject(glm.vec3(win_x, win_y, 1.0), self.view_matrix, self.projection_matrix, vp)
        return near, glm.normalize(far - near)

    def intersect_ray_with_axis(self, ray_origin, ray_dir, axis_origin, axis_dir):
        cross = glm.cross(axis_dir, ray_dir)
        denom = glm.dot(cross, cross)
        if abs(denom) < 1e-6: return None, float('inf')
        t = glm.dot(glm.cross(ray_origin - axis_origin, ray_dir), cross) / denom
        pt = axis_origin + t * axis_dir
        t_ray = glm.dot(pt - ray_origin, ray_dir)
        pt_ray = ray_origin + t_ray * ray_dir
        return pt, glm.distance(pt, pt_ray)

    def intersect_ray_aabb(self, ray_origin, ray_dir, box_min, box_max):
        t_min, t_max = 0.0, float('inf')
        for i in range(3):
            if abs(ray_dir[i]) < 1e-8:
                if ray_origin[i] < box_min[i] or ray_origin[i] > box_max[i]: return False, float('inf')
            else:
                t1 = (box_min[i] - ray_origin[i]) / ray_dir[i]
                t2 = (box_max[i] - ray_origin[i]) / ray_dir[i]
                if t1 > t2: t1, t2 = t2, t1
                t_min = max(t_min, t1)
                t_max = min(t_max, t2)
                if t_min > t_max: return False, float('inf')
        return True, t_min
    
    def intersect_ray_sphere(self, ray_origin, ray_dir, center, radius):
        oc = ray_origin - center
        a = glm.dot(ray_dir, ray_dir)
        b = 2.0 * glm.dot(oc, ray_dir)
        c = glm.dot(oc, oc) - radius * radius
        disc = b * b - 4 * a * c
        if disc < 0: return False, float('inf')
        t = (-b - np.sqrt(disc)) / (2.0 * a)
        if t < 0: t = (-b + np.sqrt(disc)) / (2.0 * a)
        return (True, t) if t >= 0 else (False, float('inf'))

    def get_object_at_3d(self, mouse_x, mouse_y):
        ray_origin, ray_dir = self.get_ray_from_mouse(mouse_x, mouse_y)
        closest_thing, closest_thing_t = None, float('inf')
        closest_brush, closest_brush_t = None, float('inf')
        
        for thing in self.editor.state.things:
            if thing.properties.get('hidden', False): continue
            hit, t = self.intersect_ray_sphere(ray_origin, ray_dir, glm.vec3(*thing.pos), 24.0)
            if hit and t < closest_thing_t:
                closest_thing_t = t
                closest_thing = thing
                
        for brush in self.editor.state.brushes:
            if brush.get('hidden', False): continue
            pos, size = brush['pos'], brush['size']
            h = [s/2 for s in size]
            bmin = glm.vec3(pos[0]-h[0], pos[1]-h[1], pos[2]-h[2])
            bmax = glm.vec3(pos[0]+h[0], pos[1]+h[1], pos[2]+h[2])
            hit, t = self.intersect_ray_aabb(ray_origin, ray_dir, bmin, bmax)
            if hit and t < closest_brush_t:
                closest_brush_t = t
                closest_brush = brush
        
        return closest_thing if closest_thing else closest_brush

    def mousePressEvent(self, event):
        if self.debug_mode_active and event.button() == Qt.LeftButton:
            # Simple debug window interaction passthrough or close logic
            if self.debug_window_rect.contains(event.pos()):
                # Simplified for brevity: just check click areas
                if event.x() > self.debug_window_rect.right() - 25 and event.y() < self.debug_window_rect.y() + 25:
                    self.debug_mode_active = False
                    if self.play_mode:
                        QApplication.setOverrideCursor(Qt.BlankCursor)
                return

        if event.button() == Qt.LeftButton and QApplication.keyboardModifiers() == Qt.ControlModifier and not self.play_mode:
            face = self.get_face_at(event.pos())
            if face:
                self.editor.selected_face = face
                self.update()
                return
        
        if event.button() == Qt.LeftButton and QApplication.keyboardModifiers() == Qt.ShiftModifier and not self.play_mode:
            obj = self.get_object_at_3d(event.x(), event.y())
            if obj:
                self.editor.save_state()
                self.editor.set_selected_object(obj)
                self.update()
                return

        if event.button() == Qt.LeftButton and self.editor.state.selected_object and not self.play_mode:
            # Gizmo Logic (Using raycast against axis lines)
            obj_pos = self.get_selected_object_pos()
            if obj_pos:
                ray_o, ray_d = self.get_ray_from_mouse(event.x(), event.y())
                best_dist = float('inf')
                hit_axis = None
                start_pt = None
                
                for axis, vec in [('x', glm.vec3(1,0,0)), ('y', glm.vec3(0,1,0)), ('z', glm.vec3(0,0,1))]:
                    pt, dist = self.intersect_ray_with_axis(ray_o, ray_d, obj_pos, vec)
                    if pt and dist < 1.5 and glm.distance(pt, obj_pos) < 40.0: # Thresholds
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
        if self.is_dragging_gizmo:
            ray_o, ray_d = self.get_ray_from_mouse(event.x(), event.y())
            axis_vec = {'x': glm.vec3(1,0,0), 'y': glm.vec3(0,1,0), 'z': glm.vec3(0,0,1)}[self.gizmo_drag_axis]
            pt, _ = self.intersect_ray_with_axis(ray_o, ray_d, self.gizmo_object_start_pos, axis_vec)
            if pt:
                diff = pt - self.drag_start_on_axis
                self.set_selected_object_pos(self.gizmo_object_start_pos + diff)
            return

        if self.play_mode:
            if self.debug_mode_active: return
            cp = event.pos()
            dx, dy = cp.x() - self.last_mouse_pos.x(), cp.y() - self.last_mouse_pos.y()
            if dx == 0 and dy == 0: return
            self.game_state.set_mouse_delta(float(dx), float(dy))
            center = self.mapToGlobal(self.rect().center())
            QCursor.setPos(center)
            self.last_mouse_pos = self.mapFromGlobal(center)
            return

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
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
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
        pos, size = glm.vec3(brush['pos']), glm.vec3(brush['size'])
        bmin, bmax = pos - size/2, pos + size/2
        
        # Ray-AABB intersection logic to find face normal
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
        
        # Identify face by max component
        if rel.x > rel.y and rel.x > rel.z: return 'east' if local.x > 0 else 'west'
        if rel.y > rel.x and rel.y > rel.z: return 'top' if local.y > 0 else 'bottom'
        return 'north' if local.z > 0 else 'south'