# engine/player.py
import pygame
import math
import glm
import numpy as np

from PyQt5.QtCore import Qt
from .constants import TILE_SIZE, WALL_TILE, GRAVITY, JUMP_STRENGTH, TERMINAL_VELOCITY

class Player:
    def __init__(self, x, z, angle=math.pi, physics_enabled=True):
        self.pos = glm.vec3(float(x), float(TILE_SIZE) * 2, float(z))
        self.velocity = glm.vec3(0, 0, 0)
        self.angle, self.pitch = angle, 0.0
        self.speed, self.camera_speed = 200, 0.2
        self.mouse_sensitivity = 0.0015
        self.width, self.height, self.depth = TILE_SIZE, TILE_SIZE * 2, TILE_SIZE
        self.on_ground = False
        self.physics_enabled = physics_enabled

    def update_angle(self, dx, dy):
        self.angle = (self.angle - dx * self.mouse_sensitivity) % (2 * math.pi)
        self.pitch = max(-math.pi/2, min(math.pi/2, self.pitch - dy * self.mouse_sensitivity))

    def update(self, keys, brushes, delta):
        forward_input = (1 if Qt.Key_W in keys or Qt.Key_Up in keys else 0) - \
                        (1 if Qt.Key_S in keys or Qt.Key_Down in keys else 0)
        # --- THIS IS THE CORRECTED LINE ---
        strafe_input = (1 if Qt.Key_A in keys or Qt.Key_Left in keys else 0) - \
                       (1 if Qt.Key_D in keys or Qt.Key_Right in keys else 0)
        # --- END OF CORRECTION ---
        is_fast = Qt.Key_Shift in keys

        speed = self.speed * 3 if is_fast else self.speed

        cam_forward = glm.vec3(math.sin(self.angle), 0, math.cos(self.angle))
        cam_right = glm.vec3(math.sin(self.angle + math.pi/2), 0, math.cos(self.angle + math.pi/2))

        move_dir = cam_forward * forward_input + cam_right * strafe_input
        if glm.length(move_dir) > 0:
            move_dir = glm.normalize(move_dir)

        if self.physics_enabled:
            # Apply gravity
            self.velocity.y += GRAVITY * delta
            if self.velocity.y < TERMINAL_VELOCITY:
                self.velocity.y = TERMINAL_VELOCITY

            # Jumping
            if Qt.Key_Space in keys and self.on_ground:
                self.velocity.y = JUMP_STRENGTH

            self.velocity.x = move_dir.x * speed
            self.velocity.z = move_dir.z * speed

            new_pos = self.pos + self.velocity * delta
            self.handle_collision(new_pos, brushes)
        else:
            self.pos += move_dir * speed * delta


    def handle_collision(self, new_pos, brushes):
        self.on_ground = False
        player_rect = pygame.Rect(new_pos.x - self.width / 2, new_pos.z - self.depth / 2, self.width, self.depth)

        for brush in brushes:
            if brush.get('is_trigger'):
                continue

            brush_rect = pygame.Rect(
                brush['pos'][0] - brush['size'][0] / 2,
                brush['pos'][2] - brush['size'][2] / 2,
                brush['size'][0],
                brush['size'][2]
            )

            if player_rect.colliderect(brush_rect):
                brush_top = brush['pos'][1] + brush['size'][1] / 2
                player_bottom = new_pos.y - self.height / 2

                if self.velocity.y <= 0 and player_bottom < brush_top and self.pos.y - self.height / 2 >= brush_top - 1.0:
                    new_pos.y = brush_top + self.height / 2
                    self.velocity.y = 0
                    self.on_ground = True

        self.pos = new_pos


    def get_position(self):
        return self.pos

    def get_view_matrix(self):
        cam_forward = glm.vec3(
            math.sin(self.angle) * math.cos(self.pitch),
            math.sin(self.pitch),
            math.cos(self.angle) * math.cos(self.pitch)
        )
        target = self.pos + cam_forward
        return glm.lookAt(self.pos, target, glm.vec3(0, 1, 0))