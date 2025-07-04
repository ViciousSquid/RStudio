import sys
import os
from PyQt5 import QtWidgets as _QtWidgets
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QSplitter, QToolBar, QLabel, QSpinBox, QCheckBox, QAction,
    QComboBox, QMessageBox, QDockWidget, QGridLayout, QLineEdit
)
from PyQt5.QtCore import Qt, QSettings, QTimer

from editor.view_2d import View2D
from engine.qt_game_view import QtGameView

class EditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RooStudio")
        self.setMinimumSize(1280, 1024)

        # --- Attributes ---
        self.brushes = []
        self.selected_brush_index = -1
        self.keys_pressed = set()
        self.is_first_show = True

        # --- UI Setup ---
        self.setDockNestingEnabled(True)
        self.create_views()
        self.create_toolbars_and_docks()
        self.setCentralWidget(QWidget(self))

        # --- Debug Window ---
        self.debug_window = self.create_debug_window()
        self.debug_timer = QTimer(self)
        self.debug_timer.setInterval(100)
        self.debug_timer.timeout.connect(self.update_debug_info)
        
        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event):
        """Apply layout settings on the first time the window is shown."""
        super().showEvent(event)
        if self.is_first_show:
            QTimer.singleShot(0, self.load_layout)
            self.is_first_show = False
            
    def create_debug_window(self):
        window = QWidget(self, Qt.Window)
        window.setWindowTitle("View Geometry")
        layout = QGridLayout(window)
        self.debug_fields = {
            '3D View': QLineEdit(readOnly=True), 'Top View': QLineEdit(readOnly=True),
            'Front View': QLineEdit(readOnly=True), 'Side View': QLineEdit(readOnly=True)
        }
        for i, (name, field) in enumerate(self.debug_fields.items()):
            layout.addWidget(QLabel(name + ":"), i, 0)
            layout.addWidget(field, i, 1)
        return window

    def toggle_debug_window(self):
        if self.debug_window.isVisible():
            self.debug_window.hide()
            self.debug_timer.stop()
        else:
            self.update_debug_info()
            self.debug_window.show()
            self.debug_timer.start()

    def update_debug_info(self):
        views = {
            '3D View': self.dock_3d, 'Top View': self.view_top,
            'Front View': self.view_front, 'Side View': self.view_side
        }
        for name, view in views.items():
            if view and view.isVisible():
                geo = view.geometry()
                self.debug_fields[name].setText(f"x:{geo.x()}, y:{geo.y()}, w:{geo.width()}, h:{geo.height()}")

    def create_views(self):
        self.view_3d = QtGameView(self)
        self.view_top = View2D(self, "top")
        self.view_front = View2D(self, "front")
        self.view_side = View2D(self, "side")

    def create_toolbars_and_docks(self):
        # --- Menubar ---
        menubar = self.menuBar()
        edit_menu, view_menu = menubar.addMenu('Edit'), menubar.addMenu('View')
        
        undo_action = QAction('Undo', self, shortcut='Ctrl+Z')
        redo_action = QAction('Redo', self, shortcut='Ctrl+Y')
        save_layout_action = QAction('Save Layout', self, triggered=self.save_layout)
        reset_layout_action = QAction('Reset Layout', self, triggered=self.reset_layout)
        debug_action = QAction('Show Geometry Panel', self, shortcut="Alt+D", triggered=self.toggle_debug_window)
        
        edit_menu.addActions([undo_action, redo_action])
        view_menu.addActions([save_layout_action, reset_layout_action, debug_action])
        
        # --- Toolbars ---
        top_toolbar = QToolBar("Main Tools")
        top_toolbar.setObjectName("MainToolbar")
        self.addToolBar(top_toolbar)
        
        top_toolbar.addAction(QAction("Hollow", self))
        top_toolbar.addAction(QAction("Subtract", self, checkable=True))
        top_toolbar.addSeparator()
        top_toolbar.addActions([undo_action, redo_action])

        bottom_toolbar = QToolBar("Grid")
        bottom_toolbar.setObjectName("GridToolbar")
        self.addToolBar(Qt.BottomToolBarArea, bottom_toolbar)
        
        bottom_toolbar.addWidget(QCheckBox("Snap to Grid", checked=True))
        bottom_toolbar.addSeparator()
        bottom_toolbar.addWidget(QLabel("Grid Size:"))
        bottom_toolbar.addWidget(QSpinBox(minimum=4, maximum=128, value=16, singleStep=4))
        bottom_toolbar.addSeparator()
        bottom_toolbar.addWidget(QLabel("World Size:"))
        bottom_toolbar.addWidget(QSpinBox(minimum=256, maximum=8192, value=1024, singleStep=256))
        spacer = QWidget()
        spacer.setSizePolicy(_QtWidgets.QSizePolicy.Expanding, _QtWidgets.QSizePolicy.Preferred)
        bottom_toolbar.addWidget(spacer)
        bottom_toolbar.addWidget(QLabel("Display:"))
        bottom_toolbar.addWidget(QComboBox())

        # --- Dock Windows and Splitters ---
        self.dock_3d = QDockWidget("3D View", self)
        self.dock_3d.setObjectName("Dock3D")
        self.dock_3d.setWidget(self.view_3d)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_3d)

        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.addWidget(self.view_top)
        self.bottom_splitter = QSplitter(Qt.Horizontal)
        self.bottom_splitter.addWidget(self.view_front)
        self.bottom_splitter.addWidget(self.view_side)
        self.right_splitter.addWidget(self.bottom_splitter)

        self.dock_2d = QDockWidget("2D Views", self)
        self.dock_2d.setObjectName("Dock2D")
        self.dock_2d.setWidget(self.right_splitter)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_2d)

        self.splitDockWidget(self.dock_3d, self.dock_2d, Qt.Horizontal)

    def load_layout(self):
        """Loads the splitter sizes from config.ini, or applies a default."""
        settings = QSettings("config.ini", QSettings.IniFormat)
        if settings.contains("Layout/main_splitter"):
            main_sizes = [int(s) for s in settings.value("Layout/main_splitter")]
            right_sizes = [int(s) for s in settings.value("Layout/right_splitter")]
            
            # The main horizontal split is between the two docks
            self.resizeDocks([self.dock_3d, self.dock_2d], main_sizes, Qt.Horizontal)
            self.right_splitter.setSizes(right_sizes)
            # The bottom splitter state is implicitly handled by its parent
        else:
            self.apply_default_layout()

    def apply_default_layout(self):
        """Applies a known-good default layout."""
        total_width = self.width()
        self.resizeDocks([self.dock_3d, self.dock_2d], [int(total_width * 0.5), int(total_width * 0.5)], Qt.Horizontal)

        total_height_2d = self.right_splitter.height()
        self.right_splitter.setSizes([total_height_2d // 2, total_height_2d // 2])
        
    def reset_layout(self):
        """Resets the layout to the hard-coded default."""
        self.apply_default_layout()
        QMessageBox.information(self, "Layout Reset", "The layout has been reset to its default state.")
        
    def save_layout(self):
        """Saves the current splitter and dock sizes to the INI file."""
        settings = QSettings("config.ini", QSettings.IniFormat)
        settings.beginGroup("Layout")
        settings.setValue("main_splitter", [self.dock_3d.width(), self.dock_2d.width()])
        settings.setValue("right_splitter", self.right_splitter.sizes())
        settings.endGroup()
        QMessageBox.information(self, "Layout Saved", "The current layout has been saved.")

    def keyPressEvent(self, event):
        self.keys_pressed.add(event.key())

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat(): self.keys_pressed.discard(event.key())

    def closeEvent(self, event):
        self.debug_window.close()
        super().closeEvent(event)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = EditorWindow()
    window.showMaximized()
    sys.exit(app.exec_())