# main.py
import sys
from PyQt5.QtWidgets import QApplication
from editor_window import MainWindow

def main():
    """
    Main function to run the PyQt5 Level Editor.
    """
    app = QApplication(sys.argv)
    editor = MainWindow()
    editor.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()