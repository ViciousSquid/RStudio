import time
import math
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import Qt, QTimer, QPoint
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GL.shaders import compileProgram, compileShader
import numpy as np
import ctypes
from engine.camera import Camera
from editor.things import Light, PlayerStart
from PyQt5.QtGui import QImage, QPixmap

# --- Matrix Math Helper ---
def perspective_projection(fov, aspect, near, far):
    if aspect == 0: return np.identity(4, dtype=np.float32)
    f = 1.0 / np.tan(np.radians(fov) / 2)
    return np.array([[f/aspect,0,0,0], [0,f,0,0], [0,0,(far+near)/(near-far), (2*far*near)/(near-far)], [0,0,-1,0]], dtype=np.float32)

# --- Shaders ---
vertex_shader_simple = """
#version 330
layout(location = 0) in vec3 a_position;
uniform mat4 projection;
uniform mat4 view;
uniform mat4 model;
void main() {
    gl_Position = projection * view * model * vec4(a_position, 1.0);
}
"""
fragment_shader_simple = """
#version 330
uniform vec3 color;
out vec4 out_color;
void main() {
    out_color = vec4(color, 1.0);
}
"""
vertex_shader_lit = """
#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
out vec3 FragPos;
out vec3 Normal;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main()
{
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = mat3(transpose(inverse(model))) * aNormal;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}
"""
fragment_shader_lit = """
#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
struct Light {
    vec3 position;
    vec3 color;
    float intensity;
};
#define MAX_LIGHTS 16
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform vec3 object_color;
void main()
{
    vec3 ambient = 0.15 * object_color;
    vec3 total_diffuse = vec3(0.0);
    vec3 norm = normalize(Normal);
    for (int i = 0; i < active_lights; i++) {
        vec3 light_dir = normalize(lights[i].position - FragPos);
        float diff = max(dot(norm, light_dir), 0.0);
        total_diffuse += lights[i].color * diff * lights[i].intensity;
    }
    vec3 result = ambient + (total_diffuse * object_color);
    FragColor = vec4(result, 1.0);
}
"""
vertex_shader_sprite = """
#version 330 core
layout (location = 0) in vec2 aPos;
layout (location = 1) in vec2 aTexCoords;

out vec2 TexCoords;

uniform mat4 projection;
uniform mat4 view;
uniform vec3 modelPos;
uniform vec2 scale;

void main()
{
    TexCoords = aTexCoords;
    vec4 position = view * vec4(modelPos, 1.0);
    position.xy += aPos * scale;
    gl_Position = projection * position;
}
"""
fragment_shader_sprite = """
#version 330 core
out vec4 FragColor;
in vec2 TexCoords;
uniform sampler2D sprite;
uniform vec3 color;

void main()
{
    FragColor = texture(sprite, TexCoords) * vec4(color, 1.0);
}
"""

class QtGameView(QOpenGLWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.render_mode = "Modern (Shaders)"
        self.brush_display_mode = "Solid Lit"
        self.camera = Camera(); self.camera.pos = [0.0, 150.0, 400.0]
        self.grid_size, self.world_size = 16, 1024
        self.mouselook_active, self.last_mouse_pos = False, QPoint()
        self.last_time = time.time()
        self.textures_loaded = False
        timer = QTimer(self); timer.setInterval(16); timer.timeout.connect(self.update_loop); timer.start()
        self.setFocusPolicy(Qt.ClickFocus)

    def initializeGL(self):
        glClearColor(0.1, 0.1, 0.15, 1.0)
        glEnable(GL_DEPTH_TEST); glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        try:
            self.shader_simple = compileProgram(compileShader(vertex_shader_simple, GL_VERTEX_SHADER), compileShader(fragment_shader_simple, GL_FRAGMENT_SHADER))
            self.shader_lit = compileProgram(compileShader(vertex_shader_lit, GL_VERTEX_SHADER), compileShader(fragment_shader_lit, GL_FRAGMENT_SHADER))
            self.shader_sprite = compileProgram(compileShader(vertex_shader_sprite, GL_VERTEX_SHADER), compileShader(fragment_shader_sprite, GL_FRAGMENT_SHADER))
        except Exception as e: print(f"Shader Error: {e}"); return
        self.create_cube_buffers()
        self.create_grid_buffers()
        self.create_sprite_buffers()

    def create_cube_buffers(self):
        # Data for a lit cube (with normals)
        lit_vertices = np.array([
            -0.5,-0.5,-0.5, 0,0,-1,  0.5,-0.5,-0.5, 0,0,-1,  0.5,0.5,-0.5, 0,0,-1,  0.5,0.5,-0.5, 0,0,-1, -0.5,0.5,-0.5, 0,0,-1, -0.5,-0.5,-0.5, 0,0,-1,
            -0.5,-0.5,0.5, 0,0,1,    0.5,-0.5,0.5, 0,0,1,    0.5,0.5,0.5, 0,0,1,    0.5,0.5,0.5, 0,0,1,   -0.5,0.5,0.5, 0,0,1,   -0.5,-0.5,0.5, 0,0,1,
            -0.5,0.5,0.5, -1,0,0,   -0.5,0.5,-0.5, -1,0,0,  -0.5,-0.5,-0.5, -1,0,0,-0.5,-0.5,-0.5, -1,0,0,-0.5,-0.5,0.5, -1,0,0,  -0.5,0.5,0.5, -1,0,0,
             0.5,0.5,0.5, 1,0,0,     0.5,0.5,-0.5, 1,0,0,   0.5,-0.5,-0.5, 1,0,0,   0.5,-0.5,-0.5, 1,0,0,  0.5,-0.5,0.5, 1,0,0,    0.5,0.5,0.5, 1,0,0,
            -0.5,-0.5,-0.5, 0,-1,0,  0.5,-0.5,-0.5, 0,-1,0,  0.5,-0.5,0.5, 0,-1,0,   0.5,-0.5,0.5, 0,-1,0, -0.5,-0.5,0.5, 0,-1,0,  -0.5,-0.5,-0.5, 0,-1,0,
            -0.5,0.5,-0.5, 0,1,0,    0.5,0.5,-0.5, 0,1,0,    0.5,0.5,0.5, 0,1,0,     0.5,0.5,0.5, 0,1,0,  -0.5,0.5,0.5, 0,1,0,   -0.5,0.5,-0.5, 0,1,0
        ], dtype=np.float32)

        # Data for a simple wireframe cube
        simple_vertices = np.array([-0.5,-0.5,-0.5, 0.5,-0.5,-0.5, 0.5,0.5,-0.5, -0.5,0.5,-0.5, -0.5,-0.5,0.5, 0.5,-0.5,0.5, 0.5,0.5,0.5, -0.5,0.5,0.5], dtype=np.float32)
        wire_indices = np.array([0,1,1,2,2,3,3,0, 4,5,5,6,6,7,7,4, 0,4,1,5,2,6,3,7], dtype=np.uint32)

        # VAO for the lit cube
        self.vao_lit_cube = glGenVertexArrays(1)
        glBindVertexArray(self.vao_lit_cube)
        self.vbo_lit_cube = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_lit_cube)
        glBufferData(GL_ARRAY_BUFFER, lit_vertices.nbytes, lit_vertices, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(0))
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, 24, ctypes.c_void_p(12))
        glEnableVertexAttribArray(1)

        # VAO for the wireframe cube
        self.vao_wire_cube = glGenVertexArrays(1)
        glBindVertexArray(self.vao_wire_cube)
        self.vbo_simple_cube = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_simple_cube)
        glBufferData(GL_ARRAY_BUFFER, simple_vertices.nbytes, simple_vertices, GL_STATIC_DRAW)
        self.ebo_wire = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo_wire)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, wire_indices.nbytes, wire_indices, GL_STATIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)
        glEnableVertexAttribArray(0)

        glBindVertexArray(0)


    def create_grid_buffers(self):
        if self.grid_size <= 0: return
        s, g = self.world_size, self.grid_size
        lines = []
        for i in range(-s, s + 1, g):
            lines.extend([[-s, 0, i], [s, 0, i], [i, 0, -s], [i, 0, s]])

        grid_vertices = np.array(lines, dtype=np.float32)
        self.grid_indices_count = len(grid_vertices)

        if not hasattr(self, 'vao_grid'):
            self.vao_grid = glGenVertexArrays(1)

        glBindVertexArray(self.vao_grid)
        if not hasattr(self, 'vbo_grid'):
            self.vbo_grid = glGenBuffers(1)

        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_grid)
        glBufferData(GL_ARRAY_BUFFER, grid_vertices.nbytes, grid_vertices, GL_DYNAMIC_DRAW)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)
        glEnableVertexAttribArray(0)
        glBindVertexArray(0)


    def create_sprite_buffers(self):
        vertices = np.array([
            -0.5,  0.5, 0.0, 1.0, # Top-left
            -0.5, -0.5, 0.0, 0.0, # Bottom-left
             0.5, -0.5, 1.0, 0.0, # Bottom-right
             0.5,  0.5, 1.0, 1.0  # Top-right
        ], dtype=np.float32)
        indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)

        self.vao_sprite = glGenVertexArrays(1); glBindVertexArray(self.vao_sprite)
        self.vbo_sprite = glGenBuffers(1); glBindBuffer(GL_ARRAY_BUFFER, self.vbo_sprite); glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)
        self.ebo_sprite = glGenBuffers(1); glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo_sprite); glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(0)); glEnableVertexAttribArray(0)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 16, ctypes.c_void_p(8)); glEnableVertexAttribArray(1)
        glBindVertexArray(0)

    def load_textures(self):
        # Ensure pixmaps are loaded by creating dummy instances if needed
        if Light.pixmap is None: Light(pos=[0,0,0])
        if PlayerStart.pixmap is None: PlayerStart(pos=[0,0,0])

        self.light_texture = self.load_texture_from_qpixmap(Light.pixmap)
        self.player_texture = self.load_texture_from_qpixmap(PlayerStart.pixmap)
        self.textures_loaded = True

    def load_texture_from_qpixmap(self, pixmap):
        if pixmap is None or pixmap.isNull():
            print("Failed to load texture: pixmap is null.")
            return 0

        image = pixmap.toImage().convertToFormat(QImage.Format_RGBA8888)

        tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, image.width(), image.height(), 0, GL_RGBA, GL_UNSIGNED_BYTE, image.bits().asstring(image.byteCount()))
        return tex_id


    def paintGL(self):
        if not self.textures_loaded:
            self.load_textures()

        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        if self.height() == 0:
            return

        view_matrix = self.camera.get_view_matrix()
        projection_matrix = perspective_projection(45.0, self.width()/self.height(), 0.1, 10000.0)

        self.draw_grid(view_matrix, projection_matrix)
        self.draw_brushes(view_matrix, projection_matrix)
        self.draw_things(view_matrix, projection_matrix)

    def draw_grid(self, view, projection):
        glUseProgram(self.shader_simple)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_simple, "projection"), 1, GL_TRUE, projection)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_simple, "view"), 1, GL_TRUE, view)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_simple, "model"), 1, GL_TRUE, np.identity(4, dtype=np.float32))
        glUniform3f(glGetUniformLocation(self.shader_simple, "color"), 0.2, 0.2, 0.2)

        if hasattr(self, 'vao_grid'):
            glBindVertexArray(self.vao_grid)
            glDrawArrays(GL_LINES, 0, self.grid_indices_count)
            glBindVertexArray(0)
        glUseProgram(0)

    def draw_brushes(self, view, projection):
        if self.render_mode == "Immediate (Legacy)":
            self.draw_brushes_immediate(view, projection)
        elif self.brush_display_mode == "Wireframe":
            self.draw_brushes_simple(view, projection)
        else:
            self.draw_brushes_lit(view, projection)

    def _draw_cube_immediate(self):
        glBegin(GL_QUADS)
        # Front Face
        glVertex3f(-0.5, -0.5, 0.5); glVertex3f(0.5, -0.5, 0.5); glVertex3f(0.5, 0.5, 0.5); glVertex3f(-0.5, 0.5, 0.5)
        # Back Face
        glVertex3f(-0.5, -0.5, -0.5); glVertex3f(-0.5, 0.5, -0.5); glVertex3f(0.5, 0.5, -0.5); glVertex3f(0.5, -0.5, -0.5)
        # Top Face
        glVertex3f(-0.5, 0.5, -0.5); glVertex3f(-0.5, 0.5, 0.5); glVertex3f(0.5, 0.5, 0.5); glVertex3f(0.5, 0.5, -0.5)
        # Bottom Face
        glVertex3f(-0.5, -0.5, -0.5); glVertex3f(0.5, -0.5, -0.5); glVertex3f(0.5, -0.5, 0.5); glVertex3f(-0.5, -0.5, 0.5)
        # Right face
        glVertex3f(0.5, -0.5, -0.5); glVertex3f(0.5, 0.5, -0.5); glVertex3f(0.5, 0.5, 0.5); glVertex3f(0.5, -0.5, 0.5)
        # Left Face
        glVertex3f(-0.5, -0.5, -0.5); glVertex3f(-0.5, -0.5, 0.5); glVertex3f(-0.5, 0.5, 0.5); glVertex3f(-0.5, 0.5, -0.5)
        glEnd()

    def draw_brushes_immediate(self, view, projection):
        glUseProgram(0) # Ensure no shaders are active
        
        glMatrixMode(GL_PROJECTION)
        glLoadMatrixf(np.transpose(projection))

        glMatrixMode(GL_MODELVIEW)
        glLoadMatrixf(np.transpose(view))

        for brush in self.editor.brushes:
            pos, size = brush['pos'], brush['size']
            is_selected = (brush == self.editor.selected_object)
            is_subtract = (brush.get('operation') == 'subtract')

            glPushMatrix()
            glTranslatef(pos[0], pos[1], pos[2])
            glScalef(size[0], size[1], size[2])

            # Draw filled cube
            color = [1.0,0.4,0.4] if is_selected else ([0.4,0.4,1.0] if is_subtract else [0.8,0.8,0.8])
            glColor3f(*color)
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            self._draw_cube_immediate()

            # Draw wireframe outline
            glColor3f(0.1, 0.1, 0.1)
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            glLineWidth(2)
            self._draw_cube_immediate()
            glLineWidth(1)
            
            glPopMatrix()
        
        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL) # Reset polygon mode

    def draw_brushes_lit(self, view, projection):
        glUseProgram(self.shader_lit)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_lit, "projection"), 1, GL_TRUE, projection)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_lit, "view"), 1, GL_TRUE, view)

        lights = [thing for thing in self.editor.things if isinstance(thing, Light)]
        glUniform1i(glGetUniformLocation(self.shader_lit, "active_lights"), len(lights))
        for i, light in enumerate(lights):
            glUniform3fv(glGetUniformLocation(self.shader_lit, f"lights[{i}].position"), 1, light.pos)
            glUniform3fv(glGetUniformLocation(self.shader_lit, f"lights[{i}].color"), 1, light.get_color())
            glUniform1f(glGetUniformLocation(self.shader_lit, f"lights[{i}].intensity"), light.properties.get('intensity', 1.0))

        glBindVertexArray(self.vao_lit_cube)
        for brush in self.editor.brushes:
            pos, size = np.array(brush['pos']), np.array(brush['size'])
            scale_matrix = np.diag([size[0], size[1], size[2], 1])
            trans_matrix = np.identity(4); trans_matrix[3, 0:3] = pos
            model_matrix = scale_matrix @ trans_matrix
            glUniformMatrix4fv(glGetUniformLocation(self.shader_lit, "model"), 1, GL_TRUE, model_matrix)

            is_selected = (brush == self.editor.selected_object)
            is_subtract = (brush.get('operation') == 'subtract')
            color = [1.0,0.4,0.4] if is_selected else ([0.4,0.4,1.0] if is_subtract else [0.8,0.8,0.8])
            glUniform3fv(glGetUniformLocation(self.shader_lit, "object_color"), 1, color)
            glDrawArrays(GL_TRIANGLES, 0, 36)
        glBindVertexArray(0)
        glUseProgram(0)

    def draw_brushes_simple(self, view, projection):
        glUseProgram(self.shader_simple)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_simple, "projection"), 1, GL_TRUE, projection)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_simple, "view"), 1, GL_TRUE, view)
        color_loc, model_loc = glGetUniformLocation(self.shader_simple, "color"), glGetUniformLocation(self.shader_simple, "model")

        glBindVertexArray(self.vao_wire_cube)
        for brush in self.editor.brushes:
            pos, size = np.array(brush['pos']), np.array(brush['size'])
            scale_matrix = np.diag([size[0], size[1], size[2], 1])
            trans_matrix = np.identity(4); trans_matrix[3, 0:3] = pos
            model_matrix = scale_matrix @ trans_matrix
            glUniformMatrix4fv(model_loc, 1, GL_TRUE, model_matrix)

            is_selected = (brush == self.editor.selected_object)
            is_subtract = (brush.get('operation') == 'subtract')
            color = [0.8,0.2,0.2] if is_selected else ([0.2,0.2,0.8] if is_subtract else [0.8,0.8,0.8])
            glUniform3fv(color_loc, 1, color)
            glDrawElements(GL_LINES, 24, GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        glUseProgram(0)

    def draw_things(self, view, projection):
        glUseProgram(self.shader_sprite)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_sprite, "projection"), 1, GL_TRUE, projection)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_sprite, "view"), 1, GL_TRUE, view)
        glUniform2f(glGetUniformLocation(self.shader_sprite, "scale"), 24, 24)

        glActiveTexture(GL_TEXTURE0)
        glUniform1i(glGetUniformLocation(self.shader_sprite, "sprite"), 0)

        glBindVertexArray(self.vao_sprite)
        for thing in self.editor.things:
            if isinstance(thing, Light):
                glBindTexture(GL_TEXTURE_2D, self.light_texture)
                color = thing.get_color()
            elif isinstance(thing, PlayerStart):
                glBindTexture(GL_TEXTURE_2D, self.player_texture)
                color = [1.0, 1.0, 1.0]
            else:
                continue

            glUniform3fv(glGetUniformLocation(self.shader_sprite, "modelPos"), 1, thing.pos)
            final_color = [c * 1.5 for c in color] if thing == self.editor.selected_object else color
            glUniform3fv(glGetUniformLocation(self.shader_sprite, "color"), 1, final_color)
            glDrawElements(GL_TRIANGLES, 6, GL_UNSIGNED_INT, None)

        glBindVertexArray(0)
        glUseProgram(0)


    def update_loop(self):
        delta = time.time() - self.last_time; self.last_time = time.time()
        if self.hasFocus():
            self.handle_keyboard_input(delta)
        self.update()

    def handle_keyboard_input(self, delta_time):
        keys = self.editor.keys_pressed
        speed = 300 * delta_time

        if Qt.Key_W in keys or Qt.Key_Up in keys: self.camera.move_forward(speed)
        if Qt.Key_S in keys or Qt.Key_Down in keys: self.camera.move_forward(-speed)
        if Qt.Key_A in keys or Qt.Key_Left in keys: self.camera.strafe(-speed)
        if Qt.Key_D in keys or Qt.Key_Right in keys: self.camera.strafe(speed)
        if Qt.Key_Space in keys: self.camera.move_up(speed)
        if Qt.Key_C in keys: self.camera.move_up(-speed)

    def mousePressEvent(self, event):
        if event.modifiers() & Qt.ShiftModifier and event.button() == Qt.LeftButton:
            obj, dist = self.get_object_at_screen_pos(event.x(), event.y())
            if obj:
                print(f"Selected {type(obj).__name__} at distance {dist}")
                self.editor.set_selected_object(obj)
            else:
                self.editor.set_selected_object(None)
            return

        if event.button() == Qt.RightButton:
            self.mouselook_active = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.BlankCursor)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.mouselook_active:
            dx = event.x() - self.last_mouse_pos.x()
            dy = event.y() - self.last_mouse_pos.y()
            self.camera.rotate(dx, dy)
            cursor_pos = self.mapToGlobal(self.last_mouse_pos)
            self.cursor().setPos(cursor_pos)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.mouselook_active = False
            self.setCursor(Qt.ArrowCursor)
        else:
            super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        scroll_delta = event.angleDelta().y()
        zoom_amount = scroll_delta * 0.5
        self.camera.zoom(zoom_amount)
        self.update()

    def update_grid(self):
        if self.isValid():
            self.create_grid_buffers()
        self.update()

    def get_object_at_screen_pos(self, x, y):
        height = self.height()
        if height == 0: return None, float('inf')

        ndc_x = (2.0 * x) / self.width() - 1.0
        ndc_y = 1.0 - (2.0 * y) / height

        proj_matrix = perspective_projection(45.0, self.width()/height, 0.1, 10000.0)
        view_matrix = self.camera.get_view_matrix()

        try:
            inv_proj = np.linalg.inv(proj_matrix)
            inv_view = np.linalg.inv(view_matrix)
        except np.linalg.LinAlgError:
            return None, float('inf')

        clip_coords = np.array([ndc_x, ndc_y, -1.0, 1.0])
        eye_coords = inv_proj @ clip_coords
        eye_coords = np.array([eye_coords[0], eye_coords[1], -1.0, 0.0])
        world_coords = inv_view @ eye_coords

        ray_dir = np.array([world_coords[0], world_coords[1], world_coords[2]])
        ray_dir = ray_dir / np.linalg.norm(ray_dir)
        ray_origin = self.camera.pos

        closest_obj = None
        min_dist = float('inf')

        all_objects = self.editor.brushes + self.editor.things

        for obj in all_objects:
            if isinstance(obj, dict): # Brush
                pos, size = obj['pos'], obj['size']
            elif isinstance(obj, (PlayerStart, Light)):
                pos, size = obj.pos, [16,16,16]
            else:
                continue

            dist = self.ray_intersect_aabb(ray_origin, ray_dir, np.array(pos), np.array(size))
            if dist is not None and dist < min_dist:
                min_dist = dist
                closest_obj = obj

        return closest_obj, min_dist

    def ray_intersect_aabb(self, ray_origin, ray_dir, box_center, box_size):
        box_min = box_center - box_size / 2
        box_max = box_center + box_size / 2

        with np.errstate(divide='ignore'):
            inv_dir = 1.0 / ray_dir

        tmin = (box_min - ray_origin) * inv_dir
        tmax = (box_max - ray_origin) * inv_dir

        t_enter = np.max(np.minimum(tmin, tmax))
        t_exit = np.min(np.maximum(tmin, tmax))

        if t_exit < t_enter or t_exit < 0:
            return None

        return t_enter if t_enter > 0 else t_exit