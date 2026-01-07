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
    
    In EDITOR mode:
      - Updates editor camera position/rotation based on input
      - Performs frustum culling for visible brushes
      
    In PLAY mode:
      - Updates player physics and position
      - Handles triggers, pickups, doors, movers
      - Performs frustum culling
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
        # Only moves when right mouse button is held (signaled by non-zero mouse delta history)
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
        
        # Mover Animation State
        self.mover_states = {}
        
        # Door Animation State
        self.door_states: Dict[int, Dict[str, Any]] = {}
        
        # Interaction State
        self.current_hud_message = ""
        
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

    def _init_doors(self):
        """Initialize door states."""
        self.door_states = {}
        for i, brush in enumerate(self.brushes):
            if brush.get('is_door'):
                if 'original_pos' not in brush:
                    brush['original_pos'] = list(brush['pos'])
                self.door_states[i] = {
                    'progress': 0.0,
                    'state': 'closed',
                    'open_timer': 0.0,
                }

    def _reset_doors(self):
        """Reset doors to original positions."""
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
        else:
            # If no mouse movement, camera movement keys won't work
            # (requires right-click hold which generates continuous deltas)
            pass
        
        # Handle keyboard movement when mouselook is active
        # In a typical editor, you hold right mouse and use WASD
        keys = self.game_state.get_keys()
        
        # Calculate movement direction based on camera orientation
        yaw_rad = math.radians(self.editor_camera.yaw)
        pitch_rad = math.radians(self.editor_camera.pitch)
        
        # Forward vector (ignoring pitch for horizontal movement)
        forward = glm.vec3(
            math.cos(yaw_rad),
            0,
            math.sin(yaw_rad)
        )
        forward = glm.normalize(forward)
        
        # Right vector
        right = glm.normalize(glm.cross(forward, glm.vec3(0, 1, 0)))
        
        # Up vector
        up = glm.vec3(0, 1, 0)
        
        # Calculate movement
        move_dir = glm.vec3(0, 0, 0)
        
        if Key_W in keys:
            move_dir += forward
        if Key_S in keys:
            move_dir -= forward
        if Key_A in keys:
            move_dir -= right
        if Key_D in keys:
            move_dir += right
        if Key_Space in keys:
            move_dir += up
        if Key_C in keys:
            move_dir -= up
        
        # Apply movement
        if glm.length(move_dir) > 0.001:
            move_dir = glm.normalize(move_dir)
            speed = self.EDITOR_CAMERA_SPEED
            
            # Check for shift (fast movement)
            if Key_Shift in keys:
                speed *= self.EDITOR_CAMERA_FAST_MULT
            
            self.editor_camera.pos += move_dir * speed * delta

    def _tick_play_mode(self, delta: float):
        """Process play mode tick - player physics, triggers, etc."""
        if not self.player:
            return
        
        # Get input
        keys = self.game_state.get_keys()
        dx, dy = self.game_state.consume_mouse_delta()
        use_key = self.game_state.consume_use_key()
        
        # Update player look direction
        if dx != 0 or dy != 0:
            self.player.update_angle(dx, dy)
        
        # Update player physics and movement
        self.player.update(keys, self.brushes, delta, terrain=self.terrain)
        
        # Handle triggers
        self._handle_triggers(use_key)
        
        # Handle interactions (Doors & Pickups prompts)
        self._handle_interactions(use_key)
        
        # Handle pickups (actual collection)
        self._handle_pickups(use_key)
        
        # Handle respawning
        self._update_respawns(delta)
        
        # Update movers
        self._update_movers(delta)
        
        # Update doors
        self._update_doors(delta)

    def _handle_interactions(self, use_key_pressed: bool):
        """
        Check for interactive objects (Doors, Pickups) in front of the player 
        and handle 'E' interaction or display HUD messages.
        """
        self.current_hud_message = ""
        
        # --- 1. DOOR INTERACTION (Raycast & Touch) ---
        found_door_idx = -1
        found_door_brush = None
        
        reach_distance = 80.0
        step_size = 16.0
        
        px, py, pz = self.player.pos
        angle = self.player.angle
        vx = math.cos(angle)
        vz = math.sin(angle)
        
        # Raycast step
        for dist in np.arange(step_size, reach_distance + step_size, step_size):
            check_x = px + vx * dist
            check_z = pz + vz * dist
            check_y = py 
            
            for i, brush in enumerate(self.brushes):
                if not brush.get('is_door'): continue
                
                pos = brush['pos']
                size = brush['size']
                
                if (pos[0] - size[0]/2 <= check_x <= pos[0] + size[0]/2 and
                    pos[2] - size[2]/2 <= check_z <= pos[2] + size[2]/2 and
                    pos[1] - size[1]/2 <= check_y <= pos[1] + size[1]/2):
                    
                    found_door_idx = i
                    found_door_brush = brush
                    break 
            
            if found_door_brush:
                break 

        # Touch check (fallback)
        if not found_door_brush:
            touch_radius = 24.0 
            for i, brush in enumerate(self.brushes):
                if not brush.get('is_door'): continue
                pos = brush['pos']
                size = brush['size']
                
                door_min_x = pos[0] - size[0]/2
                door_max_x = pos[0] + size[0]/2
                door_min_z = pos[2] - size[2]/2
                door_max_z = pos[2] + size[2]/2
                door_min_y = pos[1] - size[1]/2
                door_max_y = pos[1] + size[1]/2

                player_min_x = px - touch_radius
                player_max_x = px + touch_radius
                player_min_z = pz - touch_radius
                player_max_z = pz + touch_radius
                
                overlap_x = (player_min_x < door_max_x) and (player_max_x > door_min_x)
                overlap_z = (player_min_z < door_max_z) and (player_max_z > door_min_z)
                overlap_y = (py > door_min_y) and (py < door_max_y)

                if overlap_x and overlap_z and overlap_y:
                    found_door_idx = i
                    found_door_brush = brush
                    break

        if found_door_brush:
            # Door Logic
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
            
            # Return early if door is blocking interaction
            return

        # --- 2. PICKUP INTERACTION (Look-At) ---
        if Pickup:
            best_pickup = None
            closest_dist = float('inf')
            
            p_pos = glm.vec3(px, py, pz)
            # Player view direction (horizontal)
            p_dir = glm.vec3(vx, 0, vz) 
            
            for i, thing in enumerate(self.things):
                if not isinstance(thing, Pickup): continue
                if thing.properties.get('collected', False): continue
                if thing.properties.get('activation') != 'use': continue
                
                t_pos = glm.vec3(thing.pos)
                dist = glm.distance(p_pos, t_pos)
                
                # Check distance (must be close)
                if dist < 64.0:
                    # Check angle (must be looking at it)
                    to_thing = glm.normalize(t_pos - p_pos)
                    # Dot product > 0.8 is roughly within 35 degrees of center
                    if glm.dot(p_dir, to_thing) > 0.8:
                        if dist < closest_dist:
                            closest_dist = dist
                            best_pickup = thing
            
            if best_pickup:
                item_name = best_pickup.properties.get('item_type', 'Item').replace('_', ' ').title()
                if item_name == "Key":
                    key_name = best_pickup.properties.get('key_name', 'Key').replace('_', ' ').title()
                    self.current_hud_message = f"[E] Pick up {key_name}"
                else:
                    self.current_hud_message = f"[E] Pick up {item_name}"

    def _trigger_door_open(self, door_idx: int):
        """Helper to force a door to start opening."""
        if door_idx in self.door_states:
            state = self.door_states[door_idx]
            if state['state'] == 'closed':
                state['state'] = 'opening'

    def _handle_triggers(self, use_key_pressed: bool):
        """Check and activate triggers."""
        if not self.player:
            return
            
        player_pos = self.player.pos
        currently_in = set()
        
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_trigger'):
                continue
                
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
                    # Just entered trigger
                    self._activate_trigger(brush, i, use_key_pressed)
                else:
                    # Still in trigger - handle hurt triggers
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
                # Capture the source name (the name of this trigger)
                # If the brush has no name, fallback to a unique ID string
                source_name = brush.get('name', f'trigger_{trigger_id}')
                
                # Pass source_name to _activate_target for Logic Gate processing
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
        """
        Activate a named target. 
        source_name: The name of the object (trigger/switch) sending the signal.
        """
        # 1. Handle Logic Gates
        # Find the thing first
        target_thing = None
        for thing in self.things:
            if hasattr(thing, 'name') and thing.name == target_name:
                target_thing = thing
                break
        
        if target_thing and hasattr(target_thing, 'properties') and target_thing.properties.get('type') == 'logic_gate':
            self._process_logic_gate(target_thing, source_name)
            return

        # 2. Existing logic for Brushes (Movers/Doors)
        for brush in self.brushes:
            if brush.get('name') == target_name:
                if brush.get('is_mover'):
                    brush['start_on'] = not brush.get('start_on', False)
                elif brush.get('is_door'):
                    # ... existing door logic ...
                    idx = self.brushes.index(brush)
                    if idx in self.door_states:
                        state = self.door_states[idx]
                        if state['state'] == 'closed':
                            state['state'] = 'opening'
                        elif state['state'] == 'open':
                            state['state'] = 'closing'
                return

        # 3. Existing logic for other Things (Lights)
        if target_thing:
            if Light and isinstance(target_thing, Light):
                current = target_thing.properties.get('state', 'on')
                target_thing.properties['state'] = 'off' if current == 'on' else 'on'

    def _process_logic_gate(self, gate, source_name):
        if not source_name: return # Logic gates need a source identity to track state
        
        gate_name = gate.name
        l_type = gate.properties.get('logic_type', 'AND')
        target = gate.properties.get('target', '')
        
        # Initialize input set for this gate if missing
        if gate_name not in self.gate_inputs:
            self.gate_inputs[gate_name] = set()
            
        # TOGGLE the input signal from this source
        if source_name in self.gate_inputs[gate_name]:
            self.gate_inputs[gate_name].remove(source_name) # Turn signal OFF
        else:
            self.gate_inputs[gate_name].add(source_name) # Turn signal ON
            
        active_inputs = len(self.gate_inputs[gate_name])
        
        # Calculate Logic
        should_fire = False
        
        # We need to know TOTAL possible inputs to calculate AND/NAND correctly.
        # ere, we can infer it by counting how many triggers/switches target this gate.
        # For simplicity/robustness, let's assume 'AND' means >= 2 inputs or "All active so far".
        # Better approach: Just check if active_inputs > 0 for OR.
        
        # Count how many things actually target this gate currently
        total_possible_inputs = 0
        for b in self.brushes:
            if b.get('target') == gate_name: total_possible_inputs += 1
        for t in self.things:
            if t.properties.get('target') == gate_name and t != gate: total_possible_inputs += 1
            
        if total_possible_inputs == 0: total_possible_inputs = 1 # Avoid division by zero
        
        if l_type == 'AND':
            should_fire = (active_inputs >= total_possible_inputs)
        elif l_type == 'OR':
            should_fire = (active_inputs > 0)
        elif l_type == 'XOR':
            should_fire = (active_inputs == 1)
        elif l_type == 'NAND':
            should_fire = (active_inputs < total_possible_inputs)
        elif l_type == 'NOR':
            should_fire = (active_inputs == 0)

        # If condition met, fire the gate's target
        # To prevent infinite loops, we could track depth, but for now direct fire is fine
        if should_fire and target:
            # Pass the GATE's name as the source to the next object
            self._activate_target(target, gate_name)

    def _handle_pickups(self, use_key_pressed: bool):
        """Handle pickup collection."""
        if not self.player or not Pickup:
            return
            
        player_pos = self.player.pos
        pickup_radius = 32.0
        use_radius = 64.0
        
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
        elif item_type == 'ammo':
            # Future: track ammo
            pass
        elif item_type == 'armour':
            # Future: track armor
            pass
        
        pickup.properties['collected'] = True
        self.collected_pickups.add(pickup_id)
        
        # Check if pickup should respawn
        if pickup.properties.get('respawns', False):
            respawn_time = pickup.properties.get('respawn_time', 20.0)
            self.respawn_timers[pickup_id] = respawn_time
    
    def _update_respawns(self, delta: float):
        """Update respawn timers and respawn pickups when ready."""
        if not Pickup:
            return
        
        # List to track pickups that should respawn this tick
        to_respawn = []
        
        for pickup_id, time_remaining in list(self.respawn_timers.items()):
            self.respawn_timers[pickup_id] = time_remaining - delta
            if self.respawn_timers[pickup_id] <= 0:
                to_respawn.append(pickup_id)
        
        # Respawn pickups
        for pickup_id in to_respawn:
            del self.respawn_timers[pickup_id]
            
            # Find the pickup by index
            if pickup_id < len(self.things):
                thing = self.things[pickup_id]
                if isinstance(thing, Pickup):
                    thing.properties['collected'] = False
                    self.collected_pickups.discard(pickup_id)
    
    def has_key(self, key_name: str) -> bool:
        """Check if the player has a specific key."""
        return key_name in self.collected_keys

    def use_key(self, key_name: str) -> bool:
        """
        Use (consume) a key from the player's inventory.
        Returns True if the key was used, False if player doesn't have it.
        """
        if key_name in self.collected_keys:
            self.collected_keys.remove(key_name)
            return True
        return False

    def _update_movers(self, delta: float):
        """Update all active movers."""
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_mover') or brush.get('move_once', False):
                continue
            if not brush.get('start_on', False):
                continue
            
            if i not in self.mover_states:
                if 'original_pos' not in brush:
                    brush['original_pos'] = list(brush['pos'])
                self.mover_states[i] = {'progress': 0.0, 'forward': True}
            
            state = self.mover_states[i]
            speed = brush.get('speed', 64.0)
            distance = brush.get('distance', 128.0)
            direction = np.array(brush.get('direction', [0, 1, 0]), dtype=float)
            
            dir_length = np.linalg.norm(direction)
            if dir_length > 0:
                direction = direction / dir_length
            
            if distance > 0:
                progress_delta = (speed * delta) / distance
            else:
                progress_delta = 0
            
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
            
            # Smooth easing
            t = state['progress']
            if t < 0.5:
                eased = 4 * t * t * t
            else:
                eased = 1 - pow(-2 * t + 2, 3) / 2
            
            original = np.array(brush['original_pos'])
            offset = direction * distance * eased
            brush['pos'] = (original + offset).tolist()

    def _update_doors(self, delta: float):
        """Update door animations."""
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_door'):
                continue
            if i not in self.door_states:
                continue
            
            state = self.door_states[i]
            speed = brush.get('speed', 128.0)
            distance = brush.get('distance', 128.0)
            open_time = brush.get('open_time', 3.0)
            direction = np.array(brush.get('direction', [0, 1, 0]), dtype=float)
            
            dir_length = np.linalg.norm(direction)
            if dir_length > 0:
                direction = direction / dir_length
            
            if distance > 0:
                progress_delta = (speed * delta) / distance
            else:
                progress_delta = 0
            
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
            
            # Update position
            original = np.array(brush['original_pos'])
            offset = direction * distance * state['progress']
            brush['pos'] = (original + offset).tolist()

    # =====================================================
    # FRUSTUM CULLING
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
        
        # Key inventory (for HUD display)
        write_state.collected_keys = set(self.collected_keys)

        # Pass the HUD message to the render state
        write_state.hud_message = self.current_hud_message

        # Pass the active weapon to the render state
        write_state.active_weapon = self.active_weapon

        # --- Ensure JSON-serializable light data ---
        # Convert any glm vectors to lists in things before storing in render state
        visible_things = []
        for i, thing in enumerate(self.things):
            if self.play_mode and Pickup and isinstance(thing, Pickup) and i in self.collected_pickups:
                # Do not render collected keys
                continue
            
            # Convert glm vectors to lists if they exist (for JSON compatibility)
            if Light and isinstance(thing, Light):
                if hasattr(thing, 'pos'):
                    # Check if pos is a glm vector (has 'x' attribute)
                    if hasattr(thing.pos, 'x'):
                        thing.pos = [thing.pos[0], thing.pos[1], thing.pos[2]]
            
            visible_things.append(thing)
        
        write_state.visible_things = visible_things

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
            if b.get('is_mover', False) or b.get('is_door', False):
                # Movers and doors need copies because their positions are animated
                safe_brushes.append(b.copy())
            else:
                # Regular brushes can be passed by reference
                safe_brushes.append(b)

        write_state.visible_brushes = safe_brushes
        write_state.total_brushes = total_count
        write_state.culled_brushes = culled_count
        
        # Store ALL brushes (unculled) for shadow rendering
        # Shadows need to render even when caster is off-screen
        all_brushes = []
        for b in self.brushes:
            if b.get('hidden', False):
                continue
            if b.get('is_mover', False) or b.get('is_door', False):
                all_brushes.append(b.copy())
            else:
                all_brushes.append(b)
        write_state.all_brushes = all_brushes
        
        write_state.timestamp = time.perf_counter()