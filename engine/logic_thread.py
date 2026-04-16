"""
Game Logic Processing

This thread runs game logic at a fixed timestep (60 Hz), handling:
- Player movement and physics
- Entity interactions and triggers
- I/O event dispatching
- Mover and door animations
- Pickup collection
- Monster AI (sight detection, movement, wake logic, shooting)
- Monster physics (gravity, floor detection, wall collision, LOS)
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
    from editor.things import Speaker, Pickup, Light, Monster as MonsterThing, PathNode
except ImportError:
    Speaker = None
    Pickup = None
    Light = None
    MonsterThing = None
    PathNode = None

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

# Import debug logger for MonsterAI console output
try:
    from editor.debug_console import debug_log
except ImportError:
    def debug_log(category, message):
        print(f"[{category}] {message}")

# Monster AI tuning values
from .monster_constants import (
    MONSTER_SIGHT_RANGE,
    MONSTER_SHOOT_INTERVAL,
    MONSTER_SHOOT_ANIM_TIME,
    MONSTER_MOVE_SPEED,
    MONSTER_STOP_DISTANCE,
    MONSTER_GRAVITY,
    MONSTER_TERMINAL_VEL,
    MONSTER_MIN_WIDTH,
    MONSTER_WALL_MARGIN,
    MONSTER_DEAD_FALL_SPEED,
    MONSTER_STUCK_THRESHOLD,
    MONSTER_DETOUR_RANGE,
    WEAPON_DAMAGE,
    WEAPON_SHOOT_SOUND,
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

        # Parented lights: list of (Light, brush_dict, [ox,oy,oz]) tuples
        self._parented_lights: list = []
        
        # Interaction State
        self.current_hud_message = ""
        
        # Visual FX
        self.bullet_marks = []
        self.BULLET_FADE_TIME = 20.0
        
        # Active weapon
        self.active_weapon = None

        # Muzzle flash — set True for one frame after player fires
        self.muzzle_flash_active = False

        # Monster AI state  { id(thing): {'shoot_timer': float, 'anim_timer': float, ...} }
        self.monster_states: Dict[int, Dict[str, float]] = {}

        # Monster debug toggle (F7)
        self.monster_debug_active = False
        # Collected debug rays for the current frame
        self._debug_rays: list = []
        
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
            self._init_parented_lights()
            
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
            self.muzzle_flash_active = False

            # Reset monster AI state and clear any leftover shoot flags.
            # Also reset wake state so triggered/sight monsters sleep again.
            self.monster_states = {}
            if MonsterThing:
                for thing in self.things:
                    if isinstance(thing, MonsterThing):
                        thing.properties.pop('is_shooting', None)
                        thing.properties.pop('dead', None)
                        # Reset vertical velocity for monster physics
                        thing.properties.pop('_vel_y', None)
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
            self._reset_parented_lights()
            self.current_hud_message = ""
            self.gate_inputs = {}
            self.timer_states = {}
            self.active_weapon = None
            self.bullet_marks = []
            self.player_dead = False
            self.muzzle_flash_active = False

            # Reset monster AI state and clear shoot flags from entities
            self.monster_states = {}
            if MonsterThing:
                for thing in self.things:
                    if isinstance(thing, MonsterThing):
                        thing.properties.pop('is_shooting', None)
                        thing.properties.pop('_vel_y', None)
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
        self._update_parented_lights()
        
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
        
        # Clear muzzle flash from previous frame
        self.muzzle_flash_active = False

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
    # PARENTED LIGHTS  (light follows a mover brush)
    # =========================================================================

    def _init_parented_lights(self):
        """Snapshot original positions and build the parented-lights list."""
        self._parented_lights = []
        if not Light:
            return
        for thing in self.things:
            if not isinstance(thing, Light):
                continue
            parent_name = thing.properties.get('parent_mover', '')
            if not parent_name:
                continue
            # Find the mover brush by name
            brush = None
            for b in self.brushes:
                if b.get('is_mover') and b.get('name') == parent_name:
                    brush = b
                    break
            if brush is None:
                print(f"[Light] Warning: parent_mover '{parent_name}' "
                      f"not found for light '{thing.name}'")
                continue
            # Save the light's original editor position so we can restore it
            thing.properties['_original_pos'] = list(thing.pos)
            # Use the stored offset if present, otherwise compute it now
            offset = thing.properties.get('parent_offset')
            if not offset or offset == [0.0, 0.0, 0.0]:
                offset = [
                    thing.pos[0] - brush['pos'][0],
                    thing.pos[1] - brush['pos'][1],
                    thing.pos[2] - brush['pos'][2],
                ]
                thing.properties['parent_offset'] = offset
            self._parented_lights.append((thing, brush, offset))

    def _reset_parented_lights(self):
        """Restore lights to their original editor positions."""
        for light, _brush, _offset in self._parented_lights:
            original = light.properties.pop('_original_pos', None)
            if original is not None:
                light.pos = list(original)
        self._parented_lights = []

    def _update_parented_lights(self):
        """Move each parented light to its mover's current pos + offset."""
        for light, brush, offset in self._parented_lights:
            bpos = brush['pos']
            light.pos[0] = bpos[0] + offset[0]
            light.pos[1] = bpos[1] + offset[1]
            light.pos[2] = bpos[2] + offset[2]

    # =========================================================================
    # PLAYER SHOOTING
    # =========================================================================

    def _handle_shooting(self):
        if not self.player or not self.active_weapon:
            return

        # Activate muzzle flash for one frame
        self.muzzle_flash_active = True

        # NOTE: shoot sound is played directly by QtGameView.mousePressEvent
        # for zero-latency response.  Do NOT also queue it here.

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
            damage = WEAPON_DAMAGE.get(self.active_weapon, 25)
            health_raw = closest_monster.properties.get('health', 100)
            try:
                health = int(health_raw)
            except (ValueError, TypeError):
                health = 100
            new_health = health - damage
            closest_monster.properties['health'] = new_health

            debug_log("MonsterAI", f"Monster {closest_monster.properties.get('name')} health: {health} -> {new_health} (weapon={self.active_weapon}, dmg={damage})")

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
    # MONSTER AI — HELPER: wall-brush collision for monsters
    # =========================================================================

    def _get_wall_brushes(self):
        """Return only solid wall brushes (skip triggers, water, fog, hidden)."""
        walls = []
        for brush in self.brushes:
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            walls.append(brush)
        return walls

    def _monster_raycast_down(self, x, z, start_y=10000.0):
        """
        Cast a ray straight down from (x, start_y, z) and return the Y of
        the highest solid brush surface below that point, or None.
        """
        best_y = None
        for brush in self.brushes:
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            pos = brush['pos']
            size = brush['size']
            bx_min = pos[0] - size[0] * 0.5
            bx_max = pos[0] + size[0] * 0.5
            bz_min = pos[2] - size[2] * 0.5
            bz_max = pos[2] + size[2] * 0.5
            by_min = pos[1] - size[1] * 0.5
            by_max = pos[1] + size[1] * 0.5

            # Check if the XZ position is within this brush's horizontal footprint
            if bx_min <= x <= bx_max and bz_min <= z <= bz_max:
                # The top surface of this brush is a potential floor
                if by_max <= start_y:
                    if best_y is None or by_max > best_y:
                        best_y = by_max
        return best_y

    def _has_line_of_sight(self, start, end):
        """
        Return True if a ray from start to end does NOT hit any solid wall brush.
        Checks only wall brushes (skips triggers, water, fog, hidden).
        """
        ray_dir = end - start
        ray_len = glm.length(ray_dir)
        if ray_len < 0.001:
            return True
        ray_dir = ray_dir / ray_len

        for brush in self.brushes:
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            pos = glm.vec3(brush['pos'])
            size = glm.vec3(brush['size'])
            b_min = pos - size * 0.5
            b_max = pos + size * 0.5
            hit, dist = self._intersect_ray_aabb(start, ray_dir, b_min, b_max)
            if hit and dist < ray_len - 0.1:
                return False
        return True

    def _monster_overlaps_wall(self, mx, my, mz, margin):
        """
        Return True if a monster-sized box at (mx, my, mz) with horizontal
        half-extent = margin overlaps any solid wall brush.
        """
        for brush in self.brushes:
            if brush.get('hidden') or brush.get('is_water') or brush.get('is_fog'):
                continue
            if brush.get('is_trigger') and not (brush.get('is_mover') or brush.get('is_door')):
                continue
            pos = brush['pos']
            size = brush['size']
            bx_min = pos[0] - size[0] * 0.5
            bx_max = pos[0] + size[0] * 0.5
            by_min = pos[1] - size[1] * 0.5
            by_max = pos[1] + size[1] * 0.5
            bz_min = pos[2] - size[2] * 0.5
            bz_max = pos[2] + size[2] * 0.5

            # Monster AABB (horizontal extent = margin, vertical: my to my+128)
            m_xmin = mx - margin
            m_xmax = mx + margin
            m_ymin = my
            m_ymax = my + 128.0
            m_zmin = mz - margin
            m_zmax = mz + margin

            if (m_xmax > bx_min and m_xmin < bx_max and
                    m_ymax > by_min and m_ymin < by_max and
                    m_zmax > bz_min and m_zmin < bz_max):
                return True
        return False

    # =========================================================================
    # MONSTER AI
    # =========================================================================

    # =========================================================================
    # MONSTER AI — PATROL (PathNode navigation)
    # =========================================================================

    def _find_path_node_by_name(self, name: str):
        """Return the PathNode with the given name, or None."""
        if not name or PathNode is None:
            return None
        for t in self.things:
            if isinstance(t, PathNode) and t.properties.get('name', '') == name:
                return t
        return None

    def _build_patrol_chain(self, start_name: str, mtype: str):
        """
        Walk the next_node links starting from *start_name* and return an
        ordered list of node names.  Stops at a dead-end or when a cycle
        is detected.  Nodes that reject *mtype* via affects_type are
        skipped — chain ends there.
        """
        chain = []
        visited = set()
        current = start_name
        while current and current not in visited:
            node = self._find_path_node_by_name(current)
            if node is None:
                break
            if not node.accepts_monster_type(mtype):
                break
            visited.add(current)
            chain.append(current)
            current = node.get_next_node_name()
        return chain

    def _find_nearby_detour_node(self, m_pos, blocked_node_name, mtype):
        """
        Search for a nearby PathNode the monster can walk to in order to
        navigate around an obstacle.

        Returns the PathNode name (str) if a suitable detour is found,
        or '' if nothing is reachable.

        Selection criteria:
          - Must accept this monster's type (affects_type)
          - Must not be the node we're currently stuck heading to
          - Must not be disabled
          - Must be within MONSTER_DETOUR_RANGE
          - The first movement step toward it must not overlap a wall
        Ties are broken by distance (nearest wins).
        """
        if PathNode is None:
            return ''

        best_name = ''
        best_dist = MONSTER_DETOUR_RANGE + 1.0

        for t in self.things:
            if not isinstance(t, PathNode):
                continue
            node_name = t.properties.get('name', '')
            if not node_name or node_name == blocked_node_name:
                continue
            if t.properties.get('disabled', False):
                continue
            if not t.accepts_monster_type(mtype):
                continue

            n_pos = glm.vec3(t.pos)
            if mtype == 'flying':
                diff = n_pos - m_pos
            else:
                diff = glm.vec3(n_pos.x - m_pos.x, 0.0, n_pos.z - m_pos.z)
            dist = glm.length(diff)
            if dist > MONSTER_DETOUR_RANGE or dist < 1.0:
                continue
            if dist >= best_dist:
                continue

            # Quick reachability check: would the first step toward this
            # node be free of wall overlap?
            direction = diff / dist
            if mtype != 'flying':
                direction = glm.normalize(glm.vec3(direction.x, 0.0, direction.z))
            test_pos = m_pos + direction * MONSTER_MOVE_SPEED * 0.016  # ~1 frame
            if self._monster_overlaps_wall(test_pos.x, test_pos.y, test_pos.z,
                                           MONSTER_WALL_MARGIN):
                continue

            best_dist = dist
            best_name = node_name

        return best_name

    def _advance_patrol_index(self, monster, state, chain, patrol_mode, mname):
        """
        Advance the patrol chain index according to patrol_mode.
        Fires OnMonsterLeft on the node being departed.
        """
        if not chain:
            return

        old_idx = state.get('patrol_chain_idx', 0)
        old_name = chain[old_idx] if old_idx < len(chain) else ''
        direction = state.get('patrol_chain_dir', 1)

        # Fire OnMonsterLeft on the node we are departing
        if old_name:
            old_node = self._find_path_node_by_name(old_name)
            if old_node is not None and self.io_manager:
                self.io_manager.fire_output(old_node, 'OnMonsterLeft')
        state['patrol_at_target'] = False
        state['patrol_walking_to'] = ''

        new_idx = old_idx + direction

        if patrol_mode == 'loop':
            if new_idx >= len(chain):
                new_idx = 0
            elif new_idx < 0:
                new_idx = len(chain) - 1

        elif patrol_mode == 'ping_pong':
            if new_idx >= len(chain):
                direction = -1
                new_idx = max(0, old_idx - 1)
                if len(chain) == 1:
                    new_idx = 0
                debug_log("Pathfinding",
                          f"'{mname}' ping_pong reverse at end of chain")
            elif new_idx < 0:
                direction = 1
                new_idx = min(len(chain) - 1, old_idx + 1)
                if len(chain) == 1:
                    new_idx = 0
                debug_log("Pathfinding",
                          f"'{mname}' ping_pong reverse at start of chain")
            state['patrol_chain_dir'] = direction

        elif patrol_mode == 'once':
            if new_idx >= len(chain) or new_idx < 0:
                state['patrol_finished'] = True
                debug_log("Pathfinding",
                          f"'{mname}' completed 'once' patrol — "
                          f"holding at '{old_name}'")
                return

        state['patrol_chain_idx'] = new_idx
        next_name = chain[new_idx] if new_idx < len(chain) else ''
        if next_name:
            debug_log("Pathfinding",
                      f"'{mname}' advancing → '{next_name}' "
                      f"(chain idx {new_idx}/{len(chain)-1})")

    def _update_monster_patrol(self, monster, state, mtype: str, delta: float):
        """
        Move a monster along a chain of PathNodes.

        Called from _update_monsters' else-branch (player out of sight).
        Sight / chase always overrides patrol — this function is a no-op
        when patrol is disabled or the target is missing / rejected.

        Chain traversal:
          On first call (or when patrol_target changes), the chain is built
          by following next_node links from the patrol_target node.  The
          monster then walks through the chain respecting patrol_mode:

            loop      — wraps index back to 0 at chain end
            ping_pong — reverses direction at each end
            once      — stops at last node

        At each node:
          - If wait_time > 0 the monster pauses for that many seconds,
            firing OnWaitStart / OnWaitEnd on the node.
          - patrol_speed on the target node scales MONSTER_MOVE_SPEED.
          - OnMonsterArrived / OnMonsterLeft fire on node transitions.

        Return-to-patrol:
          When the player enters sight range, _update_monsters' in-sight
          branch takes over (chase).  When the player leaves sight range
          again, this function resumes.  The monster's patrol_chain_idx is
          preserved so it picks up where it left off — but if it has moved
          far from the chain during the chase, it first walks back to the
          node it was heading toward before the interruption.
        """
        if not monster.properties.get('patrol', False):
            if state.get('patrol_at_target'):
                state['patrol_at_target'] = False
                state['patrol_chain'] = []
            state.pop('detour_node', None)
            return

        target_name = monster.properties.get('patrol_target', '') or ''
        if not target_name:
            return

        mname = monster.properties.get('name', '?')
        patrol_mode = str(monster.properties.get('patrol_mode', 'loop')).lower()
        if patrol_mode not in ('loop', 'ping_pong', 'once'):
            patrol_mode = 'loop'

        # --- Build / rebuild the chain when target changes ----------------
        chain_built_from = state.get('patrol_chain_built_from', '')
        if chain_built_from != target_name or not state.get('patrol_chain'):
            chain = self._build_patrol_chain(target_name, mtype)
            if not chain:
                if state.get('patrol_warn_missing') != target_name:
                    state['patrol_warn_missing'] = target_name
                    node = self._find_path_node_by_name(target_name)
                    if node is None:
                        debug_log("Warning",
                                  f"Monster '{mname}' patrol_target "
                                  f"'{target_name}' not found.")
                    else:
                        debug_log("Warning",
                                  f"Monster '{mname}' (type={mtype}) "
                                  f"rejected by PathNode '{target_name}' "
                                  f"(affects_type={node.get_affects_type()}).")
                return
            state['patrol_chain'] = chain
            state['patrol_chain_built_from'] = target_name
            state['patrol_chain_idx'] = 0
            state['patrol_chain_dir'] = 1
            state['patrol_at_target'] = False
            state['patrol_waiting'] = False
            state['patrol_wait_remaining'] = 0.0
            state['patrol_finished'] = False
            state['patrol_warn_missing'] = ''
            state['patrol_warn_mismatch'] = ''
            state['patrol_walking_to'] = ''
            state['detour_node'] = ''
            debug_log("Pathfinding",
                      f"'{mname}' patrol chain built: "
                      f"{' -> '.join(chain)}  (mode={patrol_mode})")

        chain = state.get('patrol_chain', [])
        if not chain:
            return

        if state.get('patrol_finished'):
            return

        idx = state.get('patrol_chain_idx', 0)
        if idx < 0 or idx >= len(chain):
            idx = 0
            state['patrol_chain_idx'] = 0

        current_node_name = chain[idx]
        node = self._find_path_node_by_name(current_node_name)
        if node is None:
            state['patrol_chain'] = []
            return

        # --- Waiting at node? ---------------------------------------------
        if state.get('patrol_waiting'):
            remaining = state.get('patrol_wait_remaining', 0.0) - delta
            if remaining > 0.0:
                state['patrol_wait_remaining'] = remaining
                return
            state['patrol_waiting'] = False
            state['patrol_wait_remaining'] = 0.0
            if self.io_manager:
                self.io_manager.fire_output(node, 'OnWaitEnd')
            debug_log("Pathfinding",
                      f"'{mname}' finished waiting at '{current_node_name}'")
            self._advance_patrol_index(monster, state, chain, patrol_mode, mname)

            # Re-resolve the new target so we start walking this tick
            if state.get('patrol_finished'):
                return
            idx = state.get('patrol_chain_idx', 0)
            if idx < 0 or idx >= len(chain):
                return
            current_node_name = chain[idx]
            node = self._find_path_node_by_name(current_node_name)
            if node is None:
                state['patrol_chain'] = []
                return
            # Fall through to distance-compute + movement below ↓

        # --- Compute distance to current target node ----------------------
        m_pos = glm.vec3(monster.pos)
        n_pos = glm.vec3(node.pos)

        if mtype == 'flying':
            to_node = n_pos - m_pos
            dist_to_node = glm.length(to_node)
        else:
            flat = glm.vec3(n_pos.x - m_pos.x, 0.0, n_pos.z - m_pos.z)
            dist_to_node = glm.length(flat)
            to_node = flat

        radius = node.get_radius()

        # --- Arrived at current node? -------------------------------------
        # When the monster is inside the node's radius, handle arrival and
        # advance.  Critically, do NOT return after advancing — re-resolve
        # the new target and fall through to the movement code so the
        # monster starts walking toward the next node on this same tick.
        if dist_to_node <= radius:
            if not state.get('patrol_at_target'):
                state['patrol_at_target'] = True
                if self.io_manager:
                    self.io_manager.fire_output(node, 'OnMonsterArrived')
                debug_log("Pathfinding",
                          f"'{mname}' arrived at '{current_node_name}' "
                          f"(dist={dist_to_node:.0f}, radius={radius:.0f})")

            wait = node.get_wait_time()
            if wait > 0.0 and not state.get('patrol_waiting'):
                state['patrol_waiting'] = True
                state['patrol_wait_remaining'] = wait
                if self.io_manager:
                    self.io_manager.fire_output(node, 'OnWaitStart')
                debug_log("Pathfinding",
                          f"'{mname}' waiting {wait:.1f}s at "
                          f"'{current_node_name}'")
                return

            # Advance to next node in the chain
            self._advance_patrol_index(monster, state, chain, patrol_mode, mname)

            # If advance ended the patrol (once-mode finished), stop
            if state.get('patrol_finished'):
                return

            # Re-resolve the NEW target so we can start moving immediately
            idx = state.get('patrol_chain_idx', 0)
            if idx < 0 or idx >= len(chain):
                return
            current_node_name = chain[idx]
            node = self._find_path_node_by_name(current_node_name)
            if node is None:
                state['patrol_chain'] = []
                return

            # Re-read position (hasn't changed) and compute vector to NEW node
            n_pos = glm.vec3(node.pos)
            if mtype == 'flying':
                to_node = n_pos - m_pos
                dist_to_node = glm.length(to_node)
            else:
                flat = glm.vec3(n_pos.x - m_pos.x, 0.0, n_pos.z - m_pos.z)
                dist_to_node = glm.length(flat)
                to_node = flat
            radius = node.get_radius()

            # If the new target also contains the monster (overlapping radii),
            # handle that on the NEXT tick to avoid infinite recursion.
            if dist_to_node <= radius:
                return
            # Otherwise fall through to movement below ↓

        # --- Left a node we were previously at? ---------------------------
        if state.get('patrol_at_target'):
            prev_name = chain[state.get('patrol_chain_idx', 0)]
            prev_node = self._find_path_node_by_name(prev_name)
            if prev_node is not None and self.io_manager:
                self.io_manager.fire_output(prev_node, 'OnMonsterLeft')
            state['patrol_at_target'] = False
            debug_log("Pathfinding",
                      f"'{mname}' left radius of '{prev_name}'")

        # --- Announce patrol walk (once per leg) --------------------------
        if state.get('patrol_walking_to') != current_node_name:
            state['patrol_walking_to'] = current_node_name
            debug_log("Pathfinding",
                      f"'{mname}' patrolling -> '{current_node_name}' "
                      f"(dist={dist_to_node:.0f})")

        # --- Detour override: if we have an active detour, walk toward
        #     the detour node instead of the chain target. -----------------
        detour_name = state.get('detour_node', '')
        if detour_name:
            detour_node = self._find_path_node_by_name(detour_name)
            if detour_node is None or detour_node.properties.get('disabled', False):
                # Detour node was removed / disabled — cancel detour
                state['detour_node'] = ''
                debug_log("Pathfinding",
                          f"'{mname}' detour node '{detour_name}' "
                          f"gone — resuming normal patrol")
            else:
                d_pos = glm.vec3(detour_node.pos)
                if mtype == 'flying':
                    d_vec = d_pos - m_pos
                else:
                    d_vec = glm.vec3(d_pos.x - m_pos.x, 0.0, d_pos.z - m_pos.z)
                d_dist = glm.length(d_vec)
                d_radius = detour_node.get_radius()

                if d_dist <= d_radius:
                    # Reached the detour node — clear and resume normal patrol
                    state['detour_node'] = ''
                    state['patrol_blocked_count'] = 0
                    debug_log("Pathfinding",
                              f"'{mname}' reached detour node "
                              f"'{detour_name}' — resuming patrol "
                              f"toward '{current_node_name}'")
                    # Fall through to normal movement on the next tick
                    return

                # Override the movement vector to head for the detour node
                to_node = d_vec
                dist_to_node = d_dist
                speed_mult = detour_node.get_patrol_speed()
                # (node variable is NOT reassigned — only the movement
                #  direction is redirected)

        # --- Movement toward node -----------------------------------------
        if not (detour_name and state.get('detour_node')):
            speed_mult = node.get_patrol_speed()
        # else: speed_mult was set inside the detour block above
        dir_len = glm.length(to_node)
        if dir_len <= 0.001:
            return
        direction = to_node / dir_len
        if mtype != 'flying':
            direction = glm.normalize(glm.vec3(direction.x, 0.0, direction.z))

        step = direction * MONSTER_MOVE_SPEED * speed_mult * delta
        new_pos = m_pos + step

        if not self._monster_overlaps_wall(new_pos.x, new_pos.y, new_pos.z, MONSTER_WALL_MARGIN):
            monster.pos = [new_pos.x, new_pos.y, new_pos.z]
        else:
            slide_x = glm.vec3(m_pos.x + step.x, m_pos.y, m_pos.z)
            slide_z = glm.vec3(m_pos.x, m_pos.y, m_pos.z + step.z)
            if not self._monster_overlaps_wall(slide_x.x, slide_x.y, slide_x.z, MONSTER_WALL_MARGIN):
                monster.pos = [slide_x.x, slide_x.y, slide_x.z]
            elif not self._monster_overlaps_wall(slide_z.x, slide_z.y, slide_z.z, MONSTER_WALL_MARGIN):
                monster.pos = [slide_z.x, slide_z.y, slide_z.z]
            else:
                # Blocked on both axes — log it so designers can diagnose
                # tight spaces that stall patrol routes.
                blocked_count = state.get('patrol_blocked_count', 0) + 1
                state['patrol_blocked_count'] = blocked_count
                # Log once, then every 120 ticks (~2 sec at 60fps)
                if blocked_count == 1 or blocked_count % 120 == 0:
                    debug_log("Pathfinding",
                              f"'{mname}' blocked by wall collision "
                              f"en route to '{current_node_name}' "
                              f"(stuck for {blocked_count} ticks)")

                # --- Detour: after being stuck long enough, search for a
                #     nearby PathNode to route around the obstacle. ---------
                if blocked_count >= MONSTER_STUCK_THRESHOLD and not state.get('detour_node'):
                    detour = self._find_nearby_detour_node(
                        m_pos, current_node_name, mtype)
                    if detour:
                        state['detour_node'] = detour
                        state['patrol_blocked_count'] = 0
                        debug_log("Pathfinding",
                                  f"'{mname}' detouring via '{detour}' "
                                  f"to get around obstacle en route "
                                  f"to '{current_node_name}'")
                return

        # Movement succeeded — reset blocked counter
        state['patrol_blocked_count'] = 0

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
            stopping at MONSTER_STOP_DISTANCE. They are affected by gravity and cannot
            walk through walls.
          - Flying monsters move in full 3D toward the player.
          - Attacks fire on MONSTER_SHOOT_INTERVAL cooldown while in MONSTER_SIGHT_RANGE
            AND the monster has line-of-sight (not blocked by wall brushes).
          - Out-of-range monsters go idle but stay awake (they chase when you return).

        I/O events fired:
          - OnSeePlayer  — once when player enters sight range
          - OnLostPlayer — once when player leaves sight range
          - OnAttack     — each time the monster shoots
          - OnDeath      — when Kill input is received

        Dead / hidden / disabled monsters are always skipped.
        Dead monsters' sprites fall to ground if above ground level.
        """
        if not self.player or not MonsterThing:
            return

        if self.player_dead:
            return

        player_pos = self.player.pos

        # Clear per-frame debug rays
        self._debug_rays = []

        for thing in self.things:
            if not isinstance(thing, MonsterThing):
                continue

            if thing.properties.get('hidden', False):
                thing.properties.pop('is_shooting', None)
                continue
            if thing.properties.get('disabled', False):
                continue

            mid = id(thing)

            # --- Handle dead monsters: sprite falls to ground ---
            if thing.properties.get('dead', False):
                thing.properties.pop('is_shooting', None)
                # Apply gravity to the dead sprite until it hits the floor
                vel_y = thing.properties.get('_vel_y', 0.0)
                thing_pos = thing.pos
                ground_y = self._monster_raycast_down(thing_pos[0], thing_pos[2], thing_pos[1])
                if ground_y is not None:
                    sprite_h = thing.properties.get('sprite_height', 128)
                    target_y = ground_y + sprite_h / 2.0
                    if thing_pos[1] > target_y + 1.0:
                        vel_y += MONSTER_GRAVITY * delta
                        if vel_y < MONSTER_TERMINAL_VEL:
                            vel_y = MONSTER_TERMINAL_VEL
                        new_y = thing_pos[1] + vel_y * delta
                        if new_y <= target_y:
                            new_y = target_y
                            vel_y = 0.0
                        thing.pos = [thing_pos[0], new_y, thing_pos[2]]
                        thing.properties['_vel_y'] = vel_y
                    else:
                        # Snap to correct height
                        if abs(thing_pos[1] - target_y) > 1.0:
                            thing.pos = [thing_pos[0], target_y, thing_pos[2]]
                        thing.properties['_vel_y'] = 0.0
                else:
                    # No floor found – stop falling
                    thing.properties['_vel_y'] = 0.0
                continue

            # --- Get sprite dimensions for foot-based positioning ---
            sprite_width = thing.properties.get('sprite_width', 128)
            sprite_height = thing.properties.get('sprite_height', 128)
            half_height = sprite_height / 2.0

            if mid not in self.monster_states:
                self.monster_states[mid] = {
                    'shoot_timer': MONSTER_SHOOT_INTERVAL,
                    'anim_timer':  0.0,
                    'in_sight':    False,
                    'vel_y':       0.0,   # vertical velocity for gravity
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

            mtype = thing.properties.get('monster_type', 'human')

            # ---- Monster gravity & floor detection (ground types) ------------
            if mtype != 'flying':
                vel_y = state.get('vel_y', 0.0)
                # Raycast down from above the monster's current position
                ground_y = self._monster_raycast_down(thing_pos.x, thing_pos.z, thing_pos.y + 10.0)
                if ground_y is not None:
                    foot_y = thing_pos.y - half_height
                    if foot_y > ground_y + 1.0:
                        # In the air — apply gravity to foot position
                        vel_y += MONSTER_GRAVITY * delta
                        if vel_y < MONSTER_TERMINAL_VEL:
                            vel_y = MONSTER_TERMINAL_VEL
                        new_foot_y = foot_y + vel_y * delta
                        if new_foot_y <= ground_y:
                            new_foot_y = ground_y
                            vel_y = 0.0
                        new_center_y = new_foot_y + half_height
                        thing_pos = glm.vec3(thing_pos.x, new_center_y, thing_pos.z)
                        thing.pos = [thing_pos.x, thing_pos.y, thing_pos.z]
                    else:
                        # Snap to ground: foot exactly on ground
                        desired_center_y = ground_y + half_height
                        if abs(thing_pos.y - desired_center_y) > 1.0:
                            thing_pos = glm.vec3(thing_pos.x, desired_center_y, thing_pos.z)
                            thing.pos = [thing_pos.x, thing_pos.y, thing_pos.z]
                        vel_y = 0.0
                state['vel_y'] = vel_y

            # ---- LOS check — needed for both shooting and debug drawing ------
            monster_eye = glm.vec3(thing_pos.x, thing_pos.y + 64.0, thing_pos.z)
            player_eye  = glm.vec3(player_pos.x,
                                   player_pos.y + self.player.camera_height,
                                   player_pos.z)
            has_los = self._has_line_of_sight(monster_eye, player_eye)

            # Collect debug ray if F7 monster debug is active
            if self.monster_debug_active:
                self._debug_rays.append({
                    'start': [monster_eye.x, monster_eye.y, monster_eye.z],
                    'end':   [player_eye.x, player_eye.y, player_eye.z],
                    'color': 'green' if has_los else 'red',
                })

            if distance <= MONSTER_SIGHT_RANGE:
                # ---- Fire OnSeePlayer on sight transition -------------------
                if not state['in_sight']:
                    state['in_sight'] = True
                    if self.io_manager:
                        self.io_manager.fire_output(thing, 'OnSeePlayer')

                    if self.monster_debug_active:
                        mname = thing.properties.get('name', '?')
                        debug_log("MonsterAI", f"{mname} sees player (dist={distance:.0f})")
                # -------------------------------------------------------------

                # Movement toward player (with wall collision)
                if distance > MONSTER_STOP_DISTANCE:
                    direction = player_pos - thing_pos
                    dir_len = glm.length(direction)
                    if dir_len > 0.001:
                        direction = direction / dir_len
                        if mtype != 'flying':
                            direction = glm.normalize(glm.vec3(direction.x, 0.0, direction.z))
                        step = direction * MONSTER_MOVE_SPEED * delta
                        new_pos = thing_pos + step

                        # ---- Wall collision: reject move if it causes overlap ----
                        if not self._monster_overlaps_wall(new_pos.x, new_pos.y, new_pos.z, MONSTER_WALL_MARGIN):
                            thing.pos = [new_pos.x, new_pos.y, new_pos.z]
                        else:
                            # Try axis-separated movement (slide along walls)
                            slide_x = glm.vec3(thing_pos.x + step.x, thing_pos.y, thing_pos.z)
                            slide_z = glm.vec3(thing_pos.x, thing_pos.y, thing_pos.z + step.z)
                            if not self._monster_overlaps_wall(slide_x.x, slide_x.y, slide_x.z, MONSTER_WALL_MARGIN):
                                thing.pos = [slide_x.x, slide_x.y, slide_x.z]
                            elif not self._monster_overlaps_wall(slide_z.x, slide_z.y, slide_z.z, MONSTER_WALL_MARGIN):
                                thing.pos = [slide_z.x, slide_z.y, slide_z.z]
                            # else: blocked on both axes — don't move
                            # (pathfinding noise — intentionally not logged)

                # ---- Shooting (only if LOS is clear) -------------------------
                state['shoot_timer'] -= delta

                if state['shoot_timer'] <= 0.0 and has_los:
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

                    if self.monster_debug_active:
                        mname = thing.properties.get('name', '?')
                        debug_log("MonsterAI", f"{mname} attacks player for {damage} damage (LOS clear)")

                elif state['shoot_timer'] <= 0.0 and not has_los:
                    # Timer expired but no LOS — reset timer so it fires
                    # immediately when LOS is restored, but don't damage player.
                    state['shoot_timer'] = 0.1  # re-check shortly
                    if self.monster_debug_active:
                        mname = thing.properties.get('name', '?')
                        debug_log("MonsterAI", f"{mname} cannot shoot — LOS blocked")

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
                    if self.monster_debug_active:
                        mname = thing.properties.get('name', '?')
                        debug_log("MonsterAI", f"{mname} lost player (dist={distance:.0f})")
                # -------------------------------------------------------------

                thing.properties['is_shooting'] = False
                state['anim_timer'] = 0.0

                # ---- Patrol behaviour (runs only when player is not in
                # sight — sight/chase always overrides patrol) ---------------
                self._update_monster_patrol(thing, state, mtype, delta)
                # -------------------------------------------------------------

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
        write_state = self.game_state.get_write_state()
        write_state.is_play_mode = self.play_mode

        # Camera / view matrices
        if self.play_mode and self.player:
            # --- Take a snapshot of player state ---
            # Copy position (glm.vec3)
            player_pos = glm.vec3(self.player.pos.x, self.player.pos.y, self.player.pos.z)
            player_angle = self.player.angle
            player_pitch = self.player.pitch
            camera_height = self.player.camera_height   # constant, safe

            # Compute view matrix from the snapshot
            cam_pos = player_pos + glm.vec3(0, camera_height, 0)
            direction = glm.vec3(
                math.sin(player_angle) * math.cos(player_pitch),
                math.sin(player_pitch),
                math.cos(player_angle) * math.cos(player_pitch),
            )
            view_matrix = glm.lookAt(cam_pos, cam_pos + direction, glm.vec3(0, 1, 0))

            # Store snapshot in render state (optional, for HUD)
            write_state.player_pos = player_pos
            write_state.player_angle = player_angle
            write_state.player_pitch = player_pitch
            fov = 90.0
        else:
            # Editor mode – copy editor camera
            write_state.editor_camera_pos = glm.vec3(self.editor_camera.pos)
            write_state.editor_camera_yaw = self.editor_camera.yaw
            write_state.editor_camera_pitch = self.editor_camera.pitch
            write_state.editor_camera_fov = self.editor_camera.fov
            view_matrix = self.editor_camera.get_view_matrix()
            fov = self.editor_camera.fov

        write_state.camera_view_matrix = view_matrix

        # Player stats
        write_state.player_health = self.player_health
        write_state.player_max_health = self.player_max_health
        write_state.player_dead = self.player_dead
        write_state.collected_keys = set(self.collected_keys)
        write_state.hud_message = self.current_hud_message
        write_state.active_weapon = self.active_weapon

        # Muzzle flash
        write_state.muzzle_flash_active = self.muzzle_flash_active

        # Monster debug state
        write_state.monster_debug_active = self.monster_debug_active
        write_state.monster_debug_rays = list(self._debug_rays)

        # Bullet marks
        current_time = time.perf_counter()
        write_state.bullet_marks = [
            {'pos': [m['pos'].x, m['pos'].y, m['pos'].z],
            'alpha': max(0.0, 1.0 - (current_time - m['time']) / self.BULLET_FADE_TIME)}
            for m in self.bullet_marks
            if current_time - m['time'] < self.BULLET_FADE_TIME
        ]

        # ---------- FIX: COPY DYNAMIC OBJECTS ----------
        projection = glm.perspective(glm.radians(fov), self.frustum_aspect, 1.0, 10000.0)
        proj_view = projection * view_matrix
        frustum_planes = self._extract_frustum_planes(proj_view)

        visible_brushes = []
        all_brushes = []
        total_count = 0
        culled_count = 0

        for b in self.brushes:
            total_count += 1
            if b.get('hidden', False):
                culled_count += 1
                continue

            is_dynamic = b.get('is_mover', False) or b.get('is_door', False)

            if is_dynamic:
                # Shallow copy of the brush dict, then copy mutable lists
                b_ref = b.copy()
                b_ref['pos'] = list(b['pos'])
                b_ref['size'] = list(b['size'])
                # Copy other lists if they exist (e.g. direction)
                if 'direction' in b:
                    b_ref['direction'] = list(b['direction'])
                if 'original_pos' in b:
                    b_ref['original_pos'] = list(b['original_pos'])
            else:
                b_ref = b   # static brush – safe to reference directly

            all_brushes.append(b_ref)

            if self.culling_enabled:
                pos = b.get('pos', [0, 0, 0])
                size = b.get('size', [64, 64, 64])
                center = (pos[0], pos[1], pos[2])
                half = (size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
                if not self._aabb_in_frustum(frustum_planes, center, half):
                    culled_count += 1
                    continue

            visible_brushes.append(b_ref)

        write_state.visible_brushes = visible_brushes
        write_state.all_brushes = all_brushes
        write_state.total_brushes = total_count
        write_state.culled_brushes = culled_count

        # ---------- Things (including monster snapshots) ----------
        visible_things = []
        for i, thing in enumerate(self.things):
            if self.play_mode and Pickup and isinstance(thing, Pickup) and i in self.collected_pickups:
                continue
            # Convert glm.vec3 positions to list for consistency
            if hasattr(thing.pos, 'x'):
                thing.pos = [thing.pos.x, thing.pos.y, thing.pos.z]

            # Snapshot monsters to avoid data races
            if isinstance(thing, MonsterThing):
                visible_things.append(thing.get_render_snapshot())
            else:
                visible_things.append(thing)

        write_state.visible_things = visible_things
        write_state.timestamp = time.perf_counter()
