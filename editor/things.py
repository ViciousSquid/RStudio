from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt
import os

class Thing:
    """Base class for all placeable objects in the editor."""
    def __init__(self, pos):
        self.pos = pos
        # Properties are used by the Properties Manager
        self.properties = {'x': pos[0], 'y': pos[1], 'z': pos[2]}
        self.name = "Thing"

    def update_from_properties(self):
        """Updates the thing's position from its properties dictionary."""
        self.pos[0] = self.properties.get('x', 0)
        self.pos[1] = self.properties.get('y', 0)
        self.pos[2] = self.properties.get('z', 0)

class PlayerStart(Thing):
    """Represents the player's starting position."""
    def __init__(self, pos):
        super().__init__(pos)
        self.name = "Player Start"

class Light(Thing):
    """Represents a light source."""
    # Class-level pixmap to avoid loading the image repeatedly
    pixmap = None
    
    def __init__(self, pos):
        super().__init__(pos)
        self.name = "Light"
        # Add light-specific properties
        self.properties.update({'r': 255, 'g': 255, 'b': 255, 'intensity': 1.0})
        
        # Load the light icon only once
        if Light.pixmap is None:
            # Construct the path relative to this file's location
            icon_path = os.path.join(os.path.dirname(__file__), '..', 'assets', 'light.png')
            if os.path.exists(icon_path):
                Light.pixmap = QPixmap(icon_path)
            else:
                print(f"Warning: Could not find light icon at {icon_path}")
                # Create a fallback yellow square if the icon is missing
                fallback_image = QImage(42, 42, QImage.Format_ARGB32)
                fallback_image.fill(Qt.yellow)
                Light.pixmap = QPixmap.fromImage(fallback_image)

    def get_color(self):
        """Returns the light color as an (r, g, b) tuple."""
        return (self.properties.get('r', 255), self.properties.get('g', 255), self.properties.get('b', 255))