import sys
import json
import os
import subprocess
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
    QPushButton
)
from PyQt5.QtCore import Qt
from editor.view_2d import View2D
from engine.qt_game_view import QtGameView
from editor.things import Light, PlayerStart, Thing
from editor.property_editor import PropertyEditor

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Backrooms Editor")
        self.setGeometry(100, 100, 1280, 800)
        self.setMinimumSize(1200, 800)

        # Initialize core data structures first
        self.brushes = []
        self.things = []
        self.selected_object = None
        self.keys_pressed = set()

        # Initialize undo/redo stacks and save initial state
        self.undo_stack = []
        self.redo_stack = []
        self.save_state()

        # Create and add menu and toolbars
        self.create_menu_bar()
        self.create_toolbars()
        self.create_status_bar()

        # --- Create Views and Property Editor ---
        self.view_3d = QtGameView(self)
        self.view_top = View2D(self, self, "top")
        self.view_side = View2D(self, self, "side")
        self.view_front = View2D(self, self, "front")
        self.property_editor = PropertyEditor(self)

        # --- Setup Docking ---
        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)
        self.setTabPosition(Qt.AllDockWidgetAreas, QTabWidget.North)

        # Create a dock for the 3D View
        self.view_3d_dock = QDockWidget("3D View", self)
        self.view_3d_dock.setWidget(self.view_3d)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.view_3d_dock)

        # Create a dock for the 2D views
        self.right_dock = QDockWidget("2D Views", self)
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.view_top, "Top")
        self.right_tabs.addTab(self.view_side, "Side")
        self.right_tabs.addTab(self.view_front, "Front")
        self.right_dock.setWidget(self.right_tabs)
        self.addDockWidget(Qt.RightDockWidgetArea, self.right_dock)

        # Style the 2D view tabs
        self.right_tabs.setStyleSheet("""
            QTabBar::tab:selected {
                background: #0078d7;
                color: white;
            }
            QTabBar::tab {
                background: #444;
                color: #ccc;
                padding: 5px;
                border: 1px solid #222;
            }
        """)

        # --- Create and place the Subtract button next to the tabs ---
        subtract_button = QPushButton("Subtract")
        subtract_button.setToolTip("Mark the selected brush as subtractive")
        subtract_button.setStyleSheet("padding: 2px 8px;")
        subtract_button.clicked.connect(self.perform_subtraction)
        self.right_tabs.setCornerWidget(subtract_button, Qt.TopRightCorner)


        # Create a dock for the property editor
        self.properties_dock = QDockWidget("Properties", self)
        self.properties_dock.setWidget(self.property_editor)
        self.addDockWidget(Qt.RightDockWidgetArea, self.properties_dock)

        # Arrange the docks
        self.splitDockWidget(self.view_3d_dock, self.right_dock, Qt.Horizontal)
        self.splitDockWidget(self.right_dock, self.properties_dock, Qt.Vertical)

        # Set initial sizes for the docks
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
        help_menu = menubar.addMenu('Help')

        save_action = QAction('Save', self, shortcut='Ctrl+S', triggered=self.save_level)
        load_action = QAction('Load', self, shortcut='Ctrl+O', triggered=self.load_level)
        file_menu.addActions([save_action, load_action])

        undo_action = QAction('Undo', self, shortcut='Ctrl+Z', triggered=self.undo)
        redo_action = QAction('Redo', self, shortcut='Ctrl+Y', triggered=self.redo)
        edit_menu.addActions([undo_action, redo_action])

        about_action = QAction('About', self, triggered=self.show_about)
        help_menu.addAction(about_action)

    def show_about(self):
        QMessageBox.about(self, "About", "Backrooms Editor\nCSG Editing Tool")

    def create_toolbars(self):
        top_toolbar = QToolBar("Main Tools")
        self.addToolBar(top_toolbar)

        # The Subtract button has been moved next to the 2D view tabs
        
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
        if not isinstance(self.selected_object, dict):
            return

        self.save_state()
        self.selected_object['operation'] = 'subtract'
        self.update_views()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self.selected_object:
                self.set_selected_object(None)
                return

        self.keys_pressed.add(event.key())
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() in self.keys_pressed:
            self.keys_pressed.remove(event.key())
        super().keyReleaseEvent(event)

    def toggle_snap_to_grid(self, state):
        for view in [self.view_top, self.view_side, self.view_front]:
            view.snap_to_grid_enabled = (state == Qt.Checked)

    def set_grid_size(self, size):
        for view in [self.view_top, self.view_side, self.view_front]:
            view.grid_size = size
            view.update()
        self.view_3d.grid_size = size
        self.view_3d.update_grid()

    def set_world_size(self, size):
        for view in [self.view_top, self.view_side, self.view_front]:
            view.world_size = size
            view.update()
        self.view_3d.world_size = size
        self.view_3d.update_grid()

    def set_brush_display_mode(self, index):
        mode = self.display_mode_combobox.currentText()
        self.view_3d.brush_display_mode = mode
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
                'name': t.name,
                'pos': t.pos,
                'properties': t.properties
            }
            thing_list.append(thing_data)

        return {'brushes': self.brushes, 'things': thing_list}

    def save_level(self):
        filePath, _ = QFileDialog.getSaveFileName(self, "Save Level", "maps", "JSON Files (*.json)")
        if not filePath:
            return

        level_data = self._get_level_data()
        with open(filePath, 'w') as f:
            json.dump(level_data, f, indent=4)
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

        level_data = self._get_level_data()
        try:
            with open(quicksave_path, 'w') as f:
                json.dump(level_data, f, indent=4)
            print(f"Quicksave successful: {quicksave_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not quicksave level:\n{e}")
            return

        game_script_path = 'game.py'
        if not os.path.exists(game_script_path):
            QMessageBox.warning(self, "Warning", f"Could not find '{game_script_path}' to launch.")
            return
            
        try:
            command = [sys.executable, game_script_path, quicksave_path]
            subprocess.Popen(command)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not launch game:\n{e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())