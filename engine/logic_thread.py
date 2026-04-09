"""
Game Logic Processing

This thread runs game logic at a fixed timestep (60 Hz), handling:
- Player movement and physics
- Entity interactions and triggers
- I/O event dispatching
- Mover and door animations
- Pickup collection
- Monster AI (sight detection, movement, wake logic, shooting)
- Player death detection
"""

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
    from editor.things import Speaker, Pickup, Light, Monster as MonsterThing
except ImportError:
    Speaker = None
    Pickup = None
    Light = None
    MonsterThing = None

# Import I/O system
try:
    from editor.io_system import (
        IOManager, get_connections, reset_all_connections,
        get_entity_type_for_io
    )
    from editor.io_handlers import register_all_input_handlers
    IO_AVAILABLE = True
    print("[LogicThread] I/O System loaded successfully.") 
except ImportError as e:
    print(f"################################################")
    print(f"CRITICAL ERROR: I/O SYSTEM FAILED TO LOAD")
    print(f"Error details: {e}")
    print(f"################################################")
    import traceback
    traceback.print_exc()
    IO_AVAILABLE = False
    IOManager = None

# Monster AI tuning values
from .monster_constants import (
    MONSTER_SIGHT_RANGE,
    MONSTER_SHOOT_INTERVAL,
    MONSTER_SHOOT_ANIM_TIME,
    MONSTER_MOVE_SPEED,
    MONSTER_STOP_DISTANCE,
)

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
    EDITOR_CAMERA_SPEED = 300.0
    EDITOR_CAMERA_FAST_MULT = 2.5
    EDITOR_MOUSE_SENSITIVITY = 0.15
    
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
        self.terrain = None
        
        # Frustum culling settings
        self.culling_enabled = True
        self.frustum_aspect = 16.0 / 9.0
        
        # Editor camera
        self.editor_camera = Camera()
        self.editor_camera.pos = glm.vec3(0, 150, 400)
        
        self._editor_mouselook_active = False
        
        # Player stats
        self.player_health = 100
        self.player_max_health = 100
        self.player_dead = False
        self.god_mode = False
        self.buddha_mode = False
        
        # I/O System
        self.io_manager = None
        if IO_AVAILABLE and IOManager:
            self.io_manager = IOManager()
            self.io_manager.set_logic_thread(self)
            self.io_manager.set_entity_finder(self._find_entity_by_name)
            self.io_manager.set_entity_finder_by_id(self._find_entity_by_id)
            self.io_manager.set_game_state(self.game_state)
            register_all_input_handlers(self.io_manager)
        
        # Trigger state
        self.player_in_triggers: set = set()
        self.fired_once_triggers: set = set()

        # Logic Gate State (for multi-input gates)
        self.gate_inputs = {}
        
        # Timer states for logic_timer entities
        self.timer_states: Dict[int, Dict[str, float]] = {}
        
        # Hurt trigger timers
        self.hurt_trigger_timers: Dict[int, float] = {}
        self.HURT_INTERVAL = 0.5
        
        # Pickup state
        self.collected_pickups: set = set()
        self.collected_keys: set = set()
        
        # Respawn timers
        self.respawn_timers: Dict[int, float] = {}
        
        # Speaker state
        self.active_speakers: set = set()
        
        # Mover/Door Lists
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
        
        # Active weapon
        self.active_weapon = None

        # Monster AI state  { id(thing): {'shoot_timer': float, 'anim_timer': float} }
        self.monster_states: Dict[int, Dict[str, float]] = {}
        
        # Entity lookup caches (rebuilt at play-mode start for O(1) I/O lookups)
        self._name_cache: Dict[str, Any] = {}
        self._id_cache:   Dict[str, Any] = {}

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

    # =========================================================================
    # ENTITY LOOKUP (for I/O system)
    # =========================================================================
    
    def _build_entity_caches(self):
        """Build O(1) lookup dicts for I/O entity resolution.
        Called once when entering play mode and whenever entities are added/removed.
        """
        self._name_cache = {}
        self._id_cache   = {}
        for b in self.brushes:
            n = b.get('name')
            if n:
                self._name_cache[n] = b
            i = b.get('id')
            if i:
                self._id_cache[i] = b
        for t in self.things:
            n = t.properties.get('name')
            if n:
                self._name_cache[n] = t
            i = t.properties.get('id')
            if i:
                self._id_cache[i] = t

    def _find_entity_by_name(self, name: str):
        """Find an entity (brush or thing) by name — O(1) via cache."""
        if not name:
            return None
        return self._name_cache.get(name)

    def _find_entity_by_id(self, entity_id: str):
        """Find an entity (brush or thing) by stable UUID — O(1) via cache."""
        if not entity_id:
            return None
        return self._id_cache.get(entity_id)

    # =========================================================================
    # PLAYER & MODE MANAGEMENT
    # =========================================================================

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
            self.player_dead = False
            self.god_mode = False
            self.buddha_mode = False
            
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
            
            # Reset gate inputs
            self.gate_inputs = {}
            
            # Reset timer states
            self.timer_states = {}
            
            # Reset active weapon
            self.active_weapon = None
            
            # Reset visual fx
            self.bullet_marks = []

            # Reset monster AI state and clear any leftover shoot flags.
            # Also reset wake state so triggered/sight monsters sleep again.
            self.monster_states = {}
            if MonsterThing:
                for thing in self.things:
                    if isinstance(thing, MonsterThing):
                        thing.properties.pop('is_shooting', None)
                        # Restore dormant state so triggered monsters sleep on replay
                        triggered   = thing.properties.get('triggered', False)
                        wake_sight  = thing.properties.get('wake_on_sight', True)
                        if triggered or wake_sight:
                            thing.properties['awake'] = False
                        else:
                            # Neither triggered nor sight-gated — always on
                            thing.properties['awake'] = True
            
            # Reset I/O system
            if self.io_manager:
                self.io_manager.reset()
                
                # Reset fire_once connections
                for brush in self.brushes:
                    for conn in get_connections(brush):
                        conn.reset()
                for thing in self.things:
                    for conn in get_connections(thing):
                        conn.reset()
            
            # Build O(1) entity-lookup caches for I/O system
            self._build_entity_caches()

            # Fire OnPlayerSpawn from player start
            self._fire_player_spawn_outputs()
            
            # Initialize timers that start on
            self._init_logic_timers()
            
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
            self.timer_states = {}
            self.active_weapon = None
            self.bullet_marks = []
            self.player_dead = False

            # Reset monster AI state and clear shoot flags from entities
            self.monster_states = {}
            if MonsterThing:
                for thing in self.things:
                    if isinstance(thing, MonsterThing):
                        thing.properties.pop('is_shooting', None)
                        triggered  = thing.properties.get('triggered', False)
                        wake_sight = thing.properties.get('wake_on_sight', True)
                        if triggered or wake_sight:
                            thing.properties['awake'] = False
                        else:
                            thing.properties['awake'] = True
    
    def _fire_player_spawn_outputs(self):
        """Fire OnPlayerSpawn from the active player start."""
        if not self.io_manager:
            return
        
        from editor.things import PlayerStart
        for thing in self.things:
            if isinstance(thing, PlayerStart):
                self.io_manager.fire_output(thing, 'OnPlayerSpawn')
                break
    
    def _init_logic_timers(self):
        """Initialize logic timers that start enabled."""
        try:
            from editor.things import LogicTimer
        except ImportError:
            return
        
        for thing in self.things:
            if isinstance(thing, LogicTimer):
                if thing.properties.get('start_on', False):
                    entity_id = id(thing)
                    interval = float(thing.properties.get('interval', 1.0))
                    thing.properties['timer_enabled'] = True
                    self.timer_states[entity_id] = {
                        'remaining': interval,
                        'interval': interval
                    }
    
    def set_terrain(self, terrain):
        """Set terrain reference for collision detection."""
        self.terrain = terrain
    
    def set_editor_camera(self, pos: glm.vec3, yaw: float, pitch: float, fov: float):
        """Set the editor camera state."""
        self.editor_camera.pos = glm.vec3(pos)
        self.editor_camera.yaw = yaw
        self.editor_camera.pitch = pitch
        self.editor_camera.fov = fov
    
    def get_editor_camera(self) -> Camera:
        """Get the editor camera."""
        return self.editor_camera

    def set_frustum_aspect(self, aspect: float):
        """Set the aspect ratio for frustum culling."""
        self.frustum_aspect = aspect

    # =========================================================================
    # MOVER/DOOR INITIALIZATION
    # =========================================================================

    def _init_movers(self):
        """Initialize mover states and list."""
        self.mover_states = {}
        self.movers = []
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
        self.doors = []
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

    # =========================================================================
    # MAIN LOOP
    # =========================================================================
            
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
        """Process editor mode tick."""
        # Mouse look
        dx, dy = self.game_state.consume_mouse_delta()
        if dx != 0 or dy != 0:
            self._editor_mouselook_active = True
            self.editor_camera.yaw += dx * self.EDITOR_MOUSE_SENSITIVITY
            self.editor_camera.pitch -= dy * self.EDITOR_MOUSE_SENSITIVITY
            self.editor_camera.pitch = max(-89.0, min(89.0, self.editor_camera.pitch))
        
        # Keyboard movement
        keys = self.game_state.get_keys()
        
        yaw_rad = math.radians(self.editor_camera.yaw)
        forward = glm.vec3(math.cos(yaw_rad), 0, math.sin(yaw_rad))
        forward = glm.normalize(forward)
        right = glm.normalize(glm.cross(forward, glm.vec3(0, 1, 0)))
        up = glm.vec3(0, 1, 0)
        
        move_dir = glm.vec3(0, 0, 0)
        
        if Key_W in keys: move_dir += forward
        if Key_S in keys: move_dir -= forward
        if Key_A in keys: move_dir -= right
        if Key_D in keys: move_dir += right
        if Key_Space in keys: move_dir += up
        if Key_C in keys: move_dir -= up
        
        if glm.length(move_dir) > 0.001:
            move_dir = glm.normalize(move_dir)
            speed = self.EDITOR_CAMERA_SPEED
            if Key_Shift in keys:
                speed *= self.EDITOR_CAMERA_FAST_MULT
            self.editor_camera.pos += move_dir * speed * delta

    def _tick_play_mode(self, delta):
        """Process play mode tick."""
        if not self.player:
            return
        
        # Update movers & doors first (for platform carrying)
        self._update_respawns(delta)
        self._update_movers(delta)
        self._update_doors(delta)
        
        # Update I/O system (delayed events)
        if self.io_manager:
            self.io_manager.update(delta)
        
        # Update logic timers
        self._update_logic_timers(delta)

        # ---- Player dead: freeze all gameplay input ----
        if self.player_dead:
            # Drain queued inputs to prevent buildup
            self.game_state.consume_mouse_delta()
            self.game_state.consume_use_key()
            self.game_state.consume_shot()
            # Monsters still tick so their anim state is correct
            self._update_monsters(delta)
            return
        
        # Player input
        keys = self.game_state.get_keys()
        mouse_dx, mouse_dy = self.game_state.consume_mouse_delta()
        use_key = self.game_state.consume_use_key()
        
        # Mouse look
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
        
        # Physics update
        self.player.update(delta, move_dir, jump, crouch, self.brushes, 
                          self.movers, self.doors, self.terrain)
        
        # Gameplay
        self._handle_interactions(use_key)
        self._check_pickups()
        self._handle_triggers(use_key)
        
        # Player shooting
        if self.game_state.consume_shot():
            self._handle_shooting()
            
        self._update_bullet_marks()

        # Monster AI
        self._update_monsters(delta)

    # =========================================================================
    # LOGIC TIMER UPDATE
    # =========================================================================
    
    def _update_logic_timers(self, delta: float):
        """Update all logic timer entities."""
        try:
            from editor.things import LogicTimer
        except ImportError:
            return
        
        for thing in self.things:
            if not isinstance(thing, LogicTimer):
                continue
            
            if not thing.properties.get('timer_enabled', False):
                continue
            
            entity_id = id(thing)
            
            if entity_id not in self.timer_states:
                interval = float(thing.properties.get('interval', 1.0))
                self.timer_states[entity_id] = {
                    'remaining': interval,
                    'interval': interval
                }
            
            state = self.timer_states[entity_id]
            state['remaining'] -= delta
            
            if state['remaining'] <= 0:
                if self.io_manager:
                    self.io_manager.fire_output(thing, 'OnTimer')
                state['remaining'] = state['interval']

    # =========================================================================
    # TRIGGER HANDLING
    # =========================================================================

    def _handle_triggers(self, use_key_pressed: bool):
        """Check and activate triggers using the I/O system."""
        if not self.player:
            return
            
        player_pos = self.player.pos
        currently_in = set()
        
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_trigger'):
                continue
            
            if brush.get('disabled', False):
                continue
                
            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            half_size = size / 2.0
            min_b = pos - half_size
            max_b = pos + half_size
            
            inside = (min_b.x <= player_pos.x <= max_b.x and
                     min_b.y <= player_pos.y <= max_b.y and
                     min_b.z <= player_pos.z <= max_b.z)
            
            if inside:
                currently_in.add(i)
                
                if i not in self.player_in_triggers:
                    self._on_trigger_enter(brush, i)
                else:
                    if brush.get('trigger_action') == 'hurt':
                        self._process_hurt_trigger(brush, i)
        
        for i in self.player_in_triggers:
            if i not in currently_in:
                brush = self.brushes[i] if i < len(self.brushes) else None
                if brush:
                    self._on_trigger_exit(brush, i)
        
        self.player_in_triggers = currently_in

    def _apply_player_damage(self, damage):
        """Apply damage to the player, respecting god and buddha modes."""
        if self.god_mode:
            return
        self.player_health = max(0, self.player_health - damage)
        if self.buddha_mode and self.player_health < 2:
            self.player_health = 2

    def _on_trigger_enter(self, brush: dict, trigger_id: int):
        """Called when player enters a trigger."""
        trigger_type = brush.get('trigger_type', 'multiple')
        
        if trigger_type == 'once' and trigger_id in self.fired_once_triggers:
            return
        
        action = brush.get('trigger_action', 'target')
        
        if action == 'hurt':
            damage = brush.get('damage', 10)
            self._apply_player_damage(damage)
            self.hurt_trigger_timers[trigger_id] = self.HURT_INTERVAL
            
        elif action == 'target':
            if self.io_manager:
                self.io_manager.fire_output(brush, 'OnStartTouch')
                self.io_manager.fire_output(brush, 'OnTrigger')
        
        if trigger_type == 'once':
            self.fired_once_triggers.add(trigger_id)
    
    def _on_trigger_exit(self, brush: dict, trigger_id: int):
        """Called when player exits a trigger."""
        if self.io_manager:
            self.io_manager.fire_output(brush, 'OnEndTouch')

    def _process_hurt_trigger(self, brush: dict, trigger_id: int):
        """Process continuous damage from hurt trigger."""
        if trigger_id in self.hurt_trigger_timers:
            self.hurt_trigger_timers[trigger_id] -= self.TICK_DURATION
            if self.hurt_trigger_timers[trigger_id] <= 0:
                damage = brush.get('damage', 10)
                self._apply_player_damage(damage)
                self.hurt_trigger_timers[trigger_id] = self.HURT_INTERVAL


    # =========================================================================
    # INTERACTIONS
    # =========================================================================

    def _handle_interactions(self, use_key_pressed: bool):
        """Check for interactive objects in front of the player."""
        self.current_hud_message = ""
        
        found_door_idx = -1
        found_door_brush = None
        reach_distance = 80.0
        
        px, py, pz = self.player.pos
        
        for i, brush in enumerate(self.brushes):
            if not brush.get('is_door'):
                continue
            
            pos = brush['pos']
            size = brush['size']
            
            dx = abs(pos[0] - px)
            dy = abs(pos[1] - py)
            dz = abs(pos[2] - pz)
            
            if (dx < size[0]/2 + reach_distance and 
                dz < size[2]/2 + reach_distance and 
                dy < size[1]/2 + 64):
                found_door_idx = i
                found_door_brush = brush
                break

        if found_door_brush:
            door_state = self.door_states.get(found_door_idx, {}).get('state', 'closed')
            if door_state != 'closed':
                return
            if found_door_brush.get('door_auto_open', False):
                return
            
            is_locked = found_door_brush.get('door_locked', False)
            needs_key = found_door_brush.get('door_needs_key', False)
            key_name = found_door_brush.get('door_key_name', '')
            
            if is_locked:
                self.current_hud_message = "This door is locked remotely"
                if use_key_pressed and self.io_manager:
                    self.io_manager.fire_output(found_door_brush, 'OnLockedUse')
            elif needs_key:
                has_key = self.has_key(key_name)
                pretty_key_name = key_name.replace('_', ' ').title() if key_name else "Key"
                if has_key:
                    self.current_hud_message = f"Press E to unlock ({pretty_key_name})"
                    if use_key_pressed:
                        self._trigger_door_open(found_door_idx, found_door_brush)
                else:
                    self.current_hud_message = f"You need the {pretty_key_name}"
            else:
                self.current_hud_message = "Press E to open"
                if use_key_pressed:
                    self._trigger_door_open(found_door_idx, found_door_brush)
            return

        if Pickup:
            p_pos = glm.vec3(px, py, pz)
            p_forward = glm.vec3(math.sin(self.player.angle), 0, math.cos(self.player.angle))
            
            for i, thing in enumerate(self.things):
                if not isinstance(thing, Pickup):
                    continue
                if thing.properties.get('collected', False):
                    continue
                if thing.properties.get('activation') != 'use':
                    continue
                if thing.properties.get('disabled', False):
                    continue
                
                t_pos = glm.vec3(thing.pos)
                dist = glm.distance(p_pos, t_pos)
                
                if dist < 80.0:
                    to_thing = glm.normalize(t_pos - p_pos)
                    if glm.dot(p_forward, to_thing) > 0.8:
                        item_name = thing.properties.get('item_type', 'Item').replace('_', ' ').title()
                        self.current_hud_message = f"[E] Pick up {item_name}"
                        if use_key_pressed:
                            self._collect_pickup(thing, i)
                        return

    def _trigger_door_open(self, door_idx: int, door_brush: dict = None):
        """Open a door, firing I/O events."""
        if door_idx in self.door_states:
            state = self.door_states[door_idx]
            if state['state'] == 'closed':
                state['state'] = 'opening'
                if self.io_manager and door_brush:
                    self.io_manager.fire_output(door_brush, 'OnOpen')

    # =========================================================================
    # PICKUPS
    # =========================================================================

    def _check_pickups(self):
        """Check for walk-over pickups."""
        self._handle_pickups(False)

    def _handle_pickups(self, use_key_pressed: bool):
        """Handle pickup collection."""
        if not self.player or not Pickup:
            return
            
        player_pos = self.player.pos
        pickup_radius = 32.0
        
        for i, thing in enumerate(self.things):
            if not isinstance(thing, Pickup):
                continue
            if thing.properties.get('collected', False):
                continue
            if i in self.collected_pickups:
                continue
            if thing.properties.get('disabled', False):
                continue
                
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
        
        if self.io_manager:
            self.io_manager.fire_output(pickup, 'OnPickedUp')
        
        if pickup.properties.get('respawns', False):
            respawn_time = pickup.properties.get('respawn_time', 20.0)
            self.respawn_timers[pickup_id] = respawn_time
    
    def _update_respawns(self, delta: float):
        """Update respawn timers."""
        if not Pickup:
            return
        
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
                    if self.io_manager:
                        self.io_manager.fire_output(thing, 'OnRespawn')
    
    def has_key(self, key_name: str) -> bool:
        return key_name in self.collected_keys

    # =========================================================================
    # MOVER/DOOR UPDATES
    # =========================================================================

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
            
            progress_delta = (speed * delta) / distance if distance > 0 else 0
            
            was_at_end = state['progress'] >= 1.0
            was_at_start = state['progress'] <= 0.0
            
            if state['forward']:
                state['progress'] += progress_delta
                if state['progress'] >= 1.0:
                    # This timer.stop() here is fine as it applies to initial manual steps,
                    # but in auto-run mode, we ensure the timer is started after these.
                    state['progress'] = 1.0
                    state['forward'] = False
                    if not was_at_end and self.io_manager:
                        self.io_manager.fire_output(brush, 'OnFullyOpen')
            else:
                state['progress'] -= progress_delta
                if state['progress'] <= 0.0:
                    state['progress'] = 0.0
                    state['forward'] = True
                    if not was_at_start and self.io_manager:
                        self.io_manager.fire_output(brush, 'OnFullyClosed')
            
            t = state['progress']
            eased = 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2
            
            original = np.array(brush['original_pos'])
            offset = direction * distance * eased
            new_pos = original + offset
            
            current_pos = np.array(brush['pos'])
            move_delta = new_pos - current_pos
            
            brush['pos'] = new_pos.tolist()
            
            if self.player and self.player.ground_object == brush:
                self.player.pos += glm.vec3(move_delta[0], move_delta[1], move_delta[2])

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
            
            progress_delta = (speed * delta) / distance if distance > 0 else 0
            
            if state['state'] == 'opening':
                state['progress'] += progress_delta
                if state['progress'] >= 1.0:
                    state['progress'] = 1.0
                    state['state'] = 'open'
                    state['open_timer'] = open_time
                    if self.io_manager:
                        self.io_manager.fire_output(brush, 'OnFullyOpen')
                    
            elif state['state'] == 'open':
                state['open_timer'] -= delta
                if state['open_timer'] <= 0:
                    state['state'] = 'closing'
                    if self.io_manager:
                        self.io_manager.fire_output(brush, 'OnClose')
                    
            elif state['state'] == 'closing':
                state['progress'] -= progress_delta
                if state['progress'] <= 0.0:
                    state['progress'] = 0.0
                    state['state'] = 'closed'
                    if self.io_manager:
                        self.io_manager.fire_output(brush, 'OnFullyClosed')
            
            original = np.array(brush['original_pos'])
            offset = direction * distance * state['progress']
            new_pos = original + offset
            
            current_pos = np.array(brush['pos'])
            move_delta = new_pos - current_pos
            
            brush['pos'] = new_pos.tolist()
            
            if self.player and self.player.ground_object == brush:
                self.player.pos += glm.vec3(move_delta[0], move_delta[1], move_delta[2])

    # =========================================================================
    # PLAYER SHOOTING
    # =========================================================================

    def _handle_shooting(self):
        if not self.player or not self.active_weapon:
            return

        yaw_rad = self.player.angle
        pitch_rad = self.player.pitch

        dir_x = math.sin(yaw_rad) * math.cos(pitch_rad)
        dir_y = math.sin(pitch_rad)
        dir_z = math.cos(yaw_rad) * math.cos(pitch_rad)

        ray_origin = glm.vec3(self.player.pos.x,
                            self.player.pos.y + self.player.camera_height,
                            self.player.pos.z)
        ray_dir = glm.normalize(glm.vec3(dir_x, dir_y, dir_z))

        # --- Brush hit detection ---
        closest_brush_hit = None
        closest_brush_dist = float('inf')
        for brush in self.brushes:
            if (brush.get('is_trigger') or brush.get('hidden') or
                brush.get('is_water') or brush.get('is_fog')):
                continue
            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            min_b = pos - size * 0.5
            max_b = pos + size * 0.5
            hit, dist = self._intersect_ray_aabb(ray_origin, ray_dir, min_b, max_b)
            if hit and dist < closest_brush_dist:
                closest_brush_dist = dist
                closest_brush_hit = ray_origin + ray_dir * dist

        # --- Monster hit detection ---
        closest_monster = None
        closest_monster_dist = float('inf')
        from editor.things import Monster

        for thing in self.things:
            if not isinstance(thing, Monster):
                continue
            if thing.properties.get('dead', False) or thing.properties.get('hidden', False):
                continue

            radius = 64.0
            center = glm.vec3(thing.pos[0], thing.pos[1] + 64.0, thing.pos[2])
            oc = ray_origin - center
            a = glm.dot(ray_dir, ray_dir)
            b = 2.0 * glm.dot(oc, ray_dir)
            c = glm.dot(oc, oc) - radius * radius
            disc = b * b - 4 * a * c
            if disc >= 0:
                t = (-b - math.sqrt(disc)) / (2.0 * a)
                if t >= 0 and t < closest_monster_dist:
                    if t < closest_brush_dist:
                        closest_monster_dist = t
                        closest_monster = thing

        if closest_monster is not None:
            WEAPON_DAMAGE = 25
            health_raw = closest_monster.properties.get('health', 100)
            try:
                health = int(health_raw)
            except (ValueError, TypeError):
                health = 100
            new_health = health - WEAPON_DAMAGE
            closest_monster.properties['health'] = new_health

            print(f"[DEBUG] Monster {closest_monster.properties.get('name')} health: {health} -> {new_health}")

            if hasattr(self.game_state, 'sound_queue'):
                self.game_state.sound_queue.append({
                    'file': 'hit.wav',
                    'volume': 1.0,
                    'entity_id': id(closest_monster)
                })

            if new_health <= 0:
                closest_monster.properties['dead'] = True
                closest_monster.properties.pop('is_shooting', None)
                if self.io_manager:
                    self.io_manager.fire_output(closest_monster, 'OnDeath')

            hit_point = ray_origin + ray_dir * closest_monster_dist
            self.bullet_marks.append({
                'pos': hit_point,
                'time': time.perf_counter()
            })
            return

        if closest_brush_hit is not None:
            self.bullet_marks.append({
                'pos': closest_brush_hit,
                'time': time.perf_counter()
            })

    def _intersect_ray_aabb(self, origin, direction, box_min, box_max):
        """Ray-AABB intersection. Returns (hit: bool, distance: float)."""
        t_min = 0.0
        t_max = 10000.0

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

    # =========================================================================
    # MONSTER AI
    # =========================================================================

    def _update_monsters(self, delta: float):
        """
        Monster AI update — runs every play-mode tick.

        Wake logic:
          - triggered=True  → monster starts dormant; wakes only via I/O 'Wake' input.
          - triggered=False → uses wake_on_sight:
              - wake_on_sight=True  (default) → wakes when player enters MONSTER_SIGHT_RANGE.
              - wake_on_sight=False → awake from the start (no trigger, no sight check).

        Once awake:
          - Ground-type monsters slide toward the player horizontally at MONSTER_MOVE_SPEED,
            stopping at MONSTER_STOP_DISTANCE.
          - Flying monsters move in full 3D toward the player.
          - Attacks fire on MONSTER_SHOOT_INTERVAL cooldown while in MONSTER_SIGHT_RANGE.
          - Out-of-range monsters go idle but stay awake (they chase when you return).

        I/O events fired:
          - OnSeePlayer  — once when player enters sight range
          - OnLostPlayer — once when player leaves sight range
          - OnAttack     — each time the monster shoots
          - OnDeath      — when Kill input is received

        Dead / hidden / disabled monsters are always skipped.
        """
        if not self.player or not MonsterThing:
            return

        if self.player_dead:
            return

        player_pos = self.player.pos

        for thing in self.things:
            if not isinstance(thing, MonsterThing):
                continue

            if thing.properties.get('dead', False) or thing.properties.get('hidden', False):
                thing.properties.pop('is_shooting', None)
                continue
            if thing.properties.get('disabled', False):
                continue

            mid = id(thing)
            if mid not in self.monster_states:
                self.monster_states[mid] = {
                    'shoot_timer': MONSTER_SHOOT_INTERVAL,
                    'anim_timer':  0.0,
                    'in_sight':    False,   # ← NEW: tracks sight-range transitions
                }

            # ---- Process deferred Kill input --------------------------------
            if thing.properties.pop('_kill', False):
                thing.properties['dead'] = True
                thing.properties.pop('is_shooting', None)
                continue
            # -----------------------------------------------------------------

            state     = self.monster_states[mid]
            thing_pos = glm.vec3(thing.pos)
            distance  = glm.distance(player_pos, thing_pos)

            # ---- Wake logic -------------------------------------------------
            triggered  = thing.properties.get('triggered', False)
            wake_sight = thing.properties.get('wake_on_sight', True)
            awake      = thing.properties.get('awake', False)

            if not awake:
                if triggered:
                    continue
                elif not wake_sight:
                    thing.properties['awake'] = True
                    awake = True
                elif distance <= MONSTER_SIGHT_RANGE:
                    thing.properties['awake'] = True
                    awake = True
                else:
                    continue
            # -----------------------------------------------------------------

            if distance <= MONSTER_SIGHT_RANGE:
                # ---- Fire OnSeePlayer on sight transition -------------------
                if not state['in_sight']:
                    state['in_sight'] = True
                    if self.io_manager:
                        self.io_manager.fire_output(thing, 'OnSeePlayer')
                # -------------------------------------------------------------

                if distance > MONSTER_STOP_DISTANCE:
                    direction = player_pos - thing_pos
                    dir_len = glm.length(direction)
                    if dir_len > 0.001:
                        direction = direction / dir_len
                        mtype = thing.properties.get('monster_type', 'human')
                        if mtype != 'flying':
                            direction = glm.normalize(glm.vec3(direction.x, 0.0, direction.z))
                        step = direction * MONSTER_MOVE_SPEED * delta
                        new_pos = thing_pos + step
                        thing.pos = [new_pos.x, new_pos.y, new_pos.z]

                state['shoot_timer'] -= delta

                if state['shoot_timer'] <= 0.0:
                    state['shoot_timer'] = MONSTER_SHOOT_INTERVAL
                    state['anim_timer']  = MONSTER_SHOOT_ANIM_TIME

                    damage = int(thing.properties.get('damage', 10))
                    self._apply_player_damage(damage)

                    if hasattr(self.game_state, 'sound_queue'):
                        self.game_state.sound_queue.append({
                            'file': 'shoot.wav',
                            'volume': 0.6,
                            'entity_id': mid,
                        })

                    if self.io_manager:
                        self.io_manager.fire_output(thing, 'OnAttack')

                if state['anim_timer'] > 0.0:
                    state['anim_timer'] -= delta
                    thing.properties['is_shooting'] = True
                else:
                    thing.properties['is_shooting'] = False

            else:
                # ---- Fire OnLostPlayer on sight loss transition -------------
                if state['in_sight']:
                    state['in_sight'] = False
                    if self.io_manager:
                        self.io_manager.fire_output(thing, 'OnLostPlayer')
                # -------------------------------------------------------------

                thing.properties['is_shooting'] = False
                state['anim_timer'] = 0.0

        # ---- Player death check ---------------------------------------------
        if self.player_health <= 0 and not self.player_dead:
            self.player_dead = True
            if self.io_manager:
                try:
                    from editor.things import PlayerStart
                    for thing in self.things:
                        if isinstance(thing, PlayerStart):
                            self.io_manager.fire_output(thing, 'OnPlayerDeath')
                            break
                except ImportError:
                    pass
            print("[Logic] Player has died.")

    # =========================================================================
    # FRUSTUM CULLING
    # =========================================================================

    def _extract_frustum_planes(self, proj_view: glm.mat4):
        """Extract the 6 frustum planes."""
        m = proj_view
        planes = []
        planes.append(self._normalize_plane(m[0][3] + m[0][0], m[1][3] + m[1][0], m[2][3] + m[2][0], m[3][3] + m[3][0]))
        planes.append(self._normalize_plane(m[0][3] - m[0][0], m[1][3] - m[1][0], m[2][3] - m[2][0], m[3][3] - m[3][0]))
        planes.append(self._normalize_plane(m[0][3] + m[0][1], m[1][3] + m[1][1], m[2][3] + m[2][1], m[3][3] + m[3][1]))
        planes.append(self._normalize_plane(m[0][3] - m[0][1], m[1][3] - m[1][1], m[2][3] - m[2][1], m[3][3] - m[3][1]))
        planes.append(self._normalize_plane(m[0][3] + m[0][2], m[1][3] + m[1][2], m[2][3] + m[2][2], m[3][3] + m[3][2]))
        planes.append(self._normalize_plane(m[0][3] - m[0][2], m[1][3] - m[1][2], m[2][3] - m[2][2], m[3][3] - m[3][2]))
        return planes

    def _normalize_plane(self, a, b, c, d):
        length = math.sqrt(a*a + b*b + c*c)
        if length < 1e-8:
            return (0, 0, 0, 0)
        return (a/length, b/length, c/length, d/length)

    def _aabb_in_frustum(self, planes, center, half_size):
        for plane in planes:
            a, b, c, d = plane
            px = center[0] + half_size[0] if a >= 0 else center[0] - half_size[0]
            py = center[1] + half_size[1] if b >= 0 else center[1] - half_size[1]
            pz = center[2] + half_size[2] if c >= 0 else center[2] - half_size[2]
            if a*px + b*py + c*pz + d < 0:
                return False
        return True

    # =========================================================================
    # RENDER STATE PREPARATION
    # =========================================================================

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
        write_state.player_dead = self.player_dead
        
        write_state.collected_keys = set(self.collected_keys)
        write_state.hud_message = self.current_hud_message
        write_state.active_weapon = self.active_weapon

        # Transfer bullet marks
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

        # Things
        visible_things = []
        for i, thing in enumerate(self.things):
            if self.play_mode and Pickup and isinstance(thing, Pickup) and i in self.collected_pickups:
                continue
            if Light and isinstance(thing, Light):
                # FIX: Only convert to list if pos is a glm.vec3 (has .x attribute)
                # Avoids unconditional list allocation at 60 Hz per light.
                if hasattr(thing.pos, 'x'):
                    thing.pos = [thing.pos.x, thing.pos.y, thing.pos.z]
            visible_things.append(thing)
        
        write_state.visible_things = visible_things

        # Frustum culling
        projection = glm.perspective(glm.radians(fov), self.frustum_aspect, 1.0, 10000.0)
        proj_view = projection * view_matrix
        frustum_planes = self._extract_frustum_planes(proj_view)
        
        # FIX: Single pass builds both safe_brushes (culled) and all_brushes.
        # Previously two separate loops iterated self.brushes — doubled cost at 60 Hz.
        safe_brushes = []
        all_brushes  = []
        total_count  = 0
        culled_count = 0

        for b in self.brushes:
            total_count += 1
            if b.get('hidden', False):
                culled_count += 1
                continue

            is_dynamic = b.get('is_mover', False) or b.get('is_door', False)
            b_ref = b.copy() if is_dynamic else b  # copy dynamic brushes once

            all_brushes.append(b_ref)

            if self.culling_enabled:
                pos       = b.get('pos',  [0, 0, 0])
                size      = b.get('size', [64, 64, 64])
                center    = (pos[0],        pos[1],        pos[2])
                half_size = (size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
                if not self._aabb_in_frustum(frustum_planes, center, half_size):
                    culled_count += 1
                    continue

            safe_brushes.append(b_ref)

        write_state.visible_brushes = safe_brushes
        write_state.all_brushes     = all_brushes
        write_state.total_brushes   = total_count
        write_state.culled_brushes  = culled_count
        
        write_state.timestamp = time.perf_counter()