import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QSpinBox,
                             QFormLayout, QCheckBox, QComboBox, QPushButton,
                             QHBoxLayout, QColorDialog, QFileDialog, QSlider, QToolButton, QTabWidget)
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

        # Initialize all potential widgets to None
        self.locked_checkbox = None
        self.advanced_properties_button = None
        self.advanced_properties_widget = None
        self.brush_type_combo = None
        self.target_label = None
        self.target_input = None
        self.type_label = None
        self.type_combo = None
        self.fog_density_label = None
        self.fog_density_input = None
        self.fog_emit_light_label = None
        self.fog_emit_light_checkbox = None
        self.fog_color_label = None
        self.fog_color_button = None
        self.fog_noise_label = None
        self.fog_noise_checkbox = None
        self.fog_noise_speed_label = None
        self.fog_noise_speed_slider = None
        self.texture_tabs = None


        self.set_object(None)

    def clear_layout(self):
        """Removes all widgets from the main layout."""
        while self.main_layout.count():
            child = self.main_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
                # This part is to handle layouts added directly to main_layout
                layout = child.layout()
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()

    def set_object(self, obj):
        """Sets the object for the property editor and rebuilds the UI."""
        self.current_object = obj
        self.clear_layout()  # Clear previous UI

        if obj is None:
            self.main_layout.addWidget(QLabel("Nothing selected."))
            return

        if isinstance(obj, dict):  # It's a brush
            self.populate_for_brush(obj)
        elif isinstance(obj, Thing):
            # Add this line to reset the selected face when a new object is selected
            self.editor.selected_face = None 
            self.populate_for_thing(obj)
        
        self.main_layout.addStretch()


    def populate_for_brush(self, brush):
        """Populates the UI with properties for a brush object."""
        main_form_layout = QFormLayout()
        main_form_layout.setVerticalSpacing(2)
        is_locked = brush.get('lock', False)
        is_special = brush.get('is_trigger', False) or brush.get('is_fog', False) or brush.get('is_mover', False)

        # LOCK CHECKBOX
        self.locked_checkbox = QCheckBox()
        self.locked_checkbox.setStyleSheet("QCheckBox::indicator { width: 25px; height: 25px; }")
        self.locked_checkbox.setChecked(is_locked)
        self.locked_checkbox.toggled.connect(self.on_lock_changed)
        main_form_layout.addRow("LOCK:", self.locked_checkbox)

        # ADVANCED PROPERTIES
        self.advanced_properties_button = QToolButton(self)
        self.advanced_properties_button.setText("Advanced Properties")
        self.advanced_properties_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.advanced_properties_button.setArrowType(Qt.RightArrow)
        self.advanced_properties_button.setCheckable(True)
        self.advanced_properties_button.setChecked(is_special)
        self.advanced_properties_button.toggled.connect(self.toggle_advanced_properties)

        self.advanced_properties_widget = QWidget()
        advanced_layout = QFormLayout(self.advanced_properties_widget)
        advanced_layout.setContentsMargins(0, 0, 0, 0)

        # Brush Type (Trigger, Fog, Mover)
        self.brush_type_combo = QComboBox()
        self.brush_type_combo.addItems(['Trigger', 'Fog Volume', 'Mover'])
        if brush.get('is_trigger', False):
            self.brush_type_combo.setCurrentText('Trigger')
        elif brush.get('is_fog', False):
            self.brush_type_combo.setCurrentText('Fog Volume')
        elif brush.get('is_mover', False):
            self.brush_type_combo.setCurrentText('Mover')
        self.brush_type_combo.currentTextChanged.connect(self.on_brush_type_changed)
        advanced_layout.addRow("Type:", self.brush_type_combo)

        # Trigger Properties
        self.target_label = QLabel("Target:")
        self.target_input = QLineEdit(brush.get('target', ''))
        self.target_input.editingFinished.connect(lambda: self.update_object_prop('target', self.target_input.text()))
        advanced_layout.addRow(self.target_label, self.target_input)

        self.type_label = QLabel("Trigger Type:")
        self.type_combo = QComboBox()
        self.type_combo.addItems(['Once', 'Multiple'])
        self.type_combo.setCurrentText(brush.get('trigger_type', 'Once'))
        self.type_combo.currentTextChanged.connect(lambda t: self.update_object_prop('trigger_type', t))
        advanced_layout.addRow(self.type_label, self.type_combo)
        
        # Fog Properties
        self.fog_density_label = QLabel("Density:")
        self.fog_density_input = QLineEdit(str(brush.get('fog_density', 2.0)))
        self.fog_density_input.editingFinished.connect(lambda: self.update_object_prop('fog_density', float(self.fog_density_input.text()) if self.fog_density_input.text() else 0.1))
        advanced_layout.addRow(self.fog_density_label, self.fog_density_input)

        self.fog_color_label = QLabel("Colour:")
        self.fog_color_button = QPushButton()
        self.fog_color_button.setFixedSize(200, 32)
        self.update_fog_color_button(brush.get('fog_color', [0.5, 0.6, 0.7]))
        self.fog_color_button.clicked.connect(self.on_fog_color_changed)
        advanced_layout.addRow(self.fog_color_label, self.fog_color_button)

        self.fog_noise_label = QLabel("Noise:")
        self.fog_noise_checkbox = QCheckBox()
        self.fog_noise_checkbox.setStyleSheet("QCheckBox::indicator { width: 25px; height: 25px; }")
        self.fog_noise_checkbox.setChecked(brush.get('fog_noise', False))
        self.fog_noise_checkbox.toggled.connect(self.on_fog_noise_changed)
        advanced_layout.addRow(self.fog_noise_label, self.fog_noise_checkbox)
        
        self.fog_noise_speed_label = QLabel("Amount:")
        self.fog_noise_speed_slider = QSlider(Qt.Horizontal)
        self.fog_noise_speed_slider.setRange(0, 100)
        self.fog_noise_speed_slider.setValue(brush.get('fog_noise_speed', 50))
        self.fog_noise_speed_slider.valueChanged.connect(lambda v: self.update_object_prop('fog_noise_speed', v))
        advanced_layout.addRow(self.fog_noise_speed_label, self.fog_noise_speed_slider)
        
        # Mover Properties
        direction_map = {
            "Up": [0, 1, 0], "Down": [0, -1, 0],
            "North": [0, 0, 1], "South": [0, 0, -1],
            "East": [1, 0, 0], "West": [-1, 0, 0]
        }
        self.mover_name_label = QLabel("Name:")
        self.mover_name_input = QLineEdit(brush.get('name', ''))
        self.mover_name_input.editingFinished.connect(lambda: self.update_object_prop('name', self.mover_name_input.text()))
        advanced_layout.addRow(self.mover_name_label, self.mover_name_input)

        self.direction_label = QLabel("Direction:")
        self.direction_combo = QComboBox()
        self.direction_combo.addItems(list(direction_map.keys()))
        current_dir = brush.get('direction', [0, 1, 0])
        for name, vec in direction_map.items():
            if vec == current_dir:
                self.direction_combo.setCurrentText(name)
                break
        self.direction_combo.currentTextChanged.connect(lambda t: self.update_object_prop('direction', direction_map.get(t)))
        advanced_layout.addRow(self.direction_label, self.direction_combo)
        
        self.distance_label = QLabel("Distance:")
        self.distance_spin = QSpinBox(); self.distance_spin.setRange(0, 1024); self.distance_spin.setValue(brush.get('distance', 128))
        self.distance_spin.valueChanged.connect(lambda v: self.update_object_prop('distance', v))
        advanced_layout.addRow(self.distance_label, self.distance_spin)
        
        self.speed_label = QLabel("Speed:")
        self.speed_spin = QSpinBox(); self.speed_spin.setRange(1, 512); self.speed_spin.setValue(brush.get('speed', 32))
        self.speed_spin.valueChanged.connect(lambda v: self.update_object_prop('speed', v))
        advanced_layout.addRow(self.speed_label, self.speed_spin)

        self.solid_label = QLabel("Solid:")
        self.solid_check = QCheckBox(); self.solid_check.setStyleSheet("QCheckBox::indicator { width: 25px; height: 25px; }"); self.solid_check.setChecked(brush.get('solid', True))
        self.solid_check.stateChanged.connect(lambda state: self.update_object_prop('solid', state == Qt.Checked))
        advanced_layout.addRow(self.solid_label, self.solid_check)

        self.start_on_label = QLabel("Start On:")
        self.start_on_check = QCheckBox(); self.start_on_check.setStyleSheet("QCheckBox::indicator { width: 25px; height: 25px; }"); self.start_on_check.setChecked(brush.get('start_on', False))
        self.start_on_check.stateChanged.connect(lambda state: self.update_object_prop('start_on', state == Qt.Checked))
        advanced_layout.addRow(self.start_on_label, self.start_on_check)
        
        self.move_once_label = QLabel("Move Once:")
        self.move_once_check = QCheckBox(); self.move_once_check.setStyleSheet("QCheckBox::indicator { width: 25px; height: 25px; }"); self.move_once_check.setChecked(brush.get('move_once', False))
        self.move_once_check.stateChanged.connect(lambda state: self.update_object_prop('move_once', state == Qt.Checked))
        advanced_layout.addRow(self.move_once_label, self.move_once_check)

        self.preview_button = QPushButton("Preview Movement")
        self.preview_button.clicked.connect(self.editor.preview_mover_movement)
        advanced_layout.addRow(self.preview_button)

        self.main_layout.addLayout(main_form_layout)
        self.main_layout.addWidget(self.advanced_properties_button)
        self.main_layout.addWidget(self.advanced_properties_widget)
        
        # --- Texturing Section ---
        # Only show the texturing section if the brush is not a trigger or fog volume
        if not brush.get('is_trigger', False) and not brush.get('is_fog', False):
            texturing_label = QLabel("Texturing")
            texturing_label.setStyleSheet("font-weight: bold; padding-top: 10px;")
            self.main_layout.addWidget(texturing_label)

            apply_face_texture_button = QPushButton("Apply to Face")
            apply_face_texture_button.clicked.connect(self.editor.apply_texture_to_selected_face)
            self.main_layout.addWidget(apply_face_texture_button)

            apply_texture_button = QPushButton("Apply to All Faces")
            apply_texture_button.clicked.connect(self.editor.apply_texture_to_brush)
            self.main_layout.addWidget(apply_texture_button)

            self.texture_tabs = QTabWidget()
            face_names = ["North", "South", "East", "West", "Top", "Bottom"]
            for face in face_names:
                self.texture_tabs.addTab(self.create_texture_tab(brush, face.lower()), face)

            self.main_layout.addWidget(self.texture_tabs)
        
        self.update_brush_ui_state()
    
    def create_texture_tab(self, brush, face_name):
        widget = QWidget()
        layout = QFormLayout(widget)
        
        textures = brush.get('textures', {})
        face_props = textures.get(face_name, {})
        
        if isinstance(face_props, str):
            face_props = {'texture': face_props}

        texture_path = face_props.get('texture', 'default.png')
        scale_x = face_props.get('scale_x', 1.0)
        scale_y = face_props.get('scale_y', 1.0)
        rotation = face_props.get('rotation', 0)
        
        # Texture Path
        path_edit = QLineEdit(texture_path)
        path_edit.setReadOnly(True)
        layout.addRow("Texture:", path_edit)
        
        # Scale X
        scale_x_spin = QSpinBox()
        scale_x_spin.setRange(1, 1000)
        scale_x_spin.setValue(int(scale_x * 100))
        scale_x_spin.setSuffix("%")
        scale_x_spin.valueChanged.connect(lambda v, f=face_name: self.update_texture_prop(f, 'scale_x', v / 100.0))
        layout.addRow("Scale X:", scale_x_spin)

        # Scale Y
        scale_y_spin = QSpinBox()
        scale_y_spin.setRange(1, 1000)
        scale_y_spin.setValue(int(scale_y * 100))
        scale_y_spin.setSuffix("%")
        scale_y_spin.valueChanged.connect(lambda v, f=face_name: self.update_texture_prop(f, 'scale_y', v / 100.0))
        layout.addRow("Scale Y:", scale_y_spin)
        
        # Rotation
        rotation_spin = QSpinBox()
        rotation_spin.setRange(0, 359)
        rotation_spin.setValue(rotation)
        rotation_spin.setSuffix("°")
        rotation_spin.valueChanged.connect(lambda v, f=face_name: self.update_texture_prop(f, 'rotation', v))
        layout.addRow("Rotation:", rotation_spin)

        # Fit Button
        fit_button = QPushButton("Fit")
        fit_button.clicked.connect(lambda _, f=face_name: self.on_fit_button_clicked(f))
        layout.addRow(fit_button)

        return widget

    def on_fit_button_clicked(self, face_name):
        if not isinstance(self.current_object, dict):
            return
            
        brush = self.current_object
        size = brush['size']
        
        if face_name in ['top', 'bottom']:
            scale_x = size[0] / 64
            scale_y = size[2] / 64
        elif face_name in ['north', 'south']:
            scale_x = size[0] / 64
            scale_y = size[1] / 64
        elif face_name in ['east', 'west']:
            scale_x = size[2] / 64
            scale_y = size[1] / 64
        
        self.update_texture_prop(face_name, 'scale_x', scale_x)
        self.update_texture_prop(face_name, 'scale_y', scale_y)
        
        # We need to refresh the whole property editor to see the changes
        self.set_object(self.current_object)


    def update_texture_prop(self, face, key, value):
        if self.current_object and 'textures' in self.current_object:
            if face not in self.current_object['textures'] or isinstance(self.current_object['textures'][face], str):
                # If the face doesn't exist or is a string, create a dictionary for it
                self.current_object['textures'][face] = {'texture': self.current_object['textures'].get(face, 'default.png')}
            
            self.current_object['textures'][face][key] = value
            self.editor.update_all_ui()

    def toggle_advanced_properties(self, is_checked):
        """Toggles the visibility of the advanced properties widget."""
        self.advanced_properties_widget.setVisible(is_checked)
        self.advanced_properties_button.setArrowType(Qt.DownArrow if is_checked else Qt.RightArrow)
        
        if not is_checked and self.current_object:
            # When unchecked, remove all special brush properties
            self.current_object['is_trigger'] = False
            self.current_object['is_fog'] = False
            self.current_object['is_mover'] = False
            
        elif is_checked and self.current_object:
            # When checked, if no special type is active, default to Trigger
            is_trigger = self.current_object.get('is_trigger', False)
            is_fog = self.current_object.get('is_fog', False)
            is_mover = self.current_object.get('is_mover', False)
            if not (is_trigger or is_fog or is_mover):
                self.current_object['is_trigger'] = True # Default to trigger
        
        self.update_brush_ui_state()
        self.editor.update_all_ui()


    def on_brush_type_changed(self, brush_type):
        """Handler for when the brush type dropdown changes."""
        if self.current_object is None: return

        is_trigger = (brush_type == 'Trigger')
        is_fog = (brush_type == 'Fog Volume')
        is_mover = (brush_type == 'Mover')

        self.current_object['is_trigger'] = is_trigger
        self.current_object['is_fog'] = is_fog
        self.current_object['is_mover'] = is_mover

        # Apply default texture for trigger, or set default fog density for fog
        if is_trigger:
            if 'textures' not in self.current_object:
                self.current_object['textures'] = {}
            for face in ['north', 'south', 'east', 'west', 'top', 'down']:
                self.current_object['textures'][face] = 'trigger.jpg'
        elif is_fog:
            if 'fog_density' not in self.current_object:
                self.current_object['fog_density'] = 2.0
        elif is_mover:
            self.current_object['lock'] = False # Movers cannot be locked
            if 'name' not in self.current_object or not self.current_object['name']:
                self.current_object['name'] = self.editor.state.get_unique_mover_name()

        self.update_brush_ui_state()
        self.editor.update_all_ui()
    

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

    def on_fog_noise_changed(self, state):
        self.update_object_prop('fog_noise', state)
        self.update_brush_ui_state()


    def update_brush_ui_state(self):
        """Updates the visibility of UI elements based on the current brush state."""
        if self.current_object is None: return
        
        is_locked = self.current_object.get('lock', False)
        is_trigger = self.current_object.get('is_trigger', False)
        is_fog = self.current_object.get('is_fog', False)
        is_mover = self.current_object.get('is_mover', False)
        is_noise_enabled = self.current_object.get('fog_noise', False)
        
        # Enable/disable advanced properties based on lock status
        self.advanced_properties_button.setEnabled(not is_locked)
        
        # Visibility based on special brush type
        is_special = is_trigger or is_fog or is_mover
        self.advanced_properties_button.setChecked(is_special)
        self.advanced_properties_widget.setVisible(is_special)
        self.advanced_properties_button.setArrowType(Qt.DownArrow if is_special else Qt.RightArrow)
        
        # Trigger fields
        show_trigger_fields = is_trigger and not is_locked
        self.target_label.setVisible(show_trigger_fields)
        self.target_input.setVisible(show_trigger_fields)
        self.type_label.setVisible(show_trigger_fields)
        self.type_combo.setVisible(show_trigger_fields)
        
        # Fog fields
        show_fog_fields = is_fog and not is_locked
        self.fog_density_label.setVisible(show_fog_fields)
        self.fog_density_input.setVisible(show_fog_fields)
        self.fog_color_label.setVisible(show_fog_fields)
        self.fog_color_button.setVisible(show_fog_fields)
        self.fog_noise_label.setVisible(show_fog_fields)
        self.fog_noise_checkbox.setVisible(show_fog_fields)
        self.fog_noise_speed_label.setVisible(show_fog_fields and is_noise_enabled)
        self.fog_noise_speed_slider.setVisible(show_fog_fields and is_noise_enabled)

        # Mover fields
        show_mover_fields = is_mover and not is_locked
        self.mover_name_label.setVisible(show_mover_fields)
        self.mover_name_input.setVisible(show_mover_fields)
        self.direction_label.setVisible(show_mover_fields)
        self.direction_combo.setVisible(show_mover_fields)
        self.distance_label.setVisible(show_mover_fields)
        self.distance_spin.setVisible(show_mover_fields)
        self.speed_label.setVisible(show_mover_fields)
        self.speed_spin.setVisible(show_mover_fields)
        self.solid_label.setVisible(show_mover_fields)
        self.solid_check.setVisible(show_mover_fields)
        self.preview_button.setVisible(show_mover_fields)
        self.start_on_label.setVisible(show_mover_fields)
        self.start_on_check.setVisible(show_mover_fields)
        self.move_once_label.setVisible(show_mover_fields)
        self.move_once_check.setVisible(show_mover_fields)


    def on_lock_changed(self, is_locked):
        if self.current_object is None: return
        self.current_object['lock'] = is_locked
        self.update_brush_ui_state() # Refresh UI based on new lock state
        self.editor.update_all_ui()
    
    def on_fog_emit_light_changed(self, emit_light):
        if self.current_object is None: return
        self.current_object['fog_emit_light'] = emit_light
        self.editor.update_all_ui()

    def populate_for_thing(self, thing):
        """Populates the UI with properties for a Thing object."""
        layout = QFormLayout()
        
        # Special case for Light color
        if isinstance(thing, Light):
            self.add_color_picker_widget(layout, thing, 'colour')

        # Iterate through all properties of the thing
        for key, value in sorted(thing.properties.items()):
            if isinstance(thing, Light) and key == 'colour':
                continue # Skip, as we handled it above

            label_text = key.replace('_', ' ').title() + ":"
            
            # Create appropriate widget based on property type
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
                item_types = ['health', 'ammo', 'armour', 'powerup', 'key', 'message', 'weapon']
                widget.addItems(item_types)
                widget.setCurrentText(value)
                widget.currentTextChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget)
            elif isinstance(value, bool):
                widget = QCheckBox()
                widget.setStyleSheet("QCheckBox::indicator { width: 25px; height: 25px; }")
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
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        line_edit = QLineEdit(str(value))
        line_edit.setReadOnly(True) # Make it read-only
        button = QPushButton("...")
        button.setFixedWidth(30)

        def open_dialog():
            # Set the starting directory for the file dialog
            start_path = os.path.join('assets', 'sounds')
            if not os.path.exists(start_path):
                os.makedirs(start_path)
            
            filepath, _ = QFileDialog.getOpenFileName(self, "Select Sound File", start_path, "Sound Files (*.wav *.mp3)")
            if filepath:
                # Make the path relative to the 'assets' folder
                try:
                    relative_path = os.path.relpath(filepath, 'assets').replace('\\', '/')
                except ValueError:
                    # If the file is on a different drive, just use the filename
                    relative_path = os.path.basename(filepath)
                
                self.update_object_prop(key, relative_path)
                line_edit.setText(relative_path)

        button.clicked.connect(open_dialog)
        layout.addWidget(line_edit)
        layout.addWidget(button)
        form_layout.addRow(key.replace('_', ' ').title() + ":", widget)

    def add_color_picker_widget(self, form_layout, thing, key):
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
        """Updates a property on the current object."""
        if self.current_object is None: return

        if isinstance(self.current_object, dict):  # It's a brush
            self.current_object[key] = value
        elif isinstance(self.current_object, Thing):
            # For things, we need to handle potential type casting
            if key in self.current_object.properties:
                prop_type = type(self.current_object.properties.get(key))
                if prop_type == float:
                    try: value = float(value)
                    except (ValueError, TypeError): value = 0.0 # Default to 0.0 if conversion fails
            self.current_object.properties[key] = value

        self.editor.update_all_ui()