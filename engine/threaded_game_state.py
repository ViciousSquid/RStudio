import threading
import glm
import time
from typing import List, Any, Dict, Optional
from collections import deque

class RenderState:
    """
    A snapshot of the game state specifically for the renderer.
    """
    def __init__(self):
        # Camera / View
        self.camera_view_matrix = glm.mat4(1.0)
        self.projection_matrix = glm.mat4(1.0)
        self.is_play_mode = False
        
        # Editor Camera
        self.editor_camera_pos = glm.vec3(0, 0, 0)
        self.editor_camera_yaw = 0.0
        self.editor_camera_pitch = 0.0
        self.editor_camera_fov = 90.0
        
        # Player
        self.player_pos = glm.vec3(0, 0, 0)
        self.player_angle = 0.0
        self.player_pitch = 0.0
        self.player_health = 100
        self.player_max_health = 100
        self.player_dead = False
        self.active_weapon = None
        self.player_underwater = False
        self.underwater_tint = [0.0, 0.4, 0.6]

        # Player 2 (split-screen)
        self.player2_pos = glm.vec3(0, 0, 0)
        self.player2_angle = 0.0
        self.player2_pitch = 0.0
        self.player2_view_matrix = glm.mat4(1.0)
        self.player2_health = 100
        self.player2_max_health = 100
        self.player2_dead = False
        self.player2_underwater = False
        self.splitscreen_active = False
        
        # Scene Data
        self.visible_brushes = []
        self.all_brushes = []
        self.visible_things = []
        
        # HUD / Gameplay
        self.collected_keys = set()
        self.hud_message = ""
        
        # Visual FX
        self.bullet_marks = [] # List of {'pos': [x,y,z], 'alpha': float}
        self.projectiles = []  # list of {
            #     'pos': [x, y, z],
            #     'vel': [vx, vy, vz],
            #     'owner_id': int,      # id() of the monster that fired it
            #     'sprite': str,        # projectile sprite path
            #     'lifetime': float,    # seconds remaining
            #     'damage': int,
            #     'size': (w, h),       # billboard size
            # }

        # Muzzle flash — True for one frame after the player fires
        self.muzzle_flash_active = False

        # Monster debug visualisation (F7 toggle)
        self.monster_debug_active = False
        # List of {'start': [x,y,z], 'end': [x,y,z], 'color': str}
        #   color is 'green' (has LOS) or 'red' (blocked)
        self.monster_debug_rays = []
        
        # Debug / Stats
        self.total_brushes = 0
        self.culled_brushes = 0
        self.timestamp = 0.0

    def reset(self):
        """Reset all fields to defaults for reuse (avoids per-frame allocation)."""
        self.camera_view_matrix = glm.mat4(1.0)
        self.projection_matrix = glm.mat4(1.0)
        self.is_play_mode = False
        self.editor_camera_pos = glm.vec3(0, 0, 0)
        self.editor_camera_yaw = 0.0
        self.editor_camera_pitch = 0.0
        self.editor_camera_fov = 90.0
        self.player_pos = glm.vec3(0, 0, 0)
        self.player_angle = 0.0
        self.player_pitch = 0.0
        self.player_health = 100
        self.player_max_health = 100
        self.player_dead = False
        self.active_weapon = None
        self.player_underwater = False
        self.underwater_tint = [0.0, 0.4, 0.6]
        self.player2_pos = glm.vec3(0, 0, 0)
        self.player2_angle = 0.0
        self.player2_pitch = 0.0
        self.player2_view_matrix = glm.mat4(1.0)
        self.player2_health = 100
        self.player2_max_health = 100
        self.player2_dead = False
        self.player2_underwater = False
        self.splitscreen_active = False
        self.visible_brushes = []
        self.all_brushes = []
        self.visible_things = []
        self.collected_keys = set()
        self.hud_message = ""
        self.bullet_marks = []
        self.projectiles = []
        self.muzzle_flash_active = False
        self.monster_debug_active = False
        self.monster_debug_rays = []
        self.total_brushes = 0
        self.culled_brushes = 0
        self.timestamp = 0.0


class ThreadedGameState:
    """
    Thread-safe container for communication between UI/Input and Logic threads.
    """
    def __init__(self):
        self._render_state_lock = threading.Lock()
        
        # Double Buffering: One state for reading (Render), one for writing (Logic)
        self._read_state = RenderState()
        self._write_state = RenderState()
        self._has_new_frame = False
        
        # Input state
        self._keys_lock = threading.Lock()
        self._keys = set()
        self._mouse_lock = threading.Lock()
        self._mouse_delta = (0.0, 0.0)
        
        # Shot Queue — deque for O(1) popleft
        self._shot_lock = threading.Lock()
        self._shot_queue = deque()

        # Use key — protected by its own lock
        self._use_key_lock = threading.Lock()
        self._use_key_pressed = False

        # Player 2 input (gamepad / arrow keys)
        self._p2_lock = threading.Lock()
        self._p2_input = {
            'move_x': 0.0, 'move_z': 0.0,
            'look_dx': 0.0, 'look_dy': 0.0,
            'jump': False, 'crouch': False,
        }

        # Sound queue — thread-safe, accessed from logic and render threads
        self._sound_lock = threading.Lock()
        self.sound_queue = deque()

    def get_render_state(self) -> RenderState:
        """Called by RenderThread (Qt) to get the latest frame data."""
        with self._render_state_lock:
            snap = object.__new__(RenderState)
            snap.__dict__ = self._read_state.__dict__.copy()
            return snap

    def get_write_state(self) -> RenderState:
        """Called by LogicThread to get the object to write to."""
        return self._write_state

    def peek_has_new_frame(self) -> bool:
        """Non-consuming check used by update_loop."""
        with self._render_state_lock:
            return self._has_new_frame

    def request_swap(self):
        """Called by LogicThread when a frame is completely written."""
        with self._render_state_lock:
            # Swap: write becomes read, old read becomes next write buffer
            old_read = self._read_state
            self._read_state = self._write_state
            # Reuse the old read state instead of allocating a new RenderState
            old_read.reset()
            self._write_state = old_read
            self._has_new_frame = True

    def try_swap(self) -> bool:
        """Called by QtGameView to check if a new frame is available."""
        with self._render_state_lock:
            if self._has_new_frame:
                self._has_new_frame = False
                return True
            return False

    # --- Input Handling ---

    def set_keys(self, keys: set):
        with self._keys_lock:
            self._keys = keys.copy()
            
    def get_keys(self) -> set:
        with self._keys_lock:
            return self._keys.copy()
            
    def set_mouse_delta(self, dx, dy):
        with self._mouse_lock:
            self._mouse_delta = (self._mouse_delta[0] + dx, self._mouse_delta[1] + dy)
            
    def consume_mouse_delta(self):
        with self._mouse_lock:
            delta = self._mouse_delta
            self._mouse_delta = (0.0, 0.0)
            return delta

    def set_use_key(self, pressed: bool):
        """Sets the state of the use key explicitly (True/False)."""
        with self._use_key_lock:
            self._use_key_pressed = pressed
    
    def set_use_key_pressed(self):
        """Convenience method called by main_window.py to trigger the use key."""
        with self._use_key_lock:
            self._use_key_pressed = True
        
    def consume_use_key(self) -> bool:
        with self._use_key_lock:
            if self._use_key_pressed:
                self._use_key_pressed = False
                return True
            return False

    # --- Shooting Handling ---

    def queue_shot(self):
        with self._shot_lock:
            self._shot_queue.append(True)

    def consume_shot(self):
        with self._shot_lock:
            if self._shot_queue:
                self._shot_queue.popleft()
                return True
            return False

    # --- Sound Queue ---

    def queue_sound(self, request: dict):
        """Thread-safe: enqueue a sound request from any thread."""
        with self._sound_lock:
            self.sound_queue.append(request)

    # --- Player 2 Input ---

    def set_p2_input(self, move_x: float, move_z: float,
                     look_dx: float, look_dy: float,
                     jump: bool, crouch: bool = False) -> None:
        """Thread-safe: push P2 input from the render/UI thread."""
        with self._p2_lock:
            self._p2_input = {
                'move_x': float(move_x),
                'move_z': float(move_z),
                'look_dx': float(look_dx),
                'look_dy': float(look_dy),
                'jump': bool(jump),
                'crouch': bool(crouch),
            }

    def get_p2_input(self) -> dict:
        """Thread-safe: read P2 input from the logic thread."""
        with self._p2_lock:
            return self._p2_input.copy()

    def consume_sounds(self) -> list:
        """Thread-safe: drain all pending sound requests (called from render thread)."""
        with self._sound_lock:
            if not self.sound_queue:
                return []
            result = list(self.sound_queue)
            self.sound_queue.clear()
            return result
