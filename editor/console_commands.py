import os
import json
from PyQt5.QtWidgets import QMessageBox

from editor.debug_console import debug_log

class ConsoleCommandHandler:
    """
    Handles commands typed into the debug console.
    """
    def __init__(self, main_window):
        self.main_window = main_window
        self.commands = {
            'noclip': self.cmd_noclip,
            'clear': self.cmd_clear,
            'fps': self.cmd_fps,
            'map': self.cmd_map,
            # Add new commands here
        }

    def handle_command(self, cmd_string):
        """
        Parse and execute a console command.
        """
        parts = cmd_string.strip().split()
        if not parts:
            return
        cmd = parts[0].lower()
        args = parts[1:]

        handler = self.commands.get(cmd)
        if handler:
            handler(args)
        else:
            debug_log("Error", f"Unknown command: {cmd}")

    # --------------------------------------------------------------
    # Command implementations
    # --------------------------------------------------------------

    def cmd_noclip(self, args):
        view_3d = self.main_window.view_3d
        if view_3d.play_mode and getattr(view_3d, 'player', None):
            view_3d.player.physics_enabled = not view_3d.player.physics_enabled
            state = "OFF" if not view_3d.player.physics_enabled else "ON"
            self.main_window.show_toast(f"Noclip: {state}")
            debug_log("Info", f"Noclip {'enabled' if not view_3d.player.physics_enabled else 'disabled'}")
        else:
            debug_log("Warning", "Noclip is only available in Play Mode.")

    def cmd_clear(self, args):
        self.main_window.debug_console.clear()

    def cmd_fps(self, args):
        config = self.main_window.config
        show = not config.getboolean('Display', 'show_fps', fallback=False)
        if not config.has_section('Display'):
            config.add_section('Display')
        config.set('Display', 'show_fps', str(show))
        if hasattr(self.main_window, 'show_fps_checkbox'):
            self.main_window.show_fps_checkbox.setChecked(show)
        self.main_window.save_config()
        self.main_window.view_3d.update()
        debug_log("Info", f"FPS display {'ON' if show else 'OFF'}")

    def cmd_map(self, args):
        if not args:
            debug_log("Warning", "Usage: map <mapname>")
            return
        map_name = args[0]
        if not map_name.endswith('.json'):
            map_name += '.json'
        map_path = os.path.join(self.main_window.root_dir, 'maps', map_name)
        if os.path.exists(map_path):
            self.main_window.load_level_file(map_path)
            debug_log("Info", f"Loaded map {map_name}")
        else:
            debug_log("Error", f"Map not found: {map_name}")