import pygame
import math
import glm
import numpy as np

from PyQt5.QtCore import Qt
from .constants import TILE_SIZE, WALL_TILE

class Player:
    def __init__(self, x, z, angle=math.pi):
        # Ensure position attributes are always floats
        self.x, self.y, self.z = float(x), float(TILE_SIZE), float(z)
        self.angle, self.pitch = angle, 0.0
        self.speed, self.camera_speed = 0.15, 0.2
        self.mouse_sensitivity = 0.0015
        self.width, self.height, self.depth = TILE_SIZE / 2, TILE_SIZE, TILE_SIZE / 2

    def update_angle(self, dx, dy):
        self.angle = (self.angle - dx * self.mouse_sensitivity) % (2 * math.pi)
        self.pitch = max(-math.pi/2, min(math.pi/2, self.pitch - dy * self.mouse_sensitivity))

    def move_camera(self, forward, strafe, up_down, fast_move=False):
        """Moves the camera without collision detection (editor mode)."""
        speed = self.camera_speed * 3 if fast_move else self.camera_speed
        
        cam_forward = glm.vec3(math.sin(self.angle), 0, math.cos(self.angle))
        cam_right = glm.vec3(math.sin(self.angle + math.pi/2), 0, math.cos(self.angle + math.pi/2))
        
        move_dir = cam_forward * forward + cam_right * strafe
        if glm.length(move_dir) > 0:
            move_dir = glm.normalize(move_dir)
            
        self.x += move_dir.x * speed
        self.z += move_dir.z * speed
        self.y += up_down * speed

    def update(self, keys, tile_map):
        """Moves the player with collision detection (play mode)."""
        forward_input = (1 if keys.get(Qt.Key_W) or keys.get(Qt.Key_Up) else 0) - \
                        (1 if keys.get(Qt.Key_S) or keys.get(Qt.Key_Down) else 0)
        strafe_input = (1 if keys.get(Qt.Key_D) or keys.get(Qt.Key_Right) else 0) - \
                       (1 if keys.get(Qt.Key_A) or keys.get(Qt.Key_Left) else 0)
        is_fast = keys.get(Qt.Key_Shift, False)
        speed = self.speed * 3 if is_fast else self.speed

        cam_forward = glm.vec3(math.sin(self.angle), 0, math.cos(self.angle))
        cam_right = glm.vec3(math.sin(self.angle + math.pi/2), 0, math.cos(self.angle + math.pi/2))
        
        move_dir = cam_forward * forward_input + cam_right * strafe_input
        if glm.length(move_dir) > 0:
            move_dir = glm.normalize(move_dir)
        
        new_x, new_z = self.x + move_dir.x * speed, self.z + move_dir.z * speed
        
        if not self.check_collision(new_x, self.z, tile_map): self.x = new_x
        if not self.check_collision(self.x, new_z, tile_map): self.z = new_z

    def check_collision(self, next_x, next_z, tile_map):
        player_rect = pygame.Rect(next_x - self.width / 2, next_z - self.depth / 2, self.width, self.depth)
        for r in range(tile_map.shape[0]):
            for c in range(tile_map.shape[1]):
                if tile_map[r, c] == WALL_TILE:
                    wall_rect = pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                    if player_rect.colliderect(wall_rect): return True
        return False

    def get_position(self):
        """Returns the player's current position as a glm.vec3."""
        return glm.vec3(self.x, self.y, self.z)

    def get_view_matrix(self):
        position = self.get_position()
        cam_forward = glm.vec3(
            math.sin(self.angle) * math.cos(self.pitch),
            math.sin(self.pitch),
            math.cos(self.angle) * math.cos(self.pitch))
        target = position + cam_forward
        return glm.lookAt(position, target, glm.vec3(0, 1, 0))