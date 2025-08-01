import os
import sys
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, 
                             QHBoxLayout, QGridLayout, QSplitter, QApplication, 
                             QMainWindow)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap

class AssetBrowser(QWidget):
    """
    An asset browser widget with a grid view for assets and a details panel,
    separated by a horizontal splitter.
    """
    def __init__(self, asset_folder, editor=None):
        super().__init__()
        self.asset_folder = asset_folder
        self.editor = editor
        self.selected_item = None

        # --- Main Layout ---
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
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
        right_pane.setMinimumWidth(300)  # Increased from 250
        right_pane.setStyleSheet("background-color: #e8e8e8;")

        self.details_layout = QVBoxLayout(right_pane)
        self.details_layout.setContentsMargins(10, 10, 10, 10)
        
        self.preview_label = QLabel("Select an asset")
        self.preview_label.setFixedSize(256, 256)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background-color: #fff; border: 1px solid #ccc;")
        
        self.name_label = QLabel("Name: ")
        self.name_label.setStyleSheet("color: #333; font-weight: bold; padding-top: 10px;")
        self.name_label.setWordWrap(True)
        
        self.type_label = QLabel("Type: ")
        self.type_label.setStyleSheet("color: #555;")
        
        self.details_layout.addWidget(self.preview_label)
        self.details_layout.addWidget(self.name_label)
        self.details_layout.addWidget(self.type_label)
        self.details_layout.addStretch()
        
        # --- Add Panes to Splitter ---
        self.splitter.addWidget(left_pane)
        self.splitter.addWidget(right_pane)
        
        # Set initial sizes and stretch factors
        self.setMinimumWidth(1024)  # Minimum width for the whole browser
        self.splitter.setSizes([600, 300])  # More balanced initial sizes
        self.splitter.setStretchFactor(0, 2)  # Left pane gets 2/3 of space
        self.splitter.setStretchFactor(1, 1)  # Right pane gets 1/3 of space

        self.refresh_assets()

    def refresh_assets(self):
        # Clear existing widgets from the grid layout
        while self.asset_layout.count():
            child = self.asset_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        textures_path = os.path.join(self.asset_folder, 'assets/textures')
        if not os.path.exists(textures_path):
            print(f"Warning: Asset path not found at '{textures_path}'")
            return

        # --- Populate Grid View ---
        row, col = 0, 0
        num_columns = 4 # Define how many columns the grid should have

        for filename in sorted(os.listdir(textures_path)):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                filepath = os.path.join(textures_path, filename)
                item_widget = AssetItem(filepath, self)
                self.asset_layout.addWidget(item_widget, row, col)
                
                col += 1
                if col >= num_columns:
                    col = 0
                    row += 1

    def select_item(self, item):
        if self.selected_item:
            self.selected_item.deselect()
        self.selected_item = item
        self.selected_item.select()
        
        filepath = item.filepath
        try:
            pixmap = QPixmap(filepath)
            if not pixmap.isNull():
                # Scale pixmap for the larger preview area
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
        
        # Use a QVBoxLayout for a vertical arrangement (icon above text)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(5)
        
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(self.THUMBNAIL_SIZE)
        self.thumbnail.setAlignment(Qt.AlignCenter)
        self.thumbnail.setStyleSheet("background-color: #ddd; border-radius: 4px;")
        
        pixmap = QPixmap(filepath)
        if not pixmap.isNull():
            self.thumbnail.setPixmap(pixmap.scaled(self.THUMBNAIL_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        
        self.name = QLabel(os.path.basename(filepath))
        self.name.setStyleSheet("color: #222;")
        self.name.setAlignment(Qt.AlignCenter)
        self.name.setWordWrap(True)
        
        self.layout.addWidget(self.thumbnail)
        self.layout.addWidget(self.name)
        self.layout.addStretch()

        # Set initial style
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
                    background-color: #f0f0f0;
                    border-radius: 4px;
                }
                AssetItem:hover {
                    background-color: #dceaf9;
                }
            """)
            self.name.setStyleSheet("color: #222;")


# --- Main Application Runner ---
if __name__ == '__main__':
    # NOTE: Create a dummy folder structure and some images for this to run:
    # ./project_folder/
    #   └── assets/
    #       └── textures/
    #           ├── texture1.png
    #           └── texture2.jpg
    
    # Create dummy files for demonstration if they don't exist
    if not os.path.exists("./project_folder/assets/textures"):
        os.makedirs("./project_folder/assets/textures")
        # Create a dummy PNG file
        dummy_pixmap = QPixmap(100, 100)
        dummy_pixmap.fill(Qt.red)
        dummy_pixmap.save("./project_folder/assets/textures/dummy_red.png", "PNG")
        dummy_pixmap.fill(Qt.blue)
        dummy_pixmap.save("./project_folder/assets/textures/dummy_blue.png", "PNG")


    app = QApplication(sys.argv)
    
    main_window = QMainWindow()
    main_window.setWindowTitle("Asset Browser")
    main_window.setGeometry(100, 100, 800, 600) # Set initial window size

    # The 'project_folder' should be the root containing the 'assets' directory
    asset_browser = AssetBrowser('project_folder') 
    
    main_window.setCentralWidget(asset_browser)
    main_window.show()
    
    sys.exit(app.exec_())