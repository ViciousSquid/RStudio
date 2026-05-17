from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QFileDialog,
    QDialogButtonBox, QGroupBox, QMessageBox, QComboBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap


class PackageMetadataDialog(QDialog):
    """
    Collects package metadata from the author before export.
    Validates required fields and provides banner image selection.
    """
    
    def __init__(self, current_map_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Game Package")
        self.setMinimumWidth(500)
        self._banner_path: Optional[str] = None
        self._current_map = current_map_path
        
        self._build_ui()
    
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        
        # Info header
        info = QLabel(
            "Export your campaign as a .gamepackage file.\n"
            "All maps, assets, and dependencies will be bundled automatically."
        )
        info.setStyleSheet("color: #888; font-size: 12px;")
        info.setWordWrap(True)
        layout.addWidget(info)
        
        # Metadata form
        form = QFormLayout()
        form.setSpacing(8)
        
        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("My Awesome Campaign")
        form.addRow("Game Title *:", self.title_edit)
        
        self.author_edit = QLineEdit()
        self.author_edit.setPlaceholderText("Your Name")
        form.addRow("Author *:", self.author_edit)
        
        self.version_edit = QLineEdit("1.0.0")
        form.addRow("Version:", self.version_edit)
        
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("Describe your campaign...")
        self.desc_edit.setMaximumHeight(100)
        form.addRow("Description:", self.desc_edit)
        
        # Start map selection
        self.start_map_combo = QComboBox()
        self.start_map_combo.setEditable(True)
        self.start_map_combo.addItem(self._current_map)
        self.start_map_combo.setCurrentText(self._current_map)
        form.addRow("Start Map:", self.start_map_combo)
        
        layout.addLayout(form)
        
        # Banner image group
        banner_group = QGroupBox("Banner Image (Optional)")
        banner_layout = QHBoxLayout(banner_group)
        
        self.banner_preview = QLabel("No image selected")
        self.banner_preview.setFixedSize(200, 100)
        self.banner_preview.setStyleSheet("background: #333; border: 2px dashed #555;")
        self.banner_preview.setAlignment(Qt.AlignCenter)
        banner_layout.addWidget(self.banner_preview)
        
        banner_btn_layout = QVBoxLayout()
        self.select_banner_btn = QPushButton("Select Image...")
        self.select_banner_btn.clicked.connect(self._select_banner)
        self.clear_banner_btn = QPushButton("Clear")
        self.clear_banner_btn.clicked.connect(self._clear_banner)
        banner_btn_layout.addWidget(self.select_banner_btn)
        banner_btn_layout.addWidget(self.clear_banner_btn)
        banner_btn_layout.addStretch()
        banner_layout.addLayout(banner_btn_layout)
        
        layout.addWidget(banner_group)
        
        # Buttons
        btn_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        btn_box.accepted.connect(self._validate_and_accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)
    
    def _select_banner(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Banner Image", "", 
            "Images (*.png *.jpg *.jpeg *.bmp)"
        )
        if path:
            self._banner_path = path
            pixmap = QPixmap(path)
            scaled = pixmap.scaled(200, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.banner_preview.setPixmap(scaled)
    
    def _clear_banner(self):
        self._banner_path = None
        self.banner_preview.setText("No image selected")
        self.banner_preview.setPixmap(QPixmap())
    
    def _validate_and_accept(self):
        if not self.title_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Game Title is required.")
            return
        if not self.author_edit.text().strip():
            QMessageBox.warning(self, "Validation Error", "Author Name is required.")
            return
        self.accept()
    
    def get_metadata(self) -> dict:
        """Return collected metadata as dict for manifest.json."""
        return {
            "package_version": self.version_edit.text() or "1.0.0",
            "title": self.title_edit.text().strip(),
            "author": self.author_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "start_map": self.start_map_combo.currentText(),
            "banner": "assets/package_banner.png" if self._banner_path else None,
            "banner_source_path": self._banner_path
        }