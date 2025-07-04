import time
import math
from PyQt5.QtWidgets import QOpenGLWidget, QMenu
from PyQt5.QtCore import Qt, QTimer, QPoint
from OpenGL.GL import *
from OpenGL.GLU import *
from engine.camera import Camera

class QtGameView(QOpenGLWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.camera = Camera()
        self.setFocusPolicy(Qt.StrongFocus)

        self.last_mouse_pos = None
        self.left_mouse_pressed = False
        self.middle_mouse_pressed = False
        self.right_mouse_pressed = False

        self.edit_mode = 'select'  # Modes: 'select', 'resize'
        self.resize_axis = None
        self.resize_handle_size = 0.1

        self.last_frame_time = time.time()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.game_loop)
        self.timer.start(16)  # Target ~60 FPS

    def initializeGL(self):
        glClearColor(0.2, 0.2, 0.2, 1.0)
        glEnable(GL_DEPTH_TEST)

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        # Use max(1, self.height()) to avoid division by zero
        gluPerspective(45, self.width() / max(1, self.height()), 0.1, 10000.0)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        self.camera.apply()

        self.draw_grid()
        self.draw_brushes()

        if self.edit_mode == 'resize' and self.editor.selected_brush_index != -1:
            self.render_resize_gizmos()

    def game_loop(self):
        current_time = time.time()
        delta_time = current_time - self.last_frame_time
        self.last_frame_time = current_time

        self.update_camera_movement(delta_time)
        self.update()

    def update_camera_movement(self, delta_time):
        speed = 500.0 * delta_time
        look_speed = 90.0 * delta_time

        if Qt.Key_W in self.editor.keys_pressed: self.camera.move_forward(speed)
        if Qt.Key_S in self.editor.keys_pressed: self.camera.move_forward(-speed)
        if Qt.Key_A in self.editor.keys_pressed: self.camera.strafe(-speed)
        if Qt.Key_D in self.editor.keys_pressed: self.camera.strafe(speed)
        if Qt.Key_Space in self.editor.keys_pressed: self.camera.move_up(speed)
        if Qt.Key_C in self.editor.keys_pressed: self.camera.move_up(-speed)
        if Qt.Key_Up in self.editor.keys_pressed: self.camera.pitch += look_speed
        if Qt.Key_Down in self.editor.keys_pressed: self.camera.pitch -= look_speed
        if Qt.Key_Left in self.editor.keys_pressed: self.camera.yaw -= look_speed
        if Qt.Key_Right in self.editor.keys_pressed: self.camera.yaw += look_speed

    def draw_grid(self):
        glBegin(GL_LINES)
        glColor3f(0.5, 0.5, 0.5)
        for i in range(-50, 51):
            glVertex3f(i * 10, 0, -500)
            glVertex3f(i * 10, 0, 500)
            glVertex3f(-500, 0, i * 10)
            glVertex3f(500, 0, i * 10)
        glEnd()

    def draw_cube(self, pos, size):
        x, y, z = pos
        sx, sy, sz = size
        vertices = [
            [x - sx / 2, y - sy / 2, z - sz / 2], [x + sx / 2, y - sy / 2, z - sz / 2],
            [x + sx / 2, y + sy / 2, z - sz / 2], [x - sx / 2, y + sy / 2, z - sz / 2],
            [x - sx / 2, y - sy / 2, z + sz / 2], [x + sx / 2, y - sy / 2, z + sz / 2],
            [x + sx / 2, y + sy / 2, z + sz / 2], [x - sx / 2, y + sy / 2, z + sz / 2]
        ]
        edges = [
            (0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6),
            (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7)
        ]
        glBegin(GL_LINES)
        for edge in edges:
            for vertex in edge:
                glVertex3fv(vertices[vertex])
        glEnd()

    def draw_brushes(self):
        for i, brush in enumerate(self.editor.brushes):
            if i == self.editor.selected_brush_index:
                glColor3f(1, 1, 0)  # Yellow for selected
            else:
                glColor3f(1, 1, 1)  # White for others
            self.draw_cube(brush['pos'], brush['size'])

    def render_resize_gizmos(self):
        brush = self.editor.brushes[self.editor.selected_brush_index]
        pos = brush['pos']
        size = brush['size']
        
        # X, Y, Z handles
        handles = {
            'x': ([pos[0] + size[0] / 2, pos[1], pos[2]], [1, 0, 0]),
            'y': ([pos[0], pos[1] + size[1] / 2, pos[2]], [0, 1, 0]),
            'z': ([pos[0], pos[1], pos[2] + size[2] / 2], [0, 0, 1]),
        }
        
        glDisable(GL_DEPTH_TEST)
        for axis, (h_pos, color) in handles.items():
            glColor3fv(color)
            glPushMatrix()
            glTranslatef(h_pos[0], h_pos[1], h_pos[2])
            # A simple cube for the handle
            self.draw_cube([0,0,0], [self.resize_handle_size*20, self.resize_handle_size*20, self.resize_handle_size*20])
            glPopMatrix()
        glEnable(GL_DEPTH_TEST)

    def mousePressEvent(self, event):
        self.last_mouse_pos = event.pos()
        if event.button() == Qt.LeftButton:
            self.left_mouse_pressed = True
            if self.edit_mode == 'resize':
                self.resize_axis = self.check_resize_gizmo_collision(event.pos())

        elif event.button() == Qt.MiddleButton:
            self.middle_mouse_pressed = True
        elif event.button() == Qt.RightButton:
            self.right_mouse_pressed = True
            self.show_context_menu(event.pos())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.left_mouse_pressed = False
            self.resize_axis = None
        elif event.button() == Qt.MiddleButton:
            self.middle_mouse_pressed = False
        elif event.button() == Qt.RightButton:
            self.right_mouse_pressed = False

    def mouseMoveEvent(self, event):
        if self.last_mouse_pos is None:
            self.last_mouse_pos = event.pos()
            return
            
        delta = event.pos() - self.last_mouse_pos

        if self.left_mouse_pressed and self.edit_mode == 'resize' and self.resize_axis:
            self.resize_brush(delta)
        elif self.middle_mouse_pressed:
            self.camera.pan(delta.x(), delta.y())
        elif self.right_mouse_pressed:
            self.camera.rotate(delta.x(), delta.y())
            
        self.last_mouse_pos = event.pos()

    def show_context_menu(self, pos):
        menu = QMenu(self)
        
        select_action = menu.addAction("Select Mode")
        resize_action = menu.addAction("Resize Mode")
        
        action = menu.exec_(self.mapToGlobal(pos))
        
        if action == select_action:
            self.edit_mode = 'select'
        elif action == resize_action:
            self.edit_mode = 'resize'

    def check_resize_gizmo_collision(self, pos):
        # This is a simplified implementation. A more robust solution
        # would use ray casting to check for intersection.
        # For now, we'll just return a default axis for demonstration.
        return 'x' # Defaulting to X-axis for now

    def resize_brush(self, delta):
        if self.editor.selected_brush_index == -1 or self.resize_axis is None:
            return

        brush = self.editor.brushes[self.editor.selected_brush_index]
        
        # A simple scaling based on mouse movement
        scale_factor = 0.1
        
        if self.resize_axis == 'x':
            brush['size'][0] += delta.x() * scale_factor
        elif self.resize_axis == 'y':
            brush['size'][1] += delta.y() * scale_factor
        elif self.resize_axis == 'z':
            # Need to map 2D mouse movement to depth change
            brush['size'][2] += delta.y() * scale_factor
        
        self.editor.update_views()