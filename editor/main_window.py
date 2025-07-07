import sys
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QToolBar,
    QLabel,
    QSpinBox,
    QCheckBox,
    QComboBox,
    QAction,
    QMessageBox,
    QFrame
)
from PyQt5.QtCore import Qt
from editor.view_2d import View2D
from engine.qt_game_view import QtGameView
from editor.things import Light 

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Backrooms Editor")
        self.setGeometry(100, 100, 1200, 800)
        self.setMinimumSize(1200, 800)

        self.brushes = []
        self.selected_brush_index = -1
        self.selected_object = None 
        self.keys_pressed = set()
        self.cs_subtract_mode = False

        self.undo_stack = []
        self.redo_stack = []
        self.save_state()

        self.things = [] 
        # For now, if you want a default light:
        # self.things.append(Light([0, 0, 0], 100, [1.0, 1.0, 1.0]))


        # Main container widget and layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        # Create and add menu and toolbars
        self.create_menu_bar()
        self.create_toolbars() 

        # Central splitter widget
        self.splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.splitter, 1) 

        # Add bottom controls
        self.create_bottom_controls()

        # --- Setup Views ---
        self.view_3d = QtGameView(self)
        self.splitter.addWidget(self.view_3d)

        self.right_splitter = QSplitter(Qt.Vertical)
        self.splitter.addWidget(self.right_splitter)

        self.view_top = View2D(self, self, "top")
        self.right_splitter.addWidget(self.view_top)

        self.bottom_splitter = QSplitter(Qt.Horizontal)
        self.right_splitter.addWidget(self.bottom_splitter)

        self.view_side = View2D(self, self, "side")
        self.bottom_splitter.addWidget(self.view_side)

        self.view_front = View2D(self, self, "front")
        self.bottom_splitter.addWidget(self.view_front)

        self.splitter.setSizes([800, 400])
        self.setFocus()

    def save_state(self):
        state = {'brushes': [b.copy() for b in self.brushes], 'selected': self.selected_brush_index}
        self.undo_stack.append(state)
        self.redo_stack = []

    def undo(self):
        if len(self.undo_stack) > 1:
            self.redo_stack.append(self.undo_stack.pop())
            state = self.undo_stack[-1]
            self.brushes = [b.copy() for b in state['brushes']]
            self.selected_brush_index = state['selected']
            self.selected_object = self.brushes[self.selected_brush_index] if self.selected_brush_index != -1 else None
            self.update_views()

    def redo(self):
        if self.redo_stack:
            state = self.redo_stack.pop()
            self.undo_stack.append(state)
            self.brushes = [b.copy() for b in state['brushes']]
            self.selected_brush_index = state['selected']
            self.selected_object = self.brushes[self.selected_brush_index] if self.selected_brush_index != -1 else None
            self.update_views()

    # New method to set the selected object and update its index
    def set_selected_object(self, obj):
        self.selected_object = obj
        if obj is None:
            self.selected_brush_index = -1
        else:
            try:
                # Assuming obj is one of the brushes in self.brushes
                self.selected_brush_index = self.brushes.index(obj)
            except ValueError:
                # obj not found in brushes, might be a new object or an error
                self.selected_brush_index = -1 
        self.update_views() # Update views to reflect the new selection


    def create_menu_bar(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu('File')
        edit_menu = menubar.addMenu('Edit')
        help_menu = menubar.addMenu('Help')

        undo_action = QAction('Undo', self, shortcut='Ctrl+Z', triggered=self.undo)
        redo_action = QAction('Redo', self, shortcut='Ctrl+Y', triggered=self.redo)
        about_action = QAction('About', self, triggered=self.show_about)

        edit_menu.addActions([undo_action, redo_action])
        help_menu.addAction(about_action)

    def show_about(self):
        QMessageBox.about(self, "About", "Backrooms Editor\nCSG Editing Tool")

    def create_toolbars(self):
        top_toolbar = QToolBar("Main Tools")

        hollow_action = QAction("Hollow", self, triggered=self.hollow_brush)
        subtract_action = QAction("Subtract", self, checkable=True, triggered=self.toggle_subtract_mode)
        top_toolbar.addActions([hollow_action, subtract_action])
        top_toolbar.addSeparator()

        display_mode_widget = QWidget()
        display_mode_layout = QHBoxLayout(display_mode_widget)
        display_mode_layout.setContentsMargins(5, 0, 5, 0)
        self.display_mode_combobox = QComboBox()
        self.display_mode_combobox.addItems(["Wireframe", "Solid", "Textured"])
        self.display_mode_combobox.currentIndexChanged.connect(self.set_brush_display_mode)
        display_mode_layout.addWidget(QLabel("Display:"))
        display_mode_layout.addWidget(self.display_mode_combobox)
        top_toolbar.addWidget(display_mode_widget)
        top_toolbar.addSeparator()

        undo_action = QAction("Undo", self, shortcut="Ctrl+Z", triggered=self.undo)
        redo_action = QAction("Redo", self, shortcut="Ctrl+Y", triggered=self.redo)
        top_toolbar.addActions([undo_action, redo_action])

        self.main_layout.addWidget(top_toolbar)

    def create_bottom_controls(self):
        bottom_widget = QWidget()
        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(10, 5, 10, 5)

        # Snap to grid
        self.snap_checkbox = QCheckBox("Snap to Grid")
        self.snap_checkbox.setChecked(True)
        self.snap_checkbox.stateChanged.connect(self.toggle_snap_to_grid)
        bottom_layout.addWidget(self.snap_checkbox)
        bottom_layout.addSpacing(20)

        # Grid size
        bottom_layout.addWidget(QLabel("Grid Size:"))
        self.grid_size_spinbox = QSpinBox(value=16, singleStep=4)
        self.grid_size_spinbox.setRange(4, 128)
        self.grid_size_spinbox.valueChanged.connect(self.set_grid_size)
        bottom_layout.addWidget(self.grid_size_spinbox)
        bottom_layout.addSpacing(20)

        # World size
        bottom_layout.addWidget(QLabel("World Size:"))
        self.world_size_spinbox = QSpinBox(value=1024, singleStep=256)
        self.world_size_spinbox.setRange(256, 8192)
        self.world_size_spinbox.valueChanged.connect(self.set_world_size)
        bottom_layout.addWidget(self.world_size_spinbox)
        
        bottom_layout.addStretch(1) 

        # Add a separator line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        
        container_layout = QVBoxLayout()
        container_layout.setContentsMargins(0,0,0,0)
        container_layout.setSpacing(0)
        container_layout.addWidget(line)
        container_layout.addWidget(bottom_widget)

        self.main_layout.addLayout(container_layout)

    def toggle_subtract_mode(self):
        self.cs_subtract_mode = not self.cs_subtract_mode
        self.sender().setChecked(self.cs_subtract_mode)

    def hollow_brush(self):
        if self.selected_brush_index != -1:
            self.save_state()
            brush = self.brushes[self.selected_brush_index]
            wall_thickness = min(brush['size']) / 4
            hollow = {'pos': brush['pos'][:], 'size': [s - wall_thickness * 2 for s in brush['size']], 'operation': 'subtract'}
            brush.update({'operation': 'hollow', 'hollow_child': len(self.brushes)})
            self.brushes.append(hollow)
            self.update_views()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Z, Qt.Key_Y) and event.modifiers() & Qt.ControlModifier:
            return 
        self.keys_pressed.add(event.key())
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat():
            self.keys_pressed.discard(event.key())
        super().keyReleaseEvent(event)

    def toggle_snap_to_grid(self, state):
        for view in [self.view_top, self.view_side, self.view_front]:
            view.snap_to_grid_enabled = (state == Qt.Checked)

    def set_grid_size(self, size):
        for view in [self.view_top, self.view_side, self.view_front]:
            view.grid_size = size
            view.update()

    def set_world_size(self, size):
        for view in [self.view_top, self.view_side, self.view_front]:
            view.world_size = size
            view.update()

    def set_brush_display_mode(self, index):
        self.view_3d.brush_display_mode = self.display_mode_combobox.currentText()
        self.view_3d.update()

    def add_brush(self):
        self.save_state()
        new_brush = {'pos': [0, 0, 0], 'size': [64, 64, 64], 'operation': 'subtract' if self.cs_subtract_mode else 'add'}
        self.brushes.append(new_brush)
        # Call set_selected_object to correctly update both selected_brush_index and selected_object
        self.set_selected_object(new_brush)
        self.update_views()

    def update_views(self):
        self.view_3d.update()
        self.view_top.update()
        self.view_side.update()
        self.view_front.update()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())