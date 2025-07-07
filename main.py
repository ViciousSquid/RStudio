import sys
from PyQt5.QtWidgets import QApplication
from editor.main_window import MainWindow

# --- Dark Theme Stylesheet ---
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
        border: none;
    }
    QSpinBox::up-arrow, QSpinBox::down-arrow {
        width: 10px;
        height: 10px;
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
    app = QApplication(sys.argv)
    
    # Apply the global dark stylesheet
    app.setStyleSheet(dark_stylesheet)
    
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec_())