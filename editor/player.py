import math
import glm
from PyQt5.QtCore import Qt
from .constants import TILE_SIZE, GRAVITY, JUMP_STRENGTH, TERMINAL_VELOCITY

class Player:
    def __init__(self, x, z, angle=math.pi, physics_enabled=True):
        # Initialize position (Y is set to 2 tiles high by default)
        self.pos = glm.vec3(float(x), float(TILE_SIZE) * 2, float(z))
        self.velocity = glm.vec3(0, 0, 0)
        self.angle = angle
        self.pitch = 0.0

        # Physics constants
        self.speed = 200.0
        self.mouse_sensitivity = 0.0015
        self.width, self.height, self.depth = TILE_SIZE, TILE_SIZE * 2, TILE_SIZE
        self.camera_height = 40.0  # Offset from pos.y

        # Physics state
        self.on_ground = False
        self.ground_object = None  # Reference to the brush we are standing on
        self.physics_enabled = physics_enabled
        self.step_height = 18.0  # Max height the player can step up automatically

        # Pre-computed half-extents (constant for the lifetime of this player instance)
        self._half = glm.vec3(self.width / 2.0, self.height / 2.0, self.depth / 2.0)

    def get_view_matrix(self):
        """Calculate the view matrix for rendering."""
        cam_pos = self.pos + glm.vec3(0, self.camera_height, 0)
        direction = glm.vec3(
            math.sin(self.angle) * math.cos(self.pitch),
            math.sin(self.pitch),
            math.cos(self.angle) * math.cos(self.pitch),
        )
        return glm.lookAt(cam_pos, cam_pos + direction, glm.vec3(0, 1, 0))

    def update(self, delta, move_input, jump, crouch, brushes, movers=None, doors=None, terrain=None):
        """
        Update player physics.
        """
        # FIX: Build collider list with extend() instead of repeated + (avoids two full-list copies)
        colliders = list(brushes)
        if movers:
            colliders.extend(movers)
        if doors:
            colliders.extend(doors)

        # --- 1. Movement Physics ---

        forward_vec = glm.vec3(math.sin(self.angle), 0, math.cos(self.angle))
        right_vec   = glm.vec3(math.cos(self.angle), 0, -math.sin(self.angle))

        wish_dir = forward_vec * move_input.z + right_vec * move_input.x

        if glm.length(wish_dir) > 0.1:
            wish_dir = glm.normalize(wish_dir)

        target_speed = self.speed * (0.5 if crouch else 1.0)

        self.velocity.x = wish_dir.x * target_speed
        self.velocity.z = wish_dir.z * target_speed

        if not self.physics_enabled:
            self.pos += self.velocity * delta
            return

        # --- 2. Gravity & Jumping ---

        self.velocity.y += GRAVITY * delta

        if self.velocity.y < TERMINAL_VELOCITY:
            self.velocity.y = TERMINAL_VELOCITY

        if jump and self.on_ground:
            self.velocity.y = JUMP_STRENGTH
            self.on_ground  = False
            self.ground_object = None

        # --- 3. Collision Resolution ---

        # A. Horizontal X Movement
        original_pos = glm.vec3(self.pos)
        self.pos.x += self.velocity.x * delta

        if self._check_overlap(colliders, ignore_brush=self.ground_object):
            self.pos.x  = original_pos.x
            self.pos.y += self.step_height
            self.pos.x += self.velocity.x * delta

            if not self._check_overlap(colliders, ignore_brush=self.ground_object):
                pass  # step-up succeeded
            else:
                self.pos    = original_pos
                self.pos.x += self.velocity.x * delta
                self._resolve_collision(colliders, axis='x', ignore_brush=self.ground_object)

        # B. Horizontal Z Movement
        original_pos = glm.vec3(self.pos)
        self.pos.z += self.velocity.z * delta

        if self._check_overlap(colliders, ignore_brush=self.ground_object):
            self.pos.z  = original_pos.z
            self.pos.y += self.step_height
            self.pos.z += self.velocity.z * delta

            if not self._check_overlap(colliders, ignore_brush=self.ground_object):
                pass  # step-up succeeded
            else:
                self.pos    = original_pos
                self.pos.z += self.velocity.z * delta
                self._resolve_collision(colliders, axis='z', ignore_brush=self.ground_object)

        # C. Vertical Y Movement
        self.pos.y += self.velocity.y * delta

        # Reset ground state before Y collision check
        self.on_ground     = False
        self.ground_object = None

        # 1. Brush / mover collision
        self._resolve_collision(colliders, axis='y')

        # 2. Terrain collision
        if terrain and terrain.is_solid():
            terrain_height = terrain.get_height_at_safe(self.pos.x, self.pos.z)
            if terrain_height is not None:
                feet_y = self.pos.y - self.height / 2.0
                if feet_y < terrain_height:
                    self.pos.y         = terrain_height + self.height / 2.0
                    self.velocity.y    = 0
                    self.on_ground     = True
                    self.ground_object = terrain

        # Floor safety clamp
        if self.pos.y < -2000:
            self.pos     = glm.vec3(0, 100, 0)
            self.velocity = glm.vec3(0, 0, 0)

    def _resolve_collision(self, brushes, axis, ignore_brush=None):
        """
        Resolve AABB collision by pushing the player out of overlapping brushes.

        FIX: Pre-compute the constant half-extent vector once outside the loop.
        self.pos mutates during resolution (iterative accuracy), so player_min/max
        must still be recomputed from self.pos each iteration — but self._half is
        constant and does not need to be rebuilt on every iteration.
        """
        half = self._half  # constant reference — no recomputation each iteration

        for brush in brushes:
            if ignore_brush and brush is ignore_brush:
                continue

            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue

            is_dynamic_solid = brush.get('is_mover') or brush.get('is_door')
            if brush.get('is_trigger') and not is_dynamic_solid:
                continue

            # Recompute player AABB from current (possibly corrected) pos each iteration
            player_min = self.pos - half
            player_max = self.pos + half

            pos   = glm.vec3(brush['pos'])
            size  = glm.vec3(brush['size'])
            b_min = pos - size * 0.5
            b_max = pos + size * 0.5

            if (player_max.x < b_min.x or player_min.x > b_max.x or
                    player_max.y < b_min.y or player_min.y > b_max.y or
                    player_max.z < b_min.z or player_min.z > b_max.z):
                continue

            # Resolve on the relevant axis
            if axis == 'x':
                dx1 = player_max.x - b_min.x  # overlap from the left
                dx2 = b_max.x - player_min.x  # overlap from the right
                if dx1 < dx2:
                    self.pos.x -= dx1 + 0.001
                else:
                    self.pos.x += dx2 + 0.001
                self.velocity.x = 0

            elif axis == 'z':
                dz1 = player_max.z - b_min.z
                dz2 = b_max.z - player_min.z
                if dz1 < dz2:
                    self.pos.z -= dz1 + 0.001
                else:
                    self.pos.z += dz2 + 0.001
                self.velocity.z = 0

            elif axis == 'y':
                dy1 = player_max.y - b_min.y  # head hits ceiling
                dy2 = b_max.y - player_min.y  # feet hit floor
                if dy1 < dy2:
                    self.pos.y -= dy1 + 0.001
                    if self.velocity.y > 0:
                        self.velocity.y = 0
                else:
                    self.pos.y        += dy2
                    self.velocity.y    = 0
                    self.on_ground     = True
                    self.ground_object = brush

    def _check_overlap(self, brushes, ignore_brush=None):
        """
        Returns True if the player currently overlaps any solid brush.

        FIX: Half-extents computed once from self._half before the loop.
        """
        half       = self._half
        player_min = self.pos - half
        player_max = self.pos + half

        for brush in brushes:
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue

            is_dynamic_solid = brush.get('is_mover') or brush.get('is_door')
            if brush.get('is_trigger') and not is_dynamic_solid:
                continue

            if ignore_brush is not None and brush is ignore_brush:
                continue

            pos   = glm.vec3(brush['pos'])
            size  = glm.vec3(brush['size'])
            b_min = pos - size * 0.5
            b_max = pos + size * 0.5

            if (player_max.x > b_min.x and player_min.x < b_max.x and
                    player_max.y > b_min.y and player_min.y < b_max.y and
                    player_max.z > b_min.z and player_min.z < b_max.z):
                return True

        return False
