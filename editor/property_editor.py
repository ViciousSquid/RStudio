import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QSpinBox,
                             QFormLayout, QCheckBox, QComboBox, QPushButton,
                             QHBoxLayout, QColorDialog, QFileDialog)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from editor.things import Thing, Light, Pickup, Monster, Model, Speaker

class PropertyEditor(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.current_object = None
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(self.main_layout)
        
        self.locked_checkbox = None
        self.trigger_checkbox = None
        self.target_label = None
        self.target_input = None
        self.type_label = None
        self.type_combo = None
        self.fog_checkbox = None
        self.fog_density_label = None
        self.fog_density_input = None
        self.fog_emit_light_label = None
        self.fog_emit_light_checkbox = None

        self.fog_color_label = None
        self.fog_color_button = None

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

        if isinstance(obj, dict):
            self.populate_for_brush(obj)
        elif isinstance(obj, Thing):
            self.populate_for_thing(obj)

    def populate_for_brush(self, brush):
        """Populates the UI with properties for a brush object."""
        layout = QFormLayout()
        is_locked = brush.get('lock', False)
        is_trigger = brush.get('is_trigger', False)
        is_fog = brush.get('is_fog', False)

        # Create Widgets and store them as instance variables
        self.locked_checkbox = QCheckBox()
        self.locked_checkbox.setStyleSheet("QCheckBox::indicator { width: 20px; height: 20px; }")
        self.trigger_checkbox = QCheckBox()
        self.trigger_checkbox.setStyleSheet("QCheckBox::indicator { width: 20px; height: 20px; }")
        self.target_label = QLabel("Target:")
        self.target_input = QLineEdit(brush.get('target', ''))
        self.type_label = QLabel("Trigger Type:")
        self.type_combo = QComboBox()
        self.type_combo.addItems(['Once', 'Multiple'])
        self.fog_checkbox = QCheckBox()
        self.fog_checkbox.setStyleSheet("QCheckBox::indicator { width: 20px; height: 20px; }")
        self.fog_density_label = QLabel("Density:")
        self.fog_density_input = QLineEdit(str(brush.get('fog_density', 0.1)))
        self.fog_color_label = QLabel("Color:")
        self.fog_color_button = QPushButton()
        self.fog_color_button.setFixedSize(200, 20)
        self.update_fog_color_button(brush.get('fog_color', [0.5, 0.6, 0.7]))


        # Set initial state from brush properties
        self.locked_checkbox.setChecked(is_locked)
        self.trigger_checkbox.setChecked(is_trigger)
        self.type_combo.setCurrentText(brush.get('trigger_type', 'Once'))
        self.fog_checkbox.setChecked(is_fog)



        # Add to Layout
        layout.addRow("Lock:", self.locked_checkbox)
        layout.addRow("Is Trigger:", self.trigger_checkbox)
        layout.addRow(self.target_label, self.target_input)
        layout.addRow(self.type_label, self.type_combo)
        layout.addRow("Fog Volume:", self.fog_checkbox)
        layout.addRow(self.fog_density_label, self.fog_density_input)
        layout.addRow(self.fog_color_label, self.fog_color_button)



        # Connect Signals to dedicated handlers
        self.locked_checkbox.toggled.connect(self.on_lock_changed)
        self.trigger_checkbox.toggled.connect(self.on_trigger_changed)
        self.target_input.editingFinished.connect(lambda: self.update_object_prop('target', self.target_input.text()))
        self.type_combo.currentTextChanged.connect(lambda t: self.update_object_prop('trigger_type', t))
        self.fog_checkbox.toggled.connect(self.on_fog_changed)
        self.fog_density_input.editingFinished.connect(lambda: self.update_object_prop('fog_density', float(self.fog_density_input.text()) if self.fog_density_input.text() else 0.1))
        self.fog_color_button.clicked.connect(self.on_fog_color_changed)


        self.main_layout.addLayout(layout)

        # Set the initial UI state based on properties
        self.update_brush_ui_state()

    def on_fog_color_changed(self):
        if self.current_object is None:
            return
        color = QColorDialog.getColor()
        if color.isValid():
            self.current_object['fog_color'] = [color.redF(), color.greenF(), color.blueF()]
            self.update_fog_color_button(self.current_object['fog_color'])
            self.editor.update_all_ui()

    def update_fog_color_button(self, color_rgb):
        qcolor = QColor.fromRgbF(*color_rgb)
        self.fog_color_button.setStyleSheet(f"background-color: {qcolor.name()}")

    def update_brush_ui_state(self):
        """Updates the enabled/visible state of brush property widgets."""
        if self.current_object is None:
            return

        is_locked = self.current_object.get('lock', False)
        is_trigger = self.current_object.get('is_trigger', False)
        is_fog = self.current_object.get('is_fog', False)


        self.trigger_checkbox.setEnabled(not is_locked)

        show_trigger_fields = is_trigger and not is_locked
        self.target_label.setVisible(show_trigger_fields)
        self.target_input.setVisible(show_trigger_fields)
        self.type_label.setVisible(show_trigger_fields)
        self.type_combo.setVisible(show_trigger_fields)

        show_fog_fields = is_fog and not is_locked
        self.fog_density_label.setVisible(show_fog_fields)
        self.fog_density_input.setVisible(show_fog_fields)
        self.fog_color_label.setVisible(show_fog_fields)
        self.fog_color_button.setVisible(show_fog_fields)


    def on_lock_changed(self, is_locked):
        """Handler for when the lock checkbox is toggled."""
        if self.current_object is None: return
        
        self.current_object['lock'] = is_locked
        self.update_brush_ui_state()
        self.editor.update_all_ui()

    def on_trigger_changed(self, is_trigger):
        """Handler for when the trigger checkbox is toggled."""
        if self.current_object is None: return
        
        self.current_object['is_trigger'] = is_trigger
        # Automatically assign trigger texture when a brush is set as a trigger
        if is_trigger:
            self.current_object['is_fog'] = False
            if 'textures' not in self.current_object:
                self.current_object['textures'] = {}
            for face in ['north','south','east','west','top','down']:
                self.current_object['textures'][face] = 'trigger.jpg'
        self.set_object(self.current_object)
        self.editor.update_all_ui()

    def on_fog_changed(self, is_fog):
        """Handler for when the fog checkbox is toggled."""
        if self.current_object is None: return
        
        self.current_object['is_fog'] = is_fog
        if is_fog:
            self.current_object['is_trigger'] = False
        self.set_object(self.current_object)
        self.editor.update_all_ui()

    def on_fog_emit_light_changed(self, emit_light):
        """Handler for when the fog emit light checkbox is toggled."""
        if self.current_object is None: return
        
        self.current_object['fog_emit_light'] = emit_light
        self.editor.update_all_ui()

    def populate_for_thing(self, thing):
        """Populates the UI with properties for a Thing object."""
        layout = QFormLayout()
        
        # Special handling for colour picker at the top
        if isinstance(thing, Light): #
            self.add_color_picker_widget(layout, thing, 'colour')

        for key, value in sorted(thing.properties.items()):
            if isinstance(thing, Light) and key == 'colour':
                continue

            label_text = key.replace('_', ' ').title() + ":"
            
            if isinstance(thing, Light) and key == 'state':
                widget = QComboBox()
                widget.addItems(['on', 'off'])
                widget.setCurrentText(value)
                widget.currentTextChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget)
            elif isinstance(thing, Speaker) and key == 'sound_file':
                self.add_sound_file_widget(layout, thing, key, value)
            elif isinstance(thing, Pickup) and key == 'item_type':
                widget = QComboBox()
                # PICKUP TYPES
                item_types = ['health', 'ammo', 'armour', 'powerup', 'key', 'message', 'weapon']
                widget.addItems(item_types)
                widget.setCurrentText(value)
                widget.currentTextChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget)
            elif isinstance(value, bool):
                widget = QCheckBox()
                widget.setStyleSheet("QCheckBox::indicator { width: 20px; height: 20px; }")
                widget.setChecked(value)
                widget.stateChanged.connect(lambda state, k=key: self.update_object_prop(k, state == Qt.Checked))
                layout.addRow(label_text, widget)
            elif isinstance(value, int):
                widget = QSpinBox(); widget.setRange(-99999, 99999); widget.setValue(value)
                widget.valueChanged.connect(lambda v, k=key: self.update_object_prop(k, v))
                layout.addRow(label_text, widget)
            elif isinstance(value, float):
                widget = QLineEdit(str(value))
                widget.editingFinished.connect(
                    lambda le=widget, k=key: self.update_object_prop(k, float(le.text()) if le.text() and le.text().replace('.', '', 1).isdigit() else 0.0)
                )
                layout.addRow(label_text, widget)
            else:
                widget = QLineEdit(str(value))
                widget.editingFinished.connect(lambda le=widget, k=key: self.update_object_prop(k, le.text()))
                layout.addRow(label_text, widget)
                
        self.main_layout.addLayout(layout)

    def add_sound_file_widget(self, form_layout, thing, key, value):
        """Creates a sound file selector widget."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        line_edit = QLineEdit(str(value))
        line_edit.setReadOnly(True)
        button = QPushButton("...")
        button.setFixedWidth(30)

        def open_dialog():
            start_path = os.path.join('assets', 'sounds')
            if not os.path.exists(start_path):
                os.makedirs(start_path)
            
            filepath, _ = QFileDialog.getOpenFileName(self, "Select Sound File", start_path, "Sound Files (*.wav *.mp3)")
            if filepath:
                try:
                    relative_path = os.path.relpath(filepath, 'assets').replace('\\', '/')
                except ValueError:
                    relative_path = os.path.basename(filepath)
                
                self.update_object_prop(key, relative_path)
                line_edit.setText(relative_path)

        button.clicked.connect(open_dialog)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        form_layout.addRow(key.replace('_', ' ').title() + ":", widget)

    def add_color_picker_widget(self, form_layout, thing, key):
        """Creates a color picker widget for light color properties."""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        current_color_rgb = thing.properties.get(key, [255, 255, 255])
        color_swatch = QPushButton()
        color_swatch.setFixedSize(200, 32)
        
        def update_swatch():
            rgb = thing.properties.get(key, [255, 255, 255])
            color_swatch.setStyleSheet(f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]});")

        def open_color_dialog():
            current_color_rgb = thing.properties.get(key, [255, 255, 255])
            color = QColorDialog.getColor(QColor(*current_color_rgb), self, "Choose Light Colour")
            if color.isValid():
                self.update_object_prop(key, [color.red(), color.green(), color.blue()])
                update_swatch()

        color_swatch.clicked.connect(open_color_dialog)
        update_swatch()
        layout.addWidget(color_swatch)
        form_layout.addRow("Colour:", widget)


    def update_object_prop(self, key, value):
        """
        Updates a property on the current object and tells the main editor 
        to refresh the entire UI to ensure consistency.
        """
        if self.current_object is None: return

        if isinstance(self.current_object, dict):
            self.current_object[key] = value
        elif isinstance(self.current_object, Thing):
            if key in self.current_object.properties:
                prop_type = type(self.current_object.properties.get(key))
                if prop_type == float:
                    try: value = float(value)
                    except (ValueError, TypeError): value = 0.0
            self.current_object.properties[key] = value

        self.editor.update_all_ui()