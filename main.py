import sys
import os
import shutil
import argparse

os.environ["QT_PLUGIN_PATH"] = ""
os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = ""


# Dark theme
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

    from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QProgressBar
    from PyQt5.QtGui import QPixmap, QSurfaceFormat
    from PyQt5.QtCore import Qt
    from editor.main_window import MainWindow

    # ---------------------------------------------------------
    # PATH RESOLUTION
    # ---------------------------------------------------------
    if getattr(sys, 'frozen', False) or "__compiled__" in globals():
        root_directory = os.path.dirname(sys.executable)
    else:
        root_directory = os.path.dirname(os.path.abspath(__file__))

    os.chdir(root_directory)
    # ---------------------------------------------------------

    # Version print
    try:
        with open(os.path.join(root_directory, 'editor/version.txt'), 'r') as f:
            print(f"       +++ Fio {f.read().strip()}")
    except FileNotFoundError:
        print("Version file not found")

    # Splash class defined AFTER Qt import
    class ProgressSplashScreen(QWidget):
        def __init__(self, pixmap_path):
            super().__init__()
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

            pixmap = QPixmap(pixmap_path)

            layout = QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            self.setLayout(layout)

            self.image_label = QLabel()
            self.image_label.setPixmap(pixmap)
            layout.addWidget(self.image_label)

            self.progress_bar = QProgressBar()
            self.progress_bar.setFixedHeight(35)
            self.progress_bar.setAlignment(Qt.AlignCenter)
            layout.addWidget(self.progress_bar)

            self.center_on_screen()

        def center_on_screen(self):
            screen = QApplication.primaryScreen()
            geo = screen.geometry()
            self.move(
                (geo.width() - self.width()) // 2,
                (geo.height() - self.height()) // 2
            )

        def set_progress(self, value, message):
            self.progress_bar.setValue(value)
            self.progress_bar.setFormat(f"{message} ({value}%)")
            QApplication.processEvents()

        def finish(self, main_window):
            self.close()

    # Create app
    app = QApplication(sys.argv)
    app.setStyleSheet(dark_stylesheet)

    splash = ProgressSplashScreen('assets/splash.png')
    splash.show()
    splash.set_progress(5, "Configuring OpenGL...")

    # OpenGL format
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    fmt.setStencilBufferSize(8)

    import configparser
    config = configparser.ConfigParser()
    config.read('settings.ini')
    vsync = config.getboolean('Display', 'vsync', fallback=True)
    fmt.setSwapInterval(1 if vsync else 0)

    QSurfaceFormat.setDefaultFormat(fmt)

    splash.set_progress(25, "Building editor UI...")

    window = MainWindow(root_directory)

    splash.set_progress(100, "Ready.")

    window.show()
    splash.finish(window)

    sys.exit(app.exec_())
