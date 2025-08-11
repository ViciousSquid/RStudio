import time
import os
import numpy as np
import ctypes
from PyQt5.QtWidgets import QOpenGLWidget, QApplication
from PyQt5.QtCore import Qt, QTimer, QPoint, QUrl
from PyQt5.QtGui import QPainter, QColor, QFont, QCursor
from PyQt5.QtMultimedia import QSoundEffect
import OpenGL.GL as gl
import glm
from engine.camera import Camera
from editor.things import Thing, Light, PlayerStart, Monster, Pickup, Speaker
from engine.player import Player
from PIL import Image
from .renderer import Renderer
from engine import shaders

def perspective_projection(fov, aspect, near, far):
    if aspect == 0: return glm.mat4(1.0)
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
        self.culling_enabled = False
        self.selected_object = None

        # Input state
        self.mouselook_active, self.last_mouse_pos = False, QPoint()
        
        # Resource management
        self.texture_manager = {}
        self.sprite_textures = {}
        self.noise_texture_id = 0

        # Rendering backend
        self.renderer = None

        # Game mode state
        self.play_mode = False
        self.player = None
        self.tile_map = None
        self.player_in_triggers = set()
        self.fired_once_triggers = set()
        self.active_sounds = {}
        self.played_once_sounds = set()
        
        # Performance tracking
        self.fps = 0
        self.frame_count = 0
        self.last_time = time.time()
        self.last_fps_time = time.time()
        self.start_time = time.time()

        # Gizmo dragging state
        self.is_dragging_gizmo = False
        self.gizmo_drag_axis = None
        self.gizmo_object_start_pos = None
        self.drag_start_on_axis = None
        self.projection_matrix = glm.mat4(1.0)
        self.view_matrix = glm.mat4(1.0)

        timer = QTimer(self)
        timer.setInterval(16) # ~60 FPS
        timer.timeout.connect(self.update_loop)
        timer.start()
        
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)

    def initializeGL(self):
        """Initializes OpenGL and the Renderer."""
        gl.glClearColor(0.1, 0.1, 0.15, 1.0)
        self.renderer = Renderer(self.load_texture, self.grid_size, self.world_size)
        self.load_all_sprite_textures()
        
    def paintGL(self):
        """The main drawing callback. Delegates all rendering to the Renderer."""
        if not self.renderer:
            return

        if self.grid_dirty:
            self.renderer.update_grid_buffers(self.world_size, self.grid_size)
            self.grid_dirty = False

        # --- 1. Determine Camera and Projection ---
        if self.play_mode and self.player:
            self.view_matrix = self.player.get_view_matrix()
            camera_pos = self.player.pos
        else:
            self.view_matrix = self.camera.get_view_matrix()
            camera_pos = self.camera.pos
        
        aspect_ratio = self.width() / self.height() if self.height() > 0 else 0
        self.projection_matrix = perspective_projection(self.camera.fov, aspect_ratio, 0.1, 10000.0)

        # --- 2. Gather Config and Scene Data ---
        render_config = {
            "culling_enabled": self.culling_enabled,
            "brush_display_mode": self.brush_display_mode,
            "show_triggers_as_solid": self.show_triggers_as_solid,
            "show_caulk": self.editor.config.getboolean('Display', 'show_caulk', fallback=True),
            "play_mode": self.play_mode,
            "selected_object": self.selected_object,
            "time": time.time() - self.start_time,
        }

        # --- 3. Render the Scene ---
        self.renderer.render_scene(
            self.projection_matrix, self.view_matrix, camera_pos,
            self.editor.state.brushes, self.editor.state.things,
            self.selected_object,
            render_config
        )

        # --- 4. Draw UI Overlays ---
        if self.editor.config.getboolean('Display', 'show_fps', fallback=False):
            self._draw_fps_counter()

    def _draw_fps_counter(self):
        """Renders the FPS counter using QPainter."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        
        # Position the counter in the top-right corner
        rect_width = 70
        padding = 5
        rect_x = self.width() - rect_width - padding
        text_x = self.width() - rect_width
        
        painter.fillRect(rect_x, padding, rect_width, 20, QColor(0, 0, 0, 128))
        painter.drawText(text_x, 20, f"FPS: {self.fps:.0f}")
        painter.end()

    def update_grid(self):
        self.grid_dirty = True
        self.update()

    def load_texture(self, texture_name, subfolder):
        tex_cache_name = os.path.join(subfolder, texture_name)
        if tex_cache_name in self.texture_manager: return self.texture_manager[tex_cache_name]
        if texture_name == 'default.png':
            tex_id = gl.glGenTextures(1); self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id); pixels = [255, 255, 255, 255]
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 1, 1, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, (gl.GLubyte * 4)(*pixels))
            return tex_id
        if texture_name == 'caulk':
            tex_id = gl.glGenTextures(1); self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id); pixels = [255,0,255,255, 0,0,0,255, 0,0,0,255, 255,0,255,255]
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 2, 2, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, (gl.GLubyte * 16)(*pixels))
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            return tex_id
        texture_path = os.path.join('assets', subfolder, texture_name)
        if not os.path.exists(texture_path): return self.load_texture('default.png', 'textures')
        try:
            img = Image.open(texture_path).convert("RGBA"); img_data = img.tobytes()
            tex_id = gl.glGenTextures(1); self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT); gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR); gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, img.width, img.height, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, img_data)
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            return tex_id
        except Exception as e: print(f"Error loading texture '{texture_name}': {e}"); return self.load_texture('default.png', 'textures')

    def load_all_sprite_textures(self):
        things_with_sprites = {'PlayerStart': 'player.png', 'Light': 'light.png', 'Monster': 'monster.png', 'Pickup': 'pickup.png', 'Speaker': 'speaker.png'}
        for class_name, filename in things_with_sprites.items():
            tex_id = self.load_texture(filename, '')
            if tex_id: self.sprite_textures[class_name] = tex_id
        self.renderer.set_sprite_textures(self.sprite_textures)

    def update_loop(self):
        current_time = time.time()
        delta = current_time - self.last_time
        self.last_time = current_time
        self.frame_count += 1
        if current_time - self.last_fps_time > 1:
            self.fps = self.frame_count / (current_time - self.last_fps_time)
            self.frame_count = 0
            self.last_fps_time = current_time
        if self.play_mode and self.player:
            self.player.update(self.editor.keys_pressed, self.tile_map, delta)
            self.handle_triggers()
            self.update_speaker_sounds()
        elif self.hasFocus():
            self.handle_keyboard_input(delta)
        self.update()

    def set_tile_map(self, tile_map):
        self.tile_map = tile_map

    def toggle_play_mode(self, player_start_pos, player_start_angle):
        self.play_mode = not self.play_mode
        if self.play_mode:
            self.selected_object = None
            self.editor.set_selected_object(None)
            self.mouselook_active = True
            self.setCursor(Qt.BlankCursor)
            self.player = Player(
                player_start_pos[0],
                player_start_pos[2],
                np.radians(player_start_angle)
            )
            self.player.pos.y = player_start_pos[1]
            self.player_in_triggers.clear()
            self.fired_once_triggers.clear()
            self.played_once_sounds.clear()
            self.initialize_sounds()
        else:
            self.mouselook_active = False
            self.setCursor(Qt.ArrowCursor)
            self.player = None
            self.stop_all_sounds()

    def set_culling(self, enabled):
        self.culling_enabled = enabled
        self.update()
        
    def handle_triggers(self):
        if not self.player:
            return
        player_pos = self.player.pos
        currently_colliding_triggers = set()
        for i, brush in enumerate(self.editor.state.brushes):
            if not isinstance(brush, dict) or not brush.get('is_trigger'):
                continue
            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            half_size = size / 2.0
            min_bounds = pos - half_size
            max_bounds = pos + half_size
            if (min_bounds.x <= player_pos.x <= max_bounds.x and
                min_bounds.y <= player_pos.y <= max_bounds.y and
                min_bounds.z <= player_pos.z <= max_bounds.z):
                trigger_id = i
                currently_colliding_triggers.add(trigger_id)
                if trigger_id not in self.player_in_triggers:
                    self.activate_trigger(brush, trigger_id)
        self.player_in_triggers = currently_colliding_triggers
        
    def activate_trigger(self, brush, trigger_id):
        trigger_frequency = brush.get('trigger_type', 'multiple')
        if trigger_frequency == 'once' and trigger_id in self.fired_once_triggers:
            return
        target_name = brush.get('target')
        if not target_name:
            return
        target_thing = next((t for t in self.editor.state.things if hasattr(t, 'name') and t.name == target_name), None)
        if not target_thing:
            print(f"Play mode warning: Trigger target '{target_name}' not found.")
            return
        if isinstance(target_thing, Light):
            current_state = target_thing.properties.get('state', 'on')
            new_state = 'off' if current_state == 'on' else 'on'
            target_thing.properties['state'] = new_state
        elif isinstance(target_thing, Speaker):
            if target_thing.name in self.active_sounds:
                self.stop_sound_for_speaker(target_thing.name)
            else:
                self.play_sound_for_speaker(target_thing)
        if trigger_frequency == 'once':
            self.fired_once_triggers.add(trigger_id)

    def initialize_sounds(self):
        for thing in self.editor.state.things:
            if isinstance(thing, Speaker):
                is_global = thing.properties.get('global', False)
                play_on_start = thing.properties.get('play_on_start', True)
                if is_global and play_on_start:
                    self.play_sound_for_speaker(thing)
    def stop_all_sounds(self):
        for sound in self.active_sounds.values():
            sound.stop()
        self.active_sounds.clear()
    def play_sound_for_speaker(self, speaker):
        if speaker.name in self.played_once_sounds or speaker.name in self.active_sounds: return
        sound_file_rel = speaker.properties.get('sound_file')
        if not sound_file_rel: return
        sound_path = os.path.join('assets', sound_file_rel)
        if not os.path.exists(sound_path): print(f"Audio Error: Sound file not found at '{sound_path}'"); return
        sound_effect = QSoundEffect(self)
        sound_effect.setSource(QUrl.fromLocalFile(sound_path))
        sound_effect.setLoopCount(QSoundEffect.Infinite if speaker.properties.get('looping', False) else 1)
        sound_effect.setVolume(speaker.properties.get('volume', 1.0))
        if speaker.properties.get('play_once', False):
            def on_status_changed(status):
                if status == QSoundEffect.StoppedState:
                    self.played_once_sounds.add(speaker.name)
                    try: sound_effect.statusChanged.disconnect()
                    except TypeError: pass
            sound_effect.statusChanged.connect(on_status_changed)
        self.active_sounds[speaker.name] = sound_effect
        sound_effect.play()
    def stop_sound_for_speaker(self, speaker_name):
        if speaker_name in self.active_sounds:
            self.active_sounds[speaker_name].stop()
            del self.active_sounds[speaker_name]
    def update_speaker_sounds(self):
        if not self.player: return
        player_pos = self.player.pos
        for thing in self.editor.state.things:
            if isinstance(thing, Speaker) and not thing.properties.get('global', False):
                speaker_pos, radius = glm.vec3(thing.pos), thing.get_radius()
                distance = glm.distance(player_pos, speaker_pos)
                is_playing = thing.name in self.active_sounds
                if distance <= radius:
                    if not is_playing and thing.properties.get('play_on_start', True):
                        self.play_sound_for_speaker(thing)
                        is_playing = thing.name in self.active_sounds
                    if is_playing:
                        attenuation = (1.0 - (distance / radius))**2
                        final_volume = thing.properties.get('volume', 1.0) * attenuation
                        self.active_sounds[thing.name].setVolume(final_volume)
                elif is_playing:
                    self.stop_sound_for_speaker(thing.name)

    def get_selected_object_pos(self):
        if not self.editor.state.selected_object: return None
        if isinstance(self.editor.state.selected_object, dict):
            return glm.vec3(self.editor.state.selected_object['pos'])
        return glm.vec3(self.editor.state.selected_object.pos)

    def set_selected_object_pos(self, new_pos_vec):
        if not self.editor.state.selected_object: return
        grid = self.editor.grid_size_spinbox.value()
        snapped_pos_list = [round(c / grid) * grid for c in new_pos_vec]
        if isinstance(self.editor.state.selected_object, dict):
            self.editor.state.selected_object['pos'] = snapped_pos_list
        else:
            self.editor.state.selected_object.pos = snapped_pos_list

    def get_ray_from_mouse(self, x, y):
        win_x, win_y = float(x), float(self.height() - y)
        viewport = glm.vec4(0, 0, self.width(), self.height())
        near_point = glm.unProject(glm.vec3(win_x, win_y, 0.0), self.view_matrix, self.projection_matrix, viewport)
        far_point = glm.unProject(glm.vec3(win_x, win_y, 1.0), self.view_matrix, self.projection_matrix, viewport)
        ray_dir = glm.normalize(far_point - near_point)
        return near_point, ray_dir

    def intersect_ray_with_axis(self, ray_origin, ray_dir, axis_origin, axis_dir):
        cross_axis_ray = glm.cross(axis_dir, ray_dir)
        denominator = glm.dot(cross_axis_ray, cross_axis_ray)
        if abs(denominator) < 1e-6: return None, float('inf')
        t = glm.dot(glm.cross(ray_origin - axis_origin, ray_dir), cross_axis_ray) / denominator
        point_on_axis = axis_origin + t * axis_dir
        t_ray = glm.dot(point_on_axis - ray_origin, ray_dir)
        point_on_ray = ray_origin + t_ray * ray_dir
        distance = glm.distance(point_on_axis, point_on_ray)
        return point_on_axis, distance

    def handle_keyboard_input(self, delta):
        speed, keys = 300 * delta, self.editor.keys_pressed
        if any(key in keys for key in [Qt.Key_W, Qt.Key_S, Qt.Key_A, Qt.Key_D, Qt.Key_Space, Qt.Key_C]):
            if Qt.Key_W in keys: self.camera.move_forward(speed)
            if Qt.Key_S in keys: self.camera.move_forward(-speed)
            if Qt.Key_A in keys: self.camera.strafe(-speed)
            if Qt.Key_D in keys: self.camera.strafe(speed)
            if Qt.Key_Space in keys: self.camera.move_up(speed)
            if Qt.Key_C in keys: self.camera.move_up(-speed)
            self.editor.update_views()

    def get_face_at(self, mouse_pos):
        if not isinstance(self.editor.state.selected_object, dict):
            return None

        brush = self.editor.state.selected_object
        ray_origin, ray_dir = self.get_ray_from_mouse(mouse_pos.x(), mouse_pos.y())

        pos = glm.vec3(brush['pos'])
        size = glm.vec3(brush['size'])
        min_b = pos - size / 2.0
        max_b = pos + size / 2.0

        tmin = 0.0
        tmax = float('inf')

        for i in range(3):
            if abs(ray_dir[i]) < 1e-6:
                if ray_origin[i] < min_b[i] or ray_origin[i] > max_b[i]:
                    return None
            else:
                t1 = (min_b[i] - ray_origin[i]) / ray_dir[i]
                t2 = (max_b[i] - ray_origin[i]) / ray_dir[i]
                
                if t1 > t2: t1, t2 = t2, t1
                
                tmin = max(tmin, t1)
                tmax = min(tmax, t2)

        if tmin > tmax:
            return None

        intersection_point = ray_origin + ray_dir * tmin
        
        local_point = intersection_point - pos
        abs_local = abs(local_point)
        
        face_map = {
            'x': ['west', 'east'],
            'y': ['bottom', 'top'],
            'z': ['south', 'north']
        }
        
        max_coord = max(abs_local.x / size.x, abs_local.y / size.y, abs_local.z / size.z)

        face = ""
        if max_coord == abs_local.x / size.x:
            face = face_map['x'][1] if local_point.x > 0 else face_map['x'][0]
        elif max_coord == abs_local.y / size.y:
            face = face_map['y'][1] if local_point.y > 0 else face_map['y'][0]
        else:
            face = face_map['z'][1] if local_point.z > 0 else face_map['z'][0]
            
        return face

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and QApplication.keyboardModifiers() == Qt.ShiftModifier and not self.play_mode:
            face_name = self.get_face_at(event.pos())
            if face_name:
                self.editor.apply_texture_to_selected_face(face_name)
                return
                
        if event.button() == Qt.LeftButton and self.editor.state.selected_object and not self.play_mode:
            if isinstance(self.editor.state.selected_object, dict) and self.editor.state.selected_object.get('lock', False): return
            obj_pos = self.get_selected_object_pos()
            if obj_pos is None: return
            ray_origin, ray_dir = self.get_ray_from_mouse(event.x(), event.y())
            axes = {'x': glm.vec3(1, 0, 0), 'y': glm.vec3(0, 1, 0), 'z': glm.vec3(0, 0, 1)}
            gizmo_render_size = 32.0
            cam_dist = glm.distance(self.camera.pos, obj_pos)
            click_threshold = max(1.0, cam_dist * 0.025)
            min_dist_to_axis, hit_axis, hit_point = float('inf'), None, None
            for name, axis_dir in axes.items():
                point_on_axis, dist = self.intersect_ray_with_axis(ray_origin, ray_dir, obj_pos, axis_dir)
                if point_on_axis is not None:
                    dist_from_origin = glm.distance(point_on_axis, obj_pos)
                    if dist < click_threshold and dist_from_origin <= gizmo_render_size * 1.2:
                        if dist < min_dist_to_axis: min_dist_to_axis, hit_axis, hit_point = dist, name, point_on_axis
            if hit_axis:
                self.editor.save_state()
                self.is_dragging_gizmo = True
                self.gizmo_drag_axis = hit_axis
                self.gizmo_object_start_pos = obj_pos
                self.drag_start_on_axis = hit_point
                self.setCursor(Qt.ClosedHandCursor)
                return
        if not self.play_mode and event.button() == Qt.RightButton:
            self.mouselook_active, self.last_mouse_pos = True, event.pos()
            self.setCursor(Qt.BlankCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.is_dragging_gizmo:
            ray_origin, ray_dir = self.get_ray_from_mouse(event.x(), event.y())
            axis_dir = {'x': glm.vec3(1,0,0), 'y': glm.vec3(0,1,0), 'z': glm.vec3(0,0,1)}[self.gizmo_drag_axis]
            current_point_on_axis, _ = self.intersect_ray_with_axis(ray_origin, ray_dir, self.gizmo_object_start_pos, axis_dir)
            if current_point_on_axis is not None:
                displacement = current_point_on_axis - self.drag_start_on_axis
                new_pos = self.gizmo_object_start_pos + displacement
                self.set_selected_object_pos(new_pos)
                self.editor.update_all_ui()
            return
        if not self.mouselook_active:
            super().mouseMoveEvent(event)
            return
        dx, dy = event.x() - self.last_mouse_pos.x(), event.y() - self.last_mouse_pos.y()
        if self.play_mode and self.player:
            self.player.update_angle(dx, dy)
        else:
            self.camera.rotate(dx, dy)
        center_pos = self.mapToGlobal(self.rect().center())
        QCursor.setPos(center_pos)
        self.last_mouse_pos = self.mapFromGlobal(center_pos)
        self.editor.update_views()

    def mouseReleaseEvent(self, event):
        if self.is_dragging_gizmo and event.button() == Qt.LeftButton:
            self.is_dragging_gizmo = False
            self.editor.save_state()
            self.setCursor(Qt.ArrowCursor)
            return
        if event.button() == Qt.RightButton and self.mouselook_active and not self.play_mode:
            self.mouselook_active = False
            self.setCursor(Qt.ArrowCursor)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self.play_mode: return
        self.camera.fov = np.clip(self.camera.fov - event.angleDelta().y() * 0.05, 30, 120)
        self.editor.update_views()