from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextBrowser, QPushButton, 
    QLabel, QCheckBox, QComboBox, QFrame, QLineEdit
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QUrl
from PyQt5.QtGui import QFont, QTextCursor, QColor, QDesktopServices
from collections import deque
import re


class DebugLogger(QObject):
    """
    Global singleton that collects debug messages and emits signals.
    This allows the io_system to log without direct widget dependencies.
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
        self._buffer = deque(maxlen=1000)  # Keep last 1000 messages
    
    def log(self, category: str, message: str):
        """Log a message with a category tag."""
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
        """Get all buffered messages."""
        return list(self._buffer)
    
    def clear_buffer(self):
        """Clear the message buffer."""
        self._buffer.clear()


# Global logger instance
_debug_logger = None

def get_debug_logger() -> DebugLogger:
    """Get the global debug logger instance."""
    global _debug_logger
    if _debug_logger is None:
        _debug_logger = DebugLogger()
    return _debug_logger


def debug_log(category: str, message: str):
    """Convenience function to log a debug message."""
    get_debug_logger().log(category, message)


class CommandInput(QLineEdit):
    """Custom line edit that keeps command history (Quake style)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.history = []
        self.history_idx = 0

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Up:
            if self.history and self.history_idx > 0:
                self.history_idx -= 1
                self.setText(self.history[self.history_idx])
        elif event.key() == Qt.Key_Down:
            if self.history and self.history_idx < len(self.history) - 1:
                self.history_idx += 1
                self.setText(self.history[self.history_idx])
            elif self.history_idx == len(self.history) - 1:
                self.history_idx = len(self.history)
                self.clear()
        else:
            super().keyPressEvent(event)
            
    def add_history(self, command):
        if command and (not self.history or self.history[-1] != command):
            self.history.append(command)
        self.history_idx = len(self.history)


class DebugConsole(QWidget):
    """
    Floating debug console window for viewing I/O and entity logic messages.
    """
    command_issued = pyqtSignal(str) 

    # Category colors
    CATEGORY_COLORS = {
        'IO': '#4FC3F7',       # Light blue
        'Speaker': '#81C784',   # Light green
        'Trigger': '#FFB74D',   # Orange
        'Door': '#BA68C8',      # Purple
        'Timer': '#F06292',     # Pink
        'Error': '#EF5350',     # Red
        'Warning': '#FFEE58',   # Yellow
        'Info': '#FFFFFF',      # White
    }

    FONT_SIZE_MIN = 6
    FONT_SIZE_MAX = 24
    FONT_SIZE_DEFAULT = 9

    _instance = None

    @classmethod
    def get_instance(cls, parent=None):
        """Return the singleton DebugConsole, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls(parent)
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        # Track enabled categories
        self.enabled_categories = set(self.CATEGORY_COLORS.keys())
        
        # Auto-scroll flag
        self.auto_scroll = True
        
        # Message count
        self.message_count = 0

        # Current Entity Filter (None means show all)
        self.active_entity_filter = None

        # Font size
        self.font_size = self.FONT_SIZE_DEFAULT
        
        self._setup_ui()
        self._connect_logger()
        
        # Load any buffered messages
        self._load_buffer()
    
    def _setup_ui(self):
        """Set up the console UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        
        # Top toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        
        # Filter label
        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet("color: #888; font-weight: bold;")
        toolbar.addWidget(filter_label)
        
        # Category filter dropdown
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("All")
        for cat in sorted(self.CATEGORY_COLORS.keys()):
            self.filter_combo.addItem(cat)
        self.filter_combo.setCurrentText("All")
        self.filter_combo.currentTextChanged.connect(self._on_filter_changed)
        self.filter_combo.setMinimumWidth(200)
        toolbar.addWidget(self.filter_combo)
        
        # Separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.VLine)
        sep1.setStyleSheet("color: #444;")
        toolbar.addWidget(sep1)
        
        # Auto-scroll checkbox
        self.auto_scroll_cb = QCheckBox("Auto-scroll")
        self.auto_scroll_cb.setChecked(True)
        self.auto_scroll_cb.setStyleSheet("color: #aaa;")
        self.auto_scroll_cb.toggled.connect(self._on_auto_scroll_toggled)
        toolbar.addWidget(self.auto_scroll_cb)

        # Filter Empty Checkbox
        self.filter_empty_cb = QCheckBox("Filter Empty")
        self.filter_empty_cb.setToolTip("Hide messages about 0 connections")
        self.filter_empty_cb.setChecked(True) 
        self.filter_empty_cb.toggled.connect(self._refresh_console)
        toolbar.addWidget(self.filter_empty_cb)

        # Separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.VLine)
        sep2.setStyleSheet("color: #444;")
        toolbar.addWidget(sep2)

        # Entity type filters
        filter_label2 = QLabel("Hide:")
        filter_label2.setStyleSheet("color: #888; font-weight: bold;")
        toolbar.addWidget(filter_label2)

        self.hide_movers_cb = QCheckBox("Movers")
        self.hide_movers_cb.setToolTip("Hide I/O messages from Movers")
        self.hide_movers_cb.toggled.connect(self._refresh_console)
        toolbar.addWidget(self.hide_movers_cb)

        self.hide_triggers_cb = QCheckBox("Triggers")
        self.hide_triggers_cb.setToolTip("Hide I/O messages from Triggers")
        self.hide_triggers_cb.toggled.connect(self._refresh_console)
        toolbar.addWidget(self.hide_triggers_cb)

        self.hide_doors_cb = QCheckBox("Doors")
        self.hide_doors_cb.setToolTip("Hide I/O messages from Doors")
        self.hide_doors_cb.toggled.connect(self._refresh_console)
        toolbar.addWidget(self.hide_doors_cb)

        # Separator
        sep3 = QFrame()
        sep3.setFrameShape(QFrame.VLine)
        sep3.setStyleSheet("color: #444;")
        toolbar.addWidget(sep3)

        # Font size controls
        font_label = QLabel("Size:")
        font_label.setStyleSheet("color: #888;")
        toolbar.addWidget(font_label)

        font_btn_style = """
            QPushButton {
                background-color: #444;
                color: #ccc;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 3px 6px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #555;
                border-color: #F08000;
            }
            QPushButton:pressed {
                background-color: #333;
            }
        """

        decrease_btn = QPushButton("−")
        decrease_btn.setFixedWidth(28)
        decrease_btn.setToolTip("Decrease font size")
        decrease_btn.clicked.connect(self._decrease_font_size)
        decrease_btn.setStyleSheet(font_btn_style)
        toolbar.addWidget(decrease_btn)

        self.font_size_label = QLabel(str(self.font_size))
        self.font_size_label.setFixedWidth(24)
        self.font_size_label.setAlignment(Qt.AlignCenter)
        self.font_size_label.setStyleSheet("color: #aaa;")
        toolbar.addWidget(self.font_size_label)

        increase_btn = QPushButton("+")
        increase_btn.setFixedWidth(28)
        increase_btn.setToolTip("Increase font size")
        increase_btn.clicked.connect(self._increase_font_size)
        increase_btn.setStyleSheet(font_btn_style)
        toolbar.addWidget(increase_btn)
        
        toolbar.addStretch()
        
        # Message count label
        self.count_label = QLabel("0 messages")
        self.count_label.setStyleSheet("color: #666;")
        toolbar.addWidget(self.count_label)
        
        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(60)
        clear_btn.clicked.connect(self.clear)
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #444;
                color: #ccc;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 3px 8px;
            }
            QPushButton:hover {
                background-color: #555;
            }
        """)
        toolbar.addWidget(clear_btn)
        
        layout.addLayout(toolbar)
        
        # Console text area (Switching to QTextBrowser to support links/clicks)
        self.console = QTextBrowser()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", self.font_size))
        self.console.setOpenLinks(False) # Handle links manually via signal
        self.console.anchorClicked.connect(self._on_anchor_clicked)
        self.console.setStyleSheet("""
            QTextBrowser {
                background-color: #1a1a1a;
                color: #ddd;
                border: 1px solid #333;
                selection-background-color: #F08000;
            }
        """)
        layout.addWidget(self.console)
        
        # --- Command input area at the bottom ---
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        
        prompt_label = QLabel("]")
        prompt_label.setStyleSheet("color: #F08000; font-weight: bold; font-family: Consolas; font-size: 14px;")
        
        self.command_input = CommandInput()
        self.command_input.setPlaceholderText("Enter command...")
        self.command_input.setFont(QFont("Consolas", self.font_size))
        self.command_input.setStyleSheet("""
            QLineEdit {
                background-color: #1a1a1a;
                color: #ddd;
                border: 1px solid #333;
                padding: 4px;
            }
            QLineEdit:focus {
                border: 1px solid #F08000;
            }
        """)
        self.command_input.returnPressed.connect(self._on_command_entered)
        
        input_layout.addWidget(prompt_label)
        input_layout.addWidget(self.command_input)
        layout.addLayout(input_layout)
        
        # Overall widget styling
        self.setStyleSheet("""
            QWidget {
                background-color: #2b2b2b;
            }
            QComboBox {
                background-color: #3a3a3a;
                color: #ddd;
                border: 1px solid #555;
                padding: 3px;
                border-radius: 3px;
            }
            QComboBox:hover {
                border-color: #F08000;
            }
            QComboBox::drop-down {
                border: none;
            }
            QComboBox QAbstractItemView {
                background-color: #3a3a3a;
                color: #ddd;
                selection-background-color: #F08000;
            }
        """)

    # ------------------------------------------------------------------
    # Font size controls
    # ------------------------------------------------------------------

    def _increase_font_size(self):
        """Increase console font size by 1pt and refresh."""
        if self.font_size < self.FONT_SIZE_MAX:
            self.font_size += 1
            self._apply_font_size()

    def _decrease_font_size(self):
        """Decrease console font size by 1pt and refresh."""
        if self.font_size > self.FONT_SIZE_MIN:
            self.font_size -= 1
            self._apply_font_size()

    def _apply_font_size(self):
        """Apply the current font size to the console and reload all HTML."""
        self.font_size_label.setText(str(self.font_size))
        self.console.setFont(QFont("Consolas", self.font_size))
        self.command_input.setFont(QFont("Consolas", self.font_size))
        self._refresh_console()

    # ------------------------------------------------------------------
    
    def _connect_logger(self):
        """Connect to the global debug logger."""
        logger = get_debug_logger()
        logger.message_logged.connect(self._on_message)
    
    def _load_buffer(self):
        """Load any buffered messages that were logged before the console opened."""
        logger = get_debug_logger()
        for category, message in logger.get_buffer():
            self._append_message(category, message)
    
    def _on_message(self, category: str, message: str):
        """Handle a new log message."""
        self._append_message(category, message)

    def _on_command_entered(self):
        """Handle command submission from the input line."""
        cmd = self.command_input.text().strip()
        if not cmd:
            return
            
        # Echo the command to the console exactly like Quake
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(f"<br><span style='color: #F08000; font-weight: bold;'>] {cmd}</span><br>")
        
        # Add to local history and clear the line
        self.command_input.add_history(cmd)
        self.command_input.clear()
        
        # Auto-scroll to show the command we just typed
        if self.auto_scroll:
            self.console.setTextCursor(cursor)
            self.console.ensureCursorVisible()
        
        # Pass the raw string to whatever is listening
        self.command_issued.emit(cmd)

    def _on_anchor_clicked(self, url: QUrl):
        """Handle clicking on an entity name."""
        link = url.toString()
        if link.startswith("filter:"):
            entity_name = link.split(":", 1)[1]
            self._apply_entity_filter(entity_name)

    def _apply_entity_filter(self, entity_name):
        """Updates the dropdown to filter by this entity."""
        
        # If we clicked the same entity that is currently filtered, toggle it off (Reset to All)
        if self.active_entity_filter == entity_name:
            self.filter_combo.setCurrentText("All")
            return

        filter_text = f"Entity: {entity_name}"
        
        # Check if this item already exists in combo, if not add it
        idx = self.filter_combo.findText(filter_text)
        if idx == -1:
            self.filter_combo.addItem(filter_text)
            idx = self.filter_combo.count() - 1
            
        # Select it (this will trigger _on_filter_changed -> _refresh_console)
        self.filter_combo.setCurrentIndex(idx)

    def _on_filter_changed(self, text):
        """Handle filter dropdown changes."""
        
        # Clean up old entity filters if we switched away from them
        count = self.filter_combo.count()
        # Iterate backwards to safely remove
        for i in range(count - 1, -1, -1):
            item_text = self.filter_combo.itemText(i)
            # If it's an entity filter...
            if item_text.startswith("Entity: "):
                # And it's NOT the one we just selected...
                if item_text != text:
                    self.filter_combo.removeItem(i)

        if text.startswith("Entity: "):
            self.active_entity_filter = text.split("Entity: ", 1)[1]
        else:
            self.active_entity_filter = None
            
        self._refresh_console()
    
    def _append_message(self, category: str, message: str):
        """Append a message to the console with highlighting."""
        
        # 1. Check Category Filter vs Entity Filter
        current_combo_text = self.filter_combo.currentText()
        
        # If we are in "Entity: X" mode
        if self.active_entity_filter:
            # We filter OUT messages that don't contain the entity name
            # Simple substring check is usually sufficient for debug logs
            if self.active_entity_filter not in message:
                return
        # If we are in standard Category mode (and not "All")
        elif current_combo_text != "All" and category != current_combo_text:
            return

        # 2. Filter specific entity types (Movers, Triggers, Doors)
        if self.hide_movers_cb.isChecked() or self.hide_triggers_cb.isChecked() or self.hide_doors_cb.isChecked():
            match = re.match(r'^\[IO\]\s+([a-zA-Z0-9_]+)\.', message)
            if match:
                entity_name = match.group(1)
                if self.hide_movers_cb.isChecked() and entity_name.startswith('Mover'):
                    return
                if self.hide_triggers_cb.isChecked() and entity_name.startswith('Trigger'):
                    return
                if self.hide_doors_cb.isChecked() and entity_name.startswith('Door'):
                    return
            # Also filter lines with no entity name (likely unnamed triggers)
            if message.startswith('[IO] .'):
                if self.hide_triggers_cb.isChecked():
                    return

        # 3. Check "Filter Empty" Logic
        if self.filter_empty_cb.isChecked():
            if "(0 connections)" in message:
                return
            if "(no connections for output" in message:
                return
        
        # Get color for category
        color = self.CATEGORY_COLORS.get(category, '#FFFFFF')
        
        # --- HIGHLIGHTING LOGIC ---
        
        # Define styles
        # NOTE: Text-decoration:none prevents underline, but cursor becomes hand due to <a> tag
        ENT_STYLE = 'color: #F08000; font-weight: bold; text-decoration: none;'
        FIRE_STYLE = 'color: #66BB6A; font-weight: bold;'
        EMPTY_STYLE = 'color: #E35335;'
        
        # Create a replacement pattern that wraps the name in an anchor tag
        # href="filter:NAME" is captured by _on_anchor_clicked
        def get_link_html(name):
            return f'<a href="filter:{name}" style="{ENT_STYLE}" title="Click to filter by {name}">{name}</a>'

        # Apply Regex substitutions
        
        # A. Entity Names: "Name.Input"
        # We use a lambda to insert the captured name into the HTML format
        message = re.sub(
            r'(?<!=)\b([a-zA-Z0-9_]+)(?=\.)', 
            lambda m: get_link_html(m.group(1)),
            message
        )
        
        # B. Entity Names: "Name (type=...)"
        message = re.sub(
            r'\b([a-zA-Z0-9_]+)(?=\s+\(type=)', 
            lambda m: get_link_html(m.group(1)),
            message
        )
        
        # C. Entity Names: "'Name'"
        message = re.sub(
            r"'([a-zA-Z0-9_]+)'", 
            lambda m: f"'{get_link_html(m.group(1))}'", 
            message
        )

        # D. "fire_output" -> Green
        message = re.sub(
            r'\b(fire_output)\b',
            f'<span style="{FIRE_STYLE}">\\1</span>',
            message
        )

        # E. "no connections" -> Red/Orange
        message = re.sub(
            r'(no connections|0 connections)',
            f'<span style="{EMPTY_STYLE}">\\1</span>',
            message
        )

        # F. Style [Delayed] prefix (orange)
        message = re.sub(r'\[Delayed\]', '<span style="color: #FFB74D;">[Delayed]</span>', message)

        # G. Style arrow -> as green arrow character
        message = re.sub(r' -> ', ' <span style="color: #66BB6A;">→</span> ', message)
        
        # ---------------------------
        
        # Format with HTML coloring for the main message body
        html = f'<span style="color: {color};">{message}</span><br>'
        
        # Append to console
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html)
        
        # Auto-scroll if enabled
        if self.auto_scroll:
            self.console.setTextCursor(cursor)
            self.console.ensureCursorVisible()
        
        # Update count
        self.message_count += 1
        self.count_label.setText(f"{self.message_count} messages")
    
    def _refresh_console(self):
        """Reload console messages from buffer (triggered by filters or font size change)."""
        self.console.clear()
        self.message_count = 0
        
        logger = get_debug_logger()
        for category, message in logger.get_buffer():
            self._append_message(category, message)
    
    def _on_auto_scroll_toggled(self, checked: bool):
        """Handle auto-scroll toggle."""
        self.auto_scroll = checked
    
    def clear(self):
        """Clear the console and buffer."""
        self.console.clear()
        self.message_count = 0
        self.count_label.setText("0 messages")
        get_debug_logger().clear_buffer()
    
    def toggle(self):
        """Toggle visibility of the console."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()
    
    def closeEvent(self, event):
        """Handle close - just hide instead of destroying."""
        self.hide()
        event.ignore()