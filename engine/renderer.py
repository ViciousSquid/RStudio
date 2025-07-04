from OpenGL.GL import *
import math

class Renderer:
    def __init__(self):
        self.gizmo_axis_vbo = None
        self.gizmo_cone_vbo = None
        self.gizmo_cone_v_count = 0
        self._create_gizmo_buffers()


    def render_scene(self, brushes, selected_brush_index):
        glPushMatrix()
        self.draw_grid()
        for i, brush in enumerate(brushes):
            is_selected = (i == selected_brush_index)
            self.draw_brush(brush, is_selected)

        if selected_brush_index != -1 and selected_brush_index < len(brushes):
            selected_brush = brushes[selected_brush_index]
            self.render_gizmo(selected_brush['pos'])

        glPopMatrix()

    def draw_grid(self):
        glBegin(GL_LINES)
        glColor3f(0.3, 0.3, 0.3)
        for i in range(-20, 21):
            glVertex3f(i * 32, 0, -640)
            glVertex3f(i * 32, 0, 640)
            glVertex3f(-640, 0, i * 32)
            glVertex3f(640, 0, i * 32)
        glEnd()

    def _draw_cube(self):
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

    def draw_brush(self, brush, is_selected):
        pos = brush['pos']
        size = brush['size']

        glPushMatrix()
        glTranslatef(pos[0], pos[1], pos[2])
        glScalef(size[0], size[1], size[2])
        
        color = [0.8, 0.8, 1.0] if is_selected else [0.5, 0.5, 0.8]
        
        glColor3f(*color)
        self._draw_cube()

        glColor3f(1, 1, 1)
        glPolygonMode(GL_FRONT_AND_BACK, GL_LINE)
        self._draw_cube()
        glPolygonMode(GL_FRONT_AND_BACK, GL_FILL)
        
        glPopMatrix()

    def _create_gizmo_buffers(self):
        # Axis lines
        axis_verts = [
            0,0,0, 1,0,0,  1,0,0, 1,0,0,
            0,0,0, 0,1,0,  0,1,0, 0,1,0,
            0,0,0, 0,0,1,  0,0,1, 0,0,1,
        ]
        
        # Cone for arrowheads
        cone_verts = []
        num_segments = 12
        radius = 0.05 * 32 # Scale arrowheads
        height = 0.2 * 32 # Scale arrowheads
        for i in range(num_segments):
            theta1 = (i / num_segments) * 2 * math.pi
            theta2 = ((i + 1) / num_segments) * 2 * math.pi
            # Base triangle
            cone_verts.extend([0,0,0,  math.cos(theta2)*radius, 0, math.sin(theta2)*radius,  math.cos(theta1)*radius, 0, math.sin(theta1)*radius])
            # Side triangle
            cone_verts.extend([0,height,0, math.cos(theta1)*radius, 0, math.sin(theta1)*radius, math.cos(theta2)*radius, 0, math.sin(theta2)*radius])

        self.gizmo_cone_v_count = len(cone_verts) // 3
        
        # We can just draw these from arrays directly in a simple app
        self.axis_verts = axis_verts
        self.cone_verts = cone_verts

    def render_gizmo(self, position):
        glPushMatrix()
        glTranslatef(position[0], position[1], position[2])
        
        # Draw axis lines
        glLineWidth(3)
        glBegin(GL_LINES)
        # X Axis (Red)
        glColor3f(1, 0, 0)
        glVertex3f(0, 0, 0)
        glVertex3f(32, 0, 0)
        # Y Axis (Green)
        glColor3f(0, 1, 0)
        glVertex3f(0, 0, 0)
        glVertex3f(0, 32, 0)
        # Z Axis (Blue)
        glColor3f(0, 0, 1)
        glVertex3f(0, 0, 0)
        glVertex3f(0, 0, 32)
        glEnd()
        glLineWidth(1)

        # Draw arrowheads
        glPushMatrix()
        # X arrowhead
        glColor3f(1, 0, 0)
        glTranslatef(32, 0, 0)
        glRotatef(-90, 0, 1, 0)
        self._draw_gizmo_cone()
        glPopMatrix()

        glPushMatrix()
        # Y arrowhead
        glColor3f(0, 1, 0)
        glTranslatef(0, 32, 0)
        glRotatef(90, 1, 0, 0)
        self._draw_gizmo_cone()
        glPopMatrix()
        
        glPushMatrix()
        # Z arrowhead
        glColor3f(0, 0, 1)
        glTranslatef(0, 0, 32)
        self._draw_gizmo_cone()
        glPopMatrix()

        glPopMatrix()
        
    def _draw_gizmo_cone(self):
        glBegin(GL_TRIANGLES)
        for i in range(0, len(self.cone_verts), 3):
            glVertex3f(self.cone_verts[i], self.cone_verts[i+1], self.cone_verts[i+2])
        glEnd()