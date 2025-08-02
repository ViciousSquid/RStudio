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
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStatusBar,
    QToolBar,
    QLabel,
    QSpinBox,
    QCheckBox,
    QComboBox,
    QAction,
    QMessageBox,
    QFrame,
    QDockWidget,
    QTabWidget,
    QFileDialog,
    QPushButton,
    QActionGroup
)
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtGui import QFont, QIcon, QKeySequence
from editor.view_2d import View2D
from engine.qt_game_view import QtGameView
from editor.things import Light, PlayerStart, Thing, Pickup, Monster
from editor.property_editor import PropertyEditor
from editor.rand_map_gen_dial import RandomMapGeneratorDialog
from editor.rand_map_gen import generate
from editor.asset_browser import AssetBrowser
from editor.SettingsWindow import SettingsWindow
from editor.scene_hierarchy import SceneHierarchy

# --- PLACEHOLDER MODEL CLASS ---
# TODO: This class should be moved to your 'editor/things.py' file and expanded upon.
class Model(Thing):
    """Represents a 3D model placed in the world."""
    def __init__(self, pos=[0,0,0], model_path="", rotation=[0,0,0], scale=[1,1,1]):
        super().__init__(pos)
        self.type = 'Model'
        self.model_path = model_path
        self.rotation = rotation
        self.scale = scale

    def to_dict(self):
        # Extends the base Thing's dictionary representation
        data = super().to_dict()
        data.update({
            'model_path': self.model_path,
            'rotation': self.rotation,
            'scale': self.scale
        })
        return data

class MainWindow(QMainWindow):
    def __init__(self, root_dir): # MODIFICATION: Accept the application's root directory
        super().__init__()
        self.root_dir = root_dir # MODIFICATION: Store the root directory
        self.setWindowTitle("RStudio")
        self.setGeometry(100, 100, 1600, 900)
        self.setMinimumSize(1200, 800)

        # --- Config Management ---
        self.config = configparser.ConfigParser()
        self.config_path = 'settings.ini'
        self.load_config()

        self.brushes = []
        self.things = []
        self.selected_object = None
        self.keys_pressed = set()
        self.file_path = None

        self.undo_stack = []
        self.redo_stack = []

        # --- Create UI Components FIRST ---
        self.view_3d = QtGameView(self)
        self.view_3d.show_triggers_as_solid = True 
        
        self.view_top = View2D(self, self, "top")
        self.view_side = View2D(self, self, "side")
        self.view_front = View2D(self, self, "front")
        self.property_editor = PropertyEditor(self)
        self.scene_hierarchy = SceneHierarchy(self)

        # --- Create and Arrange Docks ---
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)

        self.scene_hierarchy_dock = QDockWidget("Scene", self)
        self.scene_hierarchy_dock.setWidget(self.scene_hierarchy)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.scene_hierarchy_dock)
        
        screen_width = QApplication.primaryScreen().geometry().width()
        self.scene_hierarchy_dock.setMaximumWidth(int(screen_width * 0.10))

        self.view_3d_dock = QDockWidget("3D View", self)
        self.view_3d_dock.setWidget(self.view_3d)
        self.addDockWidget(Qt.RightDockWidgetArea, self.view_3d_dock)

        self.right_dock = QDockWidget("2D Views", self)
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.view_top, "Top")
        self.right_tabs.addTab(self.view_side, "Side")
        self.right_tabs.addTab(self.view_front, "Front")
        self.right_dock.setWidget(self.right_tabs)
        self.addDockWidget(Qt.RightDockWidgetArea, self.right_dock)
        
        self.properties_dock = QDockWidget("Properties", self)
        self.properties_dock.setWidget(self.property_editor)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)

        self.splitDockWidget(self.view_3d_dock, self.right_dock, Qt.Horizontal)
        self.splitDockWidget(self.right_dock, self.properties_dock, Qt.Vertical)

        self.resizeDocks([self.view_3d_dock, self.right_dock], [800, 600], Qt.Horizontal)
        self.resizeDocks([self.right_dock, self.properties_dock], [600, 300], Qt.Vertical)

        self.right_tabs.setStyleSheet("""
            QTabBar::tab:selected { background: #0078d7; color: white; }
            QTabBar::tab { background: #444; color: #ccc; padding: 5px; border: 1px solid #222; }
        """)

        corner_widget = QWidget()
        corner_layout = QHBoxLayout(corner_widget)
        corner_layout.setContentsMargins(0, 0, 0, 0)
        subtract_button = QPushButton("Subtract")
        subtract_button.setToolTip("Mark the selected brush as subtractive")
        subtract_button.setStyleSheet("background-color: orange; padding: 2px 8px; color: black;")
        subtract_button.clicked.connect(self.perform_subtraction)
        corner_layout.addWidget(subtract_button)
        self.right_tabs.setCornerWidget(corner_widget, Qt.TopRightCorner)
        
               # Asset Browser Setup
        self.asset_browser_dock = QDockWidget("Asset Browser", self)
        self.asset_browser = AssetBrowser(self.root_dir, self)
        self.asset_browser_dock.setWidget(self.asset_browser)
        self.asset_browser_dock.setAllowedAreas(Qt.NoDockWidgetArea)
        self.asset_browser_dock.setFloating(True)
        self.asset_browser_dock.setVisible(False)
        
        # Set initial size and center position
        initial_width = 1280
        initial_height = 600
        self.asset_browser_dock.resize(initial_width, initial_height)
        
        # Calculate centered position relative to main window
        main_window_center = self.geometry().center()
        self.asset_browser_dock.move(
            main_window_center.x() - initial_width // 2,
            main_window_center.y() - initial_height // 2
        )
        
        # Add toggle action to view menu (will be connected in create_menu_bar)
        self.asset_browser_toggle_action = self.asset_browser_dock.toggleViewAction()
        self.asset_browser_toggle_action.setText("Toggle Asset Browser")
        self.asset_browser_toggle_action.setShortcut("Ctrl+T")
        
        self.create_menu_bar()
        self.create_toolbars()
        self.create_status_bar()

        self.setFocus()
        self.update_global_font()
        self.save_state()

    # --- NEW METHOD TO ADD MODELS TO THE SCENE ---
    def add_model_to_scene(self, filepath, rotation, scale):
        """Creates a new Model 'thing' and adds it to the scene data."""
        self.save_state()  # For undo functionality
        
        # Create the new model instance at the origin with the specified transform
        new_model = Model(pos=[0, 0, 0], model_path=filepath, rotation=rotation, scale=scale)
        self.things.append(new_model)
        
        # Select the new model so it can be immediately manipulated
        self.set_selected_object(new_model)
        
        QMessageBox.information(self, "Model Added", 
            f"'{os.path.basename(filepath)}' has been added to the scene.\n\n"
            "You can now use the 2D views or the property editor to position it.\n"
            "A 3D transform gizmo in the 3D view is the next step for direct manipulation.")

    # --- CORE UI UPDATE LOGIC (MODIFIED) ---
    def set_selected_object(self, obj):
        """Sets the currently selected object and triggers a full UI refresh."""
        self.selected_object = obj
        self.update_all_ui()

    def update_all_ui(self):
        """
        Updates all UI components to reflect the current state.
        This is the single source of truth for all UI refreshes.
        """
        self.property_editor.set_object(self.selected_object)
        self.update_scene_hierarchy()
        self.update_views()

    def update_views(self):
        """Forces all 2D and 3D views to repaint and reset state."""
        self.view_3d.update()
        self.view_top.reset_state()
        self.view_front.reset_state()
        self.view_side.reset_state()

    def update_scene_hierarchy(self):
        """
        Refreshes the scene list with all current items.
        """
        self.scene_hierarchy.refresh_list(self.brushes, self.things, self.selected_object)
    
    def select_object(self, obj):
        """Alias for set_selected_object to maintain compatibility."""
        self.set_selected_object(obj)

    # --- END OF CORE UI UPDATE LOGIC ---
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

    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')
        edit_menu = menubar.addMenu('Edit')
        view_menu = menubar.addMenu('View')
        tools_menu = menubar.addMenu('Tools')
        render_menu = menubar.addMenu('Render')
        help_menu = menubar.addMenu('Help')

        file_menu.addAction(QAction('New Map', self, shortcut='Ctrl+N', triggered=self.new_map))
        file_menu.addAction(QAction('&Open...', self, shortcut='Ctrl+O', triggered=self.load_level))
        file_menu.addAction(QAction('&Save', self, shortcut='Ctrl+S', triggered=self.save_level))
        file_menu.addAction(QAction('Save &As...', self, shortcut='Ctrl+Shift+S', triggered=self.save_level_as))
        file_menu.addSeparator()
        file_menu.addAction(QAction('Settings...', self, triggered=self.show_settings_dialog))
        file_menu.addSeparator()
        file_menu.addAction(QAction('Exit', self, shortcut='Ctrl+Q', triggered=self.close))

        edit_menu.addAction(QAction('Undo', self, shortcut='Ctrl+Z', triggered=self.undo))
        edit_menu.addAction(QAction('Redo', self, shortcut='Ctrl+Y', triggered=self.redo))

        view_menu.addActions([
            self.scene_hierarchy_dock.toggleViewAction(),
            self.view_3d_dock.toggleViewAction(), 
            self.right_dock.toggleViewAction(), 
            self.properties_dock.toggleViewAction()
        ])
        
        view_menu.addSeparator()
        
        asset_browser_action = self.asset_browser_dock.toggleViewAction()
        asset_browser_action.setText("Toggle Asset Browser")
        asset_browser_action.setShortcut("T")
        view_menu.addAction(asset_browser_action)
        
        view_menu.addSeparator()
        toggle_triggers_action = QAction('Solid Triggers', self, checkable=True)
        toggle_triggers_action.setChecked(self.view_3d.show_triggers_as_solid)
        toggle_triggers_action.triggered.connect(self.toggle_trigger_display)
        view_menu.addAction(toggle_triggers_action)

        tools_menu.addAction(QAction('Random Map Generator...', self, triggered=self.show_random_map_dialog))

        render_group = QActionGroup(self)
        modern_action = QAction('Modern (Shaders)', self, checkable=True, checked=True)
        immediate_action = QAction('Immediate (Legacy)', self, checkable=True)
        render_group.addAction(modern_action)
        render_group.addAction(immediate_action)
        render_menu.addActions(render_group.actions())
        modern_action.triggered.connect(lambda: self.set_render_mode("Modern (Shaders)"))
        immediate_action.triggered.connect(lambda: self.set_render_mode("Immediate (Legacy)"))

        help_menu.addAction(QAction('About', self, triggered=self.show_about))

    def apply_caulk_to_brush(self):
        if not isinstance(self.selected_object, dict):
            QMessageBox.warning(self, "No Brush Selected", "Please select a brush to apply caulk to.")
            return
        self.save_state()
        if 'textures' not in self.selected_object:
            self.selected_object['textures'] = {}
        for face in ['north','south','east','west','top','down']:
            self.selected_object['textures'][face] = 'caulk'
        self.update_views()

    def apply_texture_to_brush(self):
        if not isinstance(self.selected_object, dict):
            QMessageBox.warning(self, "No Brush Selected", "Please select a brush to apply the texture to.")
            return
        texture_path = self.asset_browser.get_selected_filepath()
        if not texture_path:
            QMessageBox.warning(self, "No Texture Selected", "Please select a texture from the Asset Browser.")
            return
        texture_name = os.path.basename(texture_path)
        self.save_state()
        if 'textures' not in self.selected_object:
            self.selected_object['textures'] = {}
        for face in ['north','south','east','west','top','down']:
            self.selected_object['textures'][face] = texture_name
        self.update_views()

    def create_toolbars(self):
        top_toolbar = QToolBar("Main Tools")
        self.addToolBar(top_toolbar)
        display_mode_widget = QWidget()
        display_mode_layout = QHBoxLayout(display_mode_widget)
        display_mode_layout.setContentsMargins(5,0,5,0)
        self.display_mode_combobox = QComboBox()
        self.display_mode_combobox.addItems(["Wireframe", "Solid Lit", "Textured"])
        self.display_mode_combobox.setCurrentText("Textured")
        self.display_mode_combobox.currentTextChanged.connect(self.set_brush_display_mode)
        display_mode_layout.addWidget(QLabel("Display:"))
        display_mode_layout.addWidget(self.display_mode_combobox)
        top_toolbar.addWidget(display_mode_widget)
        top_toolbar.addSeparator()
        undo_action = QAction(QIcon("assets/b_undo.png"),"",self,shortcut="Ctrl+Z",toolTip="Undo",triggered=self.undo)
        redo_action = QAction(QIcon("assets/b_redo.png"),"",self,shortcut="Ctrl+Y",toolTip="Redo",triggered=self.redo)
        top_toolbar.addActions([undo_action, redo_action])
        top_toolbar.addSeparator()
        self.apply_texture_action = QAction(QIcon("assets/b_applytex.png"),"",self,toolTip="Apply selected texture to brush",triggered=self.apply_texture_to_brush)
        self.update_shortcuts()
        apply_caulk_action = QAction(QIcon("assets/b_caulk.png"),"",self,toolTip="Apply caulk texture to brush",triggered=self.apply_caulk_to_brush)
        top_toolbar.addAction(self.apply_texture_action)
        top_toolbar.addAction(apply_caulk_action)
        top_toolbar.addSeparator()
        launch_button = QPushButton(QIcon("assets/b_test.png"),"")
        launch_button.setToolTip("Quicksave and launch game")
        launch_button.setStyleSheet("background-color: #7CFC00; font-weight: bold; padding: 4px 8px;")
        launch_button.clicked.connect(self.quicksave_and_launch)
        top_toolbar.addWidget(launch_button)

    def update_shortcuts(self):
        apply_texture_shortcut = self.config.get('Controls', 'apply_texture', fallback='Shift+T')
        self.apply_texture_action.setShortcut(QKeySequence(apply_texture_shortcut))

    def create_status_bar(self):
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(10, 2, 10, 2)
        
        # --- Create all the widgets first ---
        self.snap_checkbox = QCheckBox("Snap to Grid")
        self.snap_checkbox.setChecked(True)
        self.snap_checkbox.stateChanged.connect(self.toggle_snap_to_grid)
        
        self.grid_size_spinbox = QSpinBox()
        self.grid_size_spinbox.setRange(4, 128)
        self.grid_size_spinbox.setValue(16)
        self.grid_size_spinbox.setSingleStep(1)
        self.grid_size_spinbox.valueChanged.connect(self.set_grid_size)
        
        self.world_size_spinbox = QSpinBox()
        self.world_size_spinbox.setRange(512, 16384)
        self.world_size_spinbox.setValue(1024)
        self.world_size_spinbox.setSingleStep(1)
        self.world_size_spinbox.valueChanged.connect(self.set_world_size)
        
        self.culling_checkbox = QCheckBox("Enable Culling")
        self.culling_checkbox.setChecked(False)
        self.culling_checkbox.stateChanged.connect(self.toggle_culling)
        
        # --- Add widgets to the layout ---
        bottom_layout.addWidget(self.snap_checkbox)
        bottom_layout.addSpacing(20)
        bottom_layout.addWidget(QLabel("Grid Size:"))
        bottom_layout.addWidget(self.grid_size_spinbox)
        bottom_layout.addSpacing(20)
        bottom_layout.addWidget(QLabel("World Size:"))
        bottom_layout.addWidget(self.world_size_spinbox)
        
        # This is the magic line ✨
        # It adds a stretchable space that will push subsequent widgets to the right.
        bottom_layout.addStretch(1)
        
        # Now add the culling checkbox, which will appear on the far right.
        bottom_layout.addWidget(self.culling_checkbox)
        
        status_bar.addPermanentWidget(bottom_widget, 1)

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
        state = {'brushes': self.brushes, 'things': [t.to_dict() for t in self.things]}
        self.undo_stack.append(json.dumps(state))
        self.redo_stack.clear()
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def restore_state(self, state_json):
        state = json.loads(state_json)
        self.brushes = state.get('brushes', [])
        # MODIFICATION: Re-create things using the correct class, including the new Model class
        things_data = state.get('things', [])
        new_things = []
        for t_data in things_data:
            # Check for the 'type' key to differentiate our 'things'
            if t_data.get('type') == 'Model':
                # Recreate Model instance, removing 'type' from kwargs to avoid constructor error
                model_kwargs = {k: v for k, v in t_data.items() if k != 'type'}
                new_things.append(Model(**model_kwargs))
            else:
                # Use existing factory method for all other things
                new_things.append(Thing.from_dict(t_data))
        self.things = new_things
        self.set_selected_object(None)

    def undo(self):
        if len(self.undo_stack) > 1:
            current_state_json = self.undo_stack.pop()
            self.redo_stack.append(current_state_json)
            self.restore_state(self.undo_stack[-1])

    def redo(self):
        if self.redo_stack:
            state_json = self.redo_stack.pop()
            self.undo_stack.append(state_json)
            self.restore_state(state_json)

    def set_render_mode(self, mode):
        self.view_3d.render_mode = mode
        self.update_views()

    def show_about(self):
        QMessageBox.about(self, "About R-Studio", "R-Studio version 1.0.2\nhttps://github.com/ViciousSquid/RStudio")

    def new_map(self):
        self.save_state()
        self.brushes.clear()
        self.things.clear()
        self.file_path = None
        self.set_selected_object(None)

    def show_random_map_dialog(self):
        dialog = RandomMapGeneratorDialog(self)
        if dialog.exec_():
            params = dialog.get_parameters()
            map_grid = generate(method=params['style'], width=params['width'], height=params['length'], seed=params.get('seed'))
            self.brushes, self.things = self.convert_grid_to_level(map_grid)
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
            'textures': {f: 'default.png' for f in ['north','south','east','west','top','down']}
        })

        for r in range(grid_height):
            for c in range(grid_width):
                pos_x, pos_y, pos_z = c * cell_size, wall_height / 2, r * cell_size
                if grid[r, c] == 0:
                    brushes.append({
                        'pos': [pos_x, pos_y, pos_z],
                        'size': [cell_size, wall_height, cell_size],
                        'operation': 'add',
                        'textures': {f: 'default.png' for f in ['north','south','east','west','top','down']}
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
        if not isinstance(self.selected_object, dict):
            QMessageBox.warning(self, "Invalid Selection", "Please select a brush to make it subtractive.")
            return

        self.save_state()
        
        self.selected_object['operation'] = 'subtract'
        subtract_brush = self.selected_object
        
        sub_pos = subtract_brush['pos']
        sub_size = subtract_brush['size']
        sub_min = [sub_pos[0] - sub_size[0]/2, sub_pos[1] - sub_size[1]/2, sub_pos[2] - sub_size[2]/2]
        sub_max = [sub_pos[0] + sub_size[0]/2, sub_pos[1] + sub_size[1]/2, sub_pos[2] + sub_size[2]/2]
        
        new_brushes = []
        for brush in self.brushes:
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
        self.brushes = new_brushes
        
        self.update_all_ui()

    def toggle_trigger_display(self, checked):
        self.view_3d.show_triggers_as_solid = checked
        self.view_3d.update()

    def keyPressEvent(self, event):
        if self.selected_object:
            if event.key() == Qt.Key_Delete:
                self.save_state()
                if isinstance(self.selected_object, dict):
                    self.brushes.remove(self.selected_object)
                else:
                    self.things.remove(self.selected_object)
                self.set_selected_object(None)
                return

            if event.key() == Qt.Key_Space:
                self.save_state()
                if isinstance(self.selected_object, dict):
                    new_obj = copy.deepcopy(self.selected_object)
                    self.brushes.append(new_obj)
                else:
                    new_obj = copy.copy(self.selected_object)
                    self.things.append(new_obj)
                
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
            
        if event.key() == Qt.Key_Escape and self.selected_object:
            self.set_selected_object(None)
            return
            
        self.keys_pressed.add(event.key())
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() in self.keys_pressed:
            self.keys_pressed.remove(event.key())
        self.update_views()
        super().keyReleaseEvent(event)

    def toggle_snap_to_grid(self, state):
        enabled = state == Qt.Checked
        for view in [self.view_top, self.view_side, self.view_front]:
            view.snap_to_grid_enabled = enabled

    def _get_level_data(self):
        return {'brushes': self.brushes, 'things': [t.to_dict() for t in self.things]}

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
                json.dump(self._get_level_data(), f, indent=4)
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

        self.brushes = level_data.get('brushes', [])
        # MODIFICATION: Re-create things using the correct class, including the new Model class
        things_data = level_data.get('things', [])
        new_things = []
        for t_data in things_data:
            # Check for the 'type' key to differentiate our 'things'
            if t_data.get('type') == 'Model':
                # Recreate Model instance, removing 'type' from kwargs to avoid constructor error
                model_kwargs = {k: v for k, v in t_data.items() if k != 'type'}
                new_things.append(Model(**model_kwargs))
            else:
                # Use existing factory method for all other things
                new_things.append(Thing.from_dict(t_data))
        self.things = new_things

        player_start_pos = None
        for t in self.things:
            if isinstance(t, PlayerStart):
                player_start_pos = t.pos
                break

        if player_start_pos:
            self.view_3d.camera.pos = [player_start_pos[0], player_start_pos[1] + 50, player_start_pos[2] + 200]
            self.view_3d.camera.pitch = -15
            self.view_3d.camera.yaw = -90

        self.file_path = filePath
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.save_state()
        self.set_selected_object(None)
        print(f"Level loaded from {filePath}")

    def quicksave_and_launch(self):
        maps_dir = "maps"
        if not os.path.exists(maps_dir):
            os.makedirs(maps_dir)

        quicksave_path = os.path.join(maps_dir, "quick_save.json")
        try:
            with open(quicksave_path, 'w') as f:
                json.dump(self._get_level_data(), f, indent=4)
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


if __name__ == '__main__':
    config = configparser.ConfigParser()
    config.read('settings.ini')
    if config.getboolean('Display', 'high_dpi_scaling', fallback=False):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)

    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())