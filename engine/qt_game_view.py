import time
import os
import numpy as np
import ctypes
from PyQt5.QtWidgets import QOpenGLWidget, QApplication
from PyQt5.QtCore import Qt, QTimer, QPoint, QUrl
from PyQt5.QtGui import QPainter, QColor, QFont, QCursor
from PyQt5.QtMultimedia import QSoundEffect
import OpenGL.GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader
import glm
from engine.camera import Camera
from editor.things import Thing, Light, PlayerStart, Monster, Pickup, Speaker
from engine.player import Player
from PIL import Image

def perspective_projection(fov, aspect, near, far):
    if aspect == 0: return glm.mat4(1.0)
    return glm.perspective(glm.radians(fov), aspect, near, far)

# (Your existing shader code remains the same)
VERTEX_SHADER_SIMPLE = """
#version 330
layout(location = 0) in vec3 a_position;
uniform mat4 projection;
uniform mat4 view;
uniform mat4 model;
void main() {
    gl_Position = projection * view * model * vec4(a_position, 1.0);
}
"""
FRAGMENT_SHADER_SIMPLE = """
#version 330
uniform vec3 color;
out vec4 out_color;
void main() {
    out_color = vec4(color, 1.0);
}
"""
VERTEX_SHADER_LIT = """
#version 330 core
layout (location = 0) in vec3 a_pos;
layout (location = 1) in vec3 a_normal;
out vec3 FragPos;
out vec3 Normal;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    FragPos = vec3(model * vec4(a_pos, 1.0));
    Normal = mat3(transpose(inverse(model))) * a_normal;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}
"""
FRAGMENT_SHADER_LIT = """
#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
struct Light {
    vec3 position;
    vec3 color;
    float intensity;
    float radius;
};
#define MAX_LIGHTS 16
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform vec3 object_color;
uniform float alpha;
void main() {
    vec3 ambient = 0.15 * object_color;
    vec3 norm = normalize(Normal);
    vec3 total_diffuse = vec3(0.0);
    for (int i = 0; i < active_lights; i++) {
        vec3 light_dir = lights[i].position - FragPos;
        float distance = length(light_dir);
        if(distance < lights[i].radius){
            light_dir = normalize(light_dir);
            float diff = max(dot(norm, light_dir), 0.0);
            float attenuation = 1.0 - (distance / lights[i].radius);
            total_diffuse += lights[i].color * diff * lights[i].intensity * attenuation;
        }
    }
    vec3 result = ambient + (total_diffuse * object_color);
    FragColor = vec4(result, alpha);
}
"""
VERTEX_SHADER_TEXTURED = """
#version 330 core
layout (location = 0) in vec3 a_pos;
layout (location = 1) in vec3 a_normal;
layout (location = 2) in vec2 a_tex_coord;
out vec3 FragPos;
out vec3 Normal;
out vec2 TexCoord;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    FragPos = vec3(model * vec4(a_pos, 1.0));
    Normal = mat3(transpose(inverse(model))) * a_normal;
    TexCoord = a_tex_coord;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}
"""
FRAGMENT_SHADER_TEXTURED = """
#version 330 core
out vec4 FragColor;
in vec3 FragPos; in vec3 Normal; in vec2 TexCoord;
struct Light {
    vec3 position;
    vec3 color;
    float intensity;
    float radius;
};
#define MAX_LIGHTS 16
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform sampler2D texture_diffuse;
void main() {
    vec3 tex_color = texture(texture_diffuse, TexCoord).rgb;
    vec3 ambient = 0.15 * tex_color;
    vec3 norm = normalize(Normal);
    vec3 total_diffuse_light = vec3(0.0);
    for (int i = 0; i < active_lights; i++) {
        vec3 light_dir = lights[i].position - FragPos;
        float distance = length(light_dir);
        if(distance < lights[i].radius){
            light_dir = normalize(light_dir);
            float diff = max(dot(norm, light_dir), 0.0);
            float attenuation = 1.0 - (distance / lights[i].radius);
            total_diffuse_light += lights[i].color * diff * lights[i].intensity * attenuation;
        }
    }
    vec3 final_color = ambient + (total_diffuse_light * tex_color);
    FragColor = vec4(final_color, 1.0);
}
"""
VERTEX_SHADER_SPRITE = """
#version 330 core
layout (location = 0) in vec2 a_pos;
uniform mat4 projection;
uniform mat4 view;
uniform vec3 sprite_pos_world;
uniform vec2 sprite_size;
out vec2 TexCoord;
void main() {
    vec4 pos_world = vec4(sprite_pos_world, 1.0);
    vec4 pos_view = view * pos_world;
    pos_view.xy += a_pos * sprite_size;
    gl_Position = projection * pos_view;
    TexCoord = a_pos + vec2(0.5, 0.5);
    TexCoord.y = 1.0 - TexCoord.y;
}
"""
FRAGMENT_SHADER_SPRITE = """
#version 330 core
out vec4 FragColor;
in vec2 TexCoord;
uniform sampler2D sprite_texture;
void main() {
    vec4 tex_color = texture(sprite_texture, TexCoord);
    if(tex_color.a < 0.1) discard;
    FragColor = tex_color;
}
"""

class QtGameView(QOpenGLWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.brush_display_mode = "Textured"
        self.show_triggers_as_solid = False
        self.camera = Camera(); self.camera.pos = glm.vec3(0, 150, 400)
        self.grid_size, self.world_size = 16, 1024
        self.mouselook_active, self.last_mouse_pos = False, QPoint()
        self.last_time = time.time()

        self.texture_manager = {}
        self.sprite_textures = {}
        self.active_sounds = {}
        self.played_once_sounds = set()

        self.shader_simple = None; self.shader_lit = None
        self.shader_textured = None; self.shader_sprite = None

        self.vao_cube = None; self.vao_grid = None; self.vao_sprite = None
        self.grid_dirty = True

        self.culling_enabled = False
        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()

        self.play_mode = False
        self.player = None
        self.tile_map = None
        self.selected_object = None

        self.player_in_triggers = set()
        self.fired_once_triggers = set()

        timer = QTimer(self); timer.setInterval(16); timer.timeout.connect(self.update_loop); timer.start()
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)

    def set_tile_map(self, tile_map):
        self.tile_map = tile_map

    def toggle_play_mode(self, player_start_pos, player_start_angle):
        self.play_mode = not self.play_mode
        if self.play_mode:
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

    def initializeGL(self):
        gl.glClearColor(0.1, 0.1, 0.15, 1.0)
        try:
            self.shader_simple = compileProgram(compileShader(VERTEX_SHADER_SIMPLE, gl.GL_VERTEX_SHADER), compileShader(FRAGMENT_SHADER_SIMPLE, gl.GL_FRAGMENT_SHADER))
            self.shader_lit = compileProgram(compileShader(VERTEX_SHADER_LIT, gl.GL_VERTEX_SHADER), compileShader(FRAGMENT_SHADER_LIT, gl.GL_FRAGMENT_SHADER))
            self.shader_textured = compileProgram(compileShader(VERTEX_SHADER_TEXTURED, gl.GL_VERTEX_SHADER), compileShader(FRAGMENT_SHADER_TEXTURED, gl.GL_FRAGMENT_SHADER))
            self.shader_sprite = compileProgram(compileShader(VERTEX_SHADER_SPRITE, gl.GL_VERTEX_SHADER), compileShader(FRAGMENT_SHADER_SPRITE, gl.GL_FRAGMENT_SHADER))
        except Exception as e: print(f"Shader Error: {e}"); return

        self.create_cube_buffers()
        self.create_sprite_buffers()
        # Directly create the grid buffers here
        self.create_grid_buffers() 
        self.load_texture('default.png', 'textures')
        self.load_texture('caulk', 'textures')
        self.load_all_sprite_textures()

    def create_cube_buffers(self):
        # fmt: off
        vertices = np.array([
            # Positions           # Normals           # Tex Coords
            # Back Face (-Z) - South
            -0.5, -0.5, -0.5,  0.0,  0.0, -1.0,  0.0, 0.0,
             0.5, -0.5, -0.5,  0.0,  0.0, -1.0,  1.0, 0.0,
             0.5,  0.5, -0.5,  0.0,  0.0, -1.0,  1.0, 1.0,
             0.5,  0.5, -0.5,  0.0,  0.0, -1.0,  1.0, 1.0,
            -0.5,  0.5, -0.5,  0.0,  0.0, -1.0,  0.0, 1.0,
            -0.5, -0.5, -0.5,  0.0,  0.0, -1.0,  0.0, 0.0,
            # Front Face (+Z) - North
            -0.5, -0.5,  0.5,  0.0,  0.0,  1.0,  0.0, 0.0,
             0.5,  0.5,  0.5,  0.0,  0.0,  1.0,  1.0, 1.0,
             0.5, -0.5,  0.5,  0.0,  0.0,  1.0,  1.0, 0.0,
             0.5,  0.5,  0.5,  0.0,  0.0,  1.0,  1.0, 1.0,
            -0.5, -0.5,  0.5,  0.0,  0.0,  1.0,  0.0, 0.0,
            -0.5,  0.5,  0.5,  0.0,  0.0,  1.0,  0.0, 1.0,
            # Left Face (-X) - West
            -0.5,  0.5,  0.5, -1.0,  0.0,  0.0,  1.0, 0.0,
            -0.5, -0.5, -0.5, -1.0,  0.0,  0.0,  0.0, 1.0,
            -0.5,  0.5, -0.5, -1.0,  0.0,  0.0,  1.0, 1.0,
            -0.5, -0.5, -0.5, -1.0,  0.0,  0.0,  0.0, 1.0,
            -0.5,  0.5,  0.5, -1.0,  0.0,  0.0,  1.0, 0.0,
            -0.5, -0.5,  0.5, -1.0,  0.0,  0.0,  0.0, 0.0,
            # Right Face (+X) - East
             0.5,  0.5,  0.5,  1.0,  0.0,  0.0,  1.0, 0.0,
             0.5,  0.5, -0.5,  1.0,  0.0,  0.0,  1.0, 1.0,
             0.5, -0.5, -0.5,  1.0,  0.0,  0.0,  0.0, 1.0,
             0.5, -0.5, -0.5,  1.0,  0.0,  0.0,  0.0, 1.0,
             0.5, -0.5,  0.5,  1.0,  0.0,  0.0,  0.0, 0.0,
             0.5,  0.5,  0.5,  1.0,  0.0,  0.0,  1.0, 0.0,
            # Bottom Face (-Y)
            -0.5, -0.5, -0.5,  0.0, -1.0,  0.0,  0.0, 1.0,
             0.5, -0.5,  0.5,  0.0, -1.0,  0.0,  1.0, 0.0,
             0.5, -0.5, -0.5,  0.0, -1.0,  0.0,  1.0, 1.0,
             0.5, -0.5,  0.5,  0.0, -1.0,  0.0,  1.0, 0.0,
            -0.5, -0.5, -0.5,  0.0, -1.0,  0.0,  0.0, 1.0,
            -0.5, -0.5,  0.5,  0.0, -1.0,  0.0,  0.0, 0.0,
            # Top Face (+Y)
            -0.5,  0.5, -0.5,  0.0,  1.0,  0.0,  0.0, 1.0,
             0.5,  0.5, -0.5,  0.0,  1.0,  0.0,  1.0, 1.0,
             0.5,  0.5,  0.5,  0.0,  1.0,  0.0,  1.0, 0.0,
             0.5,  0.5,  0.5,  0.0,  1.0,  0.0,  1.0, 0.0,
            -0.5,  0.5,  0.5,  0.0,  1.0,  0.0,  0.0, 0.0,
            -0.5,  0.5, -0.5,  0.0,  1.0,  0.0,  0.0, 1.0
        ], dtype=np.float32)
        # fmt: on
        self.vao_cube = gl.glGenVertexArrays(1); gl.glBindVertexArray(self.vao_cube)
        vbo = gl.glGenBuffers(1); gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 32, ctypes.c_void_p(0)); gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(1, 3, gl.GL_FLOAT, gl.GL_FALSE, 32, ctypes.c_void_p(12)); gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(2, 2, gl.GL_FLOAT, gl.GL_FALSE, 32, ctypes.c_void_p(24)); gl.glEnableVertexAttribArray(2)
        gl.glBindVertexArray(0)

    def create_sprite_buffers(self):
        vertices = np.array([-0.5, -0.5, 0.5, -0.5, -0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        self.vao_sprite = gl.glGenVertexArrays(1); gl.glBindVertexArray(self.vao_sprite)
        vbo = gl.glGenBuffers(1); gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None); gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)

    def create_grid_buffers(self):
        if self.grid_size <= 0: return
        if hasattr(self, 'vao_grid') and self.vao_grid is not None: gl.glDeleteVertexArrays(1, [self.vao_grid])
        if hasattr(self, 'vbo_grid') and self.vbo_grid is not None: gl.glDeleteBuffers(1, [self.vbo_grid])
        s, g = self.world_size, self.grid_size
        lines = [[-s,0,i, s,0,i, i,0,-s, i,0,s] for i in range(-s, s + 1, g)]
        grid_vertices = np.array(lines, dtype=np.float32).flatten()
        self.grid_indices_count = len(grid_vertices) // 3
        self.vao_grid = gl.glGenVertexArrays(1); gl.glBindVertexArray(self.vao_grid)
        self.vbo_grid = gl.glGenBuffers(1); gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo_grid)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, grid_vertices.nbytes, grid_vertices, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None); gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)
        self.grid_dirty = False

    def update_grid(self):
        self.grid_dirty = True; self.update()

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

    def paintGL(self):
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS) 
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

        if self.grid_dirty:
            self.create_grid_buffers()

        if self.play_mode and self.player:
            view = self.player.get_view_matrix()
            proj = perspective_projection(self.camera.fov, self.width() / self.height() if self.height() > 0 else 0, 0.1, 10000.0)

        else:
            view = self.camera.get_view_matrix()
            proj = perspective_projection(self.camera.fov, self.width() / self.height() if self.height() > 0 else 0, 0.1, 10000.0)

        # Draw the grid first
        self.draw_grid(view, proj)

        # Prepare lists for opaque and transparent objects
        opaque_brushes = []
        transparent_objects = []
        for brush in self.editor.brushes:
            if brush.get('hidden', False):
                continue
            
            # --- MODIFICATION: Invisible triggers in play mode ---
            if self.play_mode and brush.get('is_trigger', False):
                continue

            if brush.get('is_trigger', False):
                transparent_objects.append(brush)
            else:
                opaque_brushes.append(brush)
        
        if not self.play_mode:
            transparent_objects.extend(self.editor.things)

        # Opaque Pass
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        if self.culling_enabled:
            gl.glEnable(gl.GL_CULL_FACE)
        else:
            gl.glDisable(gl.GL_CULL_FACE)

        if self.brush_display_mode == "Textured":
            self.draw_brushes_textured(view, proj, opaque_brushes)
        else:
            self.draw_brushes_lit(view, proj, opaque_brushes)
        
        # Transparent Pass
        if transparent_objects:
            camera_pos = self.camera.pos
            transparent_objects.sort(key=lambda obj: -glm.distance(glm.vec3(obj['pos'] if isinstance(obj, dict) else obj.pos), camera_pos))
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glDepthMask(gl.GL_FALSE)
            
            self.draw_sprites(view, proj, [o for o in transparent_objects if isinstance(o, Thing)])
            self.draw_brushes_lit(view, proj, [o for o in transparent_objects if isinstance(o, dict)], is_transparent_pass=True)
            
        # Reset State
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)

        # UI
        if self.editor.config.getboolean('Display', 'show_fps', fallback=False):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            font = QFont(); font.setPointSize(8)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255))
            painter.fillRect(5, 5, 70, 20, QColor(0, 0, 0, 128))
            painter.drawText(10, 20, f"FPS: {self.fps:.0f}")
            painter.end()


    def draw_grid(self, view, projection):
        if not self.shader_simple or self.vao_grid is None: return
        gl.glUseProgram(self.shader_simple)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_simple, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_simple, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_simple, "model"), 1, gl.GL_FALSE, glm.value_ptr(glm.mat4(1.0)))
        gl.glUniform3f(gl.glGetUniformLocation(self.shader_simple, "color"), 0.2, 0.2, 0.2)
        gl.glBindVertexArray(self.vao_grid)
        gl.glDrawArrays(gl.GL_LINES, 0, self.grid_indices_count)
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

    def draw_brushes_lit(self, view, projection, brushes, is_transparent_pass=False):
        if not self.shader_lit or not brushes: return
        gl.glUseProgram(self.shader_lit)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_lit, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_lit, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        lights = [t for t in self.editor.things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']
        gl.glUniform1i(gl.glGetUniformLocation(self.shader_lit, "active_lights"), len(lights))
        for i, light in enumerate(lights):
            gl.glUniform3fv(gl.glGetUniformLocation(self.shader_lit, f"lights[{i}].position"), 1, light.pos)
            gl.glUniform3fv(gl.glGetUniformLocation(self.shader_lit, f"lights[{i}].color"), 1, light.get_color())
            gl.glUniform1f(gl.glGetUniformLocation(self.shader_lit, f"lights[{i}].intensity"), light.get_intensity())
            gl.glUniform1f(gl.glGetUniformLocation(self.shader_lit, f"lights[{i}].radius"), light.get_radius())
        gl.glBindVertexArray(self.vao_cube)
        original_polygon_mode = gl.glGetIntegerv(gl.GL_POLYGON_MODE)[0]
        for brush in brushes:
            if brush.get('hidden', False):
                continue
            if is_transparent_pass: gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE if not self.show_triggers_as_solid else gl.GL_FILL)
            else: gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE if self.brush_display_mode == "Wireframe" else gl.GL_FILL)
            model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_lit, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            is_selected, is_subtract = (brush is self.selected_object), (brush.get('operation') == 'subtract')
            color, alpha = [0.8, 0.8, 0.8], 1.0
            if brush.get('is_trigger', False): color, alpha = [0.0, 1.0, 1.0], 0.3
            elif is_selected: color = [1.0, 1.0, 0.0]
            elif is_subtract: color = [1.0, 0.0, 0.0]
            gl.glUniform3fv(gl.glGetUniformLocation(self.shader_lit, "object_color"), 1, color)
            gl.glUniform1f(gl.glGetUniformLocation(self.shader_lit, "alpha"), alpha)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, original_polygon_mode)
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

    def draw_brushes_textured(self, view, projection, brushes):
        if not self.shader_textured or not brushes:
            return

        # Start with the textured shader program
        gl.glUseProgram(self.shader_textured)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        # Set uniforms that are common for all textured brushes
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_textured, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_textured, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))

        # Lighting setup
        lights = [t for t in self.editor.things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']
        gl.glUniform1i(gl.glGetUniformLocation(self.shader_textured, "active_lights"), len(lights))
        for i, light in enumerate(lights):
            gl.glUniform3fv(gl.glGetUniformLocation(self.shader_textured, f"lights[{i}].position"), 1, light.pos)
            gl.glUniform3fv(gl.glGetUniformLocation(self.shader_textured, f"lights[{i}].color"), 1, light.get_color())
            gl.glUniform1f(gl.glGetUniformLocation(self.shader_textured, f"lights[{i}].intensity"), light.get_intensity())
            gl.glUniform1f(gl.glGetUniformLocation(self.shader_textured, f"lights[{i}].radius"), light.get_radius())

        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(gl.glGetUniformLocation(self.shader_textured, "texture_diffuse"), 0)

        gl.glBindVertexArray(self.vao_cube)
        show_caulk = self.editor.config.getboolean('Display', 'show_caulk', fallback=True)

        for brush in brushes:
            if brush.get('hidden', False):
                continue

            # --- 1. Draw the textured brush itself ---
            model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_textured, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

            textures = brush.get('textures', {})
            face_keys = ['south', 'north', 'west', 'east', 'bottom', 'top']
            for i, face_key in enumerate(face_keys):
                tex_name = textures.get(face_key, 'default.png')
                if tex_name == 'caulk' and not show_caulk:
                    continue
                gl.glBindTexture(gl.GL_TEXTURE_2D, self.load_texture(tex_name, 'textures'))
                gl.glDrawArrays(gl.GL_TRIANGLES, i * 6, 6)

        # --- 2. If there's a selected object, draw its wireframe outline over everything else ---
        if self.selected_object and isinstance(self.selected_object, dict) and self.selected_object in brushes:
            brush = self.selected_object

            # Switch to the simple shader for the outline
            gl.glUseProgram(self.shader_simple)

            # Set uniforms for the simple shader
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_simple, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_simple, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
            model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_simple, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            gl.glUniform3f(gl.glGetUniformLocation(self.shader_simple, "color"), 1.0, 1.0, 0.0)  # Yellow

            # Configure GL state for wireframe drawing
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
            try:
                gl.glLineWidth(2)
            except gl.GLError:
                gl.glLineWidth(1) # Fallback if width 2 is not supported
            gl.glDisable(gl.GL_DEPTH_TEST)  # Draw on top

            # Draw the outline
            gl.glBindVertexArray(self.vao_cube)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)

            # Restore GL state
            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
            gl.glLineWidth(1)

        # Cleanup
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

    def draw_sprites(self, view, projection, things_to_draw):
        if not self.shader_sprite or not self.vao_sprite or not things_to_draw: return
        gl.glUseProgram(self.shader_sprite)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_sprite, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.shader_sprite, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glBindVertexArray(self.vao_sprite)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(gl.glGetUniformLocation(self.shader_sprite, "sprite_texture"), 0)
        for thing in things_to_draw:
            if (thing_type := thing.__class__.__name__) in self.sprite_textures:
                gl.glBindTexture(gl.GL_TEXTURE_2D, self.sprite_textures[thing_type])
                gl.glUniform3fv(gl.glGetUniformLocation(self.shader_sprite, "sprite_pos_world"), 1, thing.pos)
                size = 16.0 if isinstance(thing, Light) else 32.0
                gl.glUniform2f(gl.glGetUniformLocation(self.shader_sprite, "sprite_size"), size, size)
                gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

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

    def handle_triggers(self):
        """
        Checks for player collision with trigger volumes and activates them.
        """
        if not self.player:
            return

        player_pos = self.player.pos
        
        # A set to keep track of the triggers the player is inside THIS frame.
        currently_colliding_triggers = set()

        for i, brush in enumerate(self.editor.brushes):
            # A trigger must be a dictionary and have the 'is_trigger' key set to True
            if not isinstance(brush, dict) or not brush.get('is_trigger'):
                continue

            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            half_size = size / 2.0
            min_bounds = pos - half_size
            max_bounds = pos + half_size

            # AABB collision check
            if (min_bounds.x <= player_pos.x <= max_bounds.x and
                min_bounds.y <= player_pos.y <= max_bounds.y and
                min_bounds.z <= player_pos.z <= max_bounds.z):
                
                trigger_id = i # Use the brush's list index as its unique ID
                currently_colliding_triggers.add(trigger_id)

                # If the player was NOT in this trigger last frame, it's an "on_enter" event.
                if trigger_id not in self.player_in_triggers:
                    self.activate_trigger(brush, trigger_id)

        # Update the state for the next frame.
        self.player_in_triggers = currently_colliding_triggers
        
    def activate_trigger(self, brush, trigger_id):
        """
        Executes the action associated with a trigger.
        """
        # Respect the 'once' property. If it has fired, do nothing.
        trigger_frequency = brush.get('trigger_type', 'multiple') # Default to 'multiple'
        if trigger_frequency == 'once' and trigger_id in self.fired_once_triggers:
            return

        target_name = brush.get('target')
        if not target_name:
            return # No target to activate.

        # Find the target object by its name.
        target_thing = next((t for t in self.editor.things if hasattr(t, 'name') and t.name == target_name), None)

        if not target_thing:
            print(f"Play mode warning: Trigger target '{target_name}' not found.")
            return

        # Perform the action. This can be expanded with an 'action' property on the brush.
        if isinstance(target_thing, Light):
            current_state = target_thing.properties.get('state', 'on')
            new_state = 'off' if current_state == 'on' else 'on'
            target_thing.properties['state'] = new_state
        elif isinstance(target_thing, Speaker):
            if target_thing.name in self.active_sounds:
                self.stop_sound_for_speaker(target_thing.name)
            else:
                self.play_sound_for_speaker(target_thing)
            
        # If the trigger is 'once', record that it has been fired.
        if trigger_frequency == 'once':
            self.fired_once_triggers.add(trigger_id)

    def initialize_sounds(self):
        for thing in self.editor.things:
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
        if speaker.name in self.played_once_sounds:
            return
        if speaker.name in self.active_sounds:
            return
        
        sound_file_rel = speaker.properties.get('sound_file')
        if not sound_file_rel:
            return
        sound_path = os.path.join('assets', sound_file_rel)
        if not os.path.exists(sound_path):
            print(f"Audio Error: Sound file not found at '{sound_path}'")
            return

        sound_effect = QSoundEffect(self)
        sound_effect.setSource(QUrl.fromLocalFile(sound_path))
        sound_effect.setLoopCount(QSoundEffect.Infinite if speaker.properties.get('looping', False) else 1)
        sound_effect.setVolume(speaker.properties.get('volume', 1.0))

        if speaker.properties.get('play_once', False):
            def on_status_changed(status):
                if status == QSoundEffect.StoppedState:
                    self.played_once_sounds.add(speaker.name)
                    try:
                        sound_effect.statusChanged.disconnect()
                    except TypeError:
                        pass
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
        for thing in self.editor.things:
            if isinstance(thing, Speaker):
                if thing.properties.get('global', False):
                    continue
                
                speaker_pos = glm.vec3(thing.pos)
                radius = thing.get_radius()
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
                else:
                    if is_playing:
                        self.stop_sound_for_speaker(thing.name)

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

    def mousePressEvent(self, event):
        if not self.play_mode and event.button() == Qt.RightButton:
            self.mouselook_active, self.last_mouse_pos = True, event.pos()
            self.setCursor(Qt.BlankCursor)

    def mouseMoveEvent(self, event):
        if not self.mouselook_active: return
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
        if event.button() == Qt.RightButton and self.mouselook_active and not self.play_mode:
            self.mouselook_active = False
            self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        if self.play_mode: return
        self.camera.fov = np.clip(self.camera.fov - event.angleDelta().y() * 0.05, 30, 120)
        self.editor.update_views()