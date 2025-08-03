import pygame
import math
import glm
import numpy as np

from PyQt5.QtCore import Qt
from .constants import TILE_SIZE, WALL_TILE

class Player:
    def __init__(self, x, z, angle=math.pi):
        self.pos = glm.vec3(float(x), float(TILE_SIZE), float(z))
        self.angle, self.pitch = angle, 0.0
        self.speed, self.camera_speed = 2.5, 0.2
        self.mouse_sensitivity = 0.0015
        self.width, self.height, self.depth = TILE_SIZE / 2, TILE_SIZE, TILE_SIZE / 2

    def update_angle(self, dx, dy):
        self.angle = (self.angle - dx * self.mouse_sensitivity) % (2 * math.pi)
        self.pitch = max(-math.pi/2, min(math.pi/2, self.pitch - dy * self.mouse_sensitivity))

    def update(self, keys, tile_map, delta):
        forward_input = (1 if Qt.Key_W in keys or Qt.Key_Up in keys else 0) - \
                        (1 if Qt.Key_S in keys or Qt.Key_Down in keys else 0)
        strafe_input = (1 if Qt.Key_D in keys or Qt.Key_Right in keys else 0) - \
                    (1 if Qt.Key_A in keys or Qt.Key_Left in keys else 0)
        is_fast = Qt.Key_Shift in keys
        
        speed = (self.speed * 3 if is_fast else self.speed) * delta * 60

        cam_forward = glm.vec3(math.sin(self.angle), 0, math.cos(self.angle))
        cam_right = glm.vec3(math.sin(self.angle + math.pi/2), 0, math.cos(self.angle + math.pi/2))
        
        move_dir = cam_forward * forward_input + cam_right * strafe_input
        if glm.length(move_dir) > 0:
            move_dir = glm.normalize(move_dir)
        
        new_pos = self.pos + move_dir * speed
        
        if tile_map is None:
            self.pos = new_pos
            return

        if not self.check_collision(new_pos.x, self.pos.z, tile_map): self.pos.x = new_pos.x
        if not self.check_collision(self.pos.x, new_pos.z, tile_map): self.pos.z = new_pos.z

    def check_collision(self, next_x, next_z, tile_map):
        player_rect = pygame.Rect(next_x - self.width / 2, next_z - self.depth / 2, self.width, self.depth)
        for r in range(tile_map.shape[0]):
            for c in range(tile_map.shape[1]):
                if tile_map[r, c] == WALL_TILE:
                    wall_rect = pygame.Rect(c * TILE_SIZE, r * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                    if player_rect.colliderect(wall_rect): return True
        return False

    def get_position(self):
        return self.pos

    def get_view_matrix(self):
        # --- FIXED: Now returns a glm.mat4x4 for consistency ---
        cam_forward = glm.vec3(
            math.sin(self.angle) * math.cos(self.pitch),
            math.sin(self.pitch),
            math.cos(self.angle) * math.cos(self.pitch))
        target = self.pos + cam_forward
        return glm.lookAt(self.pos, target, glm.vec3(0, 1, 0))