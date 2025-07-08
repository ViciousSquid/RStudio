import sys
import json
import os
import subprocess
import random
import numpy as np
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
from PyQt5.QtCore import Qt
from editor.view_2d import View2D
from engine.qt_game_view import QtGameView
from editor.things import Light, PlayerStart, Thing
from editor.property_editor import PropertyEditor
from editor.rand_map_gen_dial import RandomMapGeneratorDialog
from editor.rand_map_gen import generate

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RStudio")
        self.setGeometry(100, 100, 1280, 800)
        self.setMinimumSize(1200, 800)

        self.brushes = []
        self.things = []
        self.selected_object = None
        self.keys_pressed = set()

        self.undo_stack = []
        self.redo_stack = []
        self.save_state()

        self.create_menu_bar()
        self.create_toolbars()
        self.create_status_bar()

        self.view_3d = QtGameView(self)
        self.view_top = View2D(self, self, "top")
        self.view_side = View2D(self, self, "side")
        self.view_front = View2D(self, self, "front")
        self.property_editor = PropertyEditor(self)

        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)

        self.view_3d_dock = QDockWidget("3D View", self)
        self.view_3d_dock.setWidget(self.view_3d)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.view_3d_dock)

        self.right_dock = QDockWidget("2D Views", self)
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.view_top, "Top")
        self.right_tabs.addTab(self.view_side, "Side")
        self.right_tabs.addTab(self.view_front, "Front")
        self.right_dock.setWidget(self.right_tabs)
        self.addDockWidget(Qt.RightDockWidgetArea, self.right_dock)

        self.right_tabs.setStyleSheet("""
            QTabBar::tab:selected { background: #0078d7; color: white; }
            QTabBar::tab { background: #444; color: #ccc; padding: 5px; border: 1px solid #222; }
        """)

        subtract_button = QPushButton("Subtract")
        subtract_button.setToolTip("Mark the selected brush as subtractive")
        subtract_button.setStyleSheet("padding: 2px 8px;")
        subtract_button.clicked.connect(self.perform_subtraction)
        self.right_tabs.setCornerWidget(subtract_button, Qt.TopRightCorner)

        self.properties_dock = QDockWidget("Properties", self)
        self.properties_dock.setWidget(self.property_editor)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)

        self.splitDockWidget(self.view_3d_dock, self.right_dock, Qt.Horizontal)
        self.splitDockWidget(self.right_dock, self.properties_dock, Qt.Vertical)

        self.resizeDocks([self.view_3d_dock, self.right_dock], [800, 480], Qt.Horizontal)
        self.resizeDocks([self.right_dock, self.properties_dock], [500, 300], Qt.Vertical)

        self.setFocus()

    def save_state(self):
        state = {
            'brushes': [b.copy() for b in self.brushes],
            'things': [t.copy() for t in self.things],
            'selected': self.selected_object
        }
        self.undo_stack.append(state)
        self.redo_stack = []

    def restore_state(self, state):
        self.brushes = [b.copy() for b in state.get('brushes', [])]
        self.things = [t.copy() for t in state.get('things', [])]
        self.set_selected_object(state.get('selected'))
        self.update_views()

    def undo(self):
        if len(self.undo_stack) > 1:
            self.redo_stack.append(self.undo_stack.pop())
            state = self.undo_stack[-1]
            self.restore_state(state)

    def redo(self):
        if self.redo_stack:
            state = self.redo_stack.pop()
            self.undo_stack.append(state)
            self.restore_state(state)

    def set_selected_object(self, obj):
        self.selected_object = obj
        self.property_editor.set_object(obj)
        self.update_views()

    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')
        edit_menu = menubar.addMenu('Edit')
        render_menu = menubar.addMenu('Render')
        help_menu = menubar.addMenu('Help')

        new_random_map_action = QAction('New Random Map...', self, triggered=self.show_random_map_dialog)
        save_action = QAction('Save', self, shortcut='Ctrl+S', triggered=self.save_level)
        load_action = QAction('Load', self, shortcut='Ctrl+O', triggered=self.load_level)
        file_menu.addActions([new_random_map_action, save_action, load_action])

        undo_action = QAction('Undo', self, shortcut='Ctrl+Z', triggered=self.undo)
        redo_action = QAction('Redo', self, shortcut='Ctrl+Y', triggered=self.redo)
        edit_menu.addActions([undo_action, redo_action])

        # Render menu actions
        render_group = QActionGroup(self)
        modern_action = QAction('Modern (Shaders)', self, checkable=True, checked=True)
        immediate_action = QAction('Immediate (Legacy)', self, checkable=True)
        render_group.addAction(modern_action)
        render_group.addAction(immediate_action)
        render_menu.addActions(render_group.actions())

        modern_action.triggered.connect(lambda: self.set_render_mode("Modern (Shaders)"))
        immediate_action.triggered.connect(lambda: self.set_render_mode("Immediate (Legacy)"))

        about_action = QAction('About', self, triggered=self.show_about)
        help_menu.addAction(about_action)

    def set_render_mode(self, mode):
        self.view_3d.render_mode = mode
        self.display_mode_combobox.setEnabled(mode == "Modern (Shaders)")
        self.update_views()

    def show_about(self):
        QMessageBox.about(self, "About", "Backrooms Editor\nCSG Editing Tool")

    def show_random_map_dialog(self):
        dialog = RandomMapGeneratorDialog(self)
        if dialog.exec_():
            params = dialog.get_parameters()
            
            map_grid = generate(
                method=params['style'],
                width=params['width'],
                height=params['length'],
                seed=params.get('seed') 
            )

            # Convert the grid data to a full level
            self.brushes, self.things = self.convert_grid_to_level(map_grid)

            self.view_3d.camera.pos = [0.0, 150.0, 400.0]
            self.set_selected_object(None)
            
            self.save_state()
            self.update_views()
            print("Generated new random map with subtractive brushes.")

    def convert_grid_to_level(self, grid, cell_size=128, wall_height=128):
        """
        Converts a 2D grid from the generator into a playable level
        using a large solid brush and subtractive brushes for rooms/hallways.
        """
        if not isinstance(grid, np.ndarray):
            print("Error: Map generation did not return a valid grid.")
            return [], []

        brushes = []
        things = []
        grid_height, grid_width = grid.shape
        
        # 1. Create one giant solid brush to contain the entire level
        world_width = grid_width * cell_size
        world_length = grid_height * cell_size
        
        container_pos = [world_width / 2 - cell_size/2, wall_height / 2, world_length / 2 - cell_size/2]
        container_size = [world_width, wall_height, world_length]
        
        brushes.append({'pos': container_pos, 'size': container_size, 'operation': 'add'})

        # 2. Find all floor locations to create subtractive brushes and place things
        floor_locations = []
        for r in range(grid_height):
            for c in range(grid_width):
                if grid[r, c] == 1: # FLOOR
                    # Position is centered in the cell
                    pos_x = c * cell_size
                    pos_y = wall_height / 2
                    pos_z = r * cell_size
                    floor_locations.append((pos_x, pos_y, pos_z))

                    # Create a subtractive brush for this floor cell
                    sub_brush = {
                        'pos': [pos_x, pos_y, pos_z],
                        'size': [cell_size, wall_height - 16, cell_size], # Leave a ceiling and floor
                        'operation': 'subtract'
                    }
                    brushes.append(sub_brush)

        # 3. Add a player start and lights
        if floor_locations:
            # Place player start in the first room
            player_pos = floor_locations[0]
            things.append(PlayerStart(pos=[player_pos[0], 40, player_pos[2]]))

            # Randomly place a few lights
            num_lights = len(floor_locations) // 25
            for _ in range(max(1, num_lights)):
                light_pos = random.choice(floor_locations)
                things.append(Light(pos=[light_pos[0], wall_height - 40, light_pos[2]]))
        else:
            print("Warning: Generated map has no floor space.")

        return brushes, things

    def create_toolbars(self):
        top_toolbar = QToolBar("Main Tools")
        self.addToolBar(top_toolbar)
        
        display_mode_widget = QWidget()
        display_mode_layout = QHBoxLayout(display_mode_widget)
        display_mode_layout.setContentsMargins(5, 0, 5, 0)
        self.display_mode_combobox = QComboBox()
        self.display_mode_combobox.addItems(["Wireframe", "Solid Lit"])
        self.display_mode_combobox.setCurrentText("Solid Lit")
        self.display_mode_combobox.currentIndexChanged.connect(self.set_brush_display_mode)
        display_mode_layout.addWidget(QLabel("Display:"))
        display_mode_layout.addWidget(self.display_mode_combobox)
        top_toolbar.addWidget(display_mode_widget)
        top_toolbar.addSeparator()

        undo_action = QAction("Undo", self, shortcut="Ctrl+Z", triggered=self.undo)
        redo_action = QAction("Redo", self, shortcut="Ctrl+Y", triggered=self.redo)
        top_toolbar.addActions([undo_action, redo_action])
        top_toolbar.addSeparator()

        launch_button = QPushButton("TEST")
        launch_button.setStyleSheet("background-color: #7CFC00; color: black; font-weight: bold; padding: 4px 8px;")
        launch_button.clicked.connect(self.quicksave_and_launch)
        top_toolbar.addWidget(launch_button)

    def create_status_bar(self):
        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(10, 2, 10, 2)
        self.snap_checkbox = QCheckBox("Snap to Grid")
        self.snap_checkbox.setChecked(True)
        self.snap_checkbox.stateChanged.connect(self.toggle_snap_to_grid)
        bottom_layout.addWidget(self.snap_checkbox)
        bottom_layout.addSpacing(20)
        bottom_layout.addWidget(QLabel("Grid Size:"))
        self.grid_size_spinbox = QSpinBox()
        self.grid_size_spinbox.setValue(16)
        self.grid_size_spinbox.setSingleStep(4)
        self.grid_size_spinbox.setRange(4, 128)
        self.grid_size_spinbox.valueChanged.connect(self.set_grid_size)
        bottom_layout.addWidget(self.grid_size_spinbox)
        bottom_layout.addSpacing(20)
        bottom_layout.addWidget(QLabel("World Size:"))
        self.world_size_spinbox = QSpinBox()
        self.world_size_spinbox.setValue(1024)
        self.world_size_spinbox.setSingleStep(256)
        self.world_size_spinbox.setRange(256, 8192)
        self.world_size_spinbox.valueChanged.connect(self.set_world_size)
        bottom_layout.addWidget(self.world_size_spinbox)
        bottom_layout.addStretch(1)
        status_bar.addPermanentWidget(bottom_widget, 1)

    def perform_subtraction(self):
        if isinstance(self.selected_object, dict):
            self.save_state()
            self.selected_object['operation'] = 'subtract'
            self.update_views()

    def keyPressEvent(self, event):
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
        is_enabled = (state == Qt.Checked)
        for view in [self.view_top, self.view_side, self.view_front]:
            view.snap_to_grid_enabled = is_enabled

    def set_grid_size(self, size):
        for view in [self.view_top, self.view_side, self.view_front]:
            view.grid_size = size
        self.view_3d.grid_size = size
        self.view_3d.update_grid()
        self.update_views()

    def set_world_size(self, size):
        for view in [self.view_top, self.view_side, self.view_front]:
            view.world_size = size
        self.view_3d.world_size = size
        self.view_3d.update_grid()
        self.update_views()

    def set_brush_display_mode(self, index):
        self.view_3d.brush_display_mode = self.display_mode_combobox.currentText()
        self.view_3d.update()

    def add_brush(self):
        self.save_state()
        new_brush = {'pos': [0, 0, 0], 'size': [64, 64, 64], 'operation': 'add'}
        self.brushes.append(new_brush)
        self.set_selected_object(new_brush)
        self.update_views()

    def update_views(self):
        self.view_3d.update()
        self.view_top.update()
        self.view_side.update()
        self.view_front.update()

    def _get_level_data(self):
        thing_list = []
        for t in self.things:
            thing_data = {
                'name': t.name, 'pos': t.pos, 'properties': t.properties
            }
            thing_list.append(thing_data)
        return {'brushes': self.brushes, 'things': thing_list}

    def save_level(self):
        filePath, _ = QFileDialog.getSaveFileName(self, "Save Level", "maps", "JSON Files (*.json)")
        if filePath:
            with open(filePath, 'w') as f:
                json.dump(self._get_level_data(), f, indent=4)
            print(f"Level saved to {filePath}")

    def load_level(self):
        filePath, _ = QFileDialog.getOpenFileName(self, "Load Level", "maps", "JSON Files (*.json)")
        if not filePath:
            return
            
        with open(filePath, 'r') as f:
            level_data = json.load(f)

        self.brushes = level_data.get('brushes', [])
        
        self.things = []
        player_start_pos = None
        for thing_data in level_data.get('things', []):
            name = thing_data.get('name')
            pos = thing_data.get('pos', [0,0,0])
            if name == "Light":
                self.things.append(Light(pos))
            elif name == "Player Start":
                player_start = PlayerStart(pos)
                self.things.append(player_start)
                player_start_pos = player_start.pos

        if player_start_pos:
            self.view_3d.camera.pos = [player_start_pos[0], player_start_pos[1] + 50, player_start_pos[2] + 200]
            self.view_3d.camera.pitch = -15
            self.view_3d.camera.yaw = -90

        self.set_selected_object(None)
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

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())