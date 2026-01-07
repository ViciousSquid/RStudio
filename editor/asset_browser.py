import os
import sys
import math
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame,
                             QHBoxLayout, QGridLayout, QSplitter, QApplication,
                             QMainWindow, QPushButton, QFileDialog, QTreeView, 
                             QFileSystemModel, QTabWidget, QAbstractItemView,
                             QSizePolicy)
from PyQt5.QtCore import Qt, QSize, QDir, QRect, QPointF
from PyQt5.QtGui import QPixmap, QColor, QPainter, QFont, QIcon, QPen, QPolygonF

# ... (render_obj_thumbnail function remains the same) ...
def render_obj_thumbnail(filepath, width, height):
    """
    Simple software renderer to generate a wireframe thumbnail from an OBJ file.
    """
    vertices = []
    faces = []
    
    try:
        # Limit processing to avoid freezing on huge files
        max_lines = 5000 
        line_count = 0
        
        with open(filepath, 'r') as f:
            for line in f:
                line_count += 1
                if line_count > max_lines: break
                
                if line.startswith('v '):
                    parts = line.split()
                    vertices.append([float(parts[1]), float(parts[2]), float(parts[3])])
                elif line.startswith('f '):
                    parts = line.split()
                    face_idxs = []
                    for p in parts[1:]:
                        idx = int(p.split('/')[0]) - 1
                        face_idxs.append(idx)
                    faces.append(face_idxs)
    except Exception:
        return None

    if not vertices:
        return None

    # Normalize vertices to -1..1 range
    min_v = [float('inf')] * 3
    max_v = [float('-inf')] * 3
    
    for v in vertices:
        for i in range(3):
            if v[i] < min_v[i]: min_v[i] = v[i]
            if v[i] > max_v[i]: max_v[i] = v[i]
            
    center = [(min_v[i] + max_v[i]) / 2 for i in range(3)]
    scale = 0
    for i in range(3):
        scale = max(scale, (max_v[i] - min_v[i]) / 2)
    
    if scale == 0: scale = 1
    
    # 3D Transformation (isometric-ish view)
    # Rotate Y 45, X 30
    import math
    angle_y = math.radians(45)
    angle_x = math.radians(30)
    
    cos_y, sin_y = math.cos(angle_y), math.sin(angle_y)
    cos_x, sin_x = math.cos(angle_x), math.sin(angle_x)
    
    projected_points = []
    
    for v in vertices:
        # Center
        x = (v[0] - center[0]) / scale
        y = (v[1] - center[1]) / scale
        z = (v[2] - center[2]) / scale
        
        # Rotate Y
        rx = x * cos_y - z * sin_y
        rz = x * sin_y + z * cos_y
        
        # Rotate X
        ry = y * cos_x - rz * sin_x
        # rz = y * sin_x + rz * cos_x # Depth not needed for wireframe logic here
        
        # Map to screen
        screen_x = width/2 + rx * (width * 0.4)
        screen_y = height/2 - ry * (height * 0.4) # Invert Y for screen coords
        
        projected_points.append(QPointF(screen_x, screen_y))

    # Draw
    pixmap = QPixmap(width, height)
    pixmap.fill(QColor(50, 50, 60))
    
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    
    # Draw Edges (Cyan wireframe)
    pen = QPen(QColor(0, 200, 255))
    pen.setWidthF(1.0)
    painter.setPen(pen)
    
    for face in faces:
        if len(face) < 2: continue
        
        # Check indices bounds
        valid = True
        for idx in face:
            if idx < 0 or idx >= len(projected_points):
                valid = False
                break
        if not valid: continue
        
        poly = QPolygonF()
        for idx in face:
            poly.append(projected_points[idx])
        
        # Close loop
        poly.append(projected_points[face[0]])
        
        painter.drawPolyline(poly)
        
    painter.end()
    return pixmap

# ... (AssetItem class remains the same) ...
class AssetItem(QWidget):
    """
    A widget representing a single asset (file) in the grid view.
    """
    def __init__(self, name, path, browser, is_model=False):
        super().__init__()
        self.name_text = name
        self.file_path = path
        self.browser = browser
        self.is_model = is_model
        
        self.setFixedSize(100, 120)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(2)
        
        # Thumbnail
        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(90, 90)
        self.thumb_label.setAlignment(Qt.AlignCenter)
        self.thumb_label.setStyleSheet("background-color: #333; border-radius: 4px;")
        
        self._load_thumbnail()
        
        layout.addWidget(self.thumb_label)
        
        # Name
        self.name_label = QLabel(name)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setWordWrap(True)
        self.name_label.setStyleSheet("color: #ccc; font-size: 10px;")
        layout.addWidget(self.name_label)
        
        self.selected = False

    def _load_thumbnail(self):
        pixmap = QPixmap()
        
        if self.is_model:
            # 1. Look for .png sidecar
            base_path = os.path.splitext(self.file_path)[0]
            thumb_path = base_path + ".png"
            
            if os.path.exists(thumb_path):
                pixmap.load(thumb_path)
            else:
                # 2. Generate wireframe from OBJ
                generated_pix = render_obj_thumbnail(self.file_path, 90, 90)
                if generated_pix:
                    pixmap = generated_pix
                else:
                    # 3. Fallback text
                    pixmap = QPixmap(90, 90)
                    pixmap.fill(QColor(60, 70, 80))
                    painter = QPainter(pixmap)
                    painter.setPen(QColor(200, 200, 200))
                    font = QFont("Arial", 16, QFont.Bold)
                    painter.setFont(font)
                    painter.drawText(QRect(0, 0, 90, 90), Qt.AlignCenter, "OBJ")
                    painter.end()
        else:
            # Assume image
            pixmap.load(self.file_path)

        if not pixmap.isNull():
            if self.is_model and not os.path.exists(os.path.splitext(self.file_path)[0] + ".png"):
                # Already scaled if generated
                self.thumb_label.setPixmap(pixmap)
            else:
                scaled = pixmap.scaled(90, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.thumb_label.setPixmap(scaled)
        else:
            self.thumb_label.setText("?")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.browser.select_item(self)

    def set_selected(self, selected):
        self.selected = selected
        if selected:
            self.setStyleSheet("""
                AssetItem {
                    background-color: #3c3c3c;
                    border: 1px solid #F08000;
                    border-radius: 4px;
                }
            """)
            self.name_label.setStyleSheet("color: #F08000; font-weight: bold; font-size: 10px;")
        else:
            self.setStyleSheet("""
                AssetItem {
                    background-color: transparent;
                    border: none;
                }
                AssetItem:hover {
                    background-color: #333;
                    border-radius: 4px;
                }
            """)
            self.name_label.setStyleSheet("color: #ccc; font-size: 10px;")


class AssetBrowserTab(QWidget):
    """
    A single tab content for the Asset Browser (e.g., Textures or Models).
    """
    def __init__(self, root_path, file_extensions, editor=None, is_model_tab=False):
        super().__init__()
        self.root_path = root_path
        self.current_asset_folder = root_path
        self.extensions = file_extensions
        self.is_model_tab = is_model_tab
        self.editor = editor
        self.selected_item = None
        self.items = []

        if not os.path.exists(self.current_asset_folder):
            try: os.makedirs(self.current_asset_folder)
            except: pass

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.splitter = QSplitter(Qt.Horizontal)
        self.layout.addWidget(self.splitter)

        # 1. Left Pane
        self.tree_frame = QFrame()
        tree_layout = QVBoxLayout(self.tree_frame)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(0)
        
        folder_name = os.path.basename(os.path.normpath(self.root_path))
        self.home_btn = QPushButton(f"🏠 {folder_name.capitalize()}")
        self.home_btn.setToolTip(f"Go to root {folder_name} folder")
        self.home_btn.clicked.connect(self.go_to_root)
        self.home_btn.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 8px 12px;
                background-color: #333;
                border: none;
                border-bottom: 1px solid #444;
                color: #ddd;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #444;
                color: white;
            }
        """)
        tree_layout.addWidget(self.home_btn)
        
        self.dir_model = QFileSystemModel()
        self.dir_model.setRootPath(self.root_path)
        self.dir_model.setFilter(QDir.NoDotAndDotDot | QDir.AllDirs)
        
        self.tree_view = QTreeView()
        self.tree_view.setModel(self.dir_model)
        self.tree_view.setRootIndex(self.dir_model.index(self.root_path))
        self.tree_view.setHeaderHidden(True)
        self.tree_view.setColumnHidden(1, True)
        self.tree_view.setColumnHidden(2, True)
        self.tree_view.setColumnHidden(3, True)
        self.tree_view.clicked.connect(self.on_tree_clicked)
        self.tree_view.setStyleSheet("""
            QTreeView { background-color: #252525; color: #ddd; border: none; }
            QTreeView::item { padding: 4px; }
            QTreeView::item:selected { background-color: #444; color: white; }
            QTreeView::item:hover { background-color: #333; }
        """)
        tree_layout.addWidget(self.tree_view)
        self.splitter.addWidget(self.tree_frame)

        # 2. Middle Pane
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("background-color: #2b2b2b; border: none;")
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.grid_layout.setSpacing(10)
        self.scroll_area.setWidget(self.grid_container)
        self.splitter.addWidget(self.scroll_area)

        # 3. Right Pane
        self.details_frame = QFrame()
        self.details_frame.setMinimumWidth(250)
        self.details_frame.setStyleSheet("background-color: #333; border-left: 1px solid #444;")
        details_layout = QVBoxLayout(self.details_frame)
        details_layout.setContentsMargins(10, 10, 10, 10)
        
        self.preview_label = QLabel("Select an item")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFixedSize(230, 230)
        self.preview_label.setStyleSheet("background-color: #252525; border: 1px solid #444; border-radius: 4px;")
        details_layout.addWidget(self.preview_label)
        
        self.name_info_label = QLabel("")
        self.name_info_label.setWordWrap(True)
        self.name_info_label.setStyleSheet("color: white; font-weight: bold; margin-top: 10px;")
        details_layout.addWidget(self.name_info_label)
        
        # --- NEW BUTTONS ---
        if self.is_model_tab:
            # Model Button
            self.add_btn = QPushButton("Add to Scene")
            self.add_btn.setStyleSheet(self._get_green_btn_style())
            self.add_btn.clicked.connect(self.add_current_model)
            self.add_btn.setEnabled(False)
            details_layout.addWidget(self.add_btn)
        else:
            # Texture Buttons
            self.apply_btn = QPushButton("Apply to Brush")
            self.apply_btn.setStyleSheet(self._get_green_btn_style())
            self.apply_btn.clicked.connect(self.apply_texture)
            self.apply_btn.setToolTip("Apply texture to the selected brush(es)")
            self.apply_btn.setEnabled(False)
            details_layout.addWidget(self.apply_btn)
            
            self.face_btn = QPushButton("Apply to Face")
            self.face_btn.setCheckable(True)
            self.face_btn.setStyleSheet("""
                QPushButton {
                    background-color: #444;
                    color: white;
                    padding: 8px;
                    border: 1px solid #555;
                    border-radius: 4px;
                    margin-top: 5px;
                }
                QPushButton:checked {
                    background-color: #F08000;
                    border: 1px solid #FF9020;
                }
                QPushButton:hover { background-color: #555; }
            """)
            self.face_btn.clicked.connect(self.toggle_face_mode)
            self.face_btn.setToolTip("Click a face in 3D view to apply this texture")
            self.face_btn.setEnabled(False)
            #details_layout.addWidget(self.face_btn)
        
        details_layout.addStretch()
        self.splitter.addWidget(self.details_frame)
        self.splitter.setSizes([200, 500, 250])
        self.load_directory(self.current_asset_folder)

    def _get_green_btn_style(self):
        return """
            QPushButton {
                background-color: #2E7D32; color: white; font-weight: bold;
                padding: 8px; border: 1px solid #1B5E20; border-radius: 4px; margin-top: 10px;
            }
            QPushButton:hover { background-color: #388E3C; }
            QPushButton:pressed { background-color: #1B5E20; }
            QPushButton:disabled { background-color: #555; color: #888; }
        """

    def go_to_root(self):
        self.load_directory(self.root_path)
        self.tree_view.collapseAll()
        self.tree_view.setCurrentIndex(self.dir_model.index(self.root_path))

    def on_tree_clicked(self, index):
        path = self.dir_model.filePath(index)
        self.load_directory(path)

    def load_directory(self, path):
        self.current_asset_folder = path
        for i in reversed(range(self.grid_layout.count())): 
            self.grid_layout.itemAt(i).widget().setParent(None)
        self.items.clear()
        self.selected_item = None
        self.update_details_pane(None)

        if not os.path.exists(path): return

        try:
            files = os.listdir(path)
            files.sort()
            row, col = 0, 0
            max_cols = 4 
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in self.extensions:
                    full_path = os.path.join(path, f)
                    item = AssetItem(f, full_path, self, is_model=self.is_model_tab)
                    self.grid_layout.addWidget(item, row, col)
                    self.items.append(item)
                    col += 1
                    if col >= max_cols: col, row = 0, row + 1
        except Exception as e:
            print(f"Error: {e}")

    def select_item(self, item):
        if self.selected_item: self.selected_item.set_selected(False)
        self.selected_item = item
        self.selected_item.set_selected(True)
        self.update_details_pane(item)

    def update_details_pane(self, item):
        if not item:
            self.preview_label.setText("Select an item")
            self.preview_label.setPixmap(QPixmap())
            self.name_info_label.setText("")
            self._set_buttons_enabled(False)
            return

        self.name_info_label.setText(item.name_text)
        pixmap = QPixmap()
        if self.is_model_tab:
            base = os.path.splitext(item.file_path)[0]
            if os.path.exists(base + ".png"): pixmap.load(base + ".png")
            else: 
                gen = render_obj_thumbnail(item.file_path, 230, 230)
                pixmap = gen if gen else QPixmap()
        else:
            pixmap.load(item.file_path)
            
        if not pixmap.isNull():
            if self.is_model_tab and not os.path.exists(os.path.splitext(item.file_path)[0] + ".png"):
                self.preview_label.setPixmap(pixmap)
            else:
                self.preview_label.setPixmap(pixmap.scaled(230, 230, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview_label.setText("No Preview")

        self._set_buttons_enabled(True)

    def _set_buttons_enabled(self, enabled):
        if self.is_model_tab and hasattr(self, 'add_btn'):
            self.add_btn.setEnabled(enabled)
        elif not self.is_model_tab:
            if hasattr(self, 'apply_btn'): self.apply_btn.setEnabled(enabled)
            if hasattr(self, 'face_btn'): self.face_btn.setEnabled(enabled)

    def add_current_model(self):
        if self.editor and self.selected_item:
            self.editor.add_model_to_scene(self.selected_item.file_path, [0,0,0], [1,1,1])

    def apply_texture(self):
        """Apply texture to whole brush"""
        if self.editor and hasattr(self.editor, 'apply_texture_to_brush') and self.selected_item:
            # Calculate path relative to the assets root (e.g., 'brick.png' or 'walls/brick.png')
            rel_path = os.path.relpath(self.selected_item.file_path, self.root_path)
            # Ensure forward slashes for cross-platform consistency
            rel_path = rel_path.replace('\\', '/')
            self.editor.apply_texture_to_brush(rel_path)

    def toggle_face_mode(self):
        """Toggle face painting mode in the editor"""
        if self.editor and hasattr(self.editor, 'toggle_face_paint_mode'):
            # The button state is handled by the user clicking, we just sync the editor
            # But the editor might turn it off (e.g. on tool change), so we sync logic there
            self.editor.toggle_face_paint_mode(self.face_btn.isChecked())

class AssetBrowser(QWidget):
    # ... (AssetBrowser class remains largely same, just wrapping tabs) ...
    def __init__(self, initial_path, editor=None):
        super().__init__()
        self.editor = editor
        self.resize(1280, 600)
        self.setMinimumWidth(1000)
        
        if initial_path.endswith("textures"):
            self.assets_root = os.path.dirname(initial_path)
            self.textures_path = initial_path
        else:
            self.assets_root = initial_path
            self.textures_path = os.path.join(initial_path, "textures")
            
        self.models_path = os.path.join(self.assets_root, "models")
        
        for p in [self.textures_path, self.models_path]:
            if not os.path.exists(p):
                try: os.makedirs(p)
                except: pass

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #3d3d3d; background-color: #2b2b2b; }
            QTabBar::tab { background: #1e1e1e; color: #aaa; min-width: 100px; padding: 8px; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; }
            QTabBar::tab:selected { background: #F08000; color: white; font-weight: bold; }
            QTabBar::tab:hover:!selected { background: #333; }
        """)

        self.tab_textures = AssetBrowserTab(self.textures_path, ['.png', '.jpg', '.jpeg', '.tga', '.bmp'], editor)
        self.tabs.addTab(self.tab_textures, "Textures")
        
        self.tab_models = AssetBrowserTab(self.models_path, ['.obj'], editor, is_model_tab=True)
        self.tabs.addTab(self.tab_models, "Models")

    @property
    def selected_item(self):
        w = self.tabs.currentWidget()
        return w.selected_item if w else None
    
    def get_selected_filepath(self):
        item = self.selected_item
        return item.file_path if item else None

if __name__ == '__main__':
    app = QApplication(sys.argv)
    test_root = os.path.join(os.getcwd(), "test_assets")
    tex_dir = os.path.join(test_root, "textures")
    mdl_dir = os.path.join(test_root, "models")
    if not os.path.exists(tex_dir): os.makedirs(tex_dir)
    if not os.path.exists(mdl_dir): os.makedirs(mdl_dir)
    window = QMainWindow()
    browser = AssetBrowser(tex_dir)
    window.setCentralWidget(browser)
    window.resize(1280, 600)
    window.show()
    sys.exit(app.exec_())