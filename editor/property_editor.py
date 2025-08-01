from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QSpinBox,
                             QFormLayout, QCheckBox, QComboBox, QPushButton,
                             QHBoxLayout, QColorDialog)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from editor.things import Thing, Light

class PropertyEditor(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.current_object = None
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(self.main_layout)
        
        # Define widget instance variables
        self.locked_checkbox = None
        self.trigger_checkbox = None
        self.target_label = None
        self.target_input = None
        self.type_label = None
        self.type_combo = None

        self.set_object(None)

    def clear_layout(self):
        """Removes all widgets from the main layout."""
        while self.main_layout.count():
            child = self.main_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                # Also clear widgets from child layouts before deleting the layout
                layout = child.layout()
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()

    def set_object(self, obj):
        """Sets the object for the property editor and rebuilds the UI."""
        self.current_object = obj
        self.clear_layout()

        if obj is None:
            self.main_layout.addWidget(QLabel("Nothing selected."))
            return

        # We now use isinstance on the class from brushes.py, not dict
        # Assuming you have `from editor.brushes import Brush`
        # If brush is still a dict, isinstance(obj, dict) is correct.
        if isinstance(obj, dict): # Or `isinstance(obj, Brush)`
            self.populate_for_brush(obj)
        elif isinstance(obj, Thing):
            self.populate_for_thing(obj)

    def populate_for_brush(self, brush):
        """Populates the UI with properties for a brush object."""
        layout = QFormLayout()
        is_locked = brush.get('lock', False)
        is_trigger = brush.get('is_trigger', False)

        # Create Widgets and store them as instance variables
        self.locked_checkbox = QCheckBox()
        self.trigger_checkbox = QCheckBox()
        self.target_label = QLabel("Target:")
        self.target_input = QLineEdit(brush.get('target', ''))
        self.type_label = QLabel("Trigger Type:")
        self.type_combo = QComboBox()
        self.type_combo.addItems(['Once', 'Multiple'])
        
        # Set initial state from brush properties
        self.locked_checkbox.setChecked(is_locked)
        self.trigger_checkbox.setChecked(is_trigger)
        self.type_combo.setCurrentText(brush.get('trigger_type', 'Once'))

        # Add to Layout
        layout.addRow("Lock:", self.locked_checkbox)
        layout.addRow("Is Trigger:", self.trigger_checkbox)
        layout.addRow(self.target_label, self.target_input)
        layout.addRow(self.type_label, self.type_combo)

        # Connect Signals to dedicated handlers
        self.locked_checkbox.toggled.connect(self.on_lock_changed)
        self.trigger_checkbox.toggled.connect(self.on_trigger_changed)
        self.target_input.textChanged.connect(lambda t: self.update_object_prop('target', t))
        self.type_combo.currentTextChanged.connect(lambda t: self.update_object_prop('trigger_type', t))
        
        self.main_layout.addLayout(layout)
        
        # Set the initial UI state based on properties
        self.update_brush_ui_state()

    def update_brush_ui_state(self):
        """Updates the enabled/visible state of brush property widgets."""
        if self.current_object is None:
            return
            
        is_locked = self.current_object.get('lock', False)
        is_trigger = self.current_object.get('is_trigger', False)
        
        self.trigger_checkbox.setEnabled(not is_locked)
        
        show_trigger_fields = is_trigger and not is_locked
        self.target_label.setVisible(show_trigger_fields)
        self.target_input.setVisible(show_trigger_fields)
        self.type_label.setVisible(show_trigger_fields)
        self.type_combo.setVisible(show_trigger_fields)

    def on_lock_changed(self, is_locked):
        """Handler for when the lock checkbox is toggled."""
        if self.current_object is None: return
        
        # 1. Update the data model
        self.current_object['lock'] = is_locked
        
        # 2. Update the UI state within the property editor itself
        self.update_brush_ui_state()
        
        # 3. Notify the rest of the application to update (this triggers the chain reaction)
        self.editor.update_all_ui()

    def on_trigger_changed(self, is_trigger):
        """Handler for when the trigger checkbox is toggled."""
        if self.current_object is None: return
        
        # 1. Update the data model
        self.current_object['is_trigger'] = is_trigger
        
        # 2. Update the UI state within the property editor itself
        self.update_brush_ui_state()
        
        # 3. Notify the rest of the application to update
        self.editor.update_all_ui()

    def populate_for_thing(self, thing):
        """Populates the UI with properties for a Thing object."""
        # This function remains unchanged
        layout = QFormLayout()
        
        for key, value in sorted(thing.properties.items()):
            label_text = key.replace('_', ' ').title() + ":"
            
            if isinstance(thing, Light) and key == 'color':
                self.add_color_picker_widget(layout, thing, key)
            elif isinstance(value, bool):
                widget = QCheckBox(); widget.setChecked(value)
                widget.stateChanged.connect(lambda state, k=key: self.update_object_prop(k, state == Qt.Checked))
                layout.addRow(label_text, widget)
            elif isinstance(value, int):
                widget = QSpinBox(); widget.setRange(-99999, 99999); widget.setValue(value)
                widget.valueChanged.connect(lambda v, k=key: self.update_object_prop(k, v))
                layout.addRow(label_text, widget)
            elif isinstance(value, float):
                widget = QLineEdit(str(value))
                widget.textChanged.connect(lambda t, k=key: self.update_object_prop(k, float(t) if t and t.replace('.', '', 1).isdigit() else 0.0))
                layout.addRow(label_text, widget)
            else:
                widget = QLineEdit(str(value))
                widget.textChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget)
                
        self.main_layout.addLayout(layout)

    def add_color_picker_widget(self, form_layout, thing, key):
        """Creates a color picker widget for light color properties."""
        # This function can be pasted from your existing code
        pass

    def update_object_prop(self, key, value):
        """
        Updates a property on the current object and tells the main editor 
        to refresh the entire UI to ensure consistency.
        """
        if self.current_object is None: return

        # 1. Update the data model
        if isinstance(self.current_object, dict):
            self.current_object[key] = value
        elif isinstance(self.current_object, Thing):
            # This logic correctly handles type conversion for Thing properties
            if key in self.current_object.properties:
                prop_type = type(self.current_object.properties.get(key))
                if prop_type == float:
                    try: value = float(value)
                    except (ValueError, TypeError): value = 0.0
            self.current_object.properties[key] = value

        # 2. Tell the main editor to update ALL UI components.
        self.editor.update_all_ui()