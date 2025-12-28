import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QSpinBox,
                             QFormLayout, QCheckBox, QComboBox, QPushButton,
                             QHBoxLayout, QColorDialog, QFileDialog, QGridLayout, QToolButton)
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QColor, QIcon
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
        
        # Fog properties (checkbox removed, controlled by shader dropdown now)
        self.fog_density_label = None
        self.fog_density_input = None
        self.fog_emit_light_label = None
        self.fog_emit_light_checkbox = None
        self.fog_color_label = None
        self.fog_color_button = None

        self.brush_name_label = None
        self.brush_name_input = None
        
        # Targeted by label for things
        self.targeted_by_label = None

        self.mover_checkbox = None
        self.mover_speed_label = None
        self.mover_speed_input = None
        self.mover_distance_label = None
        self.mover_distance_input = None
        self.mover_direction_label = None 
        self.mover_dir_widget = None
        self.mover_start_on_label = None
        self.mover_start_on_checkbox = None
        self.preview_btn = None
        
        # Hurt trigger widgets
        self.hurt_checkbox = None
        self.hurt_amount_label = None
        self.hurt_amount_input = None
        
        # Shader dropdown
        self.shader_label = None
        self.shader_combo = None
        
        # Glow light direction widgets
        self.glow_direction_label = None
        self.glow_direction_widget = None
        
        # Brush colour tint
        self.brush_colour_label = None
        self.brush_colour_button = None
        self.brush_colour_reset_btn = None

        self.set_object(None)
    
    def _find_targeting_sources(self, target_name):
        """Find all triggers/movers that target the given name."""
        if not target_name:
            return []
        
        sources = []
        for brush in self.editor.state.brushes:
            brush_target = brush.get('target', '')
            if brush_target == target_name:
                is_trigger = brush.get('is_trigger', False)
                is_mover = brush.get('is_mover', False)
                if is_trigger or is_mover:
                    source_name = brush.get('name', 'unnamed')
                    source_type = 'trigger' if is_trigger else 'mover'
                    sources.append((source_name, source_type))
        return sources
    
    def _check_target_exists(self, target_name):
        """Check if a target name refers to an existing object."""
        if not target_name:
            return False
        
        # Check brushes
        for brush in self.editor.state.brushes:
            if brush.get('name') == target_name:
                return True
        
        # Check things
        for thing in self.editor.state.things:
            thing_name = getattr(thing, 'name', '') or thing.properties.get('name', '')
            if thing_name == target_name:
                return True
        
        return False

    def clear_layout(self):
        while self.main_layout.count():
            child = self.main_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
            elif child.layout():
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

        if isinstance(obj, dict):
            self.populate_for_brush(obj)
        elif isinstance(obj, Thing):
            self.populate_for_thing(obj)

    def populate_for_brush(self, brush):
        layout = QFormLayout()
        is_locked = brush.get('lock', False)
        is_trigger = brush.get('is_trigger', False)
        
        # Sync is_fog to shader type for legacy support
        if brush.get('is_fog', False) and brush.get('shader') != 'Fog':
            brush['shader'] = 'Fog'

        self.locked_checkbox = QCheckBox()
        self.locked_checkbox.setStyleSheet("""
            QCheckBox::indicator:checked {
                background-color: #F08000;
                border: 1px solid #333;
            }
            QCheckBox::indicator:unchecked {
                background-color: #425f5d;
                border: 1px solid #333;
            }
            QCheckBox::indicator {
                width: 25px;
                height: 25px;
            }
        """)
        self.trigger_checkbox = QCheckBox()
        self.trigger_checkbox.setStyleSheet("""
        QCheckBox::indicator:checked {
            background-color: #F08000;
            border: 1px solid #333;
        }
        QCheckBox::indicator:unchecked {
            background-color: #425f5d;
            border: 1px solid #333;
        }
        QCheckBox::indicator {
            width: 25px;
            height: 25px;
        }
""")
        self.target_label = QLabel("Target:")
        target_value = brush.get('target', '')
        self.target_input = QLineEdit(target_value)
        
        # Style target field based on connection validity
        if brush.get('is_trigger') or brush.get('is_mover'):
            if target_value and self._check_target_exists(target_value):
                # Valid target - green
                self.target_label.setText("Target: ✓")
                self.target_label.setStyleSheet("QLabel { color: #00FF00; font-weight: bold; }")
                self.target_input.setStyleSheet("""
                    QLineEdit {
                        border: 2px solid #00FF00;
                        background-color: #1a3d1a;
                        padding: 2px;
                    }
                """)
            elif target_value:
                # Has target but doesn't exist - red
                self.target_label.setText("Target: ✗")
                self.target_label.setStyleSheet("QLabel { color: #FF6666; font-weight: bold; }")
                self.target_input.setStyleSheet("""
                    QLineEdit {
                        border: 2px solid #FF6666;
                        background-color: #3d1a1a;
                        padding: 2px;
                    }
                """)
            else:
                # No target set - amber
                self.target_label.setText("Target: (none)")
                self.target_label.setStyleSheet("QLabel { color: #FFA500; }")
                self.target_input.setStyleSheet("""
                    QLineEdit {
                        border: 1px solid #FFA500;
                        background-color: #3d3d1a;
                        padding: 2px;
                    }
                """)
        
        self.type_label = QLabel("Trigger Type:")
        self.type_combo = QComboBox()
        self.type_combo.addItems(['Once', 'Multiple'])
        
        # Hurt trigger widgets
        self.hurt_checkbox = QCheckBox()
        self.hurt_checkbox.setStyleSheet("""
            QCheckBox::indicator:checked {
                background-color: #F08000;
                border: 1px solid #333;
            }
            QCheckBox::indicator:unchecked {
                background-color: #425f5d;
                border: 1px solid #333;
            }
            QCheckBox::indicator {
                width: 25px;
                height: 25px;
            }
        """)
        self.hurt_amount_label = QLabel("Damage:")
        self.hurt_amount_input = QSpinBox()
        self.hurt_amount_input.setRange(1, 999)
        self.hurt_amount_input.setValue(brush.get('hurt_amount', 10))
        
        # Fog specific fields (only shown when shader is Fog)
        self.fog_density_label = QLabel("Fog Density:")
        self.fog_density_input = QLineEdit(str(brush.get('fog_density', 2.0)))
        self.fog_color_label = QLabel("Fog Colour:")
        self.fog_color_button = QPushButton()
        self.fog_color_button.setFixedSize(200, 32)
        self.update_fog_color_button(brush.get('fog_color', [0.5, 0.6, 0.7]))

        self.mover_checkbox = QCheckBox()
        self.mover_checkbox.setStyleSheet("""
            QCheckBox::indicator:checked {
                background-color: #F08000;
                border: 1px solid #333;
            }
            QCheckBox::indicator:unchecked {
                background-color: #425f5d;
                border: 1px solid #333;
            }
            QCheckBox::indicator {
                width: 25px;
                height: 25px;
            }
        """)
        
        self.mover_speed_label = QLabel("Speed:")
        self.mover_speed_input = QLineEdit(str(brush.get('speed', 64.0)))
        self.mover_distance_label = QLabel("Distance:")
        self.mover_distance_input = QLineEdit(str(brush.get('distance', 128.0)))
        
        self.mover_direction_label = QLabel("Direction:")
        
        self.mover_dir_widget = QWidget()
        dir_layout = QGridLayout(self.mover_dir_widget)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(2)

        def create_dir_btn(text, direction):
            btn = QPushButton(text)
            btn.setFixedSize(30, 30)
            btn.setToolTip(f"Set direction to {direction}")
            btn.clicked.connect(lambda: self.update_object_prop('direction', direction))
            return btn

        dir_layout.addWidget(create_dir_btn("UP", [0, 1, 0]), 0, 0)
        dir_layout.addWidget(create_dir_btn("DN", [0, -1, 0]), 2, 0)
        dir_layout.addWidget(create_dir_btn("N", [0, 0, 1]), 0, 3) 
        dir_layout.addWidget(create_dir_btn("W", [-1, 0, 0]), 1, 2)
        dir_layout.addWidget(create_dir_btn("E", [1, 0, 0]), 1, 4)
        dir_layout.addWidget(create_dir_btn("S", [0, 0, -1]), 2, 3)

        self.preview_btn = QPushButton("Preview")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setStyleSheet("QPushButton { background-color: #425F5D; color: white; border-radius: 4px; padding: 6px; font-weight: bold; } QPushButton:checked { background-color: #0056b3; }")
        self.preview_btn.toggled.connect(self.toggle_preview)

        self.mover_start_on_label = QLabel("Start On:")
        self.mover_start_on_checkbox = QCheckBox()
        self.mover_start_on_checkbox.setStyleSheet("""
            QCheckBox::indicator:checked {
                background-color: #F08000;
                border: 1px solid #333;
            }
            QCheckBox::indicator:unchecked {
                background-color: #425f5d;
                border: 1px solid #333;
            }
            QCheckBox::indicator {
                width: 25px;
                height: 25px;
            }
        """)

        self.brush_name_label = QLabel("Name:")
        self.brush_name_input = QLineEdit(brush.get('name', ''))
        
        # Check if this brush has a valid connection (as source or target)
        brush_name = brush.get('name', '')
        has_valid_target = False
        is_targeted_by = []
        
        # Check if brush is a trigger/mover with valid target
        if brush.get('is_trigger') or brush.get('is_mover'):
            target_name = brush.get('target', '')
            if target_name and self._check_target_exists(target_name):
                has_valid_target = True
        
        # Check if brush is targeted by something
        if brush_name:
            is_targeted_by = self._find_targeting_sources(brush_name)
        
        # Style the name input based on connection status
        if has_valid_target or is_targeted_by:
            self.brush_name_input.setStyleSheet("""
                QLineEdit {
                    border: 2px solid #00FF00;
                    background-color: #1a3d1a;
                    padding: 2px;
                }
            """)
        else:
            self.brush_name_input.setStyleSheet("")

        self.locked_checkbox.setChecked(is_locked)
        self.trigger_checkbox.setChecked(is_trigger)
        self.type_combo.setCurrentText(brush.get('trigger_type', 'Once'))
        self.hurt_checkbox.setChecked(brush.get('hurt', False))
        self.mover_checkbox.setChecked(brush.get('is_mover', False))
        self.mover_start_on_checkbox.setChecked(brush.get('start_on', False))

        layout.addRow("Lock:", self.locked_checkbox)
        layout.addRow("Is Trigger:", self.trigger_checkbox)
        layout.addRow(self.target_label, self.target_input)
        layout.addRow(self.type_label, self.type_combo)
        self.hurt_label_text = QLabel("Hurt:")
        layout.addRow(self.hurt_label_text, self.hurt_checkbox)
        layout.addRow(self.hurt_amount_label, self.hurt_amount_input)
        
        # Fog properties rows
        layout.addRow(self.fog_density_label, self.fog_density_input)
        layout.addRow(self.fog_color_label, self.fog_color_button)

        layout.addRow("Is Mover:", self.mover_checkbox)
        layout.addRow(self.brush_name_label, self.brush_name_input)
        layout.addRow(self.mover_speed_label, self.mover_speed_input)
        layout.addRow(self.mover_distance_label, self.mover_distance_input)
        layout.addRow(self.mover_direction_label, self.mover_dir_widget)
        layout.addRow(self.mover_start_on_label, self.mover_start_on_checkbox)
        layout.addRow("", self.preview_btn)

        self.locked_checkbox.toggled.connect(self.on_lock_changed)
        self.brush_name_input.editingFinished.connect(lambda: self.update_object_prop('name', self.brush_name_input.text()))
        self.trigger_checkbox.toggled.connect(self.on_trigger_changed)
        self.target_input.editingFinished.connect(lambda: self.update_object_prop('target', self.target_input.text()))
        self.type_combo.currentTextChanged.connect(lambda t: self.update_object_prop('trigger_type', t))
        self.hurt_checkbox.toggled.connect(self.on_hurt_changed)
        self.hurt_amount_input.valueChanged.connect(lambda v: self.update_object_prop('hurt_amount', v))
        self.fog_density_input.editingFinished.connect(lambda: self.update_object_prop('fog_density', float(self.fog_density_input.text()) if self.fog_density_input.text() else 0.1))
        self.fog_color_button.clicked.connect(self.on_fog_color_changed)
        
        self.mover_checkbox.toggled.connect(self.on_mover_changed)
        self.mover_speed_input.editingFinished.connect(
            lambda: self.update_object_prop('speed', float(self.mover_speed_input.text()) if self.mover_speed_input.text() else 64.0))
        self.mover_distance_input.editingFinished.connect(
            lambda: self.update_object_prop('distance', float(self.mover_distance_input.text()) if self.mover_distance_input.text() else 128.0))
        
        self.mover_start_on_checkbox.toggled.connect(
            lambda checked: self.update_object_prop('start_on', checked))

        self.main_layout.addLayout(layout)
        
        # Add Shader dropdown
        self._add_shader_dropdown(brush)
        
        # Add Brush Colour picker
        self._add_brush_colour_picker(brush)
        
        self.update_brush_ui_state()

    def _add_shader_dropdown(self, brush):
        """Add shader dropdown for procedural material selection."""
        shader_layout = QFormLayout()
        
        self.shader_label = QLabel("Shader:")
        self.shader_combo = QComboBox()
        # Default = original flat shading (backwards compatible)
        # Added 'Fog' to the list
        shader_types = ['Default', 'Metal', 'Glass', 'Concrete', 'Wood', 'Marble', 'Glow', 'Water', 'Fog']
        self.shader_combo.addItems(shader_types)
        
        current_shader = brush.get('shader', 'Default')
        self.shader_combo.setCurrentText(current_shader)
        self.shader_combo.currentTextChanged.connect(self.on_shader_changed)
        
        shader_layout.addRow(self.shader_label, self.shader_combo)
        self.main_layout.addLayout(shader_layout)
        
        # Add glow light direction selector (visible only for Glow shader)
        self._add_glow_direction_widget(brush)
    
    def on_shader_changed(self, shader_type):
        """Handle shader type changes."""
        if self.current_object is None:
            return
        
        self.current_object['shader'] = shader_type
        
        # Maintain is_fog legacy flag for renderer compatibility
        is_fog = (shader_type == 'Fog')
        self.current_object['is_fog'] = is_fog

        # If a procedural shader or Fog is selected, disable trigger
        if shader_type != 'Default':
            self.current_object['is_trigger'] = False
            # Block signals to prevent on_trigger_changed from recursion
            if self.trigger_checkbox:
                self.trigger_checkbox.blockSignals(True)
                self.trigger_checkbox.setChecked(False)
                self.trigger_checkbox.blockSignals(False)
            
            # If it's Fog, ensure default values exist
            if is_fog:
                if 'fog_density' not in self.current_object:
                    self.current_object['fog_density'] = 2.0
                if 'fog_color' not in self.current_object:
                    self.current_object['fog_color'] = [0.5, 0.6, 0.7]
            
            # If it's Glow, ensure light direction exists
            if shader_type == 'Glow':
                if 'light_direction' not in self.current_object:
                    self.current_object['light_direction'] = 'top'

        self.update_brush_ui_state()
        # Defer update_all_ui to avoid destroying the combo box while its signal is active
        QTimer.singleShot(0, self.editor.update_all_ui)

    def _add_glow_direction_widget(self, brush):
        """Add light direction selector for glow shader brushes."""
        glow_layout = QFormLayout()
        
        self.glow_direction_label = QLabel("Light Direction:")
        
        self.glow_direction_widget = QWidget()
        dir_layout = QGridLayout(self.glow_direction_widget)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(2)
        
        # Face direction buttons - similar to mover but for light emission face
        def create_face_btn(text, face_name, tooltip):
            btn = QPushButton(text)
            btn.setFixedSize(40, 30)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda: self._set_glow_direction(face_name))
            return btn
        
        # Layout: TOP centered, then N/W/E/S, then BOTTOM centered
        dir_layout.addWidget(create_face_btn("TOP", "top", "Emit light from top face"), 0, 1)
        dir_layout.addWidget(create_face_btn("N", "north", "Emit light from north face (+Z)"), 1, 2)
        dir_layout.addWidget(create_face_btn("W", "west", "Emit light from west face (-X)"), 1, 0)
        dir_layout.addWidget(create_face_btn("E", "east", "Emit light from east face (+X)"), 1, 3)
        dir_layout.addWidget(create_face_btn("S", "south", "Emit light from south face (-Z)"), 2, 2)
        dir_layout.addWidget(create_face_btn("BTM", "bottom", "Emit light from bottom face"), 2, 1)
        
        glow_layout.addRow(self.glow_direction_label, self.glow_direction_widget)
        self.main_layout.addLayout(glow_layout)
        
        # Initialize direction if not set
        if brush.get('shader') == 'Glow' and 'light_direction' not in brush:
            brush['light_direction'] = 'top'
    
    def _set_glow_direction(self, face_name):
        """Set the light emission direction for a glow brush."""
        if self.current_object is None:
            return
        self.current_object['light_direction'] = face_name
        self.editor.update_all_ui()

    def _add_brush_colour_picker(self, brush):
        """Add colour picker for brush tint."""
        colour_layout = QFormLayout()
        
        # Container widget for colour button and reset button
        colour_widget = QWidget()
        colour_hbox = QHBoxLayout(colour_widget)
        colour_hbox.setContentsMargins(0, 0, 0, 0)
        colour_hbox.setSpacing(5)
        
        self.brush_colour_label = QLabel("Colour:")
        self.brush_colour_button = QPushButton()
        self.brush_colour_button.setFixedSize(160, 32)
        
        # Get current colour or default
        current_colour = brush.get('colour', [0.8, 0.8, 0.8])
        self._update_brush_colour_button(current_colour)
        self.brush_colour_button.clicked.connect(self._on_brush_colour_clicked)
        
        # Reset button
        self.brush_colour_reset_btn = QPushButton("Reset")
        self.brush_colour_reset_btn.setFixedSize(50, 32)
        self.brush_colour_reset_btn.setToolTip("Reset to default colour (grey)")
        self.brush_colour_reset_btn.clicked.connect(self._on_brush_colour_reset)
        
        colour_hbox.addWidget(self.brush_colour_button)
        colour_hbox.addWidget(self.brush_colour_reset_btn)
        colour_hbox.addStretch()
        
        colour_layout.addRow(self.brush_colour_label, colour_widget)
        self.main_layout.addLayout(colour_layout)
    
    def _update_brush_colour_button(self, colour_rgb):
        """Update the colour button's background to show the current colour."""
        # colour_rgb is in 0.0-1.0 range
        r = int(colour_rgb[0] * 255)
        g = int(colour_rgb[1] * 255)
        b = int(colour_rgb[2] * 255)
        self.brush_colour_button.setStyleSheet(f"background-color: rgb({r}, {g}, {b});")
    
    def _on_brush_colour_clicked(self):
        """Open colour dialog for brush tint."""
        if self.current_object is None:
            return
        
        # Get current colour (0.0-1.0 range) and convert to 0-255
        current = self.current_object.get('colour', [0.8, 0.8, 0.8])
        current_qcolor = QColor(int(current[0] * 255), int(current[1] * 255), int(current[2] * 255))
        
        color = QColorDialog.getColor(current_qcolor, self, "Choose Brush Colour")
        if color.isValid():
            # Store as 0.0-1.0 range
            new_colour = [color.redF(), color.greenF(), color.blueF()]
            self.current_object['colour'] = new_colour
            self._update_brush_colour_button(new_colour)
            self.editor.update_all_ui()
    
    def _on_brush_colour_reset(self):
        """Reset brush colour to default grey."""
        if self.current_object is None:
            return
        
        default_colour = [0.8, 0.8, 0.8]
        self.current_object['colour'] = default_colour
        self._update_brush_colour_button(default_colour)
        self.editor.update_all_ui()

    def toggle_preview(self, checked):
        if self.editor:
            if checked:
                self.preview_btn.setText("Stop Preview")
                self.editor.start_mover_preview(self.current_object)
            else:
                self.preview_btn.setText("Preview Movement")
                self.editor.stop_mover_preview()
    
    def on_hurt_changed(self, is_hurt):
        """Handle hurt trigger toggle."""
        if self.current_object is None:
            return
        self.current_object['hurt'] = is_hurt
        if is_hurt:
            if 'hurt_amount' not in self.current_object:
                self.current_object['hurt_amount'] = 10
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

    def on_mover_changed(self, is_mover):
        if self.current_object is None: return
        self.current_object['is_mover'] = is_mover
        if is_mover:
            if 'speed' not in self.current_object: self.current_object['speed'] = 64.0
            if 'distance' not in self.current_object: self.current_object['distance'] = 128.0
            if 'direction' not in self.current_object: self.current_object['direction'] = [0, 1, 0]
        self.set_object(self.current_object)
        self.editor.update_all_ui()

    def update_fog_color_button(self, color_rgb):
        qcolor = QColor.fromRgbF(*color_rgb)
        self.fog_color_button.setStyleSheet(f"background-color: {qcolor.name()}")

    def update_brush_ui_state(self):
        if self.current_object is None:
            return
        is_locked = self.current_object.get('lock', False)
        is_trigger = self.current_object.get('is_trigger', False)
        
        # Check shader type
        current_shader = self.current_object.get('shader', 'Default')
        is_fog = (current_shader == 'Fog')
        is_glow = (current_shader == 'Glow')
        has_procedural_shader = current_shader not in ['Default', 'Fog']
        
        is_hurt = self.current_object.get('hurt', False)
        
        if self.trigger_checkbox:
            self.trigger_checkbox.setEnabled(not is_locked and current_shader == 'Default')
        
        show_trigger_fields = is_trigger and not is_locked
        if self.target_label:
            self.target_label.setVisible(show_trigger_fields)
        if self.target_input:
            self.target_input.setVisible(show_trigger_fields)
        if self.type_label:
            self.type_label.setVisible(show_trigger_fields)
        if self.type_combo:
            self.type_combo.setVisible(show_trigger_fields)
        
        # Hurt trigger visibility
        if self.hurt_checkbox:
            self.hurt_checkbox.setVisible(show_trigger_fields)
            self.hurt_label_text.setVisible(show_trigger_fields) 

        show_hurt_amount = show_trigger_fields and is_hurt
        if self.hurt_amount_label:
            self.hurt_amount_label.setVisible(show_hurt_amount)
        if self.hurt_amount_input:
            self.hurt_amount_input.setVisible(show_hurt_amount)
        
        # Show Fog fields only if Shader is 'Fog'
        show_fog_fields = is_fog and not is_locked
        if self.fog_density_label:
            self.fog_density_label.setVisible(show_fog_fields)
        if self.fog_density_input:
            self.fog_density_input.setVisible(show_fog_fields)
        if self.fog_color_label:
            self.fog_color_label.setVisible(show_fog_fields)
        if self.fog_color_button:
            self.fog_color_button.setVisible(show_fog_fields)
        
        # Show Glow direction fields only if Shader is 'Glow'
        show_glow_fields = is_glow and not is_locked
        if self.glow_direction_label:
            self.glow_direction_label.setVisible(show_glow_fields)
        if self.glow_direction_widget:
            self.glow_direction_widget.setVisible(show_glow_fields)
            
        # Show Colour Picker for any brush EXCEPT triggers
        # (Fog volumes can have color via the fog specific color picker, but maybe user wants tint too? 
        # The prompt said "NOT if the brush is already a trigger". 
        # Assuming we allow tint on normal brushes + procedural shaders + fog (if useful), but block on trigger.)
        show_color_picker = not is_trigger and not is_locked
        if self.brush_colour_label:
            self.brush_colour_label.setVisible(show_color_picker)
        if self.brush_colour_button:
            self.brush_colour_button.setVisible(show_color_picker)
        if self.brush_colour_reset_btn:
            self.brush_colour_reset_btn.setVisible(show_color_picker)

        is_mover = self.current_object.get('is_mover', False)
        show_mover_fields = is_mover and not is_locked
        if self.brush_name_label:
            self.brush_name_label.setVisible(show_mover_fields)
        if self.brush_name_input:
            self.brush_name_input.setVisible(show_mover_fields)
        if self.mover_speed_label:
            self.mover_speed_label.setVisible(show_mover_fields)
        if self.mover_speed_input:
            self.mover_speed_input.setVisible(show_mover_fields)
        if self.mover_distance_label:
            self.mover_distance_label.setVisible(show_mover_fields)
        if self.mover_direction_label:
            self.mover_direction_label.setVisible(show_mover_fields)
        if self.mover_dir_widget:
            self.mover_dir_widget.setVisible(show_mover_fields)
        if self.mover_start_on_label:
            self.mover_start_on_label.setVisible(show_mover_fields)
        if self.mover_start_on_checkbox:
            self.mover_start_on_checkbox.setVisible(show_mover_fields)
        if self.preview_btn:
            self.preview_btn.setVisible(show_mover_fields)
        
        # Shader dropdown - disable when trigger is active
        if self.shader_combo:
            self.shader_combo.setEnabled(not is_locked and not is_trigger)

    def on_lock_changed(self, is_locked):
        if self.current_object is None: return
        self.current_object['lock'] = is_locked
        self.update_brush_ui_state()
        self.editor.update_all_ui()

    def on_trigger_changed(self, is_trigger):
        if self.current_object is None: return
        self.current_object['is_trigger'] = is_trigger
        if is_trigger:
            self.current_object['is_fog'] = False
            self.current_object['shader'] = 'Default'  # Reset shader
            if self.shader_combo:
                self.shader_combo.setCurrentText('Default')
            if 'textures' not in self.current_object:
                self.current_object['textures'] = {}
            for face in ['north','south','east','west','top','down']:
                self.current_object['textures'][face] = 'trigger.jpg'
        else:
            # Clear hurt when disabling trigger
            self.current_object['hurt'] = False
        self.set_object(self.current_object)
        self.editor.update_all_ui()

    def populate_for_thing(self, thing):
        layout = QFormLayout()
        
        # Check if this thing is targeted by any triggers/movers
        thing_name = getattr(thing, 'name', '') or thing.properties.get('name', '')
        targeting_sources = self._find_targeting_sources(thing_name) if thing_name else []
        
        # Show "Targeted by" info if applicable
        if targeting_sources:
            source_texts = [f"{name} ({stype})" for name, stype in targeting_sources]
            self.targeted_by_label = QLabel(", ".join(source_texts))
            self.targeted_by_label.setStyleSheet("""
                QLabel {
                    color: #00FF00;
                    font-weight: bold;
                    padding: 2px;
                    background-color: #1a3d1a;
                    border: 1px solid #00AA00;
                    border-radius: 3px;
                }
            """)
            self.targeted_by_label.setWordWrap(True)
            layout.addRow("Targeted by:", self.targeted_by_label)
        
        # 1. SPECIAL CASE: Model path selector
        if isinstance(thing, Model):
            self.add_model_path_widget(layout, thing)
            self.add_vector3_widget(layout, thing, 'scale')
            self.add_vector3_widget(layout, thing, 'rotation')

        # 2. SPECIAL CASE: Light Colour
        if isinstance(thing, Light):
            self.add_color_picker_widget(layout, thing, 'colour')

        # 3. GENERIC PROPERTIES
        for key, value in sorted(thing.properties.items()):
            # Skip keys handled by special widgets
            if isinstance(thing, Light) and key == 'colour': continue
            if isinstance(thing, Model) and key in ['model_path', 'scale', 'rotation', 'type']: continue

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
                item_types = ['health', 'ammo', 'armour', 'powerup', 'key', 'message', 'weapon']
                widget.addItems(item_types)
                widget.setCurrentText(value)
                widget.currentTextChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget)
            elif isinstance(thing, Pickup) and key == 'activation':
                widget = QComboBox()
                activation_types = ['walk_over', 'use']
                widget.addItems(activation_types)
                widget.setCurrentText(value)
                widget.currentTextChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget)
            elif isinstance(value, bool):
                widget = QCheckBox()
                widget.setStyleSheet("""
                    QCheckBox::indicator:checked {
                        background-color: #F08000;
                        border: 1px solid #333;
                    }
                    QCheckBox::indicator:unchecked {
                        background-color: #425f5d;
                        border: 1px solid #333;
                    }
                    QCheckBox::indicator {
                        width: 25px;
                        height: 25px;
                    }
                """)
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

    def add_model_path_widget(self, layout, thing):
        widget = QWidget()
        h_box = QHBoxLayout(widget)
        h_box.setContentsMargins(0, 0, 0, 0)
        
        path_edit = QLineEdit(thing.properties.get('model_path', ''))
        path_edit.setReadOnly(True)
        btn = QPushButton("...")
        btn.setFixedWidth(30)
        
        def pick_model():
            filepath, _ = QFileDialog.getOpenFileName(self, "Select OBJ Model", "assets/models", "OBJ Files (*.obj)")
            if filepath:
                try: rel_path = os.path.relpath(filepath, "assets").replace("\\", "/")
                except: rel_path = filepath
                if not rel_path.startswith(".."): rel_path = os.path.join("assets", rel_path) if not rel_path.startswith("assets") else rel_path

                self.update_object_prop('model_path', rel_path)
                path_edit.setText(rel_path)

        btn.clicked.connect(pick_model)
        h_box.addWidget(path_edit)
        h_box.addWidget(btn)
        layout.addRow("Model Path:", widget)

    def add_vector3_widget(self, layout, thing, key):
        widget = QWidget()
        h_box = QHBoxLayout(widget)
        h_box.setContentsMargins(0, 0, 0, 0)
        
        val = thing.properties.get(key, [0, 0, 0])
        # Ensure it's a list of 3
        if not isinstance(val, list) or len(val) != 3: val = [0, 0, 0]
        
        coords = ['x', 'y', 'z']
        edits = []
        
        for i in range(3):
            # h_box.addWidget(QLabel(coords[i]))
            le = QLineEdit(str(val[i]))
            le.setFixedWidth(50)
            
            def update_vec(text, idx=i):
                try:
                    current_vec = thing.properties.get(key, [0,0,0])
                    current_vec[idx] = float(text)
                    self.update_object_prop(key, current_vec)
                except ValueError: pass

            le.editingFinished.connect(lambda l=le, idx=i: update_vec(l.text(), idx))
            h_box.addWidget(le)
            edits.append(le)
            
        layout.addRow(key.title() + ":", widget)

    def add_sound_file_widget(self, form_layout, thing, key, value):
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        line_edit = QLineEdit(str(value))
        line_edit.setReadOnly(True)
        button = QPushButton("...")
        button.setFixedWidth(30)
        def open_dialog():
            start_path = os.path.join('assets', 'sounds')
            if not os.path.exists(start_path): os.makedirs(start_path)
            filepath, _ = QFileDialog.getOpenFileName(self, "Select Sound File", start_path, "Sound Files (*.wav *.mp3)")
            if filepath:
                try: relative_path = os.path.relpath(filepath, 'assets').replace('\\', '/')
                except ValueError: relative_path = os.path.basename(filepath)
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