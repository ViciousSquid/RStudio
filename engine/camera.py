import math
import numpy as np

class Camera:
    def __init__(self):
        self.pos = [0.0, 0.0, 0.0]
        self.yaw = -90.0  # Looking down the negative Z-axis
        self.pitch = 0.0
        self.fov = 90.0  # --- THIS IS THE NEWLY ADDED LINE ---

    def get_view_matrix(self):
        """Calculates the view matrix for the camera's current position and orientation."""
        front = self.get_front_vector()

        # Calculate right and up vectors
        world_up = np.array([0.0, 1.0, 0.0])
        right = np.cross(front, world_up)
        right = right / np.linalg.norm(right)

        up = np.cross(right, front)
        up = up / np.linalg.norm(up)

        # Create the look-at matrix
        target = np.array(self.pos) + front

        # Manual implementation of a look-at matrix
        cam_pos = np.array(self.pos)
        z_axis = (cam_pos - target) / np.linalg.norm(cam_pos - target)
        x_axis = np.cross(world_up, z_axis) / np.linalg.norm(np.cross(world_up, z_axis))
        y_axis = np.cross(z_axis, x_axis)

        translation = np.identity(4)
        translation[0, 3] = -cam_pos[0]
        translation[1, 3] = -cam_pos[1]
        translation[2, 3] = -cam_pos[2]

        rotation = np.identity(4)
        rotation[0, 0:3] = x_axis
        rotation[1, 0:3] = y_axis
        rotation[2, 0:3] = z_axis

        return (rotation @ translation).astype(np.float32)

    def get_front_vector(self):
        """Calculates and returns the camera's normalized front vector."""
        yaw_rad = np.radians(self.yaw)
        pitch_rad = np.radians(self.pitch)

        front = np.array([
            np.cos(yaw_rad) * np.cos(pitch_rad),
            np.sin(pitch_rad),
            np.sin(yaw_rad) * np.cos(pitch_rad)
        ])
        return front / np.linalg.norm(front)

    def rotate(self, dx, dy, sensitivity=0.1):
        """Rotates the camera based on mouse movement."""
        self.yaw += dx * sensitivity
        self.pitch -= dy * sensitivity
        self.pitch = max(-89.0, min(89.0, self.pitch))

    def move_forward(self, speed):
        """Moves the camera along its front vector, ignoring the pitch."""
        front_vector = self.get_front_vector()
        self.pos[0] += front_vector[0] * speed
        self.pos[2] += front_vector[2] * speed

    def strafe(self, speed):
        """Moves the camera along its right vector."""
        rad_yaw = math.radians(self.yaw)
        self.pos[0] += math.sin(rad_yaw) * speed
        self.pos[2] -= math.cos(rad_yaw) * speed

    def move_up(self, speed):
        """Moves the camera along the world's up vector."""
        self.pos[1] += speed

    def zoom(self, amount):
        """Moves the camera forward or backward along its true front vector."""
        front_vector = self.get_front_vector()
        self.pos[0] += front_vector[0] * amount
        self.pos[1] += front_vector[1] * amount
        self.pos[2] += front_vector[2] * amount