from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                             QComboBox, QColorDialog, QPushButton,
                             QCheckBox, QGridLayout)
from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtCore import Qt
from editor.things import Thing
from functools import partial

class PropertyEditor(QWidget):
    def __init__(self, parent, editor):
        super().__init__(parent)
        self.editor = editor
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        self.current_object = None
        self.row = 0

    def set_object(self, obj):
        self.clear_layout()
        self.current_object = obj
        if obj is None:
            self.layout.addWidget(QLabel("No object selected."))
            return

        if isinstance(obj, Thing):
            self.populate_for_thing(obj)
        elif isinstance(obj, dict): # For brushes
            self.populate_for_brush(obj)

    def clear_layout(self):
        while self.layout.count():
            child = self.layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        self.row = 0

    def populate_for_thing(self, thing):
        # Display Class Name (read-only)
        self.add_read_only_property("Class", thing.__class__.__name__)

        # Editable Properties
        for key, value in sorted(thing.properties.items()):
            if key in ['type']: # Don't show the internal 'type' string
                continue

            if key == 'color':
                self.add_color_property(thing, key, value)
            elif isinstance(value, bool):
                self.add_bool_property(thing.properties, key, value)
            elif isinstance(value, list):
                self.add_vector_property(thing.properties, key, value)
            else: # Handle strings, ints, floats
                self.add_string_property(thing.properties, key, value)

    def populate_for_brush(self, brush):
        self.add_read_only_property("Type", "Brush")
        self.add_vector_property(brush, 'pos', brush['pos'])
        self.add_vector_property(brush, 'size', brush['size'])
        self.add_combo_box_property(brush, 'operation', ['add', 'subtract'], brush.get('operation', 'add'))

        if brush.get('type') == 'trigger':
            self.add_read_only_property("Trigger", "True")
            trigger_thing = self.editor.get_thing_for_trigger(brush)
            if trigger_thing:
                self.populate_for_thing(trigger_thing)

    def add_property_row(self, label_text, widget):
        grid_layout = self.layout.itemAt(0).layout() if self.row > 0 and self.layout.itemAt(0) else None
        if grid_layout is None:
            grid_layout = QGridLayout()
            grid_layout.setColumnStretch(1, 1)
            self.layout.addLayout(grid_layout)

        label = QLabel(label_text)
        grid_layout.addWidget(label, self.row, 0)
        grid_layout.addWidget(widget, self.row, 1)
        self.row += 1

    def add_read_only_property(self, key, value):
        self.add_property_row(key.replace('_', ' ').title(), QLineEdit(str(value), readOnly=True))

    def add_color_property(self, obj, key, value):
        color_btn = QPushButton()
        color_btn.clicked.connect(lambda: self.choose_color(obj, key, color_btn))
        self.update_color_button_style(color_btn, value)
        self.add_property_row(key.title(), color_btn)

    def update_color_button_style(self, button, color_value):
        """Updates the button's background color and text."""
        try:
            if isinstance(color_value, list) and len(color_value) == 3:
                r, g, b = color_value
            else:
                r, g, b = 255, 0, 255 # Default to magenta on error
                print(f"Warning: Invalid color format '{color_value}', defaulting to magenta.")

            r, g, b = int(r), int(g), int(b)
            if not (0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255):
                 raise ValueError("RGB values out of range 0-255")

            color = QColor(r, g, b)
            button.setText(f"RGB({r}, {g}, {b})")
            button.setStyleSheet(f"background-color: {color.name()}; color: {get_contrasting_text_color(color).name()};")

        except (ValueError, TypeError) as e:
            print(f"Error processing color value '{color_value}': {e}")
            button.setText("Invalid Color")
            button.setStyleSheet("background-color: #FF00FF;")

    def choose_color(self, obj, key, button):
        """Opens a color dialog and updates the property."""
        current_color_list = obj.properties.get(key, [255, 255, 255])
        initial_color = QColor(*[int(c) for c in current_color_list])

        new_color = QColorDialog.getColor(initial_color, self, "Select Color")
        if new_color.isValid():
            new_color_list = [new_color.red(), new_color.green(), new_color.blue()]
            obj.properties[key] = new_color_list
            self.update_color_button_style(button, new_color_list)
            self.editor.update_views()

    def add_string_property(self, prop_dict, key, value):
        le = QLineEdit(str(value))
        le.editingFinished.connect(lambda: self.update_property_from_string(prop_dict, key, le.text()))
        self.add_property_row(key.replace('_', ' ').title(), le)

    def add_bool_property(self, prop_dict, key, value):
        cb = QCheckBox()
        cb.setChecked(bool(value))
        cb.stateChanged.connect(lambda state, k=key: self.update_property(prop_dict, k, state == Qt.Checked))
        self.add_property_row(key.replace('_', ' ').title(), cb)

    def add_vector_property(self, prop_dict, key, value):
        self.add_property_row(key.replace('_', ' ').title(), VectorEditor(prop_dict, key, value, self.editor))

    def add_combo_box_property(self, prop_dict, key, items, value):
        combo = QComboBox()
        combo.addItems(items)
        combo.setCurrentText(value)
        combo.currentTextChanged.connect(lambda text, k=key: self.update_property(prop_dict, k, text))
        self.add_property_row(key.replace('_', ' ').title(), combo)

    def update_property(self, prop_dict, key, value):
        prop_dict[key] = value
        self.editor.update_views()

    def update_property_from_string(self, prop_dict, key, text_value):
        try:
            value = float(text_value)
            if value.is_integer():
                value = int(value)
        except ValueError:
            value = text_value # Keep as string
        self.update_property(prop_dict, key, value)


class VectorEditor(QWidget):
    def __init__(self, prop_dict, key, values, editor):
        super().__init__()
        self.prop_dict = prop_dict
        self.key = key
        self.editor = editor
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        self.line_edits = []
        for val in values:
            le = QLineEdit(str(val))
            le.editingFinished.connect(self.update_vector)
            self.layout.addWidget(le)
            self.line_edits.append(le)

    def update_vector(self):
        new_values = []
        for le in self.line_edits:
            try:
                # Try to convert to int first, then float
                if float(le.text()).is_integer():
                    new_values.append(int(float(le.text())))
                else:
                    new_values.append(float(le.text()))
            except ValueError:
                new_values.append(0.0) # or handle error appropriately
        self.prop_dict[self.key] = new_values
        self.editor.update_views()

def get_contrasting_text_color(bg_color):
    """Calculates whether black or white text is more readable on a given background color."""
    return QColor(0, 0, 0) if (bg_color.red() * 0.299 + bg_color.green() * 0.587 + bg_color.blue() * 0.114) > 186 else QColor(255, 255, 255)