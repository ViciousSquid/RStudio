import time
import math
from PyQt5.QtWidgets import QOpenGLWidget
from PyQt5.QtCore import Qt, QTimer
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader
import numpy as np
from engine.camera import Camera

# --- Helper functions for matrix math ---

def perspective_projection(fov, aspect, near, far):
    f = 1.0 / np.tan(np.radians(fov) / 2)
    # Creates a row-major perspective matrix
    return np.array([
        [f / aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (far + near) / (near - far), (2 * far * near) / (near - far)],
        [0, 0, -1, 0]
    ], dtype=np.float32)

# --- Shader Code ---

vertex_shader = """
#version 330
layout(location = 0) in vec3 a_position;
uniform mat4 projection;
uniform mat4 view;
uniform mat4 model;
void main() {
    gl_Position = projection * view * model * vec4(a_position, 1.0);
}
"""

fragment_shader_solid = """
#version 330
uniform vec3 color;
out vec4 out_color;
void main() {
    out_color = vec4(color, 1.0);
}
"""

class QtGameView(QOpenGLWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.brush_display_mode = "Wireframe"
        self.last_time = time.time()
        self.camera = Camera()
        self.camera.pos = [0.0, 150.0, 400.0]

        # Rendering resources
        self.shader_brush = None
        self.shader_grid = None
        self.vbo_cube, self.ebo_wire, self.ebo_solid = None, None, None
        self.solid_indices_count = 0
        self.vbo_grid, self.grid_indices_count = None, 0

        timer = QTimer(self)
        timer.setInterval(16)
        timer.timeout.connect(self.update_loop)
        timer.start()

    def initializeGL(self):
        glClearColor(0.1, 0.1, 0.15, 1.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        try:
            self.shader_brush = compileProgram(compileShader(vertex_shader, GL_VERTEX_SHADER), compileShader(fragment_shader_solid, GL_FRAGMENT_SHADER))
            self.shader_grid = compileProgram(compileShader(vertex_shader, GL_VERTEX_SHADER), compileShader(fragment_shader_solid, GL_FRAGMENT_SHADER))
        except Exception as e:
            print(f"Shader Error: {e}")
            return

        self.create_cube_buffers()
        self.create_grid_buffers()

    def create_cube_buffers(self):
        vertices = np.array([ # Centered cube vertices
            -0.5, -0.5, -0.5,  0.5, -0.5, -0.5,  0.5,  0.5, -0.5, -0.5,  0.5, -0.5,
            -0.5, -0.5,  0.5,  0.5, -0.5,  0.5,  0.5,  0.5,  0.5, -0.5,  0.5,  0.5
        ], dtype=np.float32)
        indices_wire = np.array([0,1, 1,2, 2,3, 3,0, 4,5, 5,6, 6,7, 7,4, 0,4, 1,5, 2,6, 3,7], dtype=np.uint32)
        indices_solid = np.array([0,2,1, 0,3,2, 4,5,6, 4,6,7, 0,1,5, 0,5,4, 2,3,7, 2,7,6, 1,2,6, 1,6,5, 0,7,3, 0,4,7], dtype=np.uint32)
        self.solid_indices_count = len(indices_solid)

        self.vbo_cube = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_cube)
        glBufferData(GL_ARRAY_BUFFER, vertices.nbytes, vertices, GL_STATIC_DRAW)

        self.ebo_wire = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo_wire)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices_wire.nbytes, indices_wire, GL_STATIC_DRAW)

        self.ebo_solid = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo_solid)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices_solid.nbytes, indices_solid, GL_STATIC_DRAW)

    def create_grid_buffers(self):
        grid_size = 2048
        step = 64
        lines = []
        for i in range(-grid_size, grid_size + 1, step):
            lines.extend([[-grid_size, 0, i], [grid_size, 0, i]])
            lines.extend([[i, 0, -grid_size], [i, 0, grid_size]])
        
        grid_vertices = np.array(lines, dtype=np.float32)
        self.grid_indices_count = len(grid_vertices)

        self.vbo_grid = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_grid)
        glBufferData(GL_ARRAY_BUFFER, grid_vertices.nbytes, grid_vertices, GL_STATIC_DRAW)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        
        # Get matrices
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        self.camera.apply()
        view_matrix = glGetFloatv(GL_MODELVIEW_MATRIX)
        projection_matrix = perspective_projection(45.0, self.width() / self.height(), 0.1, 10000.0)

        # Draw Grid
        self.draw_grid(view_matrix, projection_matrix)
        
        # Draw Brushes
        self.draw_brushes(view_matrix, projection_matrix)

    def draw_grid(self, view, projection):
        glUseProgram(self.shader_grid)
        # Set uniforms
        glUniformMatrix4fv(glGetUniformLocation(self.shader_grid, "projection"), 1, GL_TRUE, projection)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_grid, "view"), 1, GL_FALSE, view)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_grid, "model"), 1, GL_FALSE, np.identity(4, dtype=np.float32))
        glUniform3f(glGetUniformLocation(self.shader_grid, "color"), 0.2, 0.2, 0.2)

        # Bind and draw
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_grid)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)
        glEnableVertexAttribArray(0)
        glDrawArrays(GL_LINES, 0, self.grid_indices_count)

    def draw_brushes(self, view, projection):
        glUseProgram(self.shader_brush)
        
        # Set view/projection uniforms (these are the same for all brushes)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_brush, "projection"), 1, GL_TRUE, projection)
        glUniformMatrix4fv(glGetUniformLocation(self.shader_brush, "view"), 1, GL_FALSE, view)
        model_loc = glGetUniformLocation(self.shader_brush, "model")
        color_loc = glGetUniformLocation(self.shader_brush, "color")

        # Bind cube vertex data
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_cube)
        glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 0, None)
        glEnableVertexAttribArray(0)

        # Select solid or wireframe drawing mode
        if self.brush_display_mode == "Wireframe":
            glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo_wire)
        else: # Solid or Textured
            glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
            glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo_solid)

        # Loop through and draw each brush
        for i, brush in enumerate(self.editor.brushes):
            pos, size = np.array(brush['pos']), np.array(brush['size'])
            
            # Create model matrix (translate and scale) - this is row-major
            model_matrix = np.identity(4, dtype=np.float32)
            model_matrix[0,0], model_matrix[1,1], model_matrix[2,2] = size[0], size[1], size[2]
            model_matrix[3,0], model_matrix[3,1], model_matrix[3,2] = pos[0], pos[1], pos[2]
            
            # Set model-specific uniforms
            glUniformMatrix4fv(model_loc, 1, GL_TRUE, model_matrix) # Use GL_TRUE because model_matrix is row-major
            
            color = [0.8, 0.2, 0.2] if i == self.editor.selected_brush_index else ([0.2, 0.2, 0.8] if brush.get('operation') == 'subtract' else [0.8, 0.8, 0.8])
            glUniform3fv(color_loc, 1, color)
            
            # Draw call
            if self.brush_display_mode == "Wireframe":
                glDrawElements(GL_LINES, 24, GL_UNSIGNED_INT, None)
            else:
                glDrawElements(GL_TRIANGLES, self.solid_indices_count, GL_UNSIGNED_INT, None)
        
        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL) # Reset to default

    def update_loop(self):
        self.last_time = time.time()
        self.handle_input(time.time() - self.last_time)
        self.update()

    def handle_input(self, delta_time):
        keys = self.editor.keys_pressed
        move_speed = 300.0 * delta_time # Increased speed
        
        if Qt.Key_W in keys: self.camera.move_forward(move_speed)
        if Qt.Key_S in keys: self.camera.move_forward(-move_speed)
        if Qt.Key_A in keys: self.camera.strafe(-move_speed)
        if Qt.Key_D in keys: self.camera.strafe(move_speed)
        if Qt.Key_Space in keys: self.camera.move_up(move_speed)
        if Qt.Key_Shift in keys: self.camera.move_up(-move_speed)
        
        dx, dy = 0, 0
        rotate_speed = 2.0 # Adjusted for direct rotation

        if Qt.Key_Left in keys: dx = -rotate_speed
        if Qt.Key_Right in keys: dx = rotate_speed
        if Qt.Key_Up in keys: dy = -rotate_speed 
        if Qt.Key_Down in keys: dy = rotate_speed

        if dx != 0 or dy != 0:
            self.camera.rotate(dx, dy)