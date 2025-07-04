import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QAction, QMenu, QToolBar, QLabel, QSpinBox, QCheckBox, QMessageBox
from PyQt5.QtCore import Qt
from editor.view_2d import View2D
from engine.qt_game_view import QtGameView

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RooStudio")
        self.setGeometry(100, 100, 1280, 800)

        self.brushes = []
        self.selected_brush_index = -1

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self.create_toolbar()
        self.create_menu_bar()  # Add this line to create the menu bar
        self.keys_pressed = set()

        self.splitter = QSplitter(Qt.Horizontal)
        self.layout.addWidget(self.splitter)

        self.view_3d = QtGameView(self)
        self.splitter.addWidget(self.view_3d)

        self.right_splitter = QSplitter(Qt.Vertical)
        self.splitter.addWidget(self.right_splitter)

        self.view_top = View2D(self, 'top')
        self.right_splitter.addWidget(self.view_top)

        self.bottom_splitter = QSplitter(Qt.Horizontal)
        self.right_splitter.addWidget(self.bottom_splitter)

        self.view_side = View2D(self, 'side')
        self.bottom_splitter.addWidget(self.view_side)

        self.view_front = View2D(self, 'front')
        self.bottom_splitter.addWidget(self.view_front)

        self.splitter.setSizes([800, 400])

    def keyPressEvent(self, event):
        """This function is called when a key is pressed."""
        self.keys_pressed.add(event.key())
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """This function is called when a key is released."""
        if not event.isAutoRepeat():
            self.keys_pressed.discard(event.key())
        super().keyReleaseEvent(event)

    def create_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(toolbar)

        self.snap_checkbox = QCheckBox("Snap to Grid")
        self.snap_checkbox.setChecked(True)
        self.snap_checkbox.stateChanged.connect(self.toggle_snap_to_grid)
        toolbar.addWidget(self.snap_checkbox)

        toolbar.addSeparator()

        grid_size_label = QLabel("Grid Size:")
        toolbar.addWidget(grid_size_label)

        self.grid_size_spinbox = QSpinBox()
        self.grid_size_spinbox.setRange(4, 128)
        self.grid_size_spinbox.setValue(16)
        self.grid_size_spinbox.setSingleStep(4)
        self.grid_size_spinbox.valueChanged.connect(self.set_grid_size)
        toolbar.addWidget(self.grid_size_spinbox)

        toolbar.addSeparator()

        world_size_label = QLabel("World Size:")
        toolbar.addWidget(world_size_label)

        self.world_size_spinbox = QSpinBox()
        self.world_size_spinbox.setRange(256, 8192)
        self.world_size_spinbox.setValue(1024)
        self.world_size_spinbox.setSingleStep(256)
        self.world_size_spinbox.valueChanged.connect(self.set_world_size)
        toolbar.addWidget(self.world_size_spinbox)

    def create_menu_bar(self):
        menubar = self.menuBar()
        help_menu = menubar.addMenu('Help')

        about_action = QAction('About RooStudio', self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

    def show_about_dialog(self):
        about_box = QMessageBox(self)
        about_box.setWindowTitle("About")
        about_box.setText("RooStudio ---   \n version 0.1 ---   \n <a href='https://github.com/ViciousSquid/RooStudio'>https://github.com/ViciousSquid/RooStudio</a>")
        about_box.setTextFormat(Qt.RichText)
        about_box.setStandardButtons(QMessageBox.Ok)
        about_box.open()

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

    def add_brush(self):
        new_brush = {'pos': [0, 0, 0], 'size': [64, 64, 64]}
        self.brushes.append(new_brush)
        self.selected_brush_index = len(self.brushes) - 1
        self.update_views()

    def update_views(self):
        self.view_3d.update()
        self.view_top.update()
        self.view_side.update()
        self.view_front.update()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())