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

    def update(self, delta, move_input, jump, crouch, brushes, movers=None, doors=None, terrain=None, spatial_grid=None):
        """
        Update player physics.

        PERF: If spatial_grid is provided, static brush colliders are fetched
        from the grid (only nearby cells) instead of iterating every brush.
        Movers and doors are always included since they're dynamic.
        """
        # --- Build collider list ---
        if spatial_grid:
            # Use the grid to get only nearby static brushes
            half = self._half
            player_min = self.pos - half - glm.vec3(self.speed * delta + 32)  # pad for movement
            player_max = self.pos + half + glm.vec3(self.speed * delta + 32)
            colliders = spatial_grid.get_potential_colliders(player_min, player_max)
        else:
            # Fallback: all brushes (old behaviour)
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
        self._move_with_collision(delta, colliders, axis='x')

        # B. Horizontal Z Movement
        self._move_with_collision(delta, colliders, axis='z')

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

    def _move_with_collision(self, delta, colliders, axis):
        """
        Move player along one horizontal axis with collision detection and step-up.

        FIXES:
        1. Only applies movement ONCE (no double-move bug)
        2. Properly zeros velocity on collision
        3. Only steps up when on ground
        4. Checks headroom before stepping up
        """
        original_pos = glm.vec3(self.pos)

        # Get velocity component for this axis
        if axis == 'x':
            vel_component = self.velocity.x
        else:
            vel_component = self.velocity.z

        # Apply movement
        if axis == 'x':
            self.pos.x += vel_component * delta
        else:
            self.pos.z += vel_component * delta

        # Check for overlap
        if not self._check_overlap(colliders, ignore_brush=self.ground_object):
            return  # No collision, movement succeeded

        # --- Try step-up (only when on ground) ---
        if self.on_ground and vel_component != 0:
            # Check headroom before stepping up
            if self._has_headroom(colliders, self.step_height):
                # Move up by step height
                self.pos.y += self.step_height

                # Re-apply horizontal movement at elevated position
                if axis == 'x':
                    self.pos.x = original_pos.x + vel_component * delta
                else:
                    self.pos.z = original_pos.z + vel_component * delta

                # Check if step-up succeeded
                if not self._check_overlap(colliders, ignore_brush=self.ground_object):
                    return  # Step-up succeeded!

                # Step-up failed - revert to original position
                self.pos = original_pos

        # --- Resolve collision (either no step attempted, or step failed) ---
        self._resolve_collision(colliders, axis=axis, ignore_brush=self.ground_object)

        # Zero velocity on this axis since we hit something
        if axis == 'x':
            self.velocity.x = 0
        else:
            self.velocity.z = 0

    def _has_headroom(self, colliders, height):
        """Check if there's enough vertical space above the player."""
        test_pos = glm.vec3(self.pos)
        test_pos.y += height

        half = self._half
        player_min = test_pos - half
        player_max = test_pos + half

        for brush in colliders:
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue

            is_dynamic_solid = brush.get('is_mover') or brush.get('is_door')
            if brush.get('is_trigger') and not is_dynamic_solid:
                continue

            pos  = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            b_min = pos - size * 0.5
            b_max = pos + size * 0.5

            if (player_max.x > b_min.x and player_min.x < b_max.x and
                player_max.y > b_min.y and player_min.y < b_max.y and
                player_max.z > b_min.z and player_min.z < b_max.z):
                return False  # No headroom

        return True

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
