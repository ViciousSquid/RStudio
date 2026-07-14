import math
import glm
from PyQt5.QtCore import Qt
from .constants import TILE_SIZE, GRAVITY, JUMP_STRENGTH, TERMINAL_VELOCITY


# =============================================================================
# Mesh Collision Helpers
# =============================================================================

def _point_in_triangle(p, a, b, c):
    """Barycentric test: is point p inside triangle abc? All are (x,y,z) tuples."""
    def sub(v1, v2):
        return (v1[0]-v2[0], v1[1]-v2[1], v1[2]-v2[2])
    def cross(v1, v2):
        return (v1[1]*v2[2]-v1[2]*v2[1], v1[2]*v2[0]-v1[0]*v2[2], v1[0]*v2[1]-v1[1]*v2[0])
    def dot(v1, v2):
        return v1[0]*v2[0]+v1[1]*v2[1]+v1[2]*v2[2]
    
    ab = sub(b, a)
    ac = sub(c, a)
    ap = sub(p, a)
    n = cross(ab, ac)
    d = dot(n, n)
    
    if d < 0.0001:
        return False
        
    w = dot(cross(ab, ap), n) / d
    v = dot(cross(ap, ac), n) / d
    u = 1.0 - w - v
    
    return u >= -0.001 and v >= -0.001 and w >= -0.001


def _intersect_swept_sphere_triangle(sphere_pos, sphere_vel, radius, triangle, normal):
    """Swept sphere vs triangle. Returns (hit, hit_time, hit_point, slide_normal).
    
    sphere_pos: glm.vec3 - current position
    sphere_vel: glm.vec3 - velocity this frame (will move by this amount)
    radius: float - player radius (half of width/depth)
    triangle: ((v0,v1,v2), normal) from mesh collision data
    """
    v0, v1, v2 = triangle
    
    # Convert to tuples for math
    sp = (sphere_pos.x, sphere_pos.y, sphere_pos.z)
    sv = (sphere_vel.x, sphere_vel.y, sphere_vel.z)
    
    # Distance from sphere center to triangle plane
    to_v0 = (sp[0] - v0[0], sp[1] - v0[1], sp[2] - v0[2])
    dist = to_v0[0]*normal[0] + to_v0[1]*normal[1] + to_v0[2]*normal[2]
    
    # Relative velocity along normal
    vel_dot_n = sv[0]*normal[0] + sv[1]*normal[1] + sv[2]*normal[2]
    
    # If moving away from triangle and clearly not touching, no collision
    if vel_dot_n > 0 and dist > radius:
        return False, 1.0, None, None

    # Sphere fully behind the plane (inside-out geometry) — skip
    if dist < -radius:
        return False, 1.0, None, None

    # Time when sphere surface touches plane.
    # We solve: dist + vel_dot_n * t = radius  →  t = (radius - dist) / vel_dot_n
    # BUG FIX: the original code had (dist - radius) which is the wrong sign, producing
    # a negative t for any approaching sphere and causing all mesh collision to be skipped.
    if dist > radius:
        # Sphere not yet touching the plane — find exact contact time
        if abs(vel_dot_n) < 0.0001:
            # Moving parallel to a plane we haven't touched yet — no contact
            return False, 1.0, None, None
        t0 = (radius - dist) / vel_dot_n   # positive when vel_dot_n < 0 (approaching)
    else:
        # Sphere is already overlapping the plane (dist <= radius).
        # If moving further in, treat as immediate (t=0) collision so the player is
        # deflected this frame.  If moving out, let it escape without interference.
        if vel_dot_n >= 0:
            return False, 1.0, None, None
        t0 = 0.0

    if t0 < 0 or t0 > 1.0:
        return False, 1.0, None, None
    
    # Point on plane at collision time (sphere center projected to plane)
    hit_point = (
        sp[0] + sv[0]*t0 - normal[0]*radius,
        sp[1] + sv[1]*t0 - normal[1]*radius,
        sp[2] + sv[2]*t0 - normal[2]*radius,
    )
    
    # Check if point is inside triangle
    if _point_in_triangle(hit_point, v0, v1, v2):
        return True, t0, glm.vec3(*hit_point), glm.vec3(*normal)
    
    # Edge/vertex collision - test sphere vs each edge
    def closest_point_on_segment(p, a, b):
        ab = (b[0]-a[0], b[1]-a[1], b[2]-a[2])
        t = max(0.0, min(1.0, ((p[0]-a[0])*ab[0] + (p[1]-a[1])*ab[1] + (p[2]-a[2])*ab[2]) / 
               (ab[0]*ab[0] + ab[1]*ab[1] + ab[2]*ab[2] + 0.0001)))
        return (a[0] + t*ab[0], a[1] + t*ab[1], a[2] + t*ab[2])
    
    # Test against 3 edges
    edges = [(v0, v1), (v1, v2), (v2, v0)]
    for a, b in edges:
        closest = closest_point_on_segment(hit_point, a, b)
        dx = hit_point[0] - closest[0]
        dy = hit_point[1] - closest[1]
        dz = hit_point[2] - closest[2]
        edge_dist_sq = dx*dx + dy*dy + dz*dz
        if edge_dist_sq < radius*radius:
            # Hit edge - push out along vector from edge to sphere center
            edge_normal = glm.normalize(glm.vec3(dx, dy, dz))
            return True, t0, glm.vec3(*closest), edge_normal
    
    return False, 1.0, None, None

def _collide_and_slide(sphere_pos, velocity, radius, mesh_tris, mesh_bounds, max_iterations=3):
    """
    Fauerby-style collide-and-slide against a triangle mesh.
    
    Returns: (new_position, new_velocity, ground_normal, hit_ground)
    
    The key insight: when we hit a triangle, we don't stop. Instead:
    1. Move to just before the collision point
    2. Define a "sliding plane" perpendicular to the collision normal
    3. Project the remaining velocity onto this plane
    4. Recurse with the new velocity
    """
    VERY_CLOSE_DIST = 0.005  # Don't move all the way to the surface
    
    # Broad-phase rejection
    if mesh_bounds:
        min_b, max_b = mesh_bounds
        vel_mag = glm.length(velocity)
        expanded_min = (min_b[0] - radius - vel_mag, min_b[1] - radius - vel_mag, min_b[2] - radius - vel_mag)
        expanded_max = (max_b[0] + radius + vel_mag, max_b[1] + radius + vel_mag, max_b[2] + radius + vel_mag)
        
        sp = (sphere_pos.x, sphere_pos.y, sphere_pos.z)
        if (sp[0] < expanded_min[0] or sp[0] > expanded_max[0] or
            sp[1] < expanded_min[1] or sp[1] > expanded_max[1] or
            sp[2] < expanded_min[2] or sp[2] > expanded_max[2]):
            return sphere_pos + velocity, velocity, None, False
    
    # Working copies
    pos = glm.vec3(sphere_pos)
    vel = glm.vec3(velocity)
    
    ground_normal = None
    hit_ground = False
    
    # Keep track of sliding planes to prevent corner jitter
    sliding_planes = []
    
    for iteration in range(max_iterations):
        if glm.length(vel) < VERY_CLOSE_DIST:
            break
        
        # Find nearest collision
        nearest_t = 1.0
        nearest_hit_point = None
        nearest_normal = None
        
        for tri, normal in mesh_tris:
            hit, t, hit_point, hit_normal = _intersect_swept_sphere_triangle(
                pos, vel, radius, tri, normal
            )
            if hit and t < nearest_t:
                nearest_t = t
                nearest_hit_point = hit_point
                nearest_normal = hit_normal
        
        # No collision - move freely
        if nearest_normal is None:
            pos = pos + vel
            break
        
        # Collision found - move close to intersection but not exactly to it
        if nearest_t >= VERY_CLOSE_DIST:
            # Move to just before the collision
            move_dist = nearest_t - VERY_CLOSE_DIST / glm.length(vel)
            pos = pos + vel * move_dist
        
        # Define sliding plane
        # The sliding plane origin is the collision point, normal is the collision normal
        # We want to project the remaining velocity onto this plane
        
        # Distance from destination to sliding plane
        dest = pos + vel * (1.0 - nearest_t)
        slide_plane_d = -glm.dot(nearest_normal, nearest_hit_point)
        dist_to_plane = glm.dot(nearest_normal, dest) + slide_plane_d
        
        # New destination = project onto sliding plane
        new_dest = dest - nearest_normal * dist_to_plane
        
        # New velocity for next iteration
        vel = new_dest - pos
        
        # Track if we hit ground (normal pointing up)
        if nearest_normal.y > 0.5:
            ground_normal = nearest_normal
            hit_ground = True
        
        # Track sliding planes for corner cases
        sliding_planes.append((nearest_hit_point, nearest_normal))
        
        # If we have 2+ sliding planes, check if we're in a crease
        if len(sliding_planes) >= 2:
            # Project onto crease (intersection of two planes)
            n1 = sliding_planes[-2][1]
            n2 = sliding_planes[-1][1]
            crease = glm.cross(n1, n2)
            if glm.length(crease) > 0.001:
                crease = glm.normalize(crease)
                # Project velocity onto crease
                signed_dist = glm.dot(dest - pos, crease)
                vel = crease * signed_dist
            else:
                # Parallel planes - stop
                vel = glm.vec3(0)
                break
        
        # If 3 planes, we're cornered - stop
        if len(sliding_planes) >= 3:
            vel = glm.vec3(0)
            break
    
    return pos, vel, ground_normal, hit_ground


# =============================================================================
# Player Class
# =============================================================================

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

        # Separate mesh brushes from AABB brushes (single pass over colliders)
        mesh_brushes = []
        aabb_brushes = []
        for b in colliders:
            if b.get('_collision_mode') == 'mesh':
                mesh_brushes.append(b)
            else:
                aabb_brushes.append(b)

        # A. Horizontal movement with mesh collision (X then Z using collide-and-slide)
        self._move_with_mesh_collision(delta, mesh_brushes, axis='x')
        self._move_with_mesh_collision(delta, mesh_brushes, axis='z')

        # B. Horizontal movement with AABB collision
        self._move_with_collision(delta, aabb_brushes, axis='x')
        self._move_with_collision(delta, aabb_brushes, axis='z')

        # C. Vertical Y Movement
        self.pos.y += self.velocity.y * delta

        # Reset ground state before Y collision check
        self.on_ground     = False
        self.ground_object = None

        # 1. Mesh collision for Y (ground detection)
        self._resolve_mesh_collision_y(delta, mesh_brushes)

        # 2. AABB / mover collision for Y
        self._resolve_collision(aabb_brushes, axis='y', delta=delta)

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

    def _move_with_collision(self, delta, aabb_brushes, axis):
        """
        Handles movement along a specific axis with collision detection.
        """
        # 1. Determine velocity component based on axis
        if axis == 'z':
            move_val = self.velocity.z * delta
        elif axis == 'x':
            move_val = self.velocity.x * delta
        else:
            move_val = self.velocity.y * delta

        if abs(move_val) < 0.0001:
            return

        # Store current position to revert if collision occurs
        orig_pos = glm.vec3(self.pos)
        
        # 2. Apply movement
        if axis == 'z':
            self.pos.z += move_val
        elif axis == 'x':
            self.pos.x += move_val
        else:
            self.pos.y += move_val

        # 3. Calculate current player bounds using individual dimensions
        half_dims = glm.vec3(self.width * 0.5, self.height * 0.5, self.depth * 0.5)
        p_min = self.pos - half_dims
        p_max = self.pos + half_dims

        # 4. Check for collisions with potential colliders
        for brush in aabb_brushes:
            # Check headroom using the fixed signature (brush, p_min, p_max)
            if not self._has_headroom(brush, p_min, p_max):
                # Collision detected: revert position and stop movement
                self.pos = orig_pos
                if axis == 'z':
                    self.velocity.z = 0
                elif axis == 'x':
                    self.velocity.x = 0
                else:
                    self.velocity.y = 0
                return

    def _move_with_mesh_collision(self, delta, mesh_brushes, axis):
        """
        Move player along one horizontal axis using collide-and-slide against mesh brushes.
        This allows smooth sliding along ramps and slopes.
        """
        if not mesh_brushes:
            return

        # Build velocity for this axis
        if axis == 'x':
            vel = glm.vec3(self.velocity.x * delta, 0, 0)
        else:
            vel = glm.vec3(0, 0, self.velocity.z * delta)

        if glm.length(vel) < 0.001:
            return

        # Combine all triangles from all mesh brushes
        all_tris = []
        all_bounds = None
        for brush in mesh_brushes:
            tris = brush.get('_mesh_triangles', [])
            bounds = brush.get('_mesh_bounds')
            if tris:
                all_tris.extend(tris)
            # Merge bounds
            if bounds:
                if all_bounds is None:
                    all_bounds = [list(bounds[0]), list(bounds[1])]
                else:
                    for i in range(3):
                        all_bounds[0][i] = min(all_bounds[0][i], bounds[0][i])
                        all_bounds[1][i] = max(all_bounds[1][i], bounds[1][i])

        if not all_tris:
            return

        radius = min(self._half.x, self._half.z) * 0.9

        # Use collide-and-slide
        new_pos, new_vel, ground_normal, hit_ground = _collide_and_slide(
            self.pos, vel, radius, all_tris, all_bounds
        )

        # Apply result
        if axis == 'x':
            self.pos.x = new_pos.x
            # If we slid, the new velocity reflects the slide direction
            if abs(new_vel.x) < 0.001 and glm.length(new_vel) > 0.001:
                # We slid into another direction - zero X but keep the intent
                self.velocity.x = 0
            elif glm.length(new_vel) < 0.001:
                self.velocity.x = 0
        else:
            self.pos.z = new_pos.z
            if abs(new_vel.z) < 0.001 and glm.length(new_vel) > 0.001:
                self.velocity.z = 0
            elif glm.length(new_vel) < 0.001:
                self.velocity.z = 0

        # If we hit ground during horizontal movement, update state
        if hit_ground and ground_normal:
            self.on_ground = True
            # Find which brush we hit
            for brush in mesh_brushes:
                if brush.get('_mesh_triangles'):
                    self.ground_object = brush
                    break

    def _resolve_mesh_collision_y(self, delta, mesh_brushes):
        """Handle vertical mesh collision - mainly for landing on slopes."""
        if not mesh_brushes:
            return

        vel = glm.vec3(0, self.velocity.y * delta, 0)
        if glm.length(vel) < 0.001:
            return

        all_tris = []
        all_bounds = None
        for brush in mesh_brushes:
            tris = brush.get('_mesh_triangles', [])
            bounds = brush.get('_mesh_bounds')
            if tris:
                all_tris.extend(tris)
            if bounds:
                if all_bounds is None:
                    all_bounds = [list(bounds[0]), list(bounds[1])]
                else:
                    for i in range(3):
                        all_bounds[0][i] = min(all_bounds[0][i], bounds[0][i])
                        all_bounds[1][i] = max(all_bounds[1][i], bounds[1][i])

        if not all_tris:
            return

        radius = min(self._half.x, self._half.z) * 0.9

        new_pos, new_vel, ground_normal, hit_ground = _collide_and_slide(
            self.pos, vel, radius, all_tris, all_bounds
        )

        self.pos.y = new_pos.y

        if hit_ground and ground_normal and ground_normal.y > 0.3:
            self.velocity.y = 0
            self.on_ground = True
            for brush in mesh_brushes:
                if brush.get('_mesh_triangles'):
                    self.ground_object = brush
                    break

    def _has_headroom(self, brush, player_min, player_max):
        # Mesh collision: use mesh bounds for broad-phase AABB check
        if brush.get('_collision_mode') == 'mesh':
            bounds = brush.get('_mesh_bounds')
            if bounds:
                min_b, max_b = bounds
                # Standard AABB overlap test using mesh bounds
                if (player_max.x > min_b[0] and player_min.x < max_b[0] and
                    player_max.y > min_b[1] and player_min.y < max_b[1] and
                    player_max.z > min_b[2] and player_min.z < max_b[2]):
                    return False  # Overlapping mesh bounds → collision
            return True  # No bounds or no overlap → pass through

        # Standard AABB check for solid world brushes
        pos   = glm.vec3(brush['pos'])
        size  = glm.vec3(brush['size'])
        b_min = pos - size * 0.5
        b_max = pos + size * 0.5

        if (player_max.x > b_min.x and player_min.x < b_max.x and
            player_max.y > b_min.y and player_min.y < b_max.y and
            player_max.z > b_min.z and player_min.z < b_max.z):
            return False
            
        return True

    def _resolve_collision(self, brushes, axis, delta, ignore_brush=None):
        """
        Resolve AABB or mesh collision by pushing the player out of overlapping brushes.
        """
        half = self._half

        for brush in brushes:
            if ignore_brush and brush is ignore_brush:
                continue

            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue

            is_dynamic_solid = brush.get('is_mover') or brush.get('is_door')
            if brush.get('is_trigger') and not is_dynamic_solid:
                continue

            # === MESH COLLISION ===
            if brush.get('_collision_mode') == 'mesh':
                mesh_tris = brush.get('_mesh_triangles', [])
                if not mesh_tris:
                    continue
                
                # Broad-phase: check AABB first
                bounds = brush.get('_mesh_bounds')
                if bounds:
                    min_b, max_b = bounds
                    player_min = self.pos - half
                    player_max = self.pos + half
                    if (player_max.x < min_b[0] or player_min.x > max_b[0] or
                        player_max.y < min_b[1] or player_min.y > max_b[1] or
                        player_max.z < min_b[2] or player_min.z > max_b[2]):
                        continue

                # Build velocity for this frame on the current axis
                if axis == 'x':
                    vel = glm.vec3(self.velocity.x * delta, 0, 0)
                elif axis == 'z':
                    vel = glm.vec3(0, 0, self.velocity.z * delta)
                else:
                    vel = glm.vec3(0, self.velocity.y * delta, 0)
                
                # Use a small radius for the player capsule (slightly smaller than half-extents)
                radius = min(half.x, half.z) * 0.9
                
                nearest_hit = 1.0
                nearest_normal = None
                
                for tri, normal in mesh_tris:
                    # Only test triangles facing the movement direction (optimization)
                    if axis == 'y' and normal[1] <= 0.1:
                        # For ground collision, only care about upward-facing triangles
                        continue
                    
                    hit, t, hit_point, hit_normal = _intersect_swept_sphere_triangle(
                        self.pos, vel, radius, tri, normal
                    )
                    if hit and t < nearest_hit:
                        nearest_hit = t
                        nearest_normal = hit_normal
                
                if nearest_normal is not None:
                    # Push player out along the collision normal
                    penetration = radius * 0.5  # push to clear the surface
                    
                    if axis == 'x':
                        self.pos.x += nearest_normal.x * penetration
                        self.velocity.x = 0
                    elif axis == 'z':
                        self.pos.z += nearest_normal.z * penetration
                        self.velocity.z = 0
                    elif axis == 'y':
                        # For Y, we need to know if we hit from above (floor) or below (ceiling)
                        if nearest_normal.y > 0.3:  # Floor or slope
                            self.pos.y += nearest_normal.y * penetration
                            self.velocity.y = 0
                            self.on_ground = True
                            self.ground_object = brush
                        else:  # Ceiling or steep wall
                            self.pos.y += nearest_normal.y * penetration
                            if self.velocity.y > 0:
                                self.velocity.y = 0
                
                continue  # Done with this mesh brush

            # === AABB COLLISION (existing code) ===
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
                dx1 = player_max.x - b_min.x
                dx2 = b_max.x - player_min.x
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
                dy1 = player_max.y - b_min.y
                dy2 = b_max.y - player_min.y
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
        Handles both AABB and mesh collision brushes.
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

            # Mesh collision: use bounds for broad-phase
            if brush.get('_collision_mode') == 'mesh':
                bounds = brush.get('_mesh_bounds')
                if bounds:
                    min_b, max_b = bounds
                    if (player_max.x > min_b[0] and player_min.x < max_b[0] and
                        player_max.y > min_b[1] and player_min.y < max_b[1] and
                        player_max.z > min_b[2] and player_min.z < max_b[2]):
                        # Broad-phase overlap - do narrow-phase test
                        mesh_tris = brush.get('_mesh_triangles', [])
                        for tri, normal in mesh_tris:
                            # Simple sphere vs triangle test
                            sp = (self.pos.x, self.pos.y, self.pos.z)
                            # Distance to plane
                            to_v0 = (sp[0] - tri[0][0], sp[1] - tri[0][1], sp[2] - tri[0][2])
                            dist = abs(to_v0[0]*normal[0] + to_v0[1]*normal[1] + to_v0[2]*normal[2])
                            if dist < min(half.x, half.z):
                                # Close to plane - check if point projects into triangle
                                plane_point = (
                                    sp[0] - normal[0]*dist,
                                    sp[1] - normal[1]*dist,
                                    sp[2] - normal[2]*dist,
                                )
                                if _point_in_triangle(plane_point, tri[0], tri[1], tri[2]):
                                    return True
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