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
        
        self.set_object(None)

    def clear_layout(self):
        while self.main_layout.count():
            child = self.main_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                # Recursively clear nested layouts
                layout = child.layout()
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()

    def set_object(self, obj):
        self.current_object = obj
        self.clear_layout()

        if obj is None:
            self.main_layout.addWidget(QLabel("Nothing selected."))
            return

        if isinstance(obj, dict): # It's a brush
            self.populate_for_brush(obj)
        elif isinstance(obj, Thing): # It's a Thing
            self.populate_for_thing(obj)

    def populate_for_brush(self, brush):
        layout = QFormLayout()
        
        # --- Lock Brush ---
        locked_checkbox = QCheckBox()
        locked_checkbox.setChecked(brush.get('locked', False))
        locked_checkbox.stateChanged.connect(lambda state: self.update_brush_lock(brush, state == Qt.Checked))
        layout.addRow("Lock:", locked_checkbox)

        # --- Trigger Properties ---
        trigger_checkbox = QCheckBox()
        trigger_checkbox.setChecked(brush.get('is_trigger', False))
        layout.addRow("Is Trigger:", trigger_checkbox)

        target_input = QLineEdit(brush.get('target', ''))
        layout.addRow("Target:", target_input)
        
        type_combo = QComboBox()
        type_combo.addItems(['Once', 'Multiple'])
        type_combo.setCurrentText(brush.get('trigger_type', 'Once'))
        layout.addRow("Trigger Type:", type_combo)

        def toggle_trigger_fields(state):
            is_trigger = (state == Qt.Checked)
            brush['is_trigger'] = is_trigger
            for i in range(2, layout.rowCount()):
                label_item = layout.itemAt(i, QFormLayout.LabelRole)
                field_item = layout.itemAt(i, QFormLayout.FieldRole)
                if label_item and label_item.widget():
                    label_item.widget().setVisible(is_trigger)
                if field_item and field_item.widget():
                    field_item.widget().setVisible(is_trigger)
            self.editor.update_views()

        trigger_checkbox.stateChanged.connect(toggle_trigger_fields)
        
        target_input.textChanged.connect(lambda t: self.update_object_prop('target', t))
        type_combo.currentTextChanged.connect(lambda t: self.update_object_prop('trigger_type', t))

        self.main_layout.addLayout(layout)
        toggle_trigger_fields(trigger_checkbox.checkState())

    def update_brush_lock(self, brush, locked):
        brush['locked'] = locked
        self.editor.update_views()

    def populate_for_thing(self, thing):
        layout = QFormLayout()
        
        for key, value in sorted(thing.properties.items()):
            label_text = key.replace('_', ' ').title() + ":"
            
            # --- MODIFIED: Use a color picker for the 'color' property of a Light ---
            if isinstance(thing, Light) and key == 'color':
                self.add_color_picker_widget(layout, thing, key)
            elif isinstance(value, bool):
                widget = QCheckBox()
                widget.setChecked(value)
                widget.stateChanged.connect(lambda state, k=key: self.update_object_prop(k, state == Qt.Checked))
                layout.addRow(label_text, widget)
            elif isinstance(value, int):
                widget = QSpinBox()
                widget.setRange(-99999, 99999)
                widget.setValue(value)
                widget.valueChanged.connect(lambda v, k=key: self.update_object_prop(k, v))
                layout.addRow(label_text, widget)
            elif isinstance(value, float):
                # Use a QLineEdit and convert to float
                widget = QLineEdit(str(value))
                # Update on text change
                widget.textChanged.connect(
                    lambda t, k=key: self.update_object_prop(k, float(t) if t and t.replace('.', '', 1).isdigit() else 0.0)
                )
                layout.addRow(label_text, widget)
            else: # String and other types (like list, for now)
                widget = QLineEdit(str(value))
                widget.textChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget)
                
        self.main_layout.addLayout(layout)

    def add_color_picker_widget(self, form_layout, thing, key):
        color_widget = QWidget()
        layout = QHBoxLayout(color_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        r, g, b = thing.properties[key]
        current_color = QColor(r, g, b)

        color_button = QPushButton()
        color_button.setFixedSize(24, 24)
        color_button.setStyleSheet(f"background-color: {current_color.name()}; border: 1px solid #555;")
        
        color_label = QLabel(current_color.name())

        def open_color_dialog():
            r, g, b = self.current_object.properties[key]
            initial_color = QColor(r, g, b)
            color = QColorDialog.getColor(initial_color, self, "Select Light Color")

            if color.isValid():
                new_color_list = [color.red(), color.green(), color.blue()]
                self.update_object_prop(key, new_color_list)
                
                # Update UI
                color_button.setStyleSheet(f"background-color: {color.name()}; border: 1px solid #555;")
                color_label.setText(color.name())

        color_button.clicked.connect(open_color_dialog)
        
        layout.addWidget(color_button)
        layout.addWidget(color_label)
        layout.addStretch()
        
        form_layout.addRow(key.replace('_', ' ').title() + ":", color_widget)


    def update_object_prop(self, key, value):
        if self.current_object is None: return

        if isinstance(self.current_object, dict):
            self.current_object[key] = value
        elif isinstance(self.current_object, Thing):
            # Special case for properties that need conversion
            prop_type = type(self.current_object.properties.get(key))
            if prop_type == float:
                try: value = float(value)
                except (ValueError, TypeError): value = 0.0
            
            self.current_object.properties[key] = value
        
        if key.lower() == 'name':
            self.editor.update_scene_hierarchy()
        
        self.editor.update_views()