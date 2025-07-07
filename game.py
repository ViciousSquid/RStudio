import sys
import json
from PyQt5.QtWidgets import QApplication, QMainWindow
from PyQt5.QtCore import Qt
from engine.qt_game_view import QtGameView
from editor.things import Light, PlayerStart

class GameWindow(QMainWindow):
    def __init__(self, level_file):
        super().__init__()
        self.setWindowTitle("Game")
        self.setGeometry(100, 100, 1280, 720)

        # The GameWindow needs attributes that the QtGameView expects.
        self.brushes = []
        self.things = []
        self.selected_object = None
        self.keys_pressed = set() # Add the missing attribute

        # The game view will be the main widget
        self.game_view = QtGameView(self)
        self.setCentralWidget(self.game_view)

        # Load the level data
        self.load_level(level_file)

    def keyPressEvent(self, event):
        """Track pressed keys for the game view."""
        self.keys_pressed.add(event.key())
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Track released keys for the game view."""
        if not event.isAutoRepeat():
            self.keys_pressed.discard(event.key())
        super().keyReleaseEvent(event)

    def load_level(self, file_path):
        try:
            with open(file_path, 'r') as f:
                level_data = json.load(f)
        except FileNotFoundError:
            print(f"Error: Level file not found at {file_path}")
            return
        except json.JSONDecodeError:
            print(f"Error: Could not decode JSON from {file_path}")
            return

        self.brushes = level_data.get('brushes', [])
        
        self.things = []
        player_start_pos = [0, 50, 0]
        for thing_data in level_data.get('things', []):
            name = thing_data.get('name')
            pos = thing_data.get('pos', [0,0,0])

            if name == "Light":
                self.things.append(Light(pos))
            elif name == "Player Start":
                player_start = PlayerStart(pos)
                self.things.append(player_start)
                player_start_pos = player_start.pos

        # Position the camera at the player start, slightly above
        self.game_view.camera.pos = [player_start_pos[0], player_start_pos[1] + 20, player_start_pos[2]]
        print("Level loaded. Player spawned.")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python game.py <path_to_level.json>")
        sys.exit(1)

    app = QApplication(sys.argv)
    level_file = sys.argv[1]
    window = GameWindow(level_file)
    window.show()
    sys.exit(app.exec_())