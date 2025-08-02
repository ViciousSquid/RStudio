import time
import os
import numpy as np
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QPainter, QColor, QFont
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader
from engine.camera import Camera
from editor.things import Thing, Light, PlayerStart, Monster, Pickup
from PIL import Image

def perspective_projection(fov, aspect, near, far):
    if aspect == 0: return np.identity(4, dtype=np.float32)
    f = 1.0 / np.tan(np.radians(fov) / 2)
    return np.array([
        [f/aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (far+near)/(near-far), (2*far*near)/(near-far)],
        [0, 0, -1, 0]
    ], dtype=np.float32)

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
        self.camera = Camera(); self.camera.pos = [0, 150, 400]
        self.grid_size, self.world_size = 16, 1024
        self.mouselook_active, self.last_mouse_pos = False, QPoint()
        self.last_time = time.time()
        
        self.texture_manager = {}
        self.sprite_textures = {}
        
        self.shader_simple = None; self.shader_lit = None
        self.shader_textured = None; self.shader_sprite = None
        
        self.vao_cube = None; self.vao_grid = None; self.vao_sprite = None
        self.grid_dirty = True
        
        self.culling_enabled = False
        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()

        timer = QTimer(self); timer.setInterval(16); timer.timeout.connect(self.update_loop); timer.start()
        self.setFocusPolicy(Qt.ClickFocus)
        self.setMouseTracking(True)

    def set_culling(self, enabled):
        self.culling_enabled = enabled
        self.update()

    def initializeGL(self):
        glClearColor(0.1, 0.1, 0.15, 1.0)
        glEnable(GL_DEPTH_TEST)
        try:
            self.shader_simple = compileProgram(compileShader(VERTEX_SHADER_SIMPLE, GL_VERTEX_SHADER), compileShader(FRAGMENT_SHADER_SIMPLE, GL_FRAGMENT_SHADER))
            self.shader_lit = compileProgram(compileShader(VERTEX_SHADER_LIT, GL_VERTEX_SHADER), compileShader(FRAGMENT_SHADER_LIT, GL_FRAGMENT_SHADER))
            self.shader_textured = compileProgram(compileShader(VERTEX_SHADER_TEXTURED, GL_VERTEX_SHADER), compileShader(FRAGMENT_SHADER_TEXTURED, GL_FRAGMENT_SHADER))
            self.shader_sprite = compileProgram(compileShader(VERTEX_SHADER_SPRITE, GL_VERTEX_SHADER), compileShader(FRAGMENT_SHADER_SPRITE, GL_FRAGMENT_SHADER))
        except Exception as e: print(f"Shader Error: {e}"); return
        
        self.create_cube_buffers()
        self.create_sprite_buffers()
        self.update_grid()
        self.load_texture('default.png', 'textures')
        self.load_texture('caulk', 'textures')
        self.load_all_sprite_textures()

    def create_cube_buffers(self):
        vertices = np.array([-0.5,-0.5,-0.5,0,0,-1,0,0,.5,-0.5,-0.5,0,0,-1,1,0,.5,.5,-0.5,0,0,-1,1,1,.5,.5,-0.5,0,0,-1,1,1,-.5,.5,-0.5,0,0,-1,0,1,-.5,-.5,-0.5,0,0,-1,0,0,-.5,-.5,.5,0,0,1,0,0,.5,-.5,.5,0,0,1,1,0,.5,.5,.5,0,0,1,1,1,.5,.5,.5,0,0,1,1,1,-.5,.5,.5,0,0,1,0,1,-.5,-.5,.5,0,0,1,0,0,-.5,.5,.5,-1,0,0,1,0,-.5,.5,-.5,-1,0,0,1,1,-.5,-.5,-.5,-1,0,0,0,1,-.5,-.5,-.5,-1,0,0,0,1,-.5,-.5,.5,-1,0,0,0,0,-.5,.5,.5,-1,0,0,1,0,.5,.5,.5,1,0,0,1,0,.5,.5,-.5,1,0,0,1,1,.5,-.5,-.5,1,0,0,0,1,.5,-.5,-.5,1,0,0,0,1,.5,-.5,.5,1,0,0,0,0,.5,.5,.5,1,0,0,1,0,-.5,-.5,-.5,0,-1,0,0,1,.5,-.5,-.5,0,-1,0,1,1,.5,-.5,.5,0,-1,0,1,0,.5,-.5,.5,0,-1,0,1,0,-.5,-.5,.5,0,-1,0,0,0,-.5,-.5,-.5,0,-1,0,0,1,-.5,.5,-.5,0,1,0,0,1,.5,.5,-.5,0,1,0,1,1,.5,.5,.5,0,1,0,1,0,.5,.5,.5,0,1,0,1,0,-.5,.5,.5,0,1,0,0,0,-.5,.5,-.5,0,1,0,0,1], dtype=np.float32)
        self.vao_cube = glGenVertexArrays(1); glBindVertexArray(self.vao_cube)
        vbo = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, vbo); glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        glVertexAttribPointer(0,3,GL_FLOAT,GL_FALSE,32,ctypes.c_void_p(0)); glEnableVertexAttribArray(0)
        glVertexAttribPointer(1,3,GL_FLOAT,GL_FALSE,32,ctypes.c_void_p(12)); glEnableVertexAttribArray(1)
        glVertexAttribPointer(2,2,GL_FLOAT,GL_FALSE,32,ctypes.c_void_p(24)); glEnableVertexAttribArray(2)
        glBindVertexArray(0)
        
    def create_sprite_buffers(self):
        vertices = np.array([-0.5, -0.5, 0.5, -0.5, -0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        self.vao_sprite = glGenVertexArrays(1); glBindVertexArray(self.vao_sprite)
        vbo = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, vbo)
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, None); glEnableVertexAttribArray(0)
        glBindVertexArray(0)

    def create_grid_buffers(self):
        if self.grid_size <= 0: return
        if self.vao_grid is not None: glDeleteVertexArrays(1, [self.vao_grid])
        if hasattr(self, 'vbo_grid') and self.vbo_grid is not None: glDeleteBuffers(1, [self.vbo_grid])
        
        s, g = self.world_size, self.grid_size
        lines = [[-s,0,i, s,0,i, i,0,-s, i,0,s] for i in range(-s, s + 1, g)]
        grid_vertices = np.array(lines, dtype=np.float32).flatten()
        self.grid_indices_count = len(grid_vertices) // 3
        self.vao_grid = glGenVertexArrays(1); glBindVertexArray(self.vao_grid)
        self.vbo_grid = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, self.vbo_grid); glBufferData(GL_ARRAY_BUFFER, grid_vertices.nbytes, grid_vertices, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None); glEnableVertexAttribArray(0)
        glBindVertexArray(0)
        self.grid_dirty = False
        
    def update_grid(self):
        self.grid_dirty = True; self.update()

    def load_texture(self, texture_name, subfolder):
        tex_cache_name = os.path.join(subfolder, texture_name)
        if tex_cache_name in self.texture_manager: return self.texture_manager[tex_cache_name]

        if texture_name == 'default.png':
            tex_id = glGenTextures(1); self.texture_manager[tex_cache_name] = tex_id
            glBindTexture(GL_TEXTURE_2D, tex_id); pixels = [255, 255, 255, 255]
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, (GLubyte * 4)(*pixels))
            return tex_id
        if texture_name == 'caulk':
            tex_id = glGenTextures(1); self.texture_manager[tex_cache_name] = tex_id
            glBindTexture(GL_TEXTURE_2D, tex_id); pixels = [255,0,255,255, 0,0,0,255, 0,0,0,255, 255,0,255,255]
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, 2, 2, 0, GL_RGBA, GL_UNSIGNED_BYTE, (GLubyte * 16)(*pixels))
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST); glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            return tex_id
            
        texture_path = os.path.join('assets', subfolder, texture_name)
        if not os.path.exists(texture_path): return self.load_texture('default.png', 'textures')
        try:
            img = Image.open(texture_path).convert("RGBA"); img_data = img.tobytes()
            tex_id = glGenTextures(1); self.texture_manager[tex_cache_name] = tex_id
            glBindTexture(GL_TEXTURE_2D, tex_id)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT); glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR); glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, img.width, img.height, 0, GL_RGBA, GL_UNSIGNED_BYTE, img_data); glGenerateMipmap(GL_TEXTURE_2D)
            return tex_id
        except Exception as e: print(f"Error loading texture '{texture_name}': {e}"); return self.load_texture('default.png', 'textures')

    def load_all_sprite_textures(self):
        things_with_sprites = {'PlayerStart': 'player.png', 'Light': 'light.png', 'Monster': 'monster.png', 'Pickup': 'pickup.png'}
        for class_name, filename in things_with_sprites.items():
            tex_id = self.load_texture(filename, '')
            if tex_id:
                self.sprite_textures[class_name] = tex_id

    def paintGL(self):
        if self.culling_enabled:
            glEnable(GL_CULL_FACE)
        else:
            glDisable(GL_CULL_FACE)

        if self.grid_dirty: self.create_grid_buffers()
        
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        view = self.camera.get_view_matrix()
        proj = perspective_projection(self.camera.fov, self.width()/self.height() if self.height()>0 else 0, 0.1, 10000.0)

        self.draw_grid(view, proj)

        opaque_brushes = []
        transparent_objects = []
        for brush in self.editor.brushes:
            if brush.get('is_trigger', False):
                transparent_objects.append(brush)
            else:
                opaque_brushes.append(brush)
        
        transparent_objects.extend(self.editor.things)

        glDepthMask(GL_TRUE)
        if self.brush_display_mode == "Textured":
            self.draw_brushes_textured(view, proj, opaque_brushes)
        else:
            self.draw_brushes_lit(view, proj, opaque_brushes)
        
        if transparent_objects:
            camera_pos = self.camera.pos
            def sort_key(obj):
                pos = obj['pos'] if isinstance(obj, dict) else obj.pos
                return -np.linalg.norm(np.array(pos) - camera_pos)
            transparent_objects.sort(key=sort_key)

            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glDepthMask(GL_FALSE)

            self.draw_sprites(view, proj, [o for o in transparent_objects if isinstance(o, Thing)])
            
            trigger_brushes = [o for o in transparent_objects if isinstance(o, dict)]
            if trigger_brushes:
                self.draw_brushes_lit(view, proj, trigger_brushes, is_transparent_pass=True)
            
            glDepthMask(GL_TRUE)
            glDisable(GL_BLEND)
        
        if self.editor.config.getboolean('Display', 'show_fps', fallback=False):
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            font = QFont()
            font.setPointSize(8)
            painter.setFont(font)
            painter.setPen(QColor(255, 255, 255))
            painter.fillRect(5, 5, 70, 20, QColor(0, 0, 0, 128))
            painter.drawText(10, 20, f"FPS: {self.fps:.0f}")
            painter.end()

    def draw_grid(self, view, projection):
        if not self.shader_simple or self.vao_grid is None: return
        glUseProgram(self.shader_simple)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_simple, "projection"), 1, GL_TRUE, projection)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_simple, "view"), 1, GL_TRUE, view)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_simple, "model"), 1, GL_TRUE, np.identity(4, dtype=np.float32))
        glUniform3f(glGetUniformLocation(self.shader_simple, "color"), 0.2, 0.2, 0.2)
        glBindVertexArray(self.vao_grid); glDrawArrays(GL_LINES, 0, self.grid_indices_count); glBindVertexArray(0); glUseProgram(0)
            
    def draw_brushes_lit(self, view, projection, brushes, is_transparent_pass=False):
        if not self.shader_lit or not brushes: return
        glUseProgram(self.shader_lit)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_lit, "projection"), 1, GL_TRUE, projection); glUniformMatrix4fv(glGetUniformLocation(self.shader_lit, "view"), 1, GL_TRUE, view)
        
        lights = [t for t in self.editor.things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']; glUniform1i(glGetUniformLocation(self.shader_lit, "active_lights"), len(lights))
        for i, light in enumerate(lights):
            glUniform3fv(glGetUniformLocation(self.shader_lit, f"lights[{i}].position"), 1, light.pos)
            glUniform3fv(glGetUniformLocation(self.shader_lit, f"lights[{i}].color"), 1, light.get_color())
            glUniform1f(glGetUniformLocation(self.shader_lit, f"lights[{i}].intensity"), light.get_intensity())
            glUniform1f(glGetUniformLocation(self.shader_lit, f"lights[{i}].radius"), light.get_radius())
        
        glBindVertexArray(self.vao_cube)
        
        for brush in brushes:
            is_trigger = brush.get('is_trigger', False)
            
            if is_transparent_pass and not self.show_triggers_as_solid:
                glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            else:
                glPolygonMode(GL_FRONT_AND_BACK, GL_LINE if self.brush_display_mode == "Wireframe" and not is_transparent_pass else GL_FILL)

            pos, size = np.array(brush['pos']), np.array(brush['size'])
            model_matrix = np.identity(4, dtype=np.float32); model_matrix[:3, :3] = np.diag(size); model_matrix[3, :3] = pos
            glUniformMatrix4fv(glGetUniformLocation(self.shader_lit, "model"), 1, GL_FALSE, model_matrix)

            is_selected = (brush == self.editor.selected_object)
            is_subtract = (brush.get('operation') == 'subtract')
            
            if is_trigger:
                color = [0, 1, 1]; alpha = 0.3
            elif is_selected:
                color = [1, 1, 0]; alpha = 1.0
            elif is_subtract:
                color = [1, 0, 0]; alpha = 1.0
            else:
                color = [0.8, 0.8, 0.8]; alpha = 1.0
            
            glUniform3fv(glGetUniformLocation(self.shader_lit, "object_color"), 1, color)
            glUniform1f(glGetUniformLocation(self.shader_lit, "alpha"), alpha)
            glDrawArrays(GL_TRIANGLES, 0, 36)
            
        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL); glBindVertexArray(0); glUseProgram(0)

    def draw_brushes_textured(self, view, projection, brushes):
        if not self.shader_textured or not brushes: return
        glUseProgram(self.shader_textured)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_textured, "projection"), 1, GL_TRUE, projection); glUniformMatrix4fv(glGetUniformLocation(self.shader_textured, "view"), 1, GL_TRUE, view)
        
        lights = [t for t in self.editor.things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']; glUniform1i(glGetUniformLocation(self.shader_textured, "active_lights"), len(lights))
        for i, light in enumerate(lights):
            glUniform3fv(glGetUniformLocation(self.shader_textured, f"lights[{i}].position"), 1, light.pos)
            glUniform3fv(glGetUniformLocation(self.shader_textured, f"lights[{i}].color"), 1, light.get_color())
            glUniform1f(glGetUniformLocation(self.shader_textured, f"lights[{i}].intensity"), light.get_intensity())
            glUniform1f(glGetUniformLocation(self.shader_textured, f"lights[{i}].radius"), light.get_radius())
        
        glActiveTexture(GL_TEXTURE0); glUniform1i(glGetUniformLocation(self.shader_textured, "texture_diffuse"), 0); glBindVertexArray(self.vao_cube)
        show_caulk = self.editor.config.getboolean('Display', 'show_caulk', fallback=True)
        
        for brush in brushes:
            pos, size = np.array(brush['pos']), np.array(brush['size'])
            model_matrix = np.identity(4, dtype=np.float32); model_matrix[:3, :3] = np.diag(size); model_matrix[3, :3] = pos
            glUniformMatrix4fv(glGetUniformLocation(self.shader_textured, "model"), 1, GL_FALSE, model_matrix)

            textures = brush.get('textures', {})
            face_keys = ['south', 'north', 'west', 'east', 'bottom', 'top']
            for i, face_key in enumerate(face_keys):
                tex_name = textures.get(face_key, 'default.png')
                if tex_name == 'caulk' and not show_caulk: continue
                tex_id = self.load_texture(tex_name, 'textures'); glBindTexture(GL_TEXTURE_2D, tex_id)
                glDrawArrays(GL_TRIANGLES, i * 6, 6)
                
        glBindVertexArray(0); glUseProgram(0)

    def draw_sprites(self, view, projection, things_to_draw):
        if not self.shader_sprite or not self.vao_sprite or not things_to_draw: return
        glUseProgram(self.shader_sprite)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_sprite, "projection"), 1, GL_TRUE, projection)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_sprite, "view"), 1, GL_TRUE, view)
        
        glBindVertexArray(self.vao_sprite); glActiveTexture(GL_TEXTURE0)
        glUniform1i(glGetUniformLocation(self.shader_sprite, "sprite_texture"), 0)

        for thing in things_to_draw:
            thing_type = thing.__class__.__name__
            if thing_type in self.sprite_textures:
                glBindTexture(GL_TEXTURE_2D, self.sprite_textures[thing_type])
                glUniform3fv(glGetUniformLocation(self.shader_sprite, "sprite_pos_world"), 1, thing.pos)
                
                size = 16.0 if isinstance(thing, Light) else 32.0
                glUniform2f(glGetUniformLocation(self.shader_sprite, "sprite_size"), size, size)
                glDrawArrays(GL_TRIANGLE_STRIP, 0, 4)

        glBindVertexArray(0); glUseProgram(0)

    def update_loop(self):
        current_time = time.time()
        delta = current_time - self.last_time
        self.last_time = current_time

        self.frame_count += 1
        if current_time - self.last_fps_time > 1:
            self.fps = self.frame_count / (current_time - self.last_fps_time)
            self.frame_count = 0
            self.last_fps_time = current_time

        if self.hasFocus(): self.handle_keyboard_input(delta)
        self.update()

    def handle_keyboard_input(self, delta):
        speed = 300 * delta
        keys = self.editor.keys_pressed
        moved = False
        if Qt.Key_W in keys: self.camera.move_forward(speed); moved = True
        if Qt.Key_S in keys: self.camera.move_forward(-speed); moved = True
        if Qt.Key_A in keys: self.camera.strafe(-speed); moved = True
        if Qt.Key_D in keys: self.camera.strafe(speed); moved = True
        if Qt.Key_Space in keys: self.camera.move_up(speed); moved = True
        if Qt.Key_C in keys: self.camera.move_up(-speed); moved = True
        
        if moved: self.editor.update_views()
        
    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.mouselook_active = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.BlankCursor)

    def mouseMoveEvent(self, event):
        if self.mouselook_active:
            dx = event.x() - self.last_mouse_pos.x()
            dy = event.y() - self.last_mouse_pos.y()
            self.camera.rotate(dx, dy)
            self.cursor().setPos(self.mapToGlobal(self.last_mouse_pos))
            self.editor.update_views()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.mouselook_active = False
            self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.camera.fov = max(30.0, self.camera.fov - 5)
        else:
            self.camera.fov = min(120.0, self.camera.fov + 5)
        self.editor.update_views()