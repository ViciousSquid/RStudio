import threading
import time
import numpy as np
from typing import List, Dict, Any, Optional
import glm
import math

from .threaded_game_state import ThreadedGameState, RenderState
from .player import Player

class LogicThread(threading.Thread):
    """
    Separate thread for game logic processing.
    Runs at a fixed timestep (default 60 Hz) independent of rendering.
    """
    
    TICK_RATE = 60
    TICK_DURATION = 1.0 / TICK_RATE
    
    def __init__(self, game_state: ThreadedGameState, 
                 brushes: List[Dict], things: List[Any], 
                 visibility_system: Optional[Any] = None):
        super().__init__(daemon=True)
        self.game_state = game_state
        self.brushes = brushes
        self.things = things
        self.visibility_system = visibility_system
        
        self.running = False
        self.player: Optional[Player] = None
        self.play_mode = False
        
        # Trigger state
        self.player_in_triggers: set = set()
        self.fired_once_triggers: set = set()
        
        # Mover Animation State
        self.mover_states = {} 
        self._init_movers()
        
        # Performance Monitoring
        self.actual_tps = 0.0
        self._tick_count = 0
        self._last_tps_time = time.perf_counter()

    def set_player(self, player: Optional[Player]):
        """Set or clear the active player."""
        self.player = player
        
    def set_play_mode(self, enabled: bool):
        self.play_mode = enabled
        if enabled:
            self._init_movers()
        else:
            self.player_in_triggers.clear()
            self.fired_once_triggers.clear()
            self._reset_movers()

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
        """Single logic tick."""
        if not self.play_mode or not self.player:
            return
            
        # 1. Update Movers (and carry player)
        self._update_movers(delta)

        # 2. Get Input
        keys = self.game_state.get_keys()
        mouse_delta = self.game_state.consume_mouse_delta()
        
        # 3. Update Player Physics
        if mouse_delta != (0.0, 0.0):
            self.player.update_angle(mouse_delta[0], mouse_delta[1])
            
        self.player.update(keys, self.brushes, delta)
        
        # 4. Handle Triggers
        self._handle_triggers()

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

    def _handle_triggers(self):
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
                if i not in self.player_in_triggers:
                    self._activate_trigger(brush, i)
                    
        self.player_in_triggers = currently_colliding
        
    def _activate_trigger(self, brush: Dict, trigger_id: int):
        trigger_type = brush.get('trigger_type', 'multiple')
        if trigger_type == 'once' and trigger_id in self.fired_once_triggers:
            return
            
        target_name = brush.get('target')
        if not target_name:
            return
            
        for b in self.brushes:
            if b.get('name') == target_name and b.get('is_mover'):
                b['start_on'] = not b.get('start_on', False)
                
        if trigger_type == 'once':
            self.fired_once_triggers.add(trigger_id)
            
    def _prepare_render_state(self):
        write_state = self.game_state.get_write_state()
        
        if self.player:
            write_state.player_pos = glm.vec3(self.player.pos)
            write_state.player_angle = self.player.angle
            write_state.player_pitch = self.player.pitch
            write_state.camera_view_matrix = self.player.get_view_matrix()

        # Build a safe display list of brushes.
        # We MUST copy brushes that are movers, otherwise the Render thread
        # might read the dict while LogicThread is modifying 'pos' in the next tick.
        safe_brushes = []
        for b in self.brushes:
            if b.get('hidden', False):
                continue
            
            if b.get('is_mover', False):
                # Shallow copy is sufficient because 'pos' is replaced with a new list object
                # in _update_movers, not mutated in place.
                safe_brushes.append(b.copy())
            else:
                # Static brushes can be referenced directly
                safe_brushes.append(b)

        write_state.visible_brushes = safe_brushes
        write_state.visible_things = list(self.things)
        write_state.timestamp = time.perf_counter()