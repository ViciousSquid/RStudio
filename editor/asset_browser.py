import os
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QHBoxLayout
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap

class AssetBrowser(QWidget):
    def __init__(self, asset_folder, editor):
        super().__init__()
        self.asset_folder = asset_folder
        self.editor = editor
        self.selected_item = None

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("background-color: #f0f0f0;") # Overall background

        # Details Panel
        self.details_frame = QFrame()
        self.details_frame.setFrameShape(QFrame.StyledPanel)
        self.details_frame.setFixedHeight(150)
        self.details_frame.setStyleSheet("background-color: #e8e8e8; border-bottom: 1px solid #dcdcdc;")
        self.details_layout = QHBoxLayout(self.details_frame)
        
        self.preview_label = QLabel("Select an asset")
        self.preview_label.setFixedSize(128, 128)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background-color: #fff; border: 1px solid #ccc;")
        
        self.info_layout = QVBoxLayout()
        self.name_label = QLabel("Name: ")
        self.name_label.setStyleSheet("color: #333; font-weight: bold;") # Dark, bold text
        self.type_label = QLabel("Type: ")
        self.type_label.setStyleSheet("color: #555;") # Slightly lighter text
        self.info_layout.addWidget(self.name_label)
        self.info_layout.addWidget(self.type_label)
        self.info_layout.addStretch()
        
        self.details_layout.addWidget(self.preview_label)
        self.details_layout.addLayout(self.info_layout)
        
        # Asset List
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("border: none;")
        self.scroll_content = QWidget()
        self.asset_layout = QVBoxLayout(self.scroll_content)
        self.asset_layout.setAlignment(Qt.AlignTop)
        self.asset_layout.setSpacing(1)
        self.scroll_area.setWidget(self.scroll_content)

        self.main_layout.addWidget(self.details_frame)
        self.main_layout.addWidget(self.scroll_area)
        
        self.refresh_assets()

    def refresh_assets(self):
        while self.asset_layout.count():
            child = self.asset_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        textures_path = os.path.join(self.asset_folder, 'textures')
        if os.path.exists(textures_path):
            for filename in sorted(os.listdir(textures_path)):
                if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp')):
                    item_widget = AssetItem(os.path.join(textures_path, filename), self)
                    self.asset_layout.addWidget(item_widget)

    def select_item(self, item):
        if self.selected_item:
            self.selected_item.deselect()
        self.selected_item = item
        self.selected_item.select()
        
        filepath = item.filepath
        try:
            pixmap = QPixmap(filepath)
            if not pixmap.isNull():
                self.preview_label.setPixmap(pixmap.scaled(128, 128, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.preview_label.setText("Preview\nNot Available")
        except Exception:
            self.preview_label.setText("Preview\nError")
            
        self.name_label.setText(f"Name: {os.path.basename(filepath)}")
        self.type_label.setText("Type: Texture")

    def get_selected_filepath(self):
        return self.selected_item.filepath if self.selected_item else None

class AssetItem(QWidget):
    def __init__(self, filepath, browser):
        super().__init__()
        self.filepath = filepath
        self.browser = browser
        self.is_selected = False
        
        self.setMinimumHeight(28)
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(5, 0, 5, 0)
        
        self.icon = QLabel()
        self.icon.setFixedSize(24, 24)
        pixmap = QPixmap(filepath)
        if not pixmap.isNull():
            self.icon.setPixmap(pixmap.scaled(24, 24, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        
        self.name = QLabel(os.path.basename(filepath))
        self.name.setStyleSheet("color: #222;")
        
        self.layout.addWidget(self.icon)
        self.layout.addWidget(self.name)
        self.layout.addStretch()
        
    def mousePressEvent(self, event):
        self.browser.select_item(self)

    def select(self):
        self.is_selected = True
        self.setStyleSheet("background-color: #0078d7;")
        self.name.setStyleSheet("color: white;")

    def deselect(self):
        self.is_selected = False
        self.setStyleSheet("")
        self.name.setStyleSheet("color: #222;")