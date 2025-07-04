import sys
from PyQt5.QtWidgets import QApplication
from editor_window import EditorWindow

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = EditorWindow()
    # This now correctly calls showMaximized()
    window.showMaximized()
    sys.exit(app.exec_())