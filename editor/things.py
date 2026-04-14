"""
This module defines all placeable entities (Things) in the level editor.
Each Thing type has associated I/O definitions (inputs/outputs) for
the event-driven entity communication system.
"""

import os
import uuid
from PyQt5.QtGui import QPixmap, QColor
from PyQt5.QtCore import Qt   # Needed for scaling flags in get_icon_pixmap
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
    """Base class for all placeable entities."""
    pixmap_path = None
    _pixmap_cache = {}  # Class-level cache for loaded pixmaps
    _counters = {}      # Class-level counter for unique naming

    def __init__(self, pos=None, properties=None):
        self.pos = pos if pos is not None else [0, 0, 0]
        self.properties = properties if properties is not None else {}
        self.properties.setdefault('type', self.__class__.__name__.lower())
        
        # Set a default and unique name
        if 'name' not in self.properties or not self.properties['name']:
            class_name = self.__class__.__name__
            if class_name not in Thing._counters:
                Thing._counters[class_name] = 1
            else:
                Thing._counters[class_name] += 1
            self.properties['name'] = f"{class_name}_{Thing._counters[class_name]}"
        
        # Stable unique ID (persists across save/load)
        if 'id' not in self.properties:
            self.properties['id'] = str(uuid.uuid4())

        # I/O Connections - stored as list of OutputConnection objects
        if '_io_connections' not in self.properties:
            self.properties['_io_connections'] = []

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
        the first time it's requested.
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
        """Serialize to dictionary for saving."""
        props_copy = {k: v for k, v in self.properties.items() if k != '_io_connections'}
        
        serializable_props = {}
        for k, v in props_copy.items():
            # Coerce legacy string-typed values to their native types on save.
            # This heals old map files automatically on next save.
            if isinstance(v, str):
                try:
                    v = ast.literal_eval(v)
                except (ValueError, SyntaxError):
                    pass  # Genuinely a string — keep it
            
            if isinstance(v, (str, int, float, bool, list, dict, type(None))):
                serializable_props[k] = v
            else:
                serializable_props[k] = str(v)  # QColor etc.

        result = {
            'type': self.properties.get('type'),
            'pos': self.pos,
            'properties': serializable_props
        }

        # Always emit io_connections, even if empty, so loaders are unambiguous
        try:
            from .io_system import serialize_connections
            result['io_connections'] = serialize_connections(self)
        except ImportError:
            io_connections = self.properties.get('_io_connections', [])
            result['io_connections'] = [
                conn.to_dict() if hasattr(conn, 'to_dict') else conn
                for conn in io_connections
            ]

        return result

    @staticmethod
    def from_dict(data):
        """Deserialize from dictionary."""
        thing_type = data.get('type')
        if not thing_type:
            return None

        properties = data.get('properties', {})
        for key, value in properties.items():
            if isinstance(value, str):
                try:
                    properties[key] = ast.literal_eval(value)
                except (ValueError, SyntaxError):
                    pass

        thing = None
        for cls in find_subclasses(Thing):
            if cls.__name__.lower() == thing_type:
                thing = cls(pos=data.get('pos'), properties=properties)
                break
        
        if thing is None:
            if thing_type == 'thing':
                thing = Thing(pos=data.get('pos'), properties=properties)
            else:
                print(f"Warning: Unknown thing type '{thing_type}' found in map file.")
                return None
        
        io_data = data.get('io_connections', [])
        if io_data:
            try:
                from .io_system import OutputConnection
                connections = [OutputConnection.from_dict(d) for d in io_data]
                thing.properties['_io_connections'] = connections
            except ImportError:
                thing.properties['_io_connections'] = io_data
        
        return thing
    
    def add_output_connection(self, output_name, target_name, input_name, 
                               parameter="", delay=0.0, fire_once=False,
                               target_id=""):
        """Helper method to add an output connection."""
        try:
            from .io_system import OutputConnection, add_connection
            conn = OutputConnection(
                output_name=output_name,
                target_name=target_name,
                input_name=input_name,
                parameter=parameter,
                delay=delay,
                fire_once=fire_once,
                target_id=target_id
            )
            add_connection(self, conn)
            return conn
        except ImportError:
            if '_io_connections' not in self.properties:
                self.properties['_io_connections'] = []
            self.properties['_io_connections'].append({
                'output': output_name,
                'target': target_name,
                'target_id': target_id,
                'input': input_name,
                'parameter': parameter,
                'delay': delay,
                'fire_once': fire_once
            })
            return None
    
    def get_io_connections(self):
        """Get all I/O connections for this entity."""
        return self.properties.get('_io_connections', [])
    
    def clear_io_connections(self):
        """Clear all I/O connections."""
        self.properties['_io_connections'] = []

    def get_icon_pixmap(self):
        """Return a small pixmap (≈60×60) for 2D views."""
        pix = self.get_instance_pixmap()
        if pix is not None and not pix.isNull():
            return pix.scaled(60, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return None


# =============================================================================
# STANDARD THING SUBCLASSES
# =============================================================================

class PlayerStart(Thing):
    """Defines where the player spawns."""
    pixmap_path = "assets/sprites/player.png"
    
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'playerstart')
        self.properties.setdefault('angle', 0.0)

    def get_angle(self):
        return float(self.properties.get('angle', 0.0))


class Light(Thing):
    """Dynamic light source."""
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
    """Sound emitter entity."""
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
        self.properties.setdefault('state', 'off')

    def get_radius(self):
        return float(self.properties.get('radius', 512.0))


class Monster(Thing):
    """Enemy entity with subtypes (human, flying)."""
    pixmap_path = "assets/sprites/monsters/human/idle.png"   # fallback
    _subtype_sprites = {}  # cache keyed by full sprite path (includes dead/alive state)

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'monster')
        self.properties.setdefault('monster_type', 'human')  # 'human' or 'flying'
        self.properties.setdefault('id', 0)
        self.properties.setdefault('health', 100)
        self.properties.setdefault('damage', 10)

        # --- Wake / AI behaviour ---
        self.properties.setdefault('triggered', False)
        self.properties.setdefault('wake_on_sight', True)
        self.properties.setdefault('awake', False)

        # --- Set default sprite dimensions based on monster_type ---
        from engine.monster_constants import MONSTER_SPRITE_SIZES, MONSTER_SPRITE_SIZE_DEFAULT
        mtype = self.properties.get('monster_type', 'human')
        default_w, default_h = MONSTER_SPRITE_SIZES.get(mtype, MONSTER_SPRITE_SIZE_DEFAULT)
        self.properties.setdefault('sprite_width', default_w)
        self.properties.setdefault('sprite_height', default_h)

    @staticmethod
    def _resolve_sprite(custom_path: str, default_path: str, project_root: str) -> str:
        """
        Return *custom_path* when the file exists on disk, otherwise return
        *default_path*.  Falls back silently — the caller guarantees the
        default path is the safest possible choice.
        """
        if custom_path:
            if os.path.isfile(os.path.join(project_root, custom_path)):
                return custom_path
            print(f"[Monster] Custom sprite not found, using default: {custom_path}")
        return default_path

    def get_render_snapshot(self):
        """Return a lightweight dictionary snapshot for the renderer."""
        return {
            'pos': list(self.pos),                         # copy list
            'dead': self.properties.get('dead', False),
            'is_shooting': self.properties.get('is_shooting', False),
            'monster_type': self.properties.get('monster_type', 'human'),
            'sprite_width': self.properties.get('sprite_width', 128),
            'sprite_height': self.properties.get('sprite_height', 128),
            'custom_idle': self.properties.get('custom_idle', ''),
            'custom_shoot': self.properties.get('custom_shoot', ''),
            'custom_dead': self.properties.get('custom_dead', ''),
        }

    def get_sprite_path(self) -> str:
        """
        Return the sprite path for the current monster type and state.
        Priority: dead > shooting > idle.

        Custom sprites set via the Customise dialog are tried first.
        Any missing custom file is logged once and falls back to the
        appropriate default sprite for this monster_type automatically.
        """
        mtype       = self.properties.get('monster_type', 'human')
        is_dead     = self.properties.get('dead', False)
        is_shooting = self.properties.get('is_shooting', False)

        try:
            script_dir   = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
        except Exception:
            project_root = os.getcwd()

        default_idle  = f"assets/sprites/monsters/{mtype}/idle.png"
        default_dead  = f"assets/sprites/monsters/{mtype}/dead.png"
        default_shoot = f"assets/sprites/monsters/{mtype}/shoot.png"

        # Verify default dead/shoot files exist; fall back to idle if not
        if not os.path.isfile(os.path.join(project_root, default_dead)):
            default_dead = default_idle
        if not os.path.isfile(os.path.join(project_root, default_shoot)):
            default_shoot = default_idle

        if is_dead:
            return self._resolve_sprite(
                self.properties.get('custom_dead', ''), default_dead, project_root)
        elif is_shooting:
            return self._resolve_sprite(
                self.properties.get('custom_shoot', ''), default_shoot, project_root)
        else:
            return self._resolve_sprite(
                self.properties.get('custom_idle', ''), default_idle, project_root)

    def get_instance_pixmap(self):
        """
        Return the correct pixmap for the current alive/dead state.

        The cache is keyed by the full sprite path returned by get_sprite_path(),
        which already encodes both monster type AND state (idle vs dead).
        This means alive and dead sprites are cached independently, so setting
        'dead' = True on a monster that was previously rendered alive will
        correctly switch to dead.png on the next frame without a stale cache hit.
        """
        sprite_path = self.get_sprite_path()

        # Return from cache if available
        if sprite_path in Monster._subtype_sprites:
            return Monster._subtype_sprites[sprite_path]

        # Load from disk
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
            abs_path = os.path.join(project_root, sprite_path)
            if os.path.exists(abs_path):
                pixmap = QPixmap(abs_path)
                if not pixmap.isNull():
                    Monster._subtype_sprites[sprite_path] = pixmap
                    return pixmap
        except Exception:
            pass

        # Fallback: dark red square so death is still visually obvious
        if self.properties.get('dead', False):
            fallback = QPixmap(128, 128)
            fallback.fill(QColor(128, 0, 0))
            return fallback

        return super().get_instance_pixmap()

    def get_icon_pixmap(self):
        """Return a generic small monster icon for 2D views."""
        icon_path = "assets/sprites/monster.png"   # 60×60 icon
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
            abs_path = os.path.join(project_root, icon_path)
            if os.path.exists(abs_path):
                pix = QPixmap(abs_path)
                if not pix.isNull():
                    return pix
        except Exception:
            pass
        # Fallback: scale the full sprite down
        return super().get_icon_pixmap()

    @classmethod
    def clear_sprite_cache(cls):
        cls._subtype_sprites.clear()


class Pickup(Thing):
    """Collectible item entity."""
    pixmap_path = "assets/sprites/pickup.png"
    
    KEY_SPRITES = {
        'blue_key': 'assets/sprites/bluekey.png',
        'red_key': 'assets/sprites/redkey.png',
        'yellow_key': 'assets/sprites/yellowkey.png',
        'green_key': 'assets/sprites/greenkey.png',
    }
    
    GUN_SPRITES = {
        'gun1': 'assets/sprites/gun1.png',
        'gun2': 'assets/sprites/gun2.png'
    }
    
    _dynamic_sprite_cache = {}
    
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'pickup')
        self.properties.setdefault('item_type', 'health')
        self.properties.setdefault('value', 25)
        self.properties.setdefault('activation', 'walk_over')
        self.properties.setdefault('collected', False)
        self.properties.setdefault('respawns', False)
        self.properties.setdefault('respawn_time', 20.0)
        self.properties.setdefault('key_name', 'blue_key')
        self.properties.setdefault('custom_sprite', '')

    def is_gun(self):
        return self.properties.get('item_type') in ['gun1', 'gun2']
    
    def is_key(self):
        return self.properties.get('item_type') == 'key'
    
    def get_key_name(self):
        return self.properties.get('key_name', 'blue_key')
    
    def get_sprite_path(self):
        custom = self.properties.get('custom_sprite', '')
        if custom and not self.is_key() and not self.is_gun():
            return custom
        
        if self.is_key():
            key_name = self.get_key_name()
            return self.KEY_SPRITES.get(key_name, 'assets/sprites/pickup.png')
        
        item_type = self.properties.get('item_type')
        if item_type in self.GUN_SPRITES:
            return self.GUN_SPRITES[item_type]
        
        if custom:
            return custom
        
        return 'assets/sprites/pickup.png'
    
    def get_instance_pixmap(self):
        sprite_path = self.get_sprite_path()
        
        if sprite_path in Pickup._dynamic_sprite_cache:
            return Pickup._dynamic_sprite_cache[sprite_path]
        
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(script_dir, os.pardir))
        except NameError:
            project_root = os.path.abspath(os.path.join(os.getcwd()))
        
        if os.path.isabs(sprite_path):
            absolute_path = sprite_path
        else:
            absolute_path = os.path.join(project_root, sprite_path)
        
        pixmap = None
        if os.path.exists(absolute_path):
            loaded_pixmap = QPixmap(absolute_path)
            if not loaded_pixmap.isNull():
                custom = self.properties.get('custom_sprite', '')
                if custom and loaded_pixmap.width() != 75:
                    pixmap = loaded_pixmap.scaled(75, 75)
                else:
                    pixmap = loaded_pixmap
            else:
                print(f"Error: QPixmap failed to load sprite from {absolute_path}")
        else:
            print(f"Warning: Sprite file not found at: {absolute_path}")
            pixmap = Pickup.get_pixmap()
        
        Pickup._dynamic_sprite_cache[sprite_path] = pixmap
        return pixmap
    
    @classmethod
    def get_key_sprite_path(cls, key_name):
        return cls.KEY_SPRITES.get(key_name, 'assets/sprites/pickup.png')
    
    @classmethod
    def get_key_pixmap(cls, key_name):
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
        cls._dynamic_sprite_cache.clear()


class Trigger(Thing):
    """Non-visible trigger volume (for point-entity triggers)."""
    pixmap_path = None
    
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties.setdefault('type', 'trigger')
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


# =============================================================================
# LOGIC ENTITIES
# =============================================================================

class LogicRelay(Thing):
    """
    A relay that fires OnTrigger when its Trigger input is called.
    Can be enabled/disabled. Useful for creating reusable trigger chains.
    """
    pixmap_path = "assets/sprites/logic_relay.png"
    
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties['type'] = 'logic_relay'
        self.properties.setdefault('disabled', False)
        self.properties.setdefault('fire_once', False)
    
    def get_instance_pixmap(self):
        pix = super().get_instance_pixmap()
        if pix:
            return pix
        return LogicGate.get_pixmap()


class LogicGate(Thing):
    """
    Multi-input logic gate (AND, OR, XOR, NAND, NOR).
    Fires OnTrigger when gate condition is met.
    """
    pixmap_path = "assets/sprites/logic_gate.png"
    
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties['type'] = 'logic_gate'
        self.properties.setdefault('logic_type', 'AND')
        self.properties.setdefault('initial_state', 'off')

    def get_instance_pixmap(self):
        l_type = self.properties.get('logic_type', 'and').lower()
        expected_path = f"assets/sprites/logic_{l_type}.png"
        
        if expected_path in self._pixmap_cache:
            return self._pixmap_cache[expected_path]
            
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
            
        return super().get_instance_pixmap()


class LogicTimer(Thing):
    """
    Timer that fires OnTimer at a set interval.
    Can be enabled/disabled.
    """
    pixmap_path = "assets/sprites/logic_timer.png"
    
    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties['type'] = 'logic_timer'
        self.properties.setdefault('interval', 1.0)
        self.properties.setdefault('timer_enabled', False)
        self.properties.setdefault('start_on', False)
    
    def get_instance_pixmap(self):
        pix = super().get_instance_pixmap()
        if pix:
            return pix
        return LogicGate.get_pixmap()


class LevelChanger(Thing):
    """Entity that loads a new level when triggered."""
    pixmap_path = "assets/sprites/levelchanger.png"

    def __init__(self, pos=None, properties=None):
        super().__init__(pos, properties)
        self.properties['type'] = 'levelchanger'
        self.properties.setdefault('target_map', 'maps/Simple_Map_Test.json')
        self.properties.setdefault('delay', '0.0')
        self.properties.setdefault('fade_time', '0.5')
        self.properties.setdefault('show_radius', 'False')
        self.properties.setdefault('radius', '128.0')
        
        # Store direct reference to MainWindow for reliable level changing
        self._main_window = None
        try:
            from PyQt5.QtWidgets import QApplication
            for widget in QApplication.topLevelWidgets():
                if widget.__class__.__name__ == 'MainWindow':
                    self._main_window = widget
                    break
        except:
            pass

    def on_input(self, input_name: str, parameter: str = ""):
        """Called by I/O system and by ent_fire. Now literally simulates the working console command."""
        entity_name = self.properties.get('name', 'LevelChanger_2')
        map_name = (parameter or self.properties.get('target_map', '')).strip()

        print(f"[LevelChanger DEBUG] 🔥 on_input('{input_name}') called!")
        print(f"          entity  = {entity_name}")
        print(f"          parameter = '{parameter}'")
        print(f"          target_map property = '{self.properties.get('target_map', 'MISSING')}'")
        print(f"          final map name = '{map_name}'")

        if input_name == "ChangeLevel":
            return self.change_level(map_name)

        print(f"[LevelChanger] Unknown input '{input_name}'")
        return False

    def change_level(self, parameter: str = ""):
        """Load a new map when triggered."""

        target_map = parameter.strip() if parameter else self.properties.get('target_map', '').strip()

        if not target_map:
            print("ERROR: LevelChanger has no target_map and no parameter was provided!")
            return False

        if not target_map.lower().endswith('.json'):
            target_map += '.json'

        # ENFORCE MAPS FOLDER: Prepend maps/ if not already present
        if not (target_map.startswith('maps/') or target_map.startswith('maps\\')):
            target_map = f"maps/{target_map}"

        print(f"[LevelChanger] Target resolved → '{target_map}' "
            f"(I/O parameter='{parameter}', entity property='{self.properties.get('target_map')}')")

        # Get MainWindow reference
        main_window = getattr(self, '_main_window', None)

        if not main_window:
            try:
                from PyQt5.QtWidgets import QApplication
                for w in QApplication.topLevelWidgets():
                    if w.__class__.__name__ == 'MainWindow':
                        main_window = w
                        self._main_window = w
                        break
            except Exception as e:
                print(f"[LevelChanger] QApplication lookup failed: {e}")

        if not main_window:
            print("ERROR: Could not find MainWindow!")
            return False

        # Use signal instead of direct call
        if hasattr(main_window, 'load_level_signal'):
            try:
                print(f"[LevelChanger] Emitting load_level_signal('{target_map}')")
                main_window.load_level_signal.emit(target_map)
                print(f"[LevelChanger] SUCCESS: signal emitted")
                return True
            except Exception as e:
                print(f"ERROR emitting signal: {e}")
                import traceback
                traceback.print_exc()
                return False
        else:
            print("ERROR: MainWindow has no load_level_signal! Did you add it?")
            return False


# =============================================================================
# ENTITY REGISTRY
# =============================================================================

# All placeable entity types for the editor
ENTITY_TYPES = {
    'PlayerStart': PlayerStart,
    'Light': Light,
    'Speaker': Speaker,
    'Monster': Monster,
    'Pickup': Pickup,
    'Model': Model,
    'LogicRelay': LogicRelay,
    'LogicGate': LogicGate,
    'LogicTimer': LogicTimer,
    'LevelChanger': LevelChanger,
}

# Categories for editor UI
ENTITY_CATEGORIES = {
    'Gameplay': ['PlayerStart', 'Monster', 'Pickup', 'LevelChanger'],
    'Environment': ['Light', 'Speaker', 'Model'],
    'Logic': ['LogicRelay', 'LogicGate', 'LogicTimer'],
}