from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt
import os
import copy

class Thing:
    """Base class for all placeable objects in the editor."""
    def __init__(self, pos):
        self.pos = pos
        # Properties are used by the Properties Manager
        self.properties = {'x': pos[0], 'y': pos[1], 'z': pos[2]}
        self.name = "Thing"

    def update_from_properties(self):
        """Updates the thing's position from its properties dictionary."""
        self.pos[0] = self.properties.get('x', self.pos[0])
        self.pos[1] = self.properties.get('y', self.pos[1])
        self.pos[2] = self.properties.get('z', self.pos[2])

    def copy(self):
        """Creates a deep copy of the object for the undo/redo system."""
        return copy.deepcopy(self)

class PlayerStart(Thing):
    """Represents the player's starting position."""
    pixmap = None
    def __init__(self, pos):
        super().__init__(pos)
        self.name = "Player Start"
        if PlayerStart.pixmap is None:
            self.load_pixmap()

    def load_pixmap(self):
        """Loads the player start icon."""
        try:
            icon_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'player.png')
            if os.path.exists(icon_path):
                PlayerStart.pixmap = QPixmap(icon_path)
            else:
                print(f"Warning: Could not find player icon at {icon_path}")
                self.create_fallback_pixmap()
        except Exception as e:
            print(f"Error loading player icon: {e}")
            self.create_fallback_pixmap()

    def create_fallback_pixmap(self):
        """Creates a fallback magenta square if the icon is missing."""
        if PlayerStart.pixmap is None:
            fallback_image = QImage(32, 32, QImage.Format_ARGB32)
            fallback_image.fill(Qt.magenta)
            PlayerStart.pixmap = QPixmap.fromImage(fallback_image)


class Light(Thing):
    """Represents a light source."""
    pixmap = None
    
    def __init__(self, pos):
        super().__init__(pos)
        self.name = "Light"
        # Add light-specific properties
        self.properties.update({'r': 255, 'g': 255, 'b': 255, 'intensity': 1.0})
        
        if Light.pixmap is None:
            self.load_pixmap()

    def load_pixmap(self):
        """Loads the light icon."""
        try:
            icon_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'light.png')
            if os.path.exists(icon_path):
                Light.pixmap = QPixmap(icon_path)
            else:
                print(f"Warning: Could not find light icon at {icon_path}")
                self.create_fallback_pixmap()
        except Exception as e:
            print(f"Error loading light icon: {e}")
            self.create_fallback_pixmap()

    def create_fallback_pixmap(self):
        """Creates a fallback yellow square if the icon is missing."""
        if Light.pixmap is None:
            fallback_image = QImage(32, 32, QImage.Format_ARGB32)
            fallback_image.fill(Qt.yellow)
            Light.pixmap = QPixmap.fromImage(fallback_image)


    def get_color(self):
        """Returns the light color as an (r, g, b) tuple normalized to 0-1."""
        r = self.properties.get('r', 255) / 255.0
        g = self.properties.get('g', 255) / 255.0
        b = self.properties.get('b', 255) / 255.0
        return (r, g, b)