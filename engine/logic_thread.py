import threading
import time
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
    
    TICK_RATE = 60  # Logic updates per second
    TICK_DURATION = 1.0 / TICK_RATE
    
    def __init__(self, game_state: ThreadedGameState, 
                 brushes: List[Dict], things: List[Any]):
        super().__init__(daemon=True)
        self.game_state = game_state
        self.brushes = brushes
        self.things = things
        
        self.running = False
        self.player: Optional[Player] = None
        self.play_mode = False
        
        # Trigger state
        self.player_in_triggers: set = set()
        self.fired_once_triggers: set = set()
        
    def set_player(self, player: Optional[Player]):
        """Set or clear the active player."""
        self.player = player
        
    def set_play_mode(self, enabled: bool):
        self.play_mode = enabled
        if not enabled:
            self.player_in_triggers.clear()
            self.fired_once_triggers.clear()
            
    def run(self):
        """Main logic loop with fixed timestep."""
        self.running = True
        last_time = time.perf_counter()
        accumulator = 0.0
        
        while self.running:
            current_time = time.perf_counter()
            frame_time = current_time - last_time
            last_time = current_time
            
            # Clamp frame time to prevent spiral of death
            if frame_time > 0.25:
                frame_time = 0.25
                
            accumulator += frame_time
            
            # Fixed timestep updates
            while accumulator >= self.TICK_DURATION:
                self._tick(self.TICK_DURATION)
                accumulator -= self.TICK_DURATION
                
            # Prepare render state
            self._prepare_render_state()
            self.game_state.request_swap()
            
            # Don't spin too fast
            sleep_time = self.TICK_DURATION - (time.perf_counter() - current_time)
            if sleep_time > 0:
                time.sleep(sleep_time * 0.9)  # Sleep slightly less to maintain timing
                
    def stop(self):
        self.running = False
        
    def _tick(self, delta: float):
        """Single logic tick."""
        if not self.play_mode or not self.player:
            return
            
        # Get input
        keys = self.game_state.get_keys()
        mouse_delta = self.game_state.consume_mouse_delta()
        
        # Update player angle from mouse
        if mouse_delta != (0.0, 0.0):
            self.player.update_angle(mouse_delta[0], mouse_delta[1])
            
        # Update player physics
        self.player.update(keys, self.brushes, delta)
        
        # Handle triggers
        self._handle_triggers()
        
    def _handle_triggers(self):
        """Process trigger collisions."""
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
        """Activate a trigger."""
        trigger_type = brush.get('trigger_type', 'multiple')
        if trigger_type == 'once' and trigger_id in self.fired_once_triggers:
            return
            
        target_name = brush.get('target')
        if not target_name:
            return
            
        # Find and activate target
        for b in self.brushes:
            if b.get('name') == target_name and b.get('is_mover'):
                b['start_on'] = not b.get('start_on', False)
                break
                
        if trigger_type == 'once':
            self.fired_once_triggers.add(trigger_id)
            
    def _prepare_render_state(self):
        """Prepare the render state snapshot."""
        write_state = self.game_state.get_write_state()
        
        if self.player:
            write_state.player_pos = glm.vec3(self.player.pos)
            write_state.player_angle = self.player.angle
            write_state.player_pitch = self.player.pitch
            write_state.camera_view_matrix = self.player.get_view_matrix()
        
        # Simple fallback: all non-hidden brushes
        write_state.visible_brushes = [
            b for b in self.brushes if not b.get('hidden', False)
        ]
        write_state.visible_things = list(self.things)
        write_state.timestamp = time.perf_counter()