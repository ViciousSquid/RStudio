import os
import sys
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame,
                             QHBoxLayout, QGridLayout, QSplitter, QApplication,
                             QMainWindow, QPushButton, QFileDialog)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap

class AssetBrowser(QWidget):
    """
    An asset browser widget with a directory selector, a grid view for assets,
    and a details panel.
    """
    def __init__(self, asset_folder, editor=None):
        super().__init__()
        self.asset_folder = asset_folder
        self.editor = editor
        self.selected_item = None

        # --- Main Layout ---
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(5)

        # --- Browse Button ---
        self.browse_button = QPushButton(os.path.abspath(self.asset_folder))
        self.browse_button.clicked.connect(self.browse_for_folder)
        self.browse_button.setStyleSheet("""
            QPushButton {
                padding: 8px;
                text-align: left;
                background-color: #444;
                border: 1px solid #666;
                color: #f0f0f0;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        self.main_layout.addWidget(self.browse_button)

        # --- Horizontal Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.main_layout.addWidget(self.splitter)

        # --- Left Pane (Asset Grid) ---
        left_pane = QFrame()
        left_pane_layout = QVBoxLayout(left_pane)
        left_pane_layout.setContentsMargins(0, 0, 0, 0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("border: none;")

        self.scroll_content = QWidget()
        self.asset_layout = QGridLayout(self.scroll_content)
        self.asset_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.asset_layout.setSpacing(10)
        self.scroll_area.setWidget(self.scroll_content)

        left_pane_layout.addWidget(self.scroll_area)

        # --- Right Pane (Details Panel) ---
        right_pane = QFrame()
        right_pane.setFrameShape(QFrame.StyledPanel)
        right_pane.setMinimumWidth(300)
        # Matching the dark theme from main.py
        right_pane.setStyleSheet("background-color: #3c3c3c;")

        self.details_layout = QVBoxLayout(right_pane)
        self.details_layout.setContentsMargins(10, 10, 10, 10)

        self.preview_label = QLabel("Select an asset")
        self.preview_label.setFixedSize(256, 256)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background-color: #2b2b2b; border: 1px solid #555;")

        self.name_label = QLabel("Name: ")
        self.name_label.setStyleSheet("color: #f0f0f0; font-weight: bold; padding-top: 10px;")
        self.name_label.setWordWrap(True)

        self.type_label = QLabel("Type: ")
        self.type_label.setStyleSheet("color: #ccc;")

        self.details_layout.addWidget(self.preview_label)
        self.details_layout.addWidget(self.name_label)
        self.details_layout.addWidget(self.type_label)
        self.details_layout.addStretch()

        # --- Add Panes to Splitter ---
        self.splitter.addWidget(left_pane)
        self.splitter.addWidget(right_pane)

        self.setMinimumWidth(1024)
        self.splitter.setSizes([600, 300])
        self.splitter.setStretchFactor(0, 2)
        self.splitter.setStretchFactor(1, 1)

        self.refresh_assets()

    def browse_for_folder(self):
        """Opens a dialog to select a new asset folder."""
        new_folder = QFileDialog.getExistingDirectory(self, "Select Image Directory", self.asset_folder)

        if new_folder and new_folder != self.asset_folder:
            self.asset_folder = new_folder
            self.browse_button.setText(os.path.abspath(self.asset_folder))
            self.refresh_assets()

    def refresh_assets(self):
        """Reloads assets from the current asset_folder into the grid view."""
        # Clear existing widgets from the grid layout
        while self.asset_layout.count():
            child = self.asset_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # MODIFICATION: Use self.asset_folder directly
        textures_path = self.asset_folder
        if not os.path.exists(textures_path) or not os.path.isdir(textures_path):
            print(f"Warning: Asset path not found or not a directory: '{textures_path}'")
            self.preview_label.setText("Directory not found.")
            self.name_label.setText("Name: ")
            self.type_label.setText("Type: ")
            self.selected_item = None
            return

        # --- Populate Grid View ---
        row, col = 0, 0
        num_columns = 4

        for filename in sorted(os.listdir(textures_path)):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                filepath = os.path.join(textures_path, filename)
                item_widget = AssetItem(filepath, self)
                self.asset_layout.addWidget(item_widget, row, col)

                col += 1
                if col >= num_columns:
                    col = 0
                    row += 1

        # Reset details panel
        self.preview_label.setText("Select an asset")
        self.name_label.setText("Name: ")
        self.type_label.setText("Type: ")
        self.selected_item = None


    def select_item(self, item):
        if self.selected_item:
            self.selected_item.deselect()
        self.selected_item = item
        self.selected_item.select()

        filepath = item.filepath
        try:
            pixmap = QPixmap(filepath)
            if not pixmap.isNull():
                self.preview_label.setPixmap(pixmap.scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.preview_label.setText("Preview\nNot Available")
        except Exception:
            self.preview_label.setText("Preview\nError")

        self.name_label.setText(f"Name: {os.path.basename(filepath)}")
        self.type_label.setText("Type: Texture")

    def get_selected_filepath(self):
        return self.selected_item.filepath if self.selected_item else None


class AssetItem(QWidget):
    """
    A clickable widget representing a single asset in the grid.
    Displays a thumbnail and the asset's name underneath.
    """
    THUMBNAIL_SIZE = QSize(100, 100)
    ITEM_SIZE = QSize(120, 140)

    def __init__(self, filepath, browser):
        super().__init__()
        self.filepath = filepath
        self.browser = browser
        self.is_selected = False

        self.setFixedSize(self.ITEM_SIZE)

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(5)

        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(self.THUMBNAIL_SIZE)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setStyleSheet("background-color: #4a4a4a; border-radius: 4px;")

        pixmap = QPixmap(filepath)
        if not pixmap.isNull():
            self.thumbnail.setPixmap(pixmap.scaled(self.THUMBNAIL_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        self.name = QLabel(os.path.basename(filepath))
        self.name.setStyleSheet("color: #f0f0f0;")
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setWordWrap(True)

        self.layout.addWidget(self.thumbnail)
        self.layout.addWidget(self.name)
        self.layout.addStretch()

        self.update_style()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.browser.select_item(self)

    def select(self):
        self.is_selected = True
        self.update_style()

    def deselect(self):
        self.is_selected = False
        self.update_style()

    def update_style(self):
        if self.is_selected:
            self.setStyleSheet("""
                AssetItem {
                    background-color: #0078d7;
                    border-radius: 4px;
                }
            """)
            self.name.setStyleSheet("color: white;")
        else:
            self.setStyleSheet("""
                AssetItem {
                    background-color: #3c3c3c;
                    border-radius: 4px;
                }
                AssetItem:hover {
                    background-color: #4a4a4a;
                }
            """)
            self.name.setStyleSheet("color: #f0f0f0;")


# --- Main Application Runner ---
if __name__ == '__main__':
    # Define the path for dummy assets
    dummy_texture_path = "./project_folder/assets/textures"

    # Create dummy files for demonstration if they don't exist
    if not os.path.exists(dummy_texture_path):
        os.makedirs(dummy_texture_path)
        dummy_pixmap = QPixmap(100, 100)
        dummy_pixmap.fill(Qt.red)
        dummy_pixmap.save(os.path.join(dummy_texture_path, "dummy_red.png"), "PNG")
        dummy_pixmap.fill(Qt.blue)
        dummy_pixmap.save(os.path.join(dummy_texture_path, "dummy_blue.png"), "PNG")


    app = QApplication(sys.argv)
    app.setStyleSheet("""
        QWidget {
            background-color: #2b2b2b;
            color: #f0f0f0;
        }
    """)

    main_window = QMainWindow()
    main_window.setWindowTitle("Asset Browser Standalone Test")
    main_window.setGeometry(100, 100, 1024, 768)

    # MODIFICATION: Pass the specific texture path directly to the browser
    asset_browser = AssetBrowser(dummy_texture_path)

    main_window.setCentralWidget(asset_browser)
    main_window.show()

    sys.exit(app.exec_())