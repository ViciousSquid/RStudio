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
Key_Shift = 0x01000020
Key_Control = 0x01000021


class LogicThread(threading.Thread):
    """
    Unified logic thread for both editor and play mode.
    Runs continuously at a fixed timestep (60 Hz).
    """
    
    TICK_RATE = 60
    TICK_DURATION = 1.0 / TICK_RATE
    
    # Editor camera settings
    EDITOR_CAMERA_SPEED = 300.0       # Units per second
    EDITOR_CAMERA_FAST_MULT = 2.5     # Shift multiplier
    EDITOR_MOUSE_SENSITIVITY = 0.15  # Degrees per pixel
    
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
        self.terrain = None  # Reference to terrain for collision
        
        # Frustum culling settings
        self.culling_enabled = True
        self.frustum_aspect = 16.0 / 9.0
        
        # Editor camera (used when not in play mode)
        self.editor_camera = Camera()
        self.editor_camera.pos = glm.vec3(0, 150, 400)
        
        # Flag to enable editor camera keyboard movement
        self._editor_mouselook_active = False
        
        # Player stats
        self.player_health = 100
        self.player_max_health = 100
        
        # Trigger state
        self.player_in_triggers: set = set()
        self.fired_once_triggers: set = set()

        # Logic Gate State: {gate_name: {set_of_active_source_names}}
        self.gate_inputs = {}
        
        # Hurt trigger timers
        self.hurt_trigger_timers: Dict[int, float] = {}
        self.HURT_INTERVAL = 0.5
        
        # Pickup state
        self.collected_pickups: set = set()
        self.collected_keys: set = set()
        
        # Respawn timers: {pickup_id: time_remaining}
        self.respawn_timers: Dict[int, float] = {}
        
        # Speaker state
        self.active_speakers: set = set()
        
        # Initialize Mover/Door Lists
        self.movers = []
        self.doors = []
        
        # Mover Animation State
        self.mover_states = {}
        
        # Door Animation State
        self.door_states: Dict[int, Dict[str, Any]] = {}
        
        # Interaction State
        self.current_hud_message = ""
        
        # Visual FX
        self.bullet_marks = []
        self.BULLET_FADE_TIME = 20.0
        
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
        """Switch between editor and play mode."""
        self.play_mode = enabled
        if enabled:
            self._init_movers()
            self._init_doors()
            # Reset player stats
            self.player_health = 100
            self.player_max_health = 100
            # Reset pickup state
            self.collected_pickups.clear()
            self.collected_keys.clear()
            self.respawn_timers.clear()
            for thing in self.things:
                if Pickup and isinstance(thing, Pickup):
                    thing.properties['collected'] = False
            # Reset speaker state
            self.active_speakers.clear()
            self.hurt_trigger_timers.clear()
            self.current_hud_message = ""
            # Reset gate inputs tracking
            self.gate_inputs = {}
            # Reset active weapon
            self.active_weapon = None
            # Reset visual fx
            self.bullet_marks = []
        else:
            self.player_in_triggers.clear()
            self.fired_once_triggers.clear()
            self.collected_pickups.clear()
            self.collected_keys.clear()
            self.respawn_timers.clear()
            self.active_speakers.clear()
            self.hurt_trigger_timers.clear()
            self._reset_movers()
            self._reset_doors()
            self.current_hud_message = ""
            self.gate_inputs = {}
            self.active_weapon = None
            self.bullet_marks = []
    
    def set_terrain(self, terrain):
        """Set terrain reference for collision detection."""
        self.terrain = terrain
    
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
        """Set the aspect ratio for frustum culling."""
        self.frustum_aspect = aspect

    def _init_movers(self):
        """Initialize mover states and list."""
        self.mover_states = {}
        self.movers = [] # Initialize list for physics
        for i, brush in enumerate(self.brushes):
            if brush.get('is_mover'):
                self.movers.append(brush)
                if not brush.get('move_once', False):
                    if 'original_pos' not in brush:
                        brush['original_pos'] = list(brush['pos'])
                    self.mover_states[i] = {'progress': 0.0, 'forward': True}

    def _reset_movers(self):
        """Reset movers to original positions."""
        self.movers = []
        for i, brush in enumerate(self.brushes):
            if brush.get('is_mover') and 'original_pos' in brush:
                brush['pos'] = list(brush['original_pos'])
        self.mover_states = {}

    def _init_doors(self):
        """Initialize door states and list."""
        self.door_states = {}
        self.doors = [] # Initialize list for physics
        for i, brush in enumerate(self.brushes):
            if brush.get('is_door'):
                self.doors.append(brush)
                if 'original_pos' not in brush:
                    brush['original_pos'] = list(brush['pos'])
                self.door_states[i] = {
                    'progress': 0.0,
                    'state': 'closed',
                    'open_timer': 0.0,
                }

    def _reset_doors(self):
        """Reset doors to original positions."""
        self.doors = []
        for i, brush in enumerate(self.brushes):
            if brush.get('is_door') and 'original_pos' in brush:
                brush['pos'] = list(brush['original_pos'])
        self.door_states = {}
            
    def run(self):
        """Main logic loop with fixed timestep."""
        self.running = True
        last_time = time.perf_counter()
        accumulator = 0.0
        
        while self.running:
            current_time = time.perf_counter()
            frame_time = current_time - last_time
            last_time = current_time
            
            if frame_time > 0.25:
                frame_time = 0.25
                
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
        """Process one logic tick."""
        if self.play_mode:
            self._tick_play_mode(delta)
        else:
            self._tick_editor_mode(delta)

    def _tick_editor_mode(self, delta: float):
        """
        Process editor mode tick:
        - Handle camera rotation from mouse
        - Handle camera movement from WASD
        """
        # Consume mouse delta for camera rotation
        dx, dy = self.game_state.consume_mouse_delta()
        if dx != 0 or dy != 0:
            self._editor_mouselook_active = True
            self.editor_camera.yaw += dx * self.EDITOR_MOUSE_SENSITIVITY
            self.editor_camera.pitch -= dy * self.EDITOR_MOUSE_SENSITIVITY
            self.editor_camera.pitch = max(-89.0, min(89.0, self.editor_camera.pitch))
        
        # Handle keyboard movement when mouselook is active
        keys = self.game_state.get_keys()
        
        # Calculate movement direction based on camera orientation
        yaw_rad = math.radians(self.editor_camera.yaw)
        
        # Forward vector (ignoring pitch for horizontal movement)
        forward = glm.vec3(math.cos(yaw_rad), 0, math.sin(yaw_rad))
        forward = glm.normalize(forward)
        
        # Right vector
        right = glm.normalize(glm.cross(forward, glm.vec3(0, 1, 0)))
        
        # Up vector
        up = glm.vec3(0, 1, 0)
        
        # Calculate movement
        move_dir = glm.vec3(0, 0, 0)
        
        if Key_W in keys: move_dir += forward
        if Key_S in keys: move_dir -= forward
        if Key_A in keys: move_dir -= right
        if Key_D in keys: move_dir += right
        if Key_Space in keys: move_dir += up
        if Key_C in keys: move_dir -= up
        
        # Apply movement
        if glm.length(move_dir) > 0.001:
            move_dir = glm.normalize(move_dir)
            speed = self.EDITOR_CAMERA_SPEED
            if Key_Shift in keys:
                speed *= self.EDITOR_CAMERA_FAST_MULT
            self.editor_camera.pos += move_dir * speed * delta

    def _tick_play_mode(self, delta):
        if not self.player: return
        
        # --- CRITICAL FIX: Update Movers & Doors FIRST ---
        # This prevents the player from falling through platforms moving downwards,
        # and allows "carrying" logic to be applied before collision resolution.
        self._update_respawns(delta)
        self._update_movers(delta)
        self._update_doors(delta)
        
        # Inputs
        keys = self.game_state.get_keys()
        mouse_dx, mouse_dy = self.game_state.consume_mouse_delta()
        use_key = self.game_state.consume_use_key()
        
        # Mouse Look
        SENSITIVITY = 0.002
        self.player.angle -= mouse_dx * SENSITIVITY
        self.player.pitch -= mouse_dy * SENSITIVITY
        self.player.pitch = max(-1.5, min(1.5, self.player.pitch))
        
        # Movement
        move_dir = glm.vec3(0)
        if Key_W in keys: move_dir.z += 1
        if Key_S in keys: move_dir.z -= 1
        
        if Key_A in keys: move_dir.x += 1  
        if Key_D in keys: move_dir.x -= 1 
        
        jump = Key_Space in keys
        crouch = Key_C in keys
        
        # Physics Update
        self.player.update(delta, move_dir, jump, crouch, self.brushes, self.movers, self.doors, self.terrain)
        
        # Interaction / Gameplay
        self._handle_interactions(use_key)
        self._check_pickups()
        self._handle_triggers(use_key)
        
        # Shooting
        if self.game_state.consume_shot():
            self._handle_shooting()
            
        self._update_bullet_marks()

    def _check_pickups(self):
        """Helper to check specifically for walk-over pickups."""
        self._handle_pickups(False)

    def _handle_shooting(self):
        """Raycast from player camera to find hit point."""
        if not self.player or not self.active_weapon:
            return

        # Calculate Player Direction Vector
        yaw_rad = self.player.angle
        pitch_rad = self.player.pitch
        
        # Convert polar to cartesian vector (Forward vector)
        dir_x = math.sin(yaw_rad) * math.cos(pitch_rad)
        dir_y = math.sin(pitch_rad)
        dir_z = math.cos(yaw_rad) * math.cos(pitch_rad)
        
        # Assuming Y-up coordinate system
        ray_origin = glm.vec3(self.player.pos.x, self.player.pos.y + self.player.camera_height, self.player.pos.z)
        ray_dir = glm.normalize(glm.vec3(dir_x, dir_y, dir_z))

        closest_hit = None
        closest_dist = float('inf')

        # Raycast against all Brushes
        for brush in self.brushes:
            # Skip triggers, water, fog, hidden
            if (brush.get('is_trigger') or brush.get('hidden') or 
                brush.get('is_water') or brush.get('is_fog')):
                continue

            # Get AABB
            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            min_b = pos - size * 0.5
            max_b = pos + size * 0.5

            hit, dist = self._intersect_ray_aabb(ray_origin, ray_dir, min_b, max_b)
            
            if hit and dist < closest_dist:
                closest_dist = dist
                closest_hit = ray_origin + ray_dir * dist

        if closest_hit:
            self.bullet_marks.append({
                'pos': closest_hit,
                'time': time.perf_counter()
            })

    def _intersect_ray_aabb(self, origin, direction, box_min, box_max):
        """Standard Slab Method for Ray-AABB intersection."""
        t_min = 0.0
        t_max = 10000.0 # Max Range

        for i in range(3):
            if abs(direction[i]) < 1e-6:
                if origin[i] < box_min[i] or origin[i] > box_max[i]:
                    return False, 0
            else:
                inv_d = 1.0 / direction[i]
                t1 = (box_min[i] - origin[i]) * inv_d
                t2 = (box_max[i] - origin[i]) * inv_d
                
                t_near = min(t1, t2)
                t_far = max(t1, t2)
                
                t_min = max(t_min, t_near)
                t_max = min(t_max, t_far)
                
                if t_min > t_max:
                    return False, 0

        return True, t_min

    def _update_bullet_marks(self):
        current_time = time.perf_counter()
        self.bullet_marks = [
            m for m in self.bullet_marks 
            if (current_time - m['time']) < self.BULLET_FADE_TIME
        ]

    def _handle_interactions(self, use_key_pressed: bool):
        """Check for interactive objects (Doors, Pickups) in front of the player."""
        self.current_hud_message = ""
        
        # --- 1. DOOR INTERACTION (Raycast & Touch) ---
        found_door_idx = -1
        found_door_brush = None
        
        reach_distance = 80.0
        
        px, py, pz = self.player.pos
        
        # Simple proximity check since precise raycasting can be tricky with inconsistent angles
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_door'): continue
            
            pos = brush['pos']
            size = brush['size']
            
            dx = abs(pos[0] - px)
            dy = abs(pos[1] - py)
            dz = abs(pos[2] - pz)
            
            # Check within reach
            if dx < size[0]/2 + reach_distance and dz < size[2]/2 + reach_distance and dy < size[1]/2 + 64:
                found_door_idx = i
                found_door_brush = brush
                break

        if found_door_brush:
            door_state = self.door_states.get(found_door_idx, {}).get('state', 'closed')
            if door_state != 'closed': return
            if found_door_brush.get('door_auto_open', False): return
            
            is_locked = found_door_brush.get('door_locked', False)
            needs_key = found_door_brush.get('door_needs_key', False)
            key_name = found_door_brush.get('door_key_name', '')
            
            if is_locked:
                self.current_hud_message = "This door is locked remotely"
            elif needs_key:
                has_key = self.has_key(key_name)
                pretty_key_name = key_name.replace('_', ' ').title() if key_name else "Key"
                if has_key:
                    self.current_hud_message = f"Press E to unlock ({pretty_key_name})"
                    if use_key_pressed: self._trigger_door_open(found_door_idx)
                else:
                    self.current_hud_message = f"You need the {pretty_key_name}"
            else:
                self.current_hud_message = "Press E to open"
                if use_key_pressed: self._trigger_door_open(found_door_idx)
            return

        # --- 2. PICKUP INTERACTION (Look-At) ---
        if Pickup:
            p_pos = glm.vec3(px, py, pz)
            # Re-calculate forward vector properly for look-at check
            p_forward = glm.vec3(math.sin(self.player.angle), 0, math.cos(self.player.angle))
            
            for i, thing in enumerate(self.things):
                if not isinstance(thing, Pickup): continue
                if thing.properties.get('collected', False): continue
                if thing.properties.get('activation') != 'use': continue
                
                t_pos = glm.vec3(thing.pos)
                dist = glm.distance(p_pos, t_pos)
                
                if dist < 80.0:
                    to_thing = glm.normalize(t_pos - p_pos)
                    # Dot product check
                    if glm.dot(p_forward, to_thing) > 0.8:
                        item_name = thing.properties.get('item_type', 'Item').replace('_', ' ').title()
                        self.current_hud_message = f"[E] Pick up {item_name}"
                        if use_key_pressed:
                            self._collect_pickup(thing, i)
                        return

    def _trigger_door_open(self, door_idx: int):
        """Helper to force a door to start opening."""
        if door_idx in self.door_states:
            state = self.door_states[door_idx]
            if state['state'] == 'closed':
                state['state'] = 'opening'

    def _handle_triggers(self, use_key_pressed: bool):
        """Check and activate triggers."""
        if not self.player: return
            
        player_pos = self.player.pos
        currently_in = set()
        
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_trigger'): continue
                
            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            half_size = size / 2.0
            min_b = pos - half_size
            max_b = pos + half_size
            
            if (min_b.x <= player_pos.x <= max_b.x and
                min_b.y <= player_pos.y <= max_b.y and
                min_b.z <= player_pos.z <= max_b.z):
                
                currently_in.add(i)
                if i not in self.player_in_triggers:
                    self._activate_trigger(brush, i, use_key_pressed)
                else:
                    if brush.get('trigger_action') == 'hurt':
                        self._process_hurt_trigger(brush, i)
        
        self.player_in_triggers = currently_in

    def _activate_trigger(self, brush: dict, trigger_id: int, use_key: bool):
        """Activate a trigger."""
        trigger_type = brush.get('trigger_type', 'multiple')
        if trigger_type == 'once' and trigger_id in self.fired_once_triggers:
            return
        
        action = brush.get('trigger_action', 'target')
        
        if action == 'hurt':
            damage = brush.get('damage', 10)
            self.player_health = max(0, self.player_health - damage)
            self.hurt_trigger_timers[trigger_id] = self.HURT_INTERVAL
            
        elif action == 'target':
            target_name = brush.get('target')
            if target_name:
                source_name = brush.get('name', f'trigger_{trigger_id}')
                self._activate_target(target_name, source_name)
        
        if trigger_type == 'once':
            self.fired_once_triggers.add(trigger_id)

    def _process_hurt_trigger(self, brush: dict, trigger_id: int):
        """Process continuous damage from hurt trigger."""
        if trigger_id in self.hurt_trigger_timers:
            self.hurt_trigger_timers[trigger_id] -= self.TICK_DURATION
            if self.hurt_trigger_timers[trigger_id] <= 0:
                damage = brush.get('damage', 10)
                self.player_health = max(0, self.player_health - damage)
                self.hurt_trigger_timers[trigger_id] = self.HURT_INTERVAL

    def _activate_target(self, target_name: str, source_name: str = None):
        """Activate a named target."""
        # 1. Handle Logic Gates
        target_thing = None
        for thing in self.things:
            if hasattr(thing, 'name') and thing.name == target_name:
                target_thing = thing
                break
        
        if target_thing and hasattr(target_thing, 'properties') and target_thing.properties.get('type') == 'logic_gate':
            self._process_logic_gate(target_thing, source_name)
            return

        # 2. Handle Brushes (Movers/Doors)
        for brush in self.brushes:
            if brush.get('name') == target_name:
                if brush.get('is_mover'):
                    brush['start_on'] = not brush.get('start_on', False)
                elif brush.get('is_door'):
                    idx = self.brushes.index(brush)
                    if idx in self.door_states:
                        state = self.door_states[idx]
                        if state['state'] == 'closed':
                            state['state'] = 'opening'
                        elif state['state'] == 'open':
                            state['state'] = 'closing'
                return

        # 3. Handle Other Things (Lights)
        if target_thing:
            if Light and isinstance(target_thing, Light):
                current = target_thing.properties.get('state', 'on')
                target_thing.properties['state'] = 'off' if current == 'on' else 'on'

    def _process_logic_gate(self, gate, source_name):
        if not source_name: return
        
        gate_name = gate.name
        l_type = gate.properties.get('logic_type', 'AND')
        target = gate.properties.get('target', '')
        
        if gate_name not in self.gate_inputs:
            self.gate_inputs[gate_name] = set()
            
        if source_name in self.gate_inputs[gate_name]:
            self.gate_inputs[gate_name].remove(source_name)
        else:
            self.gate_inputs[gate_name].add(source_name)
            
        active_inputs = len(self.gate_inputs[gate_name])
        
        total_possible_inputs = 0
        for b in self.brushes:
            if b.get('target') == gate_name: total_possible_inputs += 1
        for t in self.things:
            if t.properties.get('target') == gate_name and t != gate: total_possible_inputs += 1
            
        if total_possible_inputs == 0: total_possible_inputs = 1
        
        should_fire = False
        if l_type == 'AND': should_fire = (active_inputs >= total_possible_inputs)
        elif l_type == 'OR': should_fire = (active_inputs > 0)
        elif l_type == 'XOR': should_fire = (active_inputs == 1)
        elif l_type == 'NAND': should_fire = (active_inputs < total_possible_inputs)
        elif l_type == 'NOR': should_fire = (active_inputs == 0)

        if should_fire and target:
            self._activate_target(target, gate_name)

    def _handle_pickups(self, use_key_pressed: bool):
        """Handle pickup collection (proximity check)."""
        if not self.player or not Pickup: return
            
        player_pos = self.player.pos
        pickup_radius = 32.0
        
        for i, thing in enumerate(self.things):
            if not isinstance(thing, Pickup): continue
            if thing.properties.get('collected', False): continue
            if i in self.collected_pickups: continue
                
            thing_pos = glm.vec3(thing.pos)
            distance = glm.distance(player_pos, thing_pos)
            
            if thing.properties.get('activation') == 'walk_over' and distance <= pickup_radius:
                self._collect_pickup(thing, i)
    
    def _collect_pickup(self, pickup, pickup_id: int):
        """Collect a pickup and apply its effect."""
        item_type = pickup.properties.get('item_type', 'health')
        value = pickup.properties.get('value', 25)
        
        if item_type == 'health':
            self.player_health = min(self.player_max_health, self.player_health + value)
        elif item_type == 'key':
            key_name = pickup.properties.get('key_name', '')
            if key_name:
                self.collected_keys.add(key_name)
        elif item_type in ['gun1', 'gun2']:
            self.active_weapon = item_type
            self.current_hud_message = f"Picked up {item_type.upper()}"
        
        pickup.properties['collected'] = True
        self.collected_pickups.add(pickup_id)
        
        if pickup.properties.get('respawns', False):
            respawn_time = pickup.properties.get('respawn_time', 20.0)
            self.respawn_timers[pickup_id] = respawn_time
    
    def _update_respawns(self, delta: float):
        """Update respawn timers and respawn pickups when ready."""
        if not Pickup: return
        
        to_respawn = []
        for pickup_id, time_remaining in list(self.respawn_timers.items()):
            self.respawn_timers[pickup_id] = time_remaining - delta
            if self.respawn_timers[pickup_id] <= 0:
                to_respawn.append(pickup_id)
        
        for pickup_id in to_respawn:
            del self.respawn_timers[pickup_id]
            if pickup_id < len(self.things):
                thing = self.things[pickup_id]
                if isinstance(thing, Pickup):
                    thing.properties['collected'] = False
                    self.collected_pickups.discard(pickup_id)
    
    def has_key(self, key_name: str) -> bool:
        return key_name in self.collected_keys

    def _update_movers(self, delta: float):
        """Update all active movers and carry the player."""
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_mover') or brush.get('move_once', False): continue
            if not brush.get('start_on', False): continue
            
            if i not in self.mover_states:
                if 'original_pos' not in brush:
                    brush['original_pos'] = list(brush['pos'])
                self.mover_states[i] = {'progress': 0.0, 'forward': True}
            
            state = self.mover_states[i]
            speed = brush.get('speed', 64.0)
            distance = brush.get('distance', 128.0)
            direction = np.array(brush.get('direction', [0, 1, 0]), dtype=float)
            
            dir_length = np.linalg.norm(direction)
            if dir_length > 0: direction = direction / dir_length
            
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
            
            t = state['progress']
            eased = 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2
            
            original = np.array(brush['original_pos'])
            offset = direction * distance * eased
            new_pos = original + offset
            
            # --- CRITICAL FIX: Velocity Inheritance ---
            current_pos = np.array(brush['pos'])
            move_delta = new_pos - current_pos
            
            # Apply new position to brush
            brush['pos'] = new_pos.tolist()
            
            # If player was standing on this brush in the previous frame, apply delta
            if self.player and self.player.ground_object == brush:
                self.player.pos += glm.vec3(move_delta[0], move_delta[1], move_delta[2])

    def _update_doors(self, delta: float):
        """Update door animations and carry the player."""
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_door'): continue
            if i not in self.door_states: continue
            
            state = self.door_states[i]
            speed = brush.get('speed', 128.0)
            distance = brush.get('distance', 128.0)
            open_time = brush.get('open_time', 3.0)
            direction = np.array(brush.get('direction', [0, 1, 0]), dtype=float)
            
            dir_length = np.linalg.norm(direction)
            if dir_length > 0: direction = direction / dir_length
            
            progress_delta = (speed * delta) / distance if distance > 0 else 0
            
            if state['state'] == 'opening':
                state['progress'] += progress_delta
                if state['progress'] >= 1.0:
                    state['progress'] = 1.0
                    state['state'] = 'open'
                    state['open_timer'] = open_time
                    
            elif state['state'] == 'open':
                state['open_timer'] -= delta
                if state['open_timer'] <= 0:
                    state['state'] = 'closing'
                    
            elif state['state'] == 'closing':
                state['progress'] -= progress_delta
                if state['progress'] <= 0.0:
                    state['progress'] = 0.0
                    state['state'] = 'closed'
            
            original = np.array(brush['original_pos'])
            offset = direction * distance * state['progress']
            new_pos = original + offset
            
            # --- CRITICAL FIX: Velocity Inheritance for Doors ---
            current_pos = np.array(brush['pos'])
            move_delta = new_pos - current_pos
            
            brush['pos'] = new_pos.tolist()
            
            # Carry player
            if self.player and self.player.ground_object == brush:
                self.player.pos += glm.vec3(move_delta[0], move_delta[1], move_delta[2])

    def _extract_frustum_planes(self, proj_view: glm.mat4):
        """Extract the 6 frustum planes."""
        m = proj_view
        planes = []
        planes.append(self._normalize_plane(m[0][3] + m[0][0], m[1][3] + m[1][0], m[2][3] + m[2][0], m[3][3] + m[3][0])) # Left
        planes.append(self._normalize_plane(m[0][3] - m[0][0], m[1][3] - m[1][0], m[2][3] - m[2][0], m[3][3] - m[3][0])) # Right
        planes.append(self._normalize_plane(m[0][3] + m[0][1], m[1][3] + m[1][1], m[2][3] + m[2][1], m[3][3] + m[3][1])) # Bottom
        planes.append(self._normalize_plane(m[0][3] - m[0][1], m[1][3] - m[1][1], m[2][3] - m[2][1], m[3][3] - m[3][1])) # Top
        planes.append(self._normalize_plane(m[0][3] + m[0][2], m[1][3] + m[1][2], m[2][3] + m[2][2], m[3][3] + m[3][2])) # Near
        planes.append(self._normalize_plane(m[0][3] - m[0][2], m[1][3] - m[1][2], m[2][3] - m[2][2], m[3][3] - m[3][2])) # Far
        return planes

    def _normalize_plane(self, a, b, c, d):
        length = math.sqrt(a*a + b*b + c*c)
        if length < 1e-8: return (0, 0, 0, 0)
        return (a/length, b/length, c/length, d/length)

    def _aabb_in_frustum(self, planes, center, half_size):
        for plane in planes:
            a, b, c, d = plane
            px = center[0] + half_size[0] if a >= 0 else center[0] - half_size[0]
            py = center[1] + half_size[1] if b >= 0 else center[1] - half_size[1]
            pz = center[2] + half_size[2] if c >= 0 else center[2] - half_size[2]
            if a*px + b*py + c*pz + d < 0: return False
        return True

    def _prepare_render_state(self):
        """Prepare render state with frustum culling."""
        write_state = self.game_state.get_write_state()
        
        write_state.is_play_mode = self.play_mode
        
        if self.play_mode and self.player:
            write_state.player_pos = glm.vec3(self.player.pos)
            write_state.player_angle = self.player.angle
            write_state.player_pitch = self.player.pitch
            view_matrix = self.player.get_view_matrix()
            fov = 90.0
        else:
            write_state.editor_camera_pos = glm.vec3(self.editor_camera.pos)
            write_state.editor_camera_yaw = self.editor_camera.yaw
            write_state.editor_camera_pitch = self.editor_camera.pitch
            write_state.editor_camera_fov = self.editor_camera.fov
            view_matrix = self.editor_camera.get_view_matrix()
            fov = self.editor_camera.fov
        
        write_state.camera_view_matrix = view_matrix
        
        write_state.player_health = self.player_health
        write_state.player_max_health = self.player_max_health
        
        write_state.collected_keys = set(self.collected_keys)
        write_state.hud_message = self.current_hud_message
        write_state.active_weapon = self.active_weapon

        # Transfer Bullet Marks to Render State
        current_time = time.perf_counter()
        render_marks = []
        for m in self.bullet_marks:
            age = current_time - m['time']
            if age < self.BULLET_FADE_TIME:
                alpha = max(0.0, 1.0 - (age / self.BULLET_FADE_TIME))
                render_marks.append({
                    'pos': [m['pos'].x, m['pos'].y, m['pos'].z],
                    'alpha': alpha
                })
        write_state.bullet_marks = render_marks

        # Ensure JSON-serializable light data
        visible_things = []
        for i, thing in enumerate(self.things):
            if self.play_mode and Pickup and isinstance(thing, Pickup) and i in self.collected_pickups:
                continue
            if Light and isinstance(thing, Light):
                if hasattr(thing, 'pos') and hasattr(thing.pos, 'x'):
                     thing.pos = [thing.pos[0], thing.pos[1], thing.pos[2]]
            visible_things.append(thing)
        
        write_state.visible_things = visible_things

        # FRUSTUM CULLING
        projection = glm.perspective(glm.radians(fov), self.frustum_aspect, 1.0, 10000.0)
        proj_view = projection * view_matrix
        frustum_planes = self._extract_frustum_planes(proj_view)
        
        safe_brushes = []
        total_count = 0
        culled_count = 0
        
        for b in self.brushes:
            total_count += 1
            if b.get('hidden', False):
                culled_count += 1
                continue
            
            if self.culling_enabled:
                pos = b.get('pos', [0, 0, 0])
                size = b.get('size', [64, 64, 64])
                center = (pos[0], pos[1], pos[2])
                half_size = (size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
                if not self._aabb_in_frustum(frustum_planes, center, half_size):
                    culled_count += 1
                    continue
            
            if b.get('is_mover', False) or b.get('is_door', False):
                safe_brushes.append(b.copy())
            else:
                safe_brushes.append(b)

        write_state.visible_brushes = safe_brushes
        write_state.total_brushes = total_count
        write_state.culled_brushes = culled_count
        
        all_brushes = []
        for b in self.brushes:
            if b.get('hidden', False): continue
            if b.get('is_mover', False) or b.get('is_door', False):
                all_brushes.append(b.copy())
            else:
                all_brushes.append(b)
        write_state.all_brushes = all_brushes
        
        write_state.timestamp = time.perf_counter()