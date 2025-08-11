# editor/main_window.py
import sys
import json
import os
import subprocess
import random
import numpy as np
import configparser
import math
import copy
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QFileDialog, QWidget, QLabel, QVBoxLayout
)
from PyQt5.QtCore import Qt, QByteArray
from PyQt5.QtGui import QKeySequence, QPixmap

from editor.things import Light, PlayerStart, Thing, Pickup, Monster, Model
from editor.rand_map_gen_dial import RandomMapGeneratorDialog
from editor.rand_map_gen import generate
from editor.SettingsWindow import SettingsWindow
from editor.ui import Ui_MainWindow, GenerateTilemapDialog
from engine.constants import TILE_SIZE, WALL_TILE, FLOOR_TILE
from editor.view_2d import View2D
from editor.editor_state import EditorState

class MainWindow(QMainWindow):
    def __init__(self, root_dir):
        super().__init__()
        self.root_dir = root_dir
        self.setWindowTitle("RStudio")
        self.setGeometry(100, 100, 1600, 900)
        self.setMinimumSize(1200, 800)

        self.config = configparser.ConfigParser()
        self.config_path = 'settings.ini'
        self.load_config()

        self.state = EditorState()
        self.keys_pressed = set()
        self.file_path = None
        
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.setFocus()
        self.update_global_font()
        self.load_layout()

    def add_model_to_scene(self, filepath, rotation, scale):
        self.save_state()
        new_model = Model(pos=[0, 0, 0], model_path=filepath, rotation=rotation, scale=scale)
        self.state.things.append(new_model)
        self.set_selected_object(new_model)

    def set_selected_object(self, obj):
        self.state.set_selected_object(obj)
        if self.config.getboolean('Display', 'sync_selection', fallback=True):
            self.view_3d.selected_object = self.state.selected_object
        else:
            self.view_3d.selected_object = None
        self.update_all_ui()

    def update_all_ui(self):
        self.property_editor.set_object(self.state.selected_object)
        self.scene_hierarchy.refresh_list()
        self.update_views()

    def update_views(self):
        self.view_3d.update()
        self.view_top.reset_state()
        self.view_front.reset_state()
        self.view_side.reset_state()

    def update_scene_hierarchy(self):
        self.scene_hierarchy.refresh_list(self.state.brushes, self.state.things, self.state.selected_object)
    
    def select_object(self, obj):
        self.set_selected_object(obj)

    @staticmethod
    def _snap_to_power_of_two(n):
        if n <= 0: return 1
        power = round(math.log2(n))
        return int(2**power)

    def load_config(self):
        self.config.read(self.config_path)

    def save_config(self):
        with open(self.config_path, 'w') as configfile:
            self.config.write(configfile)

    def update_global_font(self):
        font_size = self.config.getint('Display', 'font_size', fallback=10)
        font = QApplication.font()
        font.setPointSize(font_size)
        QApplication.setFont(font)

    def show_settings_dialog(self):
        old_dpi_setting = self.config.getboolean('Display', 'high_dpi_scaling', fallback=False)
        old_font_size = self.config.getint('Display', 'font_size', fallback=10)
        old_show_caulk = self.config.getboolean('Display', 'show_caulk', fallback=True)

        dialog = SettingsWindow(self.config, self)
        if dialog.exec_():
            self.save_config()
            self.update_shortcuts()
            new_font_size = self.config.getint('Display', 'font_size', fallback=10)
            if old_font_size != new_font_size:
                self.update_global_font()
            new_show_caulk = self.config.getboolean('Display', 'show_caulk', fallback=True)
            if old_show_caulk != new_show_caulk:
                self.update_views()
            new_dpi_setting = self.config.getboolean('Display', 'high_dpi_scaling', fallback=False)
            if old_dpi_setting != new_dpi_setting:
                    QMessageBox.information(self, "Restart Required",
                                              "High DPI scaling setting has been changed.\nPlease restart the application for the change to take effect.")

    def apply_caulk_to_brush(self):
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "No Brush Selected", "Please select a brush to apply caulk to.")
            return
        self.save_state()
        if 'textures' not in self.state.selected_object:
            self.state.selected_object['textures'] = {}
        for face in ['north','south','east','west','top','down']:
            self.state.selected_object['textures'][face] = 'caulk.jpg'
        self.update_views()

    def apply_texture_to_brush(self):
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "No Brush Selected", "Please select a brush to apply the texture to.")
            return
        texture_path = self.asset_browser.get_selected_filepath()
        if not texture_path:
            QMessageBox.warning(self, "No Texture Selected", "Please select a texture from the Asset Browser.")
            return
        texture_name = os.path.basename(texture_path)
        self.save_state()
        if 'textures' not in self.state.selected_object:
            self.state.selected_object['textures'] = {}
        for face in ['south', 'north', 'west', 'east', 'down', 'top']:
            self.state.selected_object['textures'][face] = texture_name
        self.update_views()

    def apply_texture_to_selected_face(self, face_name):
        if not isinstance(self.state.selected_object, dict):
            return

        texture_path = self.asset_browser.get_selected_filepath()
        if not texture_path:
            QMessageBox.warning(self, "No Texture Selected", "Please select a texture from the Asset Browser.")
            return

        texture_name = os.path.basename(texture_path)
        self.save_state()
        
        if 'textures' not in self.state.selected_object:
            self.state.selected_object['textures'] = {}

        self.state.selected_object['textures'][face_name] = texture_name
        self.update_views()

    def generate_collision_map(self):
        if not self.state.brushes:
            return None

        min_x_world, max_x_world = float('inf'), float('-inf')
        min_z_world, max_z_world = float('inf'), float('-inf')

        solid_brushes_exist = False
        for brush in self.state.brushes:
            if not brush.get('is_trigger', False) and not brush.get('operation') == 'subtract':
                solid_brushes_exist = True
                pos, size = np.array(brush['pos']), np.array(brush['size'])
                half_size = size / 2.0

                min_x_world = min(min_x_world, pos[0] - half_size[0])
                max_x_world = max(max_x_world, pos[0] + half_size[0])
                min_z_world = min(min_z_world, pos[2] - half_size[2])
                max_z_world = max(max_z_world, pos[2] + half_size[2])

        if not solid_brushes_exist:
            return None

        padding = TILE_SIZE * 2
        padded_min_x = min_x_world - padding
        padded_max_x = max_x_world + padding
        padded_min_z = min_z_world - padding
        padded_max_z = max_z_world + padding

        min_x_tile_idx = int(math.floor(padded_min_x / TILE_SIZE))
        max_x_tile_idx = int(math.ceil(padded_max_x / TILE_SIZE))
        min_z_tile_idx = int(math.floor(padded_min_z / TILE_SIZE))
        max_z_tile_idx = int(math.ceil(padded_max_z / TILE_SIZE))

        map_width_tiles = max_x_tile_idx - min_x_tile_idx
        map_depth_tiles = max_z_tile_idx - min_z_tile_idx

        map_width_tiles = max(1, map_width_tiles)
        map_depth_tiles = max(1, map_depth_tiles)

        collision_tile_map = np.full((map_depth_tiles, map_width_tiles), FLOOR_TILE, dtype=int)

        for brush in self.state.brushes:
            if brush.get('is_trigger', False) or brush.get('operation') == 'subtract':
                continue

            pos, size = np.array(brush['pos']), np.array(brush['size'])
            half_size = size / 2.0

            brush_min_x_world = pos[0] - half_size[0]
            brush_max_x_world = pos[0] + half_size[0]
            brush_min_z_world = pos[2] - half_size[2]
            brush_max_z_world = pos[2] + half_size[2]

            brush_min_x_map_tile = int(math.floor(brush_min_x_world / TILE_SIZE) - min_x_tile_idx)
            brush_max_x_map_tile = int(math.ceil(brush_max_x_world / TILE_SIZE) - min_x_tile_idx)
            brush_min_z_map_tile = int(math.floor(brush_min_z_world / TILE_SIZE) - min_z_tile_idx)
            brush_max_z_map_tile = int(math.ceil(brush_max_z_world / TILE_SIZE) - min_z_tile_idx)

            min_x_idx_clamped = max(0, brush_min_x_map_tile)
            max_x_idx_clamped = min(map_width_tiles, brush_max_x_map_tile)
            min_z_idx_clamped = max(0, brush_min_z_map_tile)
            max_z_idx_clamped = min(map_depth_tiles, brush_max_z_map_tile)

            if min_x_idx_clamped < max_x_idx_clamped and min_z_idx_clamped < max_z_idx_clamped:
                collision_tile_map[min_z_idx_clamped:max_x_idx_clamped, min_x_idx_clamped:max_x_idx_clamped] = WALL_TILE

        return collision_tile_map


    def enter_play_mode(self):
        player_start = None
        for thing in self.state.things:
            if isinstance(thing, PlayerStart):
                player_start = thing
                break
        
        if not player_start:
            QMessageBox.warning(self, "No Player Start", "Please add a Player Start object to the scene before entering play mode.")
            return

        physics_enabled = self.config.getboolean('Settings', 'physics', fallback=True)
        self.view_3d.set_tile_map(None)
        self.view_3d.toggle_play_mode(player_start.pos, player_start.get_angle(), physics_enabled)
        self.view_3d.setFocus() # Explicitly set focus to the 3D view


    def show_generate_tilemap_dialog(self):
        if not self.file_path:
            self.save_level_as()
            if not self.file_path:
                QMessageBox.warning(self, "File Not Saved", "Please save the level before generating a tilemap.")
                return
        self.generate_and_save_tilemap(save_png=True)


    def generate_and_save_tilemap(self, save_png=False):
        self.save_level()

        generator_script_path = os.path.join(self.root_dir, 'tools', 'generate_tilemap.py')
        if not os.path.exists(generator_script_path):
            QMessageBox.critical(self, "Error", f"Tilemap generator script not found at:\n{generator_script_path}")
            return

        try:
            command = [sys.executable, generator_script_path, self.file_path]
            if save_png:
                command.append('--save-png')
            
            subprocess.run(command, check=True)
            QMessageBox.information(self, "Success", "Collision tilemap generated successfully.")
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "Error", f"Failed to generate tilemap.\n\nError: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An unexpected error occurred:\n{e}")

    def update_shortcuts(self):
        apply_texture_shortcut = self.config.get('Controls', 'apply_texture', fallback='Shift+T')
        self.apply_texture_action.setShortcut(QKeySequence(apply_texture_shortcut))
        reset_layout_shortcut = self.config.get('Controls', 'reset_layout', fallback='Ctrl+Shift+R')
        self.reset_layout_action.setShortcut(QKeySequence(reset_layout_shortcut))
        save_layout_shortcut = self.config.get('Controls', 'save_layout', fallback='Ctrl+Shift+S')
        self.save_layout_action.setShortcut(QKeySequence(save_layout_shortcut))

    def toggle_culling(self, state):
        self.view_3d.set_culling(state == Qt.Checked)

    def set_grid_size(self, size):
        snapped_size = self._snap_to_power_of_two(size)
        if snapped_size != size:
            self.grid_size_spinbox.blockSignals(True)
            self.grid_size_spinbox.setValue(snapped_size)
            self.grid_size_spinbox.blockSignals(False)
            return
        for view in [self.view_top, self.view_side, self.view_front, self.view_3d]:
            view.grid_size = snapped_size
        self.view_3d.update_grid()
        self.update_views()

    def set_world_size(self, size):
        snapped_size = self._snap_to_power_of_two(size)
        if snapped_size != size:
            self.world_size_spinbox.blockSignals(True)
            self.world_size_spinbox.setValue(snapped_size)
            self.world_size_spinbox.blockSignals(False)
            return
        for view in [self.view_top, self.view_side, self.view_front, self.view_3d]:
            view.world_size = snapped_size
        self.view_3d.update_grid()
        self.update_views()

    def set_brush_display_mode(self, text):
        self.view_3d.brush_display_mode = text
        self.view_3d.update()

    def zoom_in_2d(self):
        current_view = self.right_tabs.currentWidget()
        if isinstance(current_view, View2D):
            current_view.zoom_in()

    def zoom_out_2d(self):
        current_view = self.right_tabs.currentWidget()
        if isinstance(current_view, View2D):
            current_view.zoom_out()

    def save_state(self):
        self.state.save_state()

    def undo(self):
        if self.state.undo():
            self.update_all_ui()

    def redo(self):
        if self.state.redo():
            self.update_all_ui()

    def set_render_mode(self, mode):
        self.view_3d.render_mode = mode
        self.update_views()

    def show_about(self):
        try:
            with open('editor/version.txt', 'r') as f:
                version = f.read().strip()
        except FileNotFoundError:
            version = "Version not found"

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("About RStudio")
        
        container_widget = QWidget()
        layout = QVBoxLayout(container_widget)

        splash_label = QLabel()
        pixmap = QPixmap('assets/splash.png')
        splash_label.setPixmap(pixmap.scaled(512, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(splash_label)

        version_label = QLabel(f"{version}<br>https://github.com/ViciousSquid/RStudio")
        version_label.setTextFormat(Qt.RichText)
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setOpenExternalLinks(True)
        layout.addWidget(version_label)
        
        msg_box.layout().addWidget(container_widget, 0, 0, 1, msg_box.layout().columnCount())
        
        msg_box.setStandardButtons(QMessageBox.Ok)

        msg_box.exec_()

    def new_map(self):
        self.state.clear_scene()
        self.file_path = None
        self.update_all_ui()

    def show_random_map_dialog(self):
        dialog = RandomMapGeneratorDialog(self)
        if dialog.exec_():
            params = dialog.get_parameters()
            map_grid = generate(method=params['style'], width=params['width'], height=params['length'], seed=params.get('seed'))
            brushes, things = self.convert_grid_to_level(map_grid)
            self.state.brushes = brushes
            self.state.things = things
            self.view_3d.camera.pos = [0, 150, 400]
            self.set_selected_object(None)
            self.save_state()
            self.update_all_ui()

    def convert_grid_to_level(self, grid, cell_size=128, wall_height=128):
        if not isinstance(grid, np.ndarray):
            print("Error: Invalid grid.")
            return [], []

        brushes, things, floor_locations = [], [], []
        grid_height, grid_width = grid.shape

        total_width = grid_width * cell_size
        total_height = grid_height * cell_size
        brushes.append({
            'pos': [total_width / 2 - cell_size/2, wall_height / 2, total_height / 2 - cell_size/2],
            'size': [total_width, wall_height, total_height],
            'operation': 'subtract',
            'textures': {f: 'assets/textures/default.png' for f in ['north','south','east','west','top','down']}
        })

        for r in range(grid_height):
            for c in range(grid_width):
                pos_x, pos_y, pos_z = c * cell_size, wall_height / 2, r * cell_size
                if grid[r, c] == 0:
                    brushes.append({
                        'pos': [pos_x, pos_y, pos_z],
                        'size': [cell_size, wall_height, cell_size],
                        'operation': 'add',
                        'textures': {f: 'assets/textures/default.png' for f in ['north','south','east','west','top','down']}
                    })
                else:
                    floor_locations.append((pos_x, pos_y, pos_z))

        if floor_locations:
            player_pos = floor_locations[0]
            things.append(PlayerStart(pos=[player_pos[0], 40, player_pos[2]]))
            for _ in range(max(1, len(floor_locations) // 25)):
                light_pos = random.choice(floor_locations)
                things.append(Light(pos=[light_pos[0], wall_height - 40, light_pos[2]]))
        else:
            print("Warning: No floor space generated.")

        return brushes, things

    def perform_subtraction(self):
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "Invalid Selection", "Please select a brush to make it subtractive.")
            return

        self.save_state()
        
        self.state.selected_object['operation'] = 'subtract'
        subtract_brush = self.state.selected_object
        
        sub_pos = subtract_brush['pos']
        sub_size = subtract_brush['size']
        sub_min = [sub_pos[0] - sub_size[0]/2, sub_pos[1] - sub_size[1]/2, sub_pos[2] - sub_size[2]/2]
        sub_max = [sub_pos[0] + sub_size[0]/2, sub_pos[1] + sub_size[1]/2, sub_pos[2] + sub_size[2]/2]
        
        new_brushes = []
        for brush in self.state.brushes:
            if brush is subtract_brush:
                continue
                
            if brush.get('operation') == 'subtract':
                new_brushes.append(brush)
                continue
                
            pos = brush['pos']
            size = brush['size']
            brush_min = [pos[0] - size[0]/2, pos[1] - size[1]/2, pos[2] - size[2]/2]
            brush_max = [pos[0] + size[0]/2, pos[1] + size[1]/2, pos[2] + size[2]/2]
            
            if not (brush_min[0] < sub_max[0] and brush_max[0] > sub_min[0] and
                    brush_min[1] < sub_max[1] and brush_max[1] > sub_min[1] and
                    brush_min[2] < sub_max[2] and brush_max[2] > sub_min[2]):
                new_brushes.append(brush)
                continue
                
            fragments = []
            
            if brush_min[0] < sub_min[0]:
                left_max = min(brush_max[0], sub_min[0])
                if left_max - brush_min[0] > 0.01:
                    fragments.append({
                        'pos': [(brush_min[0] + left_max)/2, pos[1], pos[2]],
                        'size': [left_max - brush_min[0], size[1], size[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_max[0] > sub_max[0]:
                right_min = max(brush_min[0], sub_max[0])
                if brush_max[0] - right_min > 0.01:
                    fragments.append({
                        'pos': [(right_min + brush_max[0])/2, pos[1], pos[2]],
                        'size': [brush_max[0] - right_min, size[1], size[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_min[1] < sub_min[1]:
                bottom_max = min(brush_max[1], sub_min[1])
                x_min = max(brush_min[0], sub_min[0])
                x_max = min(brush_max[0], sub_max[0])
                if bottom_max - brush_min[1] > 0.01 and x_max - x_min > 0.01:
                    fragments.append({
                        'pos': [pos[0], (brush_min[1] + bottom_max)/2, pos[2]],
                        'size': [x_max - x_min, bottom_max - brush_min[1], size[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_max[1] > sub_max[1]:
                top_min = max(brush_min[1], sub_max[1])
                x_min = max(brush_min[0], sub_min[0])
                x_max = min(brush_max[0], sub_max[0])
                if brush_max[1] - top_min > 0.01 and x_max - x_min > 0.01:
                    fragments.append({
                        'pos': [pos[0], (top_min + brush_max[1])/2, pos[2]],
                        'size': [x_max - x_min, brush_max[1] - top_min, size[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_min[2] < sub_min[2]:
                front_max = min(brush_max[2], sub_min[2])
                x_min = max(brush_min[0], sub_min[0])
                x_max = min(brush_max[0], sub_max[0])
                y_min = max(brush_min[1], sub_min[1])
                y_max = min(brush_max[1], sub_max[1])
                if front_max - brush_min[2] > 0.01 and x_max - x_min > 0.01 and y_max - y_min > 0.01:
                    fragments.append({
                        'pos': [pos[0], pos[1], (brush_min[2] + front_max)/2],
                        'size': [x_max - x_min, y_max - y_min, front_max - brush_min[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_max[2] > sub_max[2]:
                back_min = max(brush_min[2], sub_max[2])
                x_min = max(brush_min[0], sub_min[0])
                x_max = min(brush_max[0], sub_max[0])
                y_min = max(brush_min[1], sub_min[1])
                y_max = min(brush_max[1], sub_max[1])
                if brush_max[2] - back_min > 0.01 and x_max - x_min > 0.01 and y_max - y_min > 0.01:
                    fragments.append({
                        'pos': [pos[0], pos[1], (back_min + brush_max[2])/2],
                        'size': [x_max - x_min, y_max - y_min, brush_max[2] - back_min],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            new_brushes.extend(fragments)
        
        new_brushes.append(subtract_brush)
        self.state.brushes = new_brushes
        
        self.update_all_ui()

    def rotate_selected_brush(self):
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "Invalid Selection", "Please select a brush to rotate.")
            return

        current_view = self.right_tabs.currentWidget()
        if not isinstance(current_view, View2D):
            QMessageBox.warning(self, "Invalid View", "Please select a 2D view (Top, Side, or Front) to define the rotation axis.")
            return

        self.save_state()
        size = self.state.selected_object['size']
        view_type = current_view.view_type

        if view_type == 'top':
            size[0], size[2] = size[2], size[0]
        elif view_type == 'side':
            size[1], size[2] = size[2], size[1]
        elif view_type == 'front':
            size[0], size[1] = size[1], size[0]

        self.update_all_ui()

    def toggle_trigger_display(self, checked):
        self.view_3d.show_triggers_as_solid = checked
        self.view_3d.update()

    def keyPressEvent(self, event):
        if self.view_3d.play_mode:
            if event.key() == Qt.Key_Escape:
                self.view_3d.toggle_play_mode(None, None)
                self.setFocus() # Give focus back to the main window
            elif event.key() == Qt.Key_F3:
                self.view_3d.show_sprites_in_play_mode = not self.view_3d.show_sprites_in_play_mode
                self.view_3d.update()
            else:
                self.keys_pressed.add(event.key())
            return # Consume the event completely in play mode

        # Editor mode key presses below
        if self.state.selected_object:
            if event.key() == Qt.Key_Delete:
                self.save_state()
                if isinstance(self.state.selected_object, dict):
                    self.state.brushes.remove(self.state.selected_object)
                else:
                    self.state.things.remove(self.state.selected_object)
                self.set_selected_object(None)
                return

            if event.key() == Qt.Key_H:
                if event.modifiers() == Qt.ShiftModifier:
                    self.unhide_all_brushes()
                elif isinstance(self.state.selected_object, dict):
                    self.hide_selected_brush()
                return

            if event.key() == Qt.Key_Space:
                self.save_state()
                if isinstance(self.state.selected_object, dict):
                    new_obj = copy.deepcopy(self.state.selected_object)
                    self.state.brushes.append(new_obj)
                else:
                    new_obj = copy.copy(self.state.selected_object)
                    self.state.things.append(new_obj)

                current_view = self.right_tabs.currentWidget()
                if isinstance(current_view, View2D):
                    axis_map = {'top': ('x', 'z'), 'side': ('y', 'z'), 'front': ('x', 'y')}
                    pos_map = {'x': 0, 'y': 1, 'z': 2}
                    ax1_name, ax2_name = axis_map.get(current_view.view_type, ('x', 'z'))
                    offset = self.grid_size_spinbox.value()
                    pos_ref = new_obj['pos'] if isinstance(new_obj, dict) else new_obj.pos
                    pos_ref[pos_map[ax1_name]] += offset
                    pos_ref[pos_map[ax2_name]] += offset

                self.set_selected_object(new_obj)
                return

        if event.key() == Qt.Key_Escape and self.state.selected_object:
            self.set_selected_object(None)
            return

        self.keys_pressed.add(event.key())
        super().keyPressEvent(event)

    def hide_selected_brush(self):
        if isinstance(self.state.selected_object, dict):
            self.save_state()
            self.state.selected_object['hidden'] = True
            self.update_all_ui()

    def unhide_all_brushes(self):
        self.save_state()
        for brush in self.state.brushes:
            if 'hidden' in brush:
                brush['hidden'] = False
        self.update_all_ui()

    def keyReleaseEvent(self, event):
        if self.view_3d.play_mode:
            if event.key() in self.keys_pressed:
                self.keys_pressed.remove(event.key())
            return # Consume the event completely in play mode

        # Editor mode key releases below
        if event.key() in self.keys_pressed:
            self.keys_pressed.remove(event.key())
        self.update_views()
        super().keyReleaseEvent(event)

    def toggle_snap_to_grid(self, state):
        enabled = state == Qt.Checked
        for view in [self.view_top, self.view_side, self.view_front]:
            view.snap_to_grid_enabled = enabled

    def save_level_as(self):
        filePath, _ = QFileDialog.getSaveFileName(self, "Save Level As", "maps", "JSON Files (*.json)")
        if filePath:
            self.file_path = filePath
            self.save_level()

    def save_level(self):
        if not self.file_path:
            self.save_level_as()
            return
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.state.get_level_data(), f, indent=4)
            print(f"Level saved to {self.file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save level to {self.file_path}:\n{e}")

    def load_level(self):
        filePath, _ = QFileDialog.getOpenFileName(self, "Load Level", "maps", "JSON Files (*.json)")
        if not filePath:
            return

        try:
            with open(filePath, 'r') as f:
                level_data = json.load(f)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not load level from {filePath}:\n{e}")
            return

        self.state.load_from_data(level_data)

        player_start_pos = None
        for t in self.state.things:
            if isinstance(t, PlayerStart):
                player_start_pos = t.pos
                break

        if player_start_pos:
            self.view_3d.camera.pos = [player_start_pos[0], player_start_pos[1] + 50, player_start_pos[2] + 200]
            self.view_3d.camera.pitch = -15
            self.view_3d.camera.yaw = -90

        self.file_path = filePath
        self.set_selected_object(None)
        print(f"Level loaded from {filePath}")

    def quicksave_and_launch(self):
        maps_dir = "maps"
        if not os.path.exists(maps_dir):
            os.makedirs(maps_dir)

        quicksave_path = os.path.join(maps_dir, "quick_save.json")
        try:
            with open(quicksave_path, 'w') as f:
                json.dump(self.state.get_level_data(), f, indent=4)
            print(f"Quicksave successful: {quicksave_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not quicksave level:\n{e}")
            return

        game_script_path = 'game.py'
        if not os.path.exists(game_script_path):
            QMessageBox.warning(self, "Warning", f"Could not find '{game_script_path}' to launch.")
            return
        try:
            subprocess.Popen([sys.executable, game_script_path, quicksave_path])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not launch game:\n{e}")
            
    def save_layout(self):
        if not self.config.has_section('Layout'):
            self.config.add_section('Layout')
        self.config['Layout']['geometry'] = self.saveGeometry().toHex().data().decode()
        self.config['Layout']['state'] = self.saveState().toHex().data().decode()
        self.save_config()
        self.statusBar().showMessage("Layout saved.", 2000)

    def load_layout(self):
        if self.config.has_section('Layout') and self.config.has_option('Layout', 'geometry'):
            self.restoreGeometry(QByteArray.fromHex(self.config['Layout']['geometry'].encode()))
        if self.config.has_section('Layout') and self.config.has_option('Layout', 'state'):
            self.restoreState(QByteArray.fromHex(self.config['Layout']['state'].encode()))

    def reset_layout(self):
        self.scene_hierarchy_dock.setFloating(False)
        self.view_3d_dock.setFloating(False)
        self.right_dock.setFloating(False)
        self.properties_dock.setFloating(False)
        self.asset_browser_dock.setFloating(True)
        
        self.addDockWidget(Qt.LeftDockWidgetArea, self.scene_hierarchy_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.view_3d_dock)
        self.splitDockWidget(self.view_3d_dock, self.right_dock, Qt.Horizontal)
        self.splitDockWidget(self.right_dock, self.properties_dock, Qt.Vertical)
        
        self.resizeDocks([self.view_3d_dock, self.right_dock], [800, 600], Qt.Horizontal)
        self.resizeDocks([self.right_dock, self.properties_dock], [600, 300], Qt.Vertical)
        self.statusBar().showMessage("Layout reset to default.", 2000)

    def closeEvent(self, event):
        self.save_layout()
        super().closeEvent(event)