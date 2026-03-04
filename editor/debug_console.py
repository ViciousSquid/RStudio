"""
Debug Console for RStudio

A floating window that displays I/O system debug messages, entity logic events,
and other debug output. Can be toggled via View menu or tilde (~) key.
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton, 
    QLabel, QCheckBox, QComboBox, QFrame
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QUrl
from PyQt5.QtGui import QFont, QTextCursor, QColor, QDesktopServices
from collections import deque
import re


class DebugLogger(QObject):
    """
    Global singleton that collects debug messages and emits signals.
    """
    message_logged = pyqtSignal(str, str)  # (category, message)
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        super().__init__()
        self._initialized = True
        self._enabled = True
        self._buffer = deque(maxlen=1000)
    
    def log(self, category: str, message: str):
        if not self._enabled:
            return
        full_msg = f"[{category}] {message}"
        self._buffer.append((category, full_msg))
        self.message_logged.emit(category, full_msg)
    
    def set_enabled(self, enabled: bool):
        self._enabled = enabled
    
    def is_enabled(self) -> bool:
        return self._enabled
    
    def get_buffer(self):
        return list(self._buffer)
    
    def clear_buffer(self):
        self._buffer.clear()


_debug_logger = None

def get_debug_logger() -> DebugLogger:
    global _debug_logger
    if _debug_logger is None:
        _debug_logger = DebugLogger()
    return _debug_logger


def debug_log(category: str, message: str):
    get_debug_logger().log(category, message)


class DebugConsole(QWidget):
    """
    Floating debug console window – STRICT SINGLETON.
    Minimum font size is now 10 (global minimum enforced here).
    """
    
    CATEGORY_COLORS = {
        'IO': '#4FC3F7',
        'Speaker': '#81C784',
        'Trigger': '#FFB74D',
        'Door': '#BA68C8',
        'Timer': '#F06292',
        'Error': '#EF5350',
        'Warning': '#FFEE58',
        'Info': '#FFFFFF',
    }

    FONT_SIZE_MIN = 10
    FONT_SIZE_MAX = 24
    FONT_SIZE_DEFAULT = 10

    _instance = None

    @classmethod
    def get_instance(cls, parent=None):
        # Check if instance exists AND hasn't been deleted by the C++ side
        if cls._instance is None or not cls._instance.isVisible() and cls._instance.parent() is None and not cls._instance:
            # The check 'not cls._instance' handles cases where the C++ object is deleted
            try:
                # Attempt to access a property to see if it's still alive
                cls._instance.windowTitle() 
            except (RuntimeError, AttributeError):
                cls._instance = None
        
        if cls._instance is None:
            cls._instance = cls(parent)
        
        cls._instance.show()
        cls._instance.raise_()
        cls._instance.activateWindow()
        return cls._instance

    def __init__(self, parent=None):
        if DebugConsole._instance is not None:
            raise RuntimeError("DebugConsole is a singleton. Use DebugConsole.get_instance()")
        
        super().__init__(parent)
        DebugConsole._instance = self

        self.setWindowTitle("Debug Console")
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        
        self.resize(1024, 520)
        
        self.auto_scroll = True
        self.message_count = 0
        self.active_entity_filter = None
        self.font_size = self.FONT_SIZE_DEFAULT
        
        self._setup_ui()
        self._connect_logger()
        self._load_buffer()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        
        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet("color: #888; font-weight: bold;")
        toolbar.addWidget(filter_label)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("All")
        for cat in sorted(self.CATEGORY_COLORS.keys()):
            self.filter_combo.addItem(cat)
        self.filter_combo.setCurrentText("All")
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self.filter_combo.setMinimumWidth(200)
        toolbar.addWidget(self.filter_combo)
        
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color: #444;")
        toolbar.addWidget(sep1)
        
        self.auto_scroll_cb = QCheckBox("Auto-scroll")
        self.auto_scroll_cb.setChecked(True)
        self.auto_scroll_cb.setStyleSheet("color: #aaa;")
        self.auto_scroll_cb.toggled.connect(self._on_auto_scroll_toggled)
        toolbar.addWidget(self.auto_scroll_cb)

        self.filter_empty_cb = QCheckBox("Filter Empty")
        self.filter_empty_cb.setToolTip("Hide messages about 0 connections")
        self.filter_empty_cb.setChecked(True)
        self.filter_empty_cb.setStyleSheet("color: #aaa;")
        self.filter_empty_cb.toggled.connect(self._refresh_console)
        toolbar.addWidget(self.filter_empty_cb)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #444;")
        toolbar.addWidget(sep2)

        font_label = QLabel("Size:")
        font_label.setStyleSheet("color: #888;")
        toolbar.addWidget(font_label)

        font_btn_style = """
            QPushButton {
                background-color: #444; color: #ccc; border: 1px solid #555;
                border-radius: 3px; padding: 4px 8px; font-weight: bold; min-width: 32px;
            }
            QPushButton:hover { background-color: #555; border-color: #F08000; }
        """

        decrease_btn = QPushButton("−")
        decrease_btn.setStyleSheet(font_btn_style)
        decrease_btn.clicked.connect(self._decrease_font_size)
        toolbar.addWidget(decrease_btn)

        self.font_size_label = QLabel(str(self.font_size))
        self.font_size_label.setFixedWidth(30)
        self.font_size_label.setAlignment(Qt.AlignCenter)
        self.font_size_label.setStyleSheet("color: #aaa; font-weight: bold;")
        toolbar.addWidget(self.font_size_label)

        increase_btn = QPushButton("+")
        increase_btn.setStyleSheet(font_btn_style)
        increase_btn.clicked.connect(self._increase_font_size)
        toolbar.addWidget(increase_btn)
        
        toolbar.addStretch()
        
        self.count_label = QLabel("0 messages")
        self.count_label.setStyleSheet("color: #666;")
        toolbar.addWidget(self.count_label)
        
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self.clear)
        clear_btn.setStyleSheet("""
            QPushButton { background-color: #444; color: #ccc; border: 1px solid #555;
                          border-radius: 3px; padding: 3px 8px; }
            QPushButton:hover { background-color: #555; }
        """)
        toolbar.addWidget(clear_btn)
        
        layout.addLayout(toolbar)
        
        self.console = QTextBrowser()
        self.console.setReadOnly(True)
        self.console.setOpenLinks(False)
        self.console.anchorClicked.connect(self._on_anchor_clicked)
        self.console.setStyleSheet("""
            QTextBrowser {
                background-color: #1a1a1a; color: #ddd;
                border: 1px solid #333;
                selection-background-color: #F08000;
            }
        """)
        layout.addWidget(self.console)
        
        self.setStyleSheet("QWidget { background-color: #2b2b2b; }")
        
        self._apply_font_size()

    def _increase_font_size(self):
        if self.font_size < self.FONT_SIZE_MAX:
            self.font_size += 1
            self._apply_font_size()

    def _decrease_font_size(self):
        if self.font_size > self.FONT_SIZE_MIN:   # now enforced at 10
            self.font_size -= 1
            self._apply_font_size()

    def _apply_font_size(self):
        self.font_size_label.setText(str(self.font_size))
        font = QFont("Consolas", self.font_size)
        self.console.setFont(font)
        self.console.document().setDefaultFont(font)
        self._refresh_console()

    def _connect_logger(self):
        logger = get_debug_logger()
        logger.message_logged.connect(self._on_message)
    
    def _load_buffer(self):
        logger = get_debug_logger()
        for category, message in logger.get_buffer():
            self._append_message(category, message)
    
    def _on_message(self, category: str, message: str):
        self._append_message(category, message)

    def _on_anchor_clicked(self, url: QUrl):
        link = url.toString()
        if link.startswith("filter:"):
            entity_name = link.split(":", 1)[1]
            self._apply_entity_filter(entity_name)

    def _apply_entity_filter(self, entity_name):
        if self.active_entity_filter == entity_name:
            self.filter_combo.setCurrentText("All")
            return
        filter_text = f"Entity: {entity_name}"
        idx = self.filter_combo.findText(filter_text)
        if idx == -1:
            self.filter_combo.addItem(filter_text)
            idx = self.filter_combo.count() - 1
        self.filter_combo.setCurrentIndex(idx)

    def _on_filter_changed(self, text):
        count = self.filter_combo.count()
        for i in range(count - 1, -1, -1):
            item_text = self.filter_combo.itemText(i)
            if item_text.startswith("Entity: ") and item_text != text:
                self.filter_combo.removeItem(i)
        if text.startswith("Entity: "):
            self.active_entity_filter = text.split("Entity: ", 1)[1]
        else:
            self.active_entity_filter = None
        self._refresh_console()
    
    def _append_message(self, category: str, message: str):
        current_combo_text = self.filter_combo.currentText()
        if self.active_entity_filter:
            if self.active_entity_filter not in message:
                return
        elif current_combo_text != "All" and category != current_combo_text:
            return

        if self.filter_empty_cb.isChecked():
            if "(0 connections)" in message or "(no connections for output" in message:
                return
        
        color = self.CATEGORY_COLORS.get(category, '#FFFFFF')
        
        ENT_STYLE = 'color: #F08000; font-weight: bold; text-decoration: none;'
        FIRE_STYLE = 'color: #66BB6A; font-weight: bold;'
        EMPTY_STYLE = 'color: #E35335;'
        
        def get_link_html(name):
            return f'<a href="filter:{name}" style="{ENT_STYLE}" title="Click to filter by {name}">{name}</a>'

        message = re.sub(r'(?<!=)\b([a-zA-Z0-9_]+)(?=\.)', lambda m: get_link_html(m.group(1)), message)
        message = re.sub(r'\b([a-zA-Z0-9_]+)(?=\s+\(type=)', lambda m: get_link_html(m.group(1)), message)
        message = re.sub(r"'([a-zA-Z0-9_]+)'", lambda m: f"'{get_link_html(m.group(1))}'", message)
        message = re.sub(r'\b(fire_output)\b', f'<span style="{FIRE_STYLE}">\\1</span>', message)
        message = re.sub(r'(no connections|0 connections)', f'<span style="{EMPTY_STYLE}">\\1</span>', message)
        
        html = f'<span style="color: {color};">{message}</span><br>'
        
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html)
        
        if self.auto_scroll:
            self.console.setTextCursor(cursor)
            self.console.ensureCursorVisible()
        
        self.message_count += 1
        self.count_label.setText(f"{self.message_count} messages")
    
    def _refresh_console(self):
        self.console.clear()
        self.message_count = 0
        logger = get_debug_logger()
        for category, message in logger.get_buffer():
            self._append_message(category, message)
    
    def _on_auto_scroll_toggled(self, checked: bool):
        self.auto_scroll = checked
    
    def clear(self):
        self.console.clear()
        self.message_count = 0
        self.count_label.setText("0 messages")
        get_debug_logger().clear_buffer()
    
    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()
    
    def closeEvent(self, event):
        self.hide()
        event.ignore()