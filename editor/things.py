import os
from PyQt5.QtGui import QPixmap
import json
import ast

def find_subclasses(cls):
    """Recursively finds all subclasses of a given class."""
    all_subclasses = []
    for subclass in cls.__subclasses__():
        all_subclasses.append(subclass)
        all_subclasses.extend(find_subclasses(subclass))
    return all_subclasses

class Thing:
    pixmap_path = None
    _pixmap_cache = {} # Class-level cache for loaded pixmaps
    _counters = {} # Class-level counter for unique naming

    def __init__(self, pos=None, properties=None):
        self.pos = pos if pos is not None else [0, 0, 0]
        self.properties = properties if properties is not None else {}
        self.properties.setdefault('type', self.__class__.__name__.lower())
        
        # --- Set a default and unique name ---
        if 'name' not in self.properties or not self.properties['name']:
            class_name = self.__class__.__name__
            if class_name not in Thing._counters:
                Thing._counters[class_name] = 1
            else:
                Thing._counters[class_name] += 1
            self.properties['name'] = f"{class_name}_{Thing._counters[class_name]}"
        
        # --- Support for lock, hidden, and color (for tagging) ---
        # These are optional and not set by default to keep save files clean
        # self.properties.setdefault('lock', False)
        # self.properties.setdefault('hidden', False)
        # self.properties.setdefault('color', None)

    @property
    def name(self):
        """Gets the name from the properties dictionary."""
        return self.properties.get('name', '')

    @name.setter
    def name(self, value):
        """Sets the name in the properties dictionary."""
        self.properties['name'] = value

    @classmethod
    def get_pixmap(cls):
        """
        Gets the QPixmap for this class, loading it from disk and caching it
        the first time it's requested. This is the new on-demand system.
        """
        class_name = cls.__name__
        if class_name in cls._pixmap_cache:
            return cls._pixmap_cache[class_name]

        if not cls.pixmap_path:
            cls._pixmap_cache[class_name] = None
            return None

        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
        except NameError:
            project_root = os.path.abspath(os.path.join(os.getcwd()))

        absolute_path = os.path.join(project_root, cls.pixmap_path)

        pixmap = None
        if os.path.exists(absolute_path):
            loaded_pixmap = QPixmap(absolute_path)
            if not loaded_pixmap.isNull():
                pixmap = loaded_pixmap
            else:
                print(f"Error: QPixmap failed to load image for {class_name} from {absolute_path}")
        else:
            print(f"Warning: Sprite file not found for {class_name} at: {absolute_path}")

        cls._pixmap_cache[class_name] = pixmap
        return pixmap
    
    def get_instance_pixmap(self):
        """
        Gets the QPixmap for this specific instance. 
        Override in subclasses for dynamic sprite selection.
        """
        return self.__class__.get_pixmap()

    def to_dict(self):
        serializable_props = {k: str(v) for k, v in self.properties.items()}
        return {'type': self.properties.get('type'), 'pos': self.pos, 'properties': serializable_props}

    @staticmethod
    def from_dict(data):
        thing_type = data.get('type')
        if not thing_type: return None

        properties = data.get('properties', {})
        for key, value in properties.items():
            if isinstance(value, str):
                try: properties[key] = ast.literal_eval(value)
                except (ValueError, SyntaxError): pass

        for cls in find_subclasses(Thing):
            # Use lower() for case-insensitive matching with type property
            if cls.__name__.lower() == thing_type:
                return cls(pos=data.get('pos'), properties=properties)
        
        # Fallback for base Thing if no specific subclass matches
        if thing_type == 'thing':
            return Thing(pos=data.get('pos'), properties=properties)
        
        print(f"Warning: Unknown thing type '{thing_type}' found in map file.")
        return None

# --- Thing Subclasses ---

class PlayerStart(Thing):
    pixmap_path = "assets/sprites/player.png"
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'playerstart')
        self.properties.setdefault('angle', 0.0)

    def get_angle(self):
        return float(self.properties.get('angle', 0.0))

class Light(Thing):
    pixmap_path = "assets/sprites/light.png"
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'light')
        self.properties.setdefault('colour', [255, 255, 255])
        self.properties.setdefault('intensity', 1.0)
        self.properties.setdefault('radius', 512.0)
        self.properties.setdefault('state', 'on')
        self.properties.setdefault('show_radius', False)
        self.properties.setdefault('casts_shadows', False)

    def get_color(self):
        color = self.properties.get('colour', [255, 255, 255])
        return [c / 255.0 for c in color]

    def get_intensity(self):
        return float(self.properties.get('intensity', 1.0))

    def get_radius(self):
        return float(self.properties.get('radius', 512.0))

class Speaker(Thing):
    pixmap_path = "assets/sprites/speaker.png"
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'speaker')
        self.properties.setdefault('sound_file', "")
        self.properties.setdefault('radius', 512.0)
        self.properties.setdefault('global', False)
        self.properties.setdefault('show_radius', False)
        self.properties.setdefault('volume', 1.0)
        self.properties.setdefault('looping', False)
        self.properties.setdefault('play_on_start', False)
        self.properties.setdefault('triggered', False)  # Can be triggered by a trigger brush
        self.properties.setdefault('state', 'off')  # 'on' or 'off' - current playback state

    def get_radius(self):
        return float(self.properties.get('radius', 512.0))

class Monster(Thing):
    pixmap_path = "assets/sprites/monster.png"
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'monster')
        self.properties.setdefault('id', 0)

class Pickup(Thing):
    pixmap_path = "assets/sprites/pickup.png"
    
    
    # Key sprite mappings
    KEY_SPRITES = {
        'blue_key': 'assets/sprites/bluekey.png',
        'red_key': 'assets/sprites/redkey.png',
        'yellow_key': 'assets/sprites/yellowkey.png',
        'green_key': 'assets/sprites/greenkey.png',
    }

    # NEW: Gun sprite mappings
    GUN_SPRITES = {
        'gun1': 'assets/sprites/gun1.png',
        'gun2': 'assets/sprites/gun2.png'
    }
    
    # Cache for dynamically loaded sprites (keyed by path)
    _dynamic_sprite_cache = {}
    
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'pickup')
        self.properties.setdefault('item_type', 'health')
        self.properties.setdefault('value', 25)
        self.properties.setdefault('activation', 'walk_over')  # 'walk_over' or 'use'
        self.properties.setdefault('collected', False)  # Runtime state
        
        # Only Pickups have respawn functionality
        self.properties.setdefault('respawns', False)
        self.properties.setdefault('respawn_time', 20.0)
        
        # Key-specific properties (only relevant when item_type == 'key')
        self.properties.setdefault('key_name', 'blue_key')  # Default key name
        
        # Custom sprite override (user-selected sprite)
        self.properties.setdefault('custom_sprite', '')  # Path to custom sprite

    def is_gun(self):
        return self.properties.get('item_type') in ['gun1', 'gun2']
    
    def is_key(self):
        """Check if this pickup is a key."""
        return self.properties.get('item_type') == 'key'
    
    def get_key_name(self):
        """Get the key name for matching with doors."""
        return self.properties.get('key_name', 'blue_key')
    
    def get_sprite_path(self):
        """Get the appropriate sprite path based on item type."""
        # Custom sprite takes highest priority (unless it's a key/gun logic override)
        custom = self.properties.get('custom_sprite', '')
        if custom and not self.is_key() and not self.is_gun():
            return custom
        
        # For keys, use key-specific sprites
        if self.is_key():
            key_name = self.get_key_name()
            return self.KEY_SPRITES.get(key_name, 'assets/sprites/pickup.png')

        # NEW: For guns, use gun-specific sprites
        item_type = self.properties.get('item_type')
        if item_type in self.GUN_SPRITES:
            return self.GUN_SPRITES[item_type]
        
        # Custom sprite for generic pickups
        if custom:
            return custom
        
        # Default
        return 'assets/sprites/pickup.png'
    
    def get_instance_pixmap(self):
        """
        Gets the QPixmap for this specific Pickup instance.
        Handles keys and custom sprites dynamically.
        """
        sprite_path = self.get_sprite_path()
        
        # Check dynamic cache first
        if sprite_path in Pickup._dynamic_sprite_cache:
            return Pickup._dynamic_sprite_cache[sprite_path]
        
        # Try to load the sprite
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
        except NameError:
            project_root = os.path.abspath(os.path.join(os.getcwd()))
        
        # Handle both relative and absolute paths
        if os.path.isabs(sprite_path):
            absolute_path = sprite_path
        else:
            absolute_path = os.path.join(project_root, sprite_path)
        
        pixmap = None
        if os.path.exists(absolute_path):
            loaded_pixmap = QPixmap(absolute_path)
            if not loaded_pixmap.isNull():
                # Scale to 75x75 if it's a custom sprite
                custom = self.properties.get('custom_sprite', '')
                if custom and loaded_pixmap.width() != 75:
                    pixmap = loaded_pixmap.scaled(75, 75)
                else:
                    pixmap = loaded_pixmap
            else:
                print(f"Error: QPixmap failed to load sprite from {absolute_path}")
        else:
            print(f"Warning: Sprite file not found at: {absolute_path}")
            # Fall back to default class pixmap
            pixmap = Pickup.get_pixmap()
        
        # Cache and return
        Pickup._dynamic_sprite_cache[sprite_path] = pixmap
        return pixmap
    
    @classmethod
    def get_key_sprite_path(cls, key_name):
        """Class method to get sprite path for a specific key name."""
        return cls.KEY_SPRITES.get(key_name, 'assets/sprites/pickup.png')
    
    @classmethod
    def get_key_pixmap(cls, key_name):
        """Get a pixmap for a specific key by name (for HUD display)."""
        sprite_path = cls.get_key_sprite_path(key_name)
        
        if sprite_path in cls._dynamic_sprite_cache:
            return cls._dynamic_sprite_cache[sprite_path]
        
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
        except NameError:
            project_root = os.path.abspath(os.path.join(os.getcwd()))
        
        absolute_path = os.path.join(project_root, sprite_path)
        
        pixmap = None
        if os.path.exists(absolute_path):
            loaded_pixmap = QPixmap(absolute_path)
            if not loaded_pixmap.isNull():
                pixmap = loaded_pixmap
        
        cls._dynamic_sprite_cache[sprite_path] = pixmap
        return pixmap
    
    @classmethod
    def clear_sprite_cache(cls):
        """Clear the dynamic sprite cache (useful when sprites are changed)."""
        cls._dynamic_sprite_cache.clear()

class Trigger(Thing):
    pixmap_path = None
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'trigger')
        self.properties.setdefault('target', '')
        self.properties.setdefault('action', 'on_enter')

class Model(Thing):
    """Represents a 3D model placed in the world."""
    pixmap_path = "assets/sprites/model.png"
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'model')
        self.properties.setdefault('model_path', "")
        self.properties.setdefault('rotation', [0, 0, 0])
        self.properties.setdefault('scale', [1, 1, 1])

class LogicGate(Thing):
    pixmap_path = "assets/sprites/logic_gate.png" # Fallback sprite
    
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'logic_gate')
        self.properties.setdefault('logic_type', 'AND') # AND, OR, XOR, NAND, NOR
        self.properties.setdefault('target', '')
        self.properties.setdefault('initial_state', 'off')

    def get_instance_pixmap(self):
        """
        Dynamically load sprite based on logic type (e.g., 'logic_and.png').
        """
        l_type = self.properties.get('logic_type', 'and').lower()
        # You can supply 'logic_and.png', 'logic_or.png', etc.
        expected_path = f"assets/sprites/logic_{l_type}.png"
        
        # Check dynamic cache
        if expected_path in self._pixmap_cache:
            return self._pixmap_cache[expected_path]
            
        # Try to load
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
            abs_path = os.path.join(project_root, expected_path)
            
            if os.path.exists(abs_path):
                pix = QPixmap(abs_path)
                if not pix.isNull():
                    self._pixmap_cache[expected_path] = pix
                    return pix
        except:
            pass
            
        # Fallback to default class pixmap if specific type sprite missing
        return super().get_instance_pixmap()