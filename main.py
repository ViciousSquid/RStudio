import sys
import os
import shutil
import argparse
from PyQt5.QtWidgets import QApplication, QSplashScreen
from PyQt5.QtGui import QPixmap
from editor.main_window import MainWindow

# --- NEW FUNCTION ---
def clean_pycache():
    """
    Finds and deletes all '__pycache__' folders recursively
    from the script's root directory.
    """
    project_root = os.path.dirname(os.path.abspath(__file__))
    print(f"🧹 Starting cleanup from root: {project_root}")

    for root, dirs, files in os.walk(project_root):
        if '__pycache__' in dirs:
            pycache_path = os.path.join(root, '__pycache__')
            print(f"🗑️ Found and removing: {pycache_path}")
            try:
                shutil.rmtree(pycache_path)
            except OSError as e:
                print(f"Error removing {pycache_path}: {e}")
    print("✨ Cleanup complete.")

# --- Dark Theme Stylesheet (remains the same) ---
dark_stylesheet = """
    QWidget {
        background-color: #2b2b2b;
        color: #f0f0f0;
        border: none;
    }
    QMainWindow {
        background-color: #3c3c3c;
    }
    QDockWidget {
        background-color: #3c3c3c;
        titlebar-close-icon: url(close.png);
        titlebar-normal-icon: url(float.png);
    }
    QDockWidget::title {
        text-align: left;
        background: #555;
        padding-left: 5px;
        padding-top: 3px;
        padding-bottom: 3px;
    }
    QMenuBar {
        background-color: #4a4a4a;
        color: #f0f0f0;
    }
    QMenuBar::item {
        background-color: #4a4a4a;
        color: #f0f0f0;
    }
    QMenuBar::item:selected {
        background-color: #0078d7;
    }
    QMenu {
        background-color: #4a4a4a;
        border: 1px solid #000;
    }
    QMenu::item:selected {
        background-color: #0078d7;
    }
    QToolBar {
        background-color: #4a4a4a;
        border: none;
    }
    QPushButton {
        background-color: #555;
        color: #f0f0f0;
        border: 1px solid #666;
        padding: 5px;
        min-width: 50px;
    }
    QPushButton:hover {
        background-color: #6a6a6a;
    }
    QPushButton:pressed {
        background-color: #0078d7;
    }
    QTabWidget::pane {
        border-top: 2px solid #555;
    }
    QTabBar::tab {
        background: #444;
        color: #ccc;
        border: 1px solid #222;
        padding: 5px;
    }
    QTabBar::tab:selected {
        background: #0078d7;
        color: white;
    }
    QStatusBar {
        background-color: #4a4a4a;
    }
    QSpinBox, QComboBox, QLineEdit {
        background-color: #444;
        color: #f0f0f0;
        border: 1px solid #666;
        padding: 3px;
    }
    QSpinBox::up-button, QSpinBox::down-button {
        subcontrol-origin: border;
        width: 16px;
        border-left: 1px solid #666;
        background-color: #555;
    }
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {
        background-color: #6a6a6a;
    }
    QSpinBox::up-button:pressed, QSpinBox::down-button:pressed {
        background-color: #0078d7;
    }
    QSpinBox::up-arrow {
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 6px solid #f0f0f0;
        width: 0px;
        height: 0px;
    }
    QSpinBox::down-arrow {
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 6px solid #f0f0f0;
        width: 0px;
        height: 0px;
    }
    QCheckBox::indicator {
        width: 13px;
        height: 13px;
    }
    QFrame {
        border: 1px solid #555;
    }
"""

if __name__ == "__main__":
    # --- NEW ARGUMENT PARSING LOGIC ---
    parser = argparse.ArgumentParser(description="RStudio development tools")
    parser.add_argument(
        '-c', '--clean',
        action='store_true',
        help="Checks for and deletes all '__pycache__' folders on startup."
    )
    args = parser.parse_args()

    if args.clean:
        clean_pycache()
    # ------------------------------------

    app = QApplication(sys.argv)
    
    # Apply the global dark stylesheet
    app.setStyleSheet(dark_stylesheet)
    
    # Create and show the splash screen
    splash_pixmap = QPixmap('assets/splash.png')
    splash = QSplashScreen(splash_pixmap)
    splash.show()
    app.processEvents() # Added to ensure splash screen is drawn immediately
    
    main_win = MainWindow()
    main_win.show()
    
    # Close the splash screen once the main window is shown
    splash.finish(main_win)
    
    sys.exit(app.exec_())