import math
import numpy as np
import glm

class Camera:
    def __init__(self):
        self.pos = glm.vec3(0.0, 0.0, 0.0)
        self.yaw = -90.0
        self.pitch = 0.0
        self.fov = 90.0

    def get_view_matrix(self):
        """Calculates the view matrix for the camera's current position and orientation."""
        front = self.get_front_vector()
        return glm.lookAt(self.pos, self.pos + front, glm.vec3(0, 1, 0))

    def get_front_vector(self):
        """Calculates and returns the camera's normalized front vector."""
        yaw_rad = glm.radians(self.yaw)
        pitch_rad = glm.radians(self.pitch)

        front = glm.vec3(
            glm.cos(yaw_rad) * glm.cos(pitch_rad),
            glm.sin(pitch_rad),
            glm.sin(yaw_rad) * glm.cos(pitch_rad)
        )
        return glm.normalize(front)

    def rotate(self, dx, dy, sensitivity=0.1):
        """Rotates the camera based on mouse movement."""
        self.yaw += dx * sensitivity
        self.pitch -= dy * sensitivity
        self.pitch = max(-89.0, min(89.0, self.pitch))

    def move_forward(self, speed):
        """Moves the camera along its front vector, ignoring the pitch."""
        front = self.get_front_vector()
        move_vector = glm.normalize(glm.vec3(front.x, 0, front.z))
        self.pos += move_vector * speed

    def strafe(self, speed):
        """Moves the camera along its right vector."""
        front = self.get_front_vector()
        right = glm.normalize(glm.cross(front, glm.vec3(0, 1, 0)))
        self.pos += right * speed


    def move_up(self, speed):
        """Moves the camera along the world's up vector."""
        self.pos.y += speed

    def zoom(self, amount):
        """Moves the camera forward or backward along its true front vector."""
        front_vector = self.get_front_vector()
        self.pos += front_vector * amount