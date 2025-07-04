# engine/camera.py
import math
from OpenGL.GL import *

class Camera:
    def __init__(self):
        self.pos = [0, 5, 20]
        self.yaw = -90.0  # Rotation around the Y-axis
        self.pitch = 0.0  # Rotation around the X-axis

    def apply(self):
        """Applies the camera transformations to the OpenGL matrix stack."""
        glRotatef(self.pitch, 1, 0, 0)
        glRotatef(self.yaw, 0, 1, 0)
        glTranslatef(-self.pos[0], -self.pos[1], -self.pos[2])

    def move_forward(self, distance):
        """Moves the camera forward or backward along its direction."""
        rad_yaw = math.radians(self.yaw)
        self.pos[0] += distance * math.cos(rad_yaw)
        self.pos[2] += distance * math.sin(rad_yaw)

    def strafe(self, distance):
        """Moves the camera left or right relative to its direction."""
        rad_yaw = math.radians(self.yaw)
        self.pos[0] += distance * math.sin(rad_yaw)
        self.pos[2] -= distance * math.cos(rad_yaw)

    def move_up(self, distance):
        """Moves the camera directly up or down."""
        self.pos[1] += distance

    def rotate(self, dx, dy):
        """Rotates the camera's view based on mouse movement."""
        sensitivity = 0.1
        self.yaw += dx * sensitivity
        self.pitch -= dy * sensitivity

        # Clamp pitch to avoid flipping
        if self.pitch > 89.0:
            self.pitch = 89.0
        if self.pitch < -89.0:
            self.pitch = -89.0

    def pan(self, dx, dy):
        """Pans the camera left/right and up/down."""
        pan_speed = 0.05
        rad_yaw = math.radians(self.yaw)
        
        # Pan right/left
        self.pos[0] -= dx * pan_speed * math.sin(rad_yaw)
        self.pos[2] += dx * pan_speed * math.cos(rad_yaw)
        
        # Pan up/down
        self.pos[1] += dy * pan_speed