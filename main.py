import sys
from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtCore import Qt
from editor.main_window import MainWindow # Changed import to MainWindow
from editor.things import Light

if __name__ == '__main__':
    # Set high DPI scaling attribute before creating the application
    # QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    # QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon("assets/icon.png"))

    # Load the pixmap for the Light class.
    try:
        Light.pixmap = QPixmap("assets/light.png")
    except Exception as e:
        print(f"Could not load light.png: {e}")
        Light.pixmap = None

    # Create and show the main window
    main_window = MainWindow() # Changed instantiation to MainWindow
    main_window.show()
    
    sys.exit(app.exec_())