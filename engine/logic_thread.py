import threading
import time
import numpy as np
from typing import List, Dict, Any, Optional
import glm
import math

from .threaded_game_state import ThreadedGameState, RenderState
from .player import Player
from .camera import Camera

# Import Thing subclasses for type checking
try:
    from editor.things import Speaker, Pickup, Light
except ImportError:
    Speaker = None
    Pickup = None
    Light = None

# Qt key constants (matching PyQt5.QtCore.Qt)
Key_W = 0x57
Key_S = 0x53
Key_A = 0x41
Key_D = 0x44
Key_Space = 0x20
Key_C = 0x43

class LogicThread(threading.Thread):
    """
    Separate thread for game logic processing.
    Runs at a fixed timestep (default 60 Hz) independent of rendering.
    Handles both play mode (player physics) and editor mode (camera movement).
    """
    
    TICK_RATE = 60
    TICK_DURATION = 1.0 / TICK_RATE
    EDITOR_CAMERA_SPEED = 300.0  # Units per second
    
    def __init__(self, game_state: ThreadedGameState, 
                 editor_state, 
                 visibility_system: Optional[Any] = None):
        super().__init__(daemon=True)
        self.game_state = game_state
        self.editor_state = editor_state
        self.visibility_system = visibility_system
        
        self.running = False
        self.player: Optional[Player] = None
        self.play_mode = False
        
        # Frustum culling settings
        self.culling_enabled = True
        self.frustum_aspect = 16.0 / 9.0  # Default aspect ratio
        
        # Editor camera (used when not in play mode)
        self.editor_camera = Camera()
        self.editor_camera.pos = glm.vec3(0, 150, 400)
        
        # Player stats
        self.player_health = 100
        self.player_max_health = 100
        
        # Trigger state
        self.player_in_triggers: set = set()
        self.fired_once_triggers: set = set()
        
        # Hurt trigger timers: trigger_id -> time_until_next_damage
        self.hurt_trigger_timers: Dict[int, float] = {}
        self.HURT_INTERVAL = 0.5  # Damage every 0.5 seconds
        
        # Pickup state
        self.collected_pickups: set = set()
        
        # Speaker state (for triggered speakers)
        self.active_speakers: set = set()
        
        # Mover Animation State
        self.mover_states = {} 
        self._init_movers()
        
        # Performance Monitoring
        self.actual_tps = 0.0
        self._tick_count = 0
        self._last_tps_time = time.perf_counter()

    @property
    def brushes(self):
        """Dynamically get current brushes from editor state."""
        return self.editor_state.brushes
    
    @property
    def things(self):
        """Dynamically get current things from editor state."""
        return self.editor_state.things

    def set_player(self, player: Optional[Player]):
        """Set or clear the active player."""
        self.player = player
        
    def set_play_mode(self, enabled: bool):
        self.play_mode = enabled
        if enabled:
            self._init_movers()
            # Reset player stats
            self.player_health = 100
            self.player_max_health = 100
            # Reset pickup state
            self.collected_pickups.clear()
            for thing in self.things:
                if Pickup and isinstance(thing, Pickup):
                    thing.properties['collected'] = False
            # Reset speaker state
            self.active_speakers.clear()
            # Reset hurt trigger timers
            self.hurt_trigger_timers.clear()
        else:
            self.player_in_triggers.clear()
            self.fired_once_triggers.clear()
            self.collected_pickups.clear()
            self.active_speakers.clear()
            self.hurt_trigger_timers.clear()
            self._reset_movers()
    
    def set_editor_camera(self, pos: glm.vec3, yaw: float, pitch: float, fov: float):
        """Set the editor camera state (thread-safe initialization)."""
        self.editor_camera.pos = glm.vec3(pos)
        self.editor_camera.yaw = yaw
        self.editor_camera.pitch = pitch
        self.editor_camera.fov = fov
    
    def get_editor_camera(self) -> Camera:
        """Get the editor camera for external access."""
        return self.editor_camera

    def set_frustum_aspect(self, aspect: float):
        """Set the aspect ratio for frustum culling (called when viewport resizes)."""
        self.frustum_aspect = aspect

    def _init_movers(self):
        """Initialize mover states."""
        self.mover_states = {}
        for i, brush in enumerate(self.brushes):
            if brush.get('is_mover') and not brush.get('move_once', False):
                if 'original_pos' not in brush:
                    brush['original_pos'] = list(brush['pos'])
                self.mover_states[i] = {'progress': 0.0, 'forward': True}

    def _reset_movers(self):
        """Reset movers to original positions."""
        for i, brush in enumerate(self.brushes):
            if brush.get('is_mover') and 'original_pos' in brush:
                brush['pos'] = list(brush['original_pos'])
        self.mover_states = {}
            
    def run(self):
        """Main logic loop with fixed timestep."""
        self.running = True
        last_time = time.perf_counter()
        accumulator = 0.0
        
        while self.running:
            current_time = time.perf_counter()
            frame_time = current_time - last_time
            last_time = current_time
            
            if frame_time > 0.25: frame_time = 0.25
                
            accumulator += frame_time
            
            while accumulator >= self.TICK_DURATION:
                self._tick(self.TICK_DURATION)
                accumulator -= self.TICK_DURATION
                self._update_tps_counter()
                
            self._prepare_render_state()
            self.game_state.request_swap()
            
            sleep_time = self.TICK_DURATION - (time.perf_counter() - current_time)
            if sleep_time > 0:
                time.sleep(sleep_time * 0.9)
                
    def stop(self):
        self.running = False

    def _update_tps_counter(self):
        self._tick_count += 1
        t = time.perf_counter()
        if t - self._last_tps_time >= 1.0:
            self.actual_tps = self._tick_count / (t - self._last_tps_time)
            self._tick_count = 0
            self._last_tps_time = t
        
    def _tick(self, delta: float):
        """Single logic tick - handles both play mode and editor mode."""
        # Get Input (used in both modes)
        keys = self.game_state.get_keys()
        mouse_delta = self.game_state.consume_mouse_delta()
        
        if self.play_mode and self.player:
            # === PLAY MODE ===
            use_key_pressed = self.game_state.consume_use_key()
            
            # 1. Update Movers (and carry player)
            self._update_movers(delta)

            # 2. Update Player Physics
            if mouse_delta != (0.0, 0.0):
                self.player.update_angle(mouse_delta[0], mouse_delta[1])
                
            self.player.update(keys, self.brushes, delta)
            
            # 3. Handle Triggers (including hurt triggers)
            self._handle_triggers(delta)
            
            # 4. Handle Pickups
            self._handle_pickups(use_key_pressed)
        else:
            # === EDITOR MODE ===
            # Handle editor camera rotation from mouse
            if mouse_delta != (0.0, 0.0):
                self.editor_camera.rotate(mouse_delta[0], mouse_delta[1])
            
            # Handle editor camera movement from keyboard
            speed = self.EDITOR_CAMERA_SPEED * delta
            if Key_W in keys:
                self.editor_camera.move_forward(speed)
            if Key_S in keys:
                self.editor_camera.move_forward(-speed)
            if Key_A in keys:
                self.editor_camera.strafe(-speed)
            if Key_D in keys:
                self.editor_camera.strafe(speed)
            if Key_Space in keys:
                self.editor_camera.move_up(speed)
            if Key_C in keys:
                self.editor_camera.move_up(-speed)

    def _update_movers(self, delta):
        """Calculate new mover positions and move player if standing on one."""
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_mover') or brush.get('move_once', False): continue
            if not brush.get('start_on', False): continue
            
            # Initialize state if missing
            if i not in self.mover_states:
                if 'original_pos' not in brush: brush['original_pos'] = list(brush['pos'])
                self.mover_states[i] = {'progress': 0.0, 'forward': True}
            
            state = self.mover_states[i]
            speed = brush.get('speed', 64.0)
            distance = brush.get('distance', 128.0)
            direction = np.array(brush.get('direction', [0, 1, 0]), dtype=float)
            
            # Normalize direction
            dir_len = np.linalg.norm(direction)
            if dir_len > 0: direction = direction / dir_len
            
            # Animation Logic
            progress_delta = (speed * delta) / distance if distance > 0 else 0
            
            if state['forward']:
                state['progress'] += progress_delta
                if state['progress'] >= 1.0:
                    state['progress'] = 1.0
                    state['forward'] = False
            else:
                state['progress'] -= progress_delta
                if state['progress'] <= 0.0:
                    state['progress'] = 0.0
                    state['forward'] = True
            
            # Calculate position
            eased_progress = self._ease_in_out(state['progress'])
            original = np.array(brush['original_pos'])
            new_pos_np = original + direction * distance * eased_progress
            new_pos_list = new_pos_np.tolist()

            # --- Physics: Apply velocity to player if standing on this brush ---
            if self.player and self.player.ground_object is brush:
                # Calculate how much the brush moved this specific tick
                current_brush_pos = glm.vec3(brush['pos'])
                next_brush_pos = glm.vec3(new_pos_list)
                brush_delta = next_brush_pos - current_brush_pos
                
                # 1. Move player by that delta
                self.player.pos += brush_delta

                # 2. GLUE FIX: If mover is going down, force player slightly deeper
                # This ensures collision detection (in player.py) registers the collision
                # and keeps 'on_ground' = True.
                if brush_delta.y < 0:
                    self.player.pos.y -= 0.1

            # Update brush position
            brush['pos'] = new_pos_list

    def _ease_in_out(self, t):
        if t < 0.5: return 4 * t * t * t
        else: return 1 - pow(-2 * t + 2, 3) / 2

    def _handle_triggers(self, delta: float):
        if not self.player:
            return
            
        player_pos = self.player.pos
        currently_colliding = set()
        
        for i, brush in enumerate(self.brushes):
            if not isinstance(brush, dict) or not brush.get('is_trigger'):
                continue
                
            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            half_size = size / 2.0
            min_bounds = pos - half_size
            max_bounds = pos + half_size
            
            if (min_bounds.x <= player_pos.x <= max_bounds.x and
                min_bounds.y <= player_pos.y <= max_bounds.y and
                min_bounds.z <= player_pos.z <= max_bounds.z):
                currently_colliding.add(i)
                
                trigger_type = brush.get('trigger_type', 'multiple').lower()
                
                # Handle hurt triggers - continuous damage while inside
                if brush.get('hurt', False):
                    self._handle_hurt_trigger(i, brush, delta)
                
                if trigger_type == 'once':
                    # Only fire once, ever
                    if i not in self.player_in_triggers and i not in self.fired_once_triggers:
                        self._activate_trigger(brush, i)
                        self.fired_once_triggers.add(i)
                else:
                    # 'multiple' - fire on entry only (not continuously)
                    if i not in self.player_in_triggers:
                        self._activate_trigger(brush, i)
        
        # Clean up hurt timers for triggers we've left
        triggers_left = self.player_in_triggers - currently_colliding
        for trigger_id in triggers_left:
            if trigger_id in self.hurt_trigger_timers:
                del self.hurt_trigger_timers[trigger_id]
                    
        self.player_in_triggers = currently_colliding
    
    def _handle_hurt_trigger(self, trigger_id: int, brush: Dict, delta: float):
        """Handle damage from hurt triggers."""
        hurt_amount = brush.get('hurt_amount', 10)
        
        # Initialize timer if first time entering
        if trigger_id not in self.hurt_trigger_timers:
            # Deal damage immediately on first contact
            self._apply_damage(hurt_amount)
            self.hurt_trigger_timers[trigger_id] = self.HURT_INTERVAL
        else:
            # Count down timer
            self.hurt_trigger_timers[trigger_id] -= delta
            
            # Deal damage when timer expires
            if self.hurt_trigger_timers[trigger_id] <= 0:
                self._apply_damage(hurt_amount)
                self.hurt_trigger_timers[trigger_id] = self.HURT_INTERVAL
    
    def _apply_damage(self, amount: int):
        """Apply damage to the player."""
        self.player_health = max(0, self.player_health - amount)
        # Could add death handling here if health reaches 0
        
    def _activate_trigger(self, brush: Dict, trigger_id: int):
        target_name = brush.get('target')
        if not target_name:
            return
        
        # Try to find target in brushes (movers)
        for b in self.brushes:
            if b.get('name') == target_name and b.get('is_mover'):
                b['start_on'] = not b.get('start_on', False)
                return
        
        # Try to find target in things (speakers, lights, etc.)
        for thing in self.things:
            if hasattr(thing, 'name') and thing.name == target_name:
                # Handle Speaker
                if Speaker and isinstance(thing, Speaker):
                    # Toggle speaker state
                    current_state = thing.properties.get('state', 'off')
                    thing.properties['state'] = 'on' if current_state == 'off' else 'off'
                    return
                # Handle Light
                if Light and isinstance(thing, Light):
                    current_state = thing.properties.get('state', 'on')
                    thing.properties['state'] = 'on' if current_state == 'off' else 'off'
                    return
            
    def _handle_pickups(self, use_key_pressed: bool):
        """Handle pickup collection based on activation type."""
        if not self.player or not Pickup:
            return
            
        player_pos = self.player.pos
        pickup_radius = 32.0  # Distance to collect a pickup
        use_radius = 64.0     # Distance to use a pickup with E key
        
        for i, thing in enumerate(self.things):
            if not isinstance(thing, Pickup):
                continue
            if thing.properties.get('collected', False):
                continue
            if i in self.collected_pickups:
                continue
                
            thing_pos = glm.vec3(thing.pos)
            distance = glm.distance(player_pos, thing_pos)
            
            activation = thing.properties.get('activation', 'walk_over')
            
            should_collect = False
            if activation == 'walk_over' and distance <= pickup_radius:
                should_collect = True
            elif activation == 'use' and use_key_pressed and distance <= use_radius:
                should_collect = True
                
            if should_collect:
                self._collect_pickup(thing, i)
    
    def _collect_pickup(self, pickup, pickup_id: int):
        """Actually collect a pickup and apply its effect."""
        item_type = pickup.properties.get('item_type', 'health')
        value = pickup.properties.get('value', 25)
        
        if item_type == 'health':
            self.player_health = min(self.player_max_health, self.player_health + value)
        elif item_type == 'armour':
            # Could add armor system later
            pass
        elif item_type == 'ammo':
            # Could add ammo system later
            pass
            
        # Mark as collected
        pickup.properties['collected'] = True
        self.collected_pickups.add(pickup_id)

    # =====================================================
    # FRUSTUM CULLING METHODS
    # =====================================================
    
    def _extract_frustum_planes(self, proj_view: glm.mat4):
        """
        Extract the 6 frustum planes from a projection*view matrix.
        Returns list of (a, b, c, d) tuples representing plane equations ax + by + cz + d = 0
        Planes point inward (positive = inside frustum).
        """
        m = proj_view
        planes = []
        
        # Left:   row3 + row0
        planes.append(self._normalize_plane(
            m[0][3] + m[0][0],
            m[1][3] + m[1][0],
            m[2][3] + m[2][0],
            m[3][3] + m[3][0]
        ))
        # Right:  row3 - row0
        planes.append(self._normalize_plane(
            m[0][3] - m[0][0],
            m[1][3] - m[1][0],
            m[2][3] - m[2][0],
            m[3][3] - m[3][0]
        ))
        # Bottom: row3 + row1
        planes.append(self._normalize_plane(
            m[0][3] + m[0][1],
            m[1][3] + m[1][1],
            m[2][3] + m[2][1],
            m[3][3] + m[3][1]
        ))
        # Top:    row3 - row1
        planes.append(self._normalize_plane(
            m[0][3] - m[0][1],
            m[1][3] - m[1][1],
            m[2][3] - m[2][1],
            m[3][3] - m[3][1]
        ))
        # Near:   row3 + row2
        planes.append(self._normalize_plane(
            m[0][3] + m[0][2],
            m[1][3] + m[1][2],
            m[2][3] + m[2][2],
            m[3][3] + m[3][2]
        ))
        # Far:    row3 - row2
        planes.append(self._normalize_plane(
            m[0][3] - m[0][2],
            m[1][3] - m[1][2],
            m[2][3] - m[2][2],
            m[3][3] - m[3][2]
        ))
        
        return planes

    def _normalize_plane(self, a, b, c, d):
        """Normalize a plane equation."""
        length = math.sqrt(a*a + b*b + c*c)
        if length < 1e-8:
            return (0, 0, 0, 0)
        return (a/length, b/length, c/length, d/length)

    def _aabb_in_frustum(self, planes, center, half_size):
        """
        Test if an AABB is inside or intersects the frustum.
        Uses the "p-vertex" optimization for fast rejection.
        Returns True if potentially visible, False if definitely outside.
        """
        for plane in planes:
            a, b, c, d = plane
            
            # Find the "positive vertex" (p-vertex) - the corner furthest in the plane's normal direction
            px = center[0] + half_size[0] if a >= 0 else center[0] - half_size[0]
            py = center[1] + half_size[1] if b >= 0 else center[1] - half_size[1]
            pz = center[2] + half_size[2] if c >= 0 else center[2] - half_size[2]
            
            # If p-vertex is outside this plane, the entire AABB is outside
            if a*px + b*py + c*pz + d < 0:
                return False
        
        return True

    def _prepare_render_state(self):
        """Prepare render state with frustum culling."""
        write_state = self.game_state.get_write_state()
        
        # Set mode flag
        write_state.is_play_mode = self.play_mode
        
        # Get camera info based on mode
        if self.play_mode and self.player:
            # Play mode - use player camera
            write_state.player_pos = glm.vec3(self.player.pos)
            write_state.player_angle = self.player.angle
            write_state.player_pitch = self.player.pitch
            camera_pos = self.player.pos
            view_matrix = self.player.get_view_matrix()
            fov = 90.0  # Player FOV
        else:
            # Editor mode - use editor camera
            write_state.editor_camera_pos = glm.vec3(self.editor_camera.pos)
            write_state.editor_camera_yaw = self.editor_camera.yaw
            write_state.editor_camera_pitch = self.editor_camera.pitch
            write_state.editor_camera_fov = self.editor_camera.fov
            camera_pos = self.editor_camera.pos
            view_matrix = self.editor_camera.get_view_matrix()
            fov = self.editor_camera.fov
        
        write_state.camera_view_matrix = view_matrix
        
        # Player stats
        write_state.player_health = self.player_health
        write_state.player_max_health = self.player_max_health

        # --- FRUSTUM CULLING ---
        # Build projection matrix
        projection = glm.perspective(glm.radians(fov), self.frustum_aspect, 1.0, 10000.0)
        proj_view = projection * view_matrix
        frustum_planes = self._extract_frustum_planes(proj_view)
        
        # Build visible brush list with culling
        safe_brushes = []
        total_count = 0
        culled_count = 0
        
        for b in self.brushes:
            total_count += 1
            
            # Always skip hidden brushes
            if b.get('hidden', False):
                culled_count += 1
                continue
            
            # Frustum cull check (only if culling is enabled)
            if self.culling_enabled:
                pos = b.get('pos', [0, 0, 0])
                size = b.get('size', [64, 64, 64])
                center = (pos[0], pos[1], pos[2])
                half_size = (size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
                
                if not self._aabb_in_frustum(frustum_planes, center, half_size):
                    culled_count += 1
                    continue
            
            # Visible - add to render list
            if b.get('is_mover', False):
                safe_brushes.append(b.copy())
            else:
                safe_brushes.append(b)

        write_state.visible_brushes = safe_brushes
        write_state.total_brushes = total_count
        write_state.culled_brushes = culled_count
        
        # Filter out collected pickups from visible things (only in play mode)
        visible_things = []
        for i, thing in enumerate(self.things):
            if self.play_mode and Pickup and isinstance(thing, Pickup) and i in self.collected_pickups:
                continue
            visible_things.append(thing)
        
        write_state.visible_things = visible_things
        write_state.timestamp = time.perf_counter()
