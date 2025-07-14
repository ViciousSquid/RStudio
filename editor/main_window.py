import sys
import json
import os
import subprocess
import random
import numpy as np
import configparser
import math
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
from PyQt5.QtGui import QFont, QIcon
from editor.view_2d import View2D
from engine.qt_game_view import QtGameView
from editor.things import Light, PlayerStart, Thing
from editor.property_editor import PropertyEditor
from editor.rand_map_gen_dial import RandomMapGeneratorDialog
from editor.rand_map_gen import generate
from editor.asset_browser import AssetBrowser
from editor.SettingsWindow import SettingsWindow

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
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
        self.file_path = None # To keep track of the current file

        self.undo_stack = []
        self.redo_stack = []

        # --- Create UI Components FIRST ---
        self.view_3d = QtGameView(self)
        self.view_top = View2D(self, self, "top")
        self.view_side = View2D(self, self, "side")
        self.view_front = View2D(self, self, "front")
        self.property_editor = PropertyEditor(self, self)

        # --- Create and Arrange Docks ---
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)

        self.view_3d_dock = QDockWidget("3D View", self)
        self.view_3d_dock.setWidget(self.view_3d)
        self.view_3d_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.view_3d_dock)

        self.right_dock = QDockWidget("2D Views", self)
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.view_top, "Top")
        self.right_tabs.addTab(self.view_side, "Side")
        self.right_tabs.addTab(self.view_front, "Front")
        self.right_dock.setWidget(self.right_tabs)
        self.right_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(Qt.RightDockWidgetArea, self.right_dock)

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

        zoom_in_button = QPushButton("+")
        zoom_in_button.setToolTip("Zoom in")
        zoom_in_button.clicked.connect(self.zoom_in_2d)
        corner_layout.addWidget(zoom_in_button)

        zoom_out_button = QPushButton("-")
        zoom_out_button.setToolTip("Zoom out")
        zoom_out_button.clicked.connect(self.zoom_out_2d)
        corner_layout.addWidget(zoom_out_button)

        self.right_tabs.setCornerWidget(corner_widget, Qt.TopRightCorner)

        self.properties_dock = QDockWidget("Properties", self)
        self.properties_dock.setWidget(self.property_editor)
        self.properties_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)

        self.asset_browser_dock = QDockWidget("Asset Browser", self)
        self.asset_browser = AssetBrowser("assets", self)
        self.asset_browser_dock.setWidget(self.asset_browser)
        self.asset_browser_dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.asset_browser_dock.setFloating(True)
        self.asset_browser_dock.setVisible(False)
        self.addDockWidget(Qt.RightDockWidgetArea, self.asset_browser_dock)

        self.splitDockWidget(self.view_3d_dock, self.right_dock, Qt.Horizontal)
        self.splitDockWidget(self.right_dock, self.properties_dock, Qt.Vertical)

        self.resizeDocks([self.view_3d_dock, self.right_dock], [1000, 600], Qt.Horizontal)
        self.resizeDocks([self.right_dock, self.properties_dock], [600, 300], Qt.Vertical)

        # --- Create Menus and Toolbars AFTER Docks Exist ---
        self.create_menu_bar()
        self.create_toolbars()
        self.create_status_bar()

        self.setFocus()
        self.update_global_font()

        # Initialize with a base state for undo
        self.save_state()

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

        view_menu.addActions([self.view_3d_dock.toggleViewAction(), self.right_dock.toggleViewAction(), self.properties_dock.toggleViewAction()])

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
        print("Applied 'caulk' to selected brush.")
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
        print(f"Applied texture '{texture_name}' to selected brush.")
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

        apply_texture_action = QAction(QIcon("assets/b_applytex.png"),"",self,toolTip="Apply selected texture to brush",triggered=self.apply_texture_to_brush)
        apply_caulk_action = QAction(QIcon("assets/b_caulk.png"),"",self,toolTip="Apply caulk texture to brush",triggered=self.apply_caulk_to_brush)
        top_toolbar.addAction(apply_texture_action)
        top_toolbar.addAction(apply_caulk_action)

        top_toolbar.addSeparator()

        launch_button = QPushButton(QIcon("assets/b_test.png"),"")
        launch_button.setToolTip("Quicksave and launch game")
        launch_button.setStyleSheet("background-color: #7CFC00; font-weight: bold; padding: 4px 8px;")
        launch_button.clicked.connect(self.quicksave_and_launch)
        top_toolbar.addWidget(launch_button)

    def create_status_bar(self):
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)

        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(10,2,10,2)

        self.snap_checkbox = QCheckBox("Snap to Grid")
        self.snap_checkbox.setChecked(True)
        self.snap_checkbox.stateChanged.connect(self.toggle_snap_to_grid)

        self.grid_size_spinbox = QSpinBox()
        self.grid_size_spinbox.setRange(4, 128)
        self.grid_size_spinbox.setValue(16)
        self.grid_size_spinbox.setSingleStep(1)
        self.grid_size_spinbox.valueChanged.connect(self.set_grid_size)

        self.world_size_spinbox = QSpinBox()
        self.world_size_spinbox.setRange(256, 8192)
        self.world_size_spinbox.setValue(1024)
        self.world_size_spinbox.setSingleStep(1)
        self.world_size_spinbox.valueChanged.connect(self.set_world_size)

        bottom_layout.addWidget(self.snap_checkbox)
        bottom_layout.addSpacing(20)
        bottom_layout.addWidget(QLabel("Grid Size:"))
        bottom_layout.addWidget(self.grid_size_spinbox)
        bottom_layout.addSpacing(20)
        bottom_layout.addWidget(QLabel("World Size:"))
        bottom_layout.addWidget(self.world_size_spinbox)
        bottom_layout.addStretch(1)

        status_bar.addPermanentWidget(bottom_widget, 1)

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
        self.things = [Thing.from_dict(t_data) for t_data in state.get('things', [])]
        self.set_selected_object(None)
        self.update_views()

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

    def set_selected_object(self, obj):
        self.selected_object = obj
        if self.property_editor:
            self.property_editor.set_object(obj)
        self.update_views()

    def set_render_mode(self, mode):
        self.view_3d.render_mode = mode
        if hasattr(self, 'display_mode_combobox'):
            self.display_mode_combobox.setEnabled(mode == "Modern (Shaders)")
        self.update_views()

    def show_about(self):
        QMessageBox.about(self, "About R-Studio", "R-Studio version 1.0.2\nA hobby level editor.")

    def new_map(self):
        self.save_state()
        self.brushes.clear()
        self.things.clear()
        self.file_path = None
        self.set_selected_object(None)
        self.update_views()

    def show_random_map_dialog(self):
        dialog = RandomMapGeneratorDialog(self)
        if dialog.exec_():
            params = dialog.get_parameters()
            map_grid = generate(method=params['style'], width=params['width'], height=params['length'], seed=params.get('seed'))
            self.brushes, self.things = self.convert_grid_to_level(map_grid)
            self.view_3d.camera.pos = [0, 150, 400]
            self.set_selected_object(None)
            self.save_state()
            self.update_views()
            print("Generated new random map.")

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
        if isinstance(self.selected_object, dict):
            self.save_state()
            self.selected_object['operation'] = 'subtract'
            self.update_views()
        else:
            QMessageBox.warning(self, "Invalid Selection", "Please select a brush to make it subtractive.")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_T:
            if not self.asset_browser_dock.isVisible():
                screen_rect = QApplication.desktop().screenGeometry()
                center_point = screen_rect.center()
                dock_size_hint = self.asset_browser_dock.sizeHint()
                new_x = center_point.x() - dock_size_hint.width() / 2 + 200
                new_y = center_point.y() - dock_size_hint.height() / 2
                self.asset_browser_dock.move(int(new_x), int(new_y))

            self.asset_browser_dock.setVisible(not self.asset_browser_dock.isVisible())
            return
        if event.key() == Qt.Key_Escape and self.selected_object:
            self.set_selected_object(None)
            return
        self.keys_pressed.add(event.key())
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() in self.keys_pressed:
            self.keys_pressed.remove(event.key())
        super().keyReleaseEvent(event)

    def toggle_snap_to_grid(self, state):
        enabled = state == Qt.Checked
        for view in [self.view_top, self.view_side, self.view_front]:
            view.snap_to_grid_enabled = enabled

    def update_views(self):
        self.view_3d.update()
        self.view_top.update()
        self.view_side.update()
        self.view_front.update()

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
        self.things = [Thing.from_dict(t_data) for t_data in level_data.get('things', [])]

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
        self.set_selected_object(None)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.save_state()
        self.update_views()
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