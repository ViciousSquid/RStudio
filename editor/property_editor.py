from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QSpinBox, 
                             QFormLayout, QCheckBox, QComboBox)
from PyQt5.QtCore import Qt
from editor.things import Thing

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
            # Iterate from row 1 to skip the "Is Trigger" checkbox itself
            for i in range(1, layout.rowCount()):
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
        # Call this once to set initial visibility
        toggle_trigger_fields(trigger_checkbox.checkState())

    def populate_for_thing(self, thing):
        layout = QFormLayout()
        
        for key, value in sorted(thing.properties.items()):
            label_text = key.replace('_', ' ').title() + ":"
            
            if isinstance(value, bool):
                widget = QCheckBox()
                widget.setChecked(value)
                widget.stateChanged.connect(lambda state, k=key: self.update_object_prop(k, state == Qt.Checked))
            elif isinstance(value, int):
                widget = QSpinBox()
                widget.setRange(-99999, 99999)
                widget.setValue(value)
                widget.valueChanged.connect(lambda v, k=key: self.update_object_prop(k, v))
            elif isinstance(value, float):
                widget = QLineEdit(str(value))
                widget.textChanged.connect(lambda t, k=key: self.update_object_prop(k, float(t) if t and t.replace('.', '', 1).isdigit() else 0.0))
            elif isinstance(value, list):
                widget = QLineEdit(str(value))
                widget.textChanged.connect(lambda t, k=key: self.update_object_prop(k, eval(t) if t else []))
            else: # String and other types
                widget = QLineEdit(str(value))
                widget.textChanged.connect(lambda t, k=key: self.update_object_prop(k, t))

            layout.addRow(label_text, widget)
            
        self.main_layout.addLayout(layout)

    def update_object_prop(self, key, value):
        if self.current_object is None: return

        if isinstance(self.current_object, dict):
            self.current_object[key] = value
        elif isinstance(self.current_object, Thing):
            self.current_object.properties[key] = value
        
        if key.lower() == 'name':
            self.editor.update_scene_hierarchy()
        
        self.editor.update_views()