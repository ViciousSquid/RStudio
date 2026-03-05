import sys
import os
import shutil
import argparse
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QProgressBar
from PyQt5.QtGui import QPixmap, QSurfaceFormat
from PyQt5.QtCore import Qt
from editor.main_window import MainWindow


def clean_pycache():
    """
    Depreceted 
    """
    pass

class ProgressSplashScreen(QWidget):
    """Custom splash screen with uniform progress bar."""
    def __init__(self, pixmap_path):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        
        # Load splash image
        pixmap = QPixmap(pixmap_path)
        
        # Main layout
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        
        # Image container
        self.image_label = QLabel()
        self.image_label.setPixmap(pixmap)
        layout.addWidget(self.image_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: none;
                background-color: #2b2b2b;
                color: white;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #007acc;
            }
        """)
        layout.addWidget(self.progress_bar)
        
        # Center on screen
        self.center_on_screen()

    def center_on_screen(self):
        screen_geometry = QApplication.desktop().screenGeometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)

    def set_progress(self, value, message):
        self.progress_bar.setValue(value)
        self.progress_bar.setFormat(f"{message} ({value}%)")
        QApplication.processEvents()

    def finish(self, main_window):
        self.close()

# Dark theme stylesheet
dark_stylesheet = """
    QMainWindow {
        background-color: #2b2b2b;
    }
    QWidget {
        background-color: #2b2b2b;
        color: #e0e0e0;
        font-family: "Segoe UI", Arial, sans-serif;
    }
    QPushButton {
        background-color: #3c3f41;
        border: 1px solid #555;
        padding: 5px;
        min-width: 60px;
    }
    QPushButton:hover {
        background-color: #4b4d4d;
    }
    QPushButton:pressed {
        background-color: #2b2b2b;
    }
    QLineEdit, QTextEdit, QSpinBox, QComboBox {
        background-color: #3c3f41;
        border: 1px solid #555;
        color: #e0e0e0;
        padding: 2px;
    }
    QMenuBar {
        background-color: #3c3f41;
        color: #e0e0e0;
    }
    QMenuBar::item:selected {
        background-color: #4b4d4d;
    }
    QMenu {
        background-color: #3c3f41;
        color: #e0e0e0;
        border: 1px solid #555;
    }
    QMenu::item:selected {
        background-color: #4b4d4d;
    }
    QDockWidget {
        titlebar-close-icon: url(assets/close.png);
        titlebar-normal-icon: url(assets/undock.png);
    }
    QDockWidget::title {
        background-color: #3c3f41;
        padding-left: 10px;
        padding-top: 4px;
    }
    QScrollBar:vertical {
        border: none;
        background: #2b2b2b;
        width: 12px;
        margin: 0px;
    }
    QScrollBar::handle:vertical {
        background: #4b4d4d;
        min-height: 20px;
        border-radius: 6px;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    QTabWidget::pane {
        border: 1px solid #555;
    }
    QTabBar::tab {
        background-color: #3c3f41;
        padding: 8px 12px;
        border-right: 1px solid #555;
    }
    QTabBar::tab:selected {
        background-color: #2b2b2b;
        border-bottom: 2px solid #007acc;
    }
    QStatusBar {
        background-color: #3c3f41;
        color: #e0e0e0;
    }
    QProgressBar {
        border: 1px solid #555;
        border-radius: 3px;
        text-align: center;
    }
    QProgressBar::chunk {
        background-color: #007acc;
    }
    QFrame {
        border: 1px solid #555;
    }
"""

if __name__ == "__main__":
    # ---------------------------------------------------------
    # NUITKA PATH RESOLUTION LOGIC
    # ---------------------------------------------------------
    if getattr(sys, 'frozen', False) or "__compiled__" in globals():
        # Running as a compiled EXE: The root directory is where the EXE lives
        root_directory = os.path.dirname(sys.executable)
    else:
        # Running as a Python script: The root directory is the file location
        root_directory = os.path.dirname(os.path.abspath(__file__))

    # Force the Working Directory to be the root folder.
    # Without this, 'assets/splash.png' will fail to load when double-clicking the EXE.
    os.chdir(root_directory)
    # ---------------------------------------------------------

    # Print version first thing
    try:
        version_file_path = os.path.join(root_directory, 'editor/version.txt')
        with open(version_file_path, 'r') as f:
            version = f.read().strip()
            print(f"       +++ RStudio {version}")
    except FileNotFoundError:
        print("Version file not found")

    # Create application first
    app = QApplication(sys.argv)
    app.setStyleSheet(dark_stylesheet)

    # Create and show splash screen IMMEDIATELY
    # Using relative path which is now safe due to os.chdir()
    splash = ProgressSplashScreen('assets/splash.png')
    splash.show()
    splash.set_progress(5, "Configuring OpenGL...")

    # Set OpenGL format BEFORE any GL widget is created
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    splash.set_progress(15, "Loading editor modules...")

    # Clean pycache (logic handles skipping if compiled)
    clean_pycache()

    splash.set_progress(25, "Building editor UI...")

    # NOTE: Shader compilation happens inside MainWindow -> Renderer.__init__.
    # Renderer accepts an optional progress_callback kwarg (see renderer.py),
    # but we cannot pass it through MainWindow without editing that file too.
    # The performance optimisations (normalMatrix, inverseModel, reduced FBM)
    # are all active regardless — the callback only affects splash bar labels.
    window = MainWindow(root_directory)

    splash.set_progress(80, "Initialising scene...")
    splash.set_progress(90, "Building UI layout...")
    splash.set_progress(100, "Ready.")

    window.show()
    splash.finish(window)

    sys.exit(app.exec_())