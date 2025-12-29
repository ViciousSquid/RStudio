import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QSpinBox,
                             QFormLayout, QCheckBox, QComboBox, QPushButton,
                             QHBoxLayout, QColorDialog, QFileDialog, QGridLayout, QToolButton)
from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon
from editor.things import Thing, Light, Pickup, Monster, Model, Speaker

class ClickableLineEdit(QLineEdit):
    clicked_while_empty = pyqtSignal()
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and not self.text().strip():
            self.clicked_while_empty.emit()
        super().mousePressEvent(event)

class PropertyEditor(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.current_object = None
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(2)
        self.setLayout(self.main_layout)
        
        self.locked_checkbox = None
        self.trigger_checkbox = None
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

        self.brush_name_label = None
        self.brush_name_input = None
        
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
        
        self.door_checkbox = None
        self.door_checkbox_label = None
        self.door_direction_label = None
        self.door_direction_combo = None
        self.door_distance_label = None
        self.door_distance_input = None
        self.door_lip_label = None
        self.door_lip_input = None
        self.door_speed_label = None
        self.door_speed_input = None
        self.door_auto_open_checkbox = None
        self.door_locked_checkbox = None
        self.door_needs_key_checkbox = None
        self.door_key_name_label = None
        self.door_key_name_input = None
        self.door_preview_btn = None
        
        self.hurt_checkbox = None
        self.hurt_amount_label = None
        self.hurt_amount_input = None
        
        self.shader_label = None
        self.shader_combo = None
        
        self.glow_direction_label = None
        self.glow_direction_widget = None
        
        self.brush_colour_label = None
        self.brush_colour_button = None
        self.brush_colour_reset_btn = None
        self.brush_colour_widget = None
        
        # Pickup-specific widgets
        self.pickup_key_name_label = None
        self.pickup_key_name_input = None

        self.set_object(None)
    
    def _find_targeting_sources(self, target_name):
        if not target_name: return []
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
        if not target_name: return False
        for brush in self.editor.state.brushes:
            if brush.get('name') == target_name: return True
        for thing in self.editor.state.things:
            thing_name = getattr(thing, 'name', '') or thing.properties.get('name', '')
            if thing_name == target_name: return True
        return False
    
    def _start_connection_from_field(self, brush):
        if not brush.get('is_trigger') and not brush.get('is_mover'): return
        if hasattr(self.editor, 'right_tabs'):
            current_view = self.editor.right_tabs.currentWidget()
            from editor.view_2d import View2D
            if isinstance(current_view, View2D):
                current_view.start_connection_mode(brush)
                if hasattr(self.editor, 'show_toast'):
                    self.editor.show_toast("Drag to target, ESC to cancel")

    def clear_layout(self):
        while self.main_layout.count():
            child = self.main_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
            elif child.layout():
                layout = child.layout()
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget(): item.widget().deleteLater()

    def set_object(self, obj):
        self.current_object = obj
        self.clear_layout()
        if obj is None:
            self.main_layout.addWidget(QLabel("Nothing selected."))
            return
        if isinstance(obj, dict): self.populate_for_brush(obj)
        elif isinstance(obj, Thing): self.populate_for_thing(obj)

    def populate_for_brush(self, brush):
        layout = QFormLayout()
        layout.setSpacing(4)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        
        is_locked = brush.get('lock', False)
        is_trigger = brush.get('is_trigger', False)
        is_mover = brush.get('is_mover', False)
        
        if brush.get('is_fog', False) and brush.get('shader') != 'Fog':
            brush['shader'] = 'Fog'

        self.brush_name_label = QLabel("Name:")
        self.brush_name_label.setStyleSheet("QLabel { background-color: #6C3BAA; color: white; font-weight: bold; padding: 6px 8px; border-radius: 3px; }")
        self.brush_name_input = QLineEdit(brush.get('name', ''))
        self.brush_name_input.setStyleSheet("QLineEdit { background-color: #6C3BAA; color: white; font-weight: bold; padding: 6px; border: 2px solid #8B5AC2; border-radius: 3px; } QLineEdit:focus { border: 2px solid #A875D6; background-color: #7B4AB9; }")
        self.brush_name_input.setPlaceholderText("Enter name...")
        
        brush_name = brush.get('name', '')
        has_valid_target = False
        is_targeted_by = []
        
        if brush.get('is_trigger') or brush.get('is_mover'):
            target_name = brush.get('target', '')
            if target_name and self._check_target_exists(target_name): has_valid_target = True
        
        if brush_name: is_targeted_by = self._find_targeting_sources(brush_name)

        layout.addRow(self.brush_name_label, self.brush_name_input)

        if is_targeted_by:
            source_texts = [f"{name} ({stype})" for name, stype in is_targeted_by]
            self.targeted_by_label = QLabel(", ".join(source_texts))
            self.targeted_by_label.setStyleSheet("QLabel { color: #00FF00; font-weight: bold; padding: 2px; background-color: #1a3d1a; border: 1px solid #00AA00; border-radius: 3px; }")
            self.targeted_by_label.setWordWrap(True)
            layout.addRow("Targeted by:", self.targeted_by_label)

        self.locked_checkbox = QCheckBox("Prevent selection/editing")
        self.locked_checkbox.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 20px; height: 20px; }")
        
        self.trigger_checkbox = QCheckBox("Can trigger other objects")
        self.trigger_checkbox.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 20px; height: 20px; }")
        
        self.target_label = QLabel("Target:")
        self.target_input = ClickableLineEdit(brush.get('target', ''))
        self.target_input.setPlaceholderText("Click to connect...")
        self.target_input.clicked_while_empty.connect(lambda: self._start_connection_from_field(brush))

        if has_valid_target:
            self.target_input.setStyleSheet("QLineEdit { background-color: #1a3d1a; border: 2px solid #00AA00; color: #00FF00; font-weight: bold; padding: 4px; border-radius: 3px; } QLineEdit:focus { border: 2px solid #00FF00; }")
        else:
            target_name = brush.get('target', '')
            if target_name:
                self.target_input.setStyleSheet("QLineEdit { background-color: #3d1a1a; border: 2px solid #AA0000; color: #FF6666; font-weight: bold; padding: 4px; border-radius: 3px; } QLineEdit:focus { border: 2px solid #FF0000; }")
            else:
                self.target_input.setStyleSheet("")

        self.type_label = QLabel("Trigger Type:")
        self.type_combo = QComboBox()
        self.type_combo.addItems(['Once', 'Multiple'])
        
        self.hurt_checkbox = QCheckBox("Hurts player")
        self.hurt_checkbox.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 20px; height: 20px; }")
        self.hurt_amount_label = QLabel("Damage:")
        self.hurt_amount_input = QSpinBox()
        self.hurt_amount_input.setRange(1, 1000)
        self.hurt_amount_input.setValue(brush.get('hurt_amount', 10))
        
        self.fog_density_label = QLabel("Fog Density:")
        self.fog_density_input = QLineEdit(str(brush.get('fog_density', 2.0)))
        self.fog_color_label = QLabel("Fog Color:")
        self.fog_color_button = QPushButton()
        self.fog_color_button.setFixedSize(100, 25)
        self.update_fog_color_button(brush.get('fog_color', [0.5, 0.6, 0.7]))

        self.mover_checkbox = QCheckBox("Moves back and forth")
        self.mover_checkbox.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 20px; height: 20px; }")
        self.mover_speed_label = QLabel("Speed:")
        self.mover_speed_input = QLineEdit(str(brush.get('speed', 64.0)))
        self.mover_distance_label = QLabel("Distance:")
        self.mover_distance_input = QLineEdit(str(brush.get('distance', 128.0)))
        self.mover_direction_label = QLabel("Direction:")
        self.mover_dir_widget = QWidget()
        dir_layout = QHBoxLayout(self.mover_dir_widget)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(2)
        
        direction = brush.get('direction', [0, 1, 0])
        self.dir_x_input = QLineEdit(str(direction[0]))
        self.dir_y_input = QLineEdit(str(direction[1]))
        self.dir_z_input = QLineEdit(str(direction[2]))
        for inp in [self.dir_x_input, self.dir_y_input, self.dir_z_input]:
            inp.setFixedWidth(40)
        dir_layout.addWidget(QLabel("X:")); dir_layout.addWidget(self.dir_x_input)
        dir_layout.addWidget(QLabel("Y:")); dir_layout.addWidget(self.dir_y_input)
        dir_layout.addWidget(QLabel("Z:")); dir_layout.addWidget(self.dir_z_input)
        dir_layout.addStretch()
        
        self.mover_start_on_label = QLabel("Start On:")
        self.mover_start_on_checkbox = QCheckBox("Begin moving immediately")
        self.mover_start_on_checkbox.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 20px; height: 20px; }")
        
        self.preview_btn = QPushButton("Preview Movement")
        self.preview_btn.setCheckable(True)
        self.preview_btn.setStyleSheet("QPushButton { background-color: #425F5D; color: white; border-radius: 4px; padding: 6px; font-weight: bold; } QPushButton:checked { background-color: #0056b3; }")
        self.preview_btn.toggled.connect(self.toggle_preview)
        
        # Door widgets
        self.door_checkbox_label = QLabel("Is Door:")
        self.door_checkbox = QCheckBox("Acts as a door")
        self.door_checkbox.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 20px; height: 20px; }")
        self.door_checkbox.setChecked(brush.get('is_door', False))
        
        self.door_direction_label = QLabel("Open Direction:")
        self.door_direction_combo = QComboBox()
        self.door_direction_combo.addItems(['up', 'down', 'north', 'south', 'east', 'west'])
        self.door_direction_combo.setCurrentText(brush.get('door_direction', 'up'))
        
        self.door_distance_label = QLabel("Open Distance:")
        self.door_distance_input = QLineEdit(str(brush.get('door_distance', 128.0)))
        
        self.door_lip_label = QLabel("Lip (stay closed):")
        self.door_lip_input = QLineEdit(str(brush.get('door_lip', 8.0)))
        
        self.door_speed_label = QLabel("Door Speed:")
        self.door_speed_input = QLineEdit(str(brush.get('door_speed', 64.0)))
        
        self.door_auto_open_checkbox = QCheckBox("Auto-open when near")
        self.door_auto_open_checkbox.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 20px; height: 20px; }")
        self.door_auto_open_checkbox.setChecked(brush.get('door_auto_open', False))
        
        self.door_locked_checkbox = QCheckBox("Locked (can be triggered)")
        self.door_locked_checkbox.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 20px; height: 20px; }")
        self.door_locked_checkbox.setChecked(brush.get('door_locked', False))
        
        self.door_needs_key_checkbox = QCheckBox("Needs key")
        self.door_needs_key_checkbox.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 20px; height: 20px; }")
        self.door_needs_key_checkbox.setChecked(brush.get('door_needs_key', False))
        
        self.door_key_name_label = QLabel("Key Name:")
        self.door_key_name_input = QLineEdit(brush.get('door_key_name', ''))
        self.door_key_name_input.setPlaceholderText("e.g. blue_key")
        
        self.door_preview_btn = QPushButton("Preview Door")
        self.door_preview_btn.setCheckable(True)
        self.door_preview_btn.setStyleSheet("QPushButton { background-color: #425F5D; color: white; border-radius: 4px; padding: 6px; font-weight: bold; } QPushButton:checked { background-color: #0056b3; }")
        self.door_preview_btn.toggled.connect(self.toggle_door_preview)

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
        
        layout.addRow(self.fog_density_label, self.fog_density_input)
        layout.addRow(self.fog_color_label, self.fog_color_button)

        layout.addRow("Is Mover:", self.mover_checkbox)
        layout.addRow(self.mover_speed_label, self.mover_speed_input)
        layout.addRow(self.mover_distance_label, self.mover_distance_input)
        layout.addRow(self.mover_direction_label, self.mover_dir_widget)
        layout.addRow(self.mover_start_on_label, self.mover_start_on_checkbox)
        layout.addRow("", self.preview_btn)
        
        layout.addRow(self.door_checkbox_label, self.door_checkbox)
        layout.addRow(self.door_direction_label, self.door_direction_combo)
        layout.addRow(self.door_distance_label, self.door_distance_input)
        layout.addRow(self.door_lip_label, self.door_lip_input)
        layout.addRow(self.door_speed_label, self.door_speed_input)
        layout.addRow("", self.door_auto_open_checkbox)
        layout.addRow("", self.door_locked_checkbox)
        layout.addRow("", self.door_needs_key_checkbox)
        layout.addRow(self.door_key_name_label, self.door_key_name_input)
        layout.addRow("", self.door_preview_btn)

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
        self.mover_speed_input.editingFinished.connect(lambda: self.update_object_prop('speed', float(self.mover_speed_input.text()) if self.mover_speed_input.text() else 64.0))
        self.mover_distance_input.editingFinished.connect(lambda: self.update_object_prop('distance', float(self.mover_distance_input.text()) if self.mover_distance_input.text() else 128.0))
        self.mover_start_on_checkbox.toggled.connect(lambda checked: self.update_object_prop('start_on', checked))
        
        self.door_checkbox.toggled.connect(self.on_door_changed)
        self.door_direction_combo.currentTextChanged.connect(lambda t: self.update_object_prop('door_direction', t))
        self.door_distance_input.editingFinished.connect(lambda: self.update_object_prop('door_distance', float(self.door_distance_input.text()) if self.door_distance_input.text() else 128.0))
        self.door_lip_input.editingFinished.connect(lambda: self.update_object_prop('door_lip', float(self.door_lip_input.text()) if self.door_lip_input.text() else 8.0))
        self.door_speed_input.editingFinished.connect(lambda: self.update_object_prop('door_speed', float(self.door_speed_input.text()) if self.door_speed_input.text() else 64.0))
        self.door_auto_open_checkbox.toggled.connect(lambda checked: self.update_object_prop('door_auto_open', checked))
        self.door_locked_checkbox.toggled.connect(lambda checked: self.update_object_prop('door_locked', checked))
        self.door_needs_key_checkbox.toggled.connect(self.on_door_needs_key_changed)
        self.door_key_name_input.editingFinished.connect(lambda: self.update_object_prop('door_key_name', self.door_key_name_input.text()))

        self.main_layout.addLayout(layout)
        self._add_shader_dropdown(brush)
        self._add_brush_colour_picker(brush)
        self.main_layout.addStretch()
        self.update_brush_ui_state()

    def _add_shader_dropdown(self, brush):
        shader_layout = QFormLayout()
        shader_layout.setSpacing(4)
        shader_layout.setContentsMargins(0, 0, 0, 0)
        self.shader_label = QLabel("Shader:")
        self.shader_combo = QComboBox()
        shader_types = ['Default', 'Metal', 'Glass', 'Concrete', 'Wood', 'Marble', 'Glow', 'Water', 'Fog']
        self.shader_combo.addItems(shader_types)
        current_shader = brush.get('shader', 'Default')
        self.shader_combo.setCurrentText(current_shader)
        self.shader_combo.currentTextChanged.connect(self.on_shader_changed)
        shader_layout.addRow(self.shader_label, self.shader_combo)
        self.main_layout.addLayout(shader_layout)
        self._add_glow_direction_widget(brush)
    
    def on_shader_changed(self, shader_type):
        if self.current_object is None: return
        self.current_object['shader'] = shader_type
        is_fog = (shader_type == 'Fog')
        self.current_object['is_fog'] = is_fog
        if shader_type != 'Default':
            self.current_object['is_trigger'] = False
            if self.trigger_checkbox:
                self.trigger_checkbox.blockSignals(True)
                self.trigger_checkbox.setChecked(False)
                self.trigger_checkbox.blockSignals(False)
            if is_fog:
                if 'fog_density' not in self.current_object: self.current_object['fog_density'] = 2.0
                if 'fog_color' not in self.current_object: self.current_object['fog_color'] = [0.5, 0.6, 0.7]
            if shader_type == 'Glow':
                if 'light_direction' not in self.current_object: self.current_object['light_direction'] = 'top'
        self.update_brush_ui_state()
        QTimer.singleShot(0, self.editor.update_all_ui)

    def _add_glow_direction_widget(self, brush):
        glow_layout = QFormLayout()
        glow_layout.setSpacing(4)
        glow_layout.setContentsMargins(0, 0, 0, 0)
        self.glow_direction_label = QLabel("Light Direction:")
        self.glow_direction_widget = QWidget()
        dir_layout = QGridLayout(self.glow_direction_widget)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(2)
        def create_face_btn(text, face_name, tooltip):
            btn = QPushButton(text)
            btn.setFixedSize(40, 30)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda: self._set_glow_direction(face_name))
            return btn
        dir_layout.addWidget(create_face_btn("TOP", "top", "Emit light from top face"), 0, 1)
        dir_layout.addWidget(create_face_btn("N", "north", "Emit light from north face (+Z)"), 1, 2)
        dir_layout.addWidget(create_face_btn("W", "west", "Emit light from west face (-X)"), 1, 0)
        dir_layout.addWidget(create_face_btn("E", "east", "Emit light from east face (+X)"), 1, 3)
        dir_layout.addWidget(create_face_btn("S", "south", "Emit light from south face (-Z)"), 2, 2)
        dir_layout.addWidget(create_face_btn("BTM", "bottom", "Emit light from bottom face"), 2, 1)
        glow_layout.addRow(self.glow_direction_label, self.glow_direction_widget)
        self.main_layout.addLayout(glow_layout)
        if brush.get('shader') == 'Glow' and 'light_direction' not in brush:
            brush['light_direction'] = 'top'
    
    def _set_glow_direction(self, face_name):
        if self.current_object is None: return
        self.current_object['light_direction'] = face_name
        self.editor.update_all_ui()

    def _add_brush_colour_picker(self, brush):
        colour_layout = QFormLayout()
        colour_layout.setSpacing(4)
        colour_layout.setContentsMargins(0, 0, 0, 0)
        self.brush_colour_widget = QWidget()
        colour_hbox = QHBoxLayout(self.brush_colour_widget)
        colour_hbox.setContentsMargins(0, 0, 0, 0)
        colour_hbox.setSpacing(5)
        self.brush_colour_label = QLabel("Colour:")
        self.brush_colour_button = QPushButton()
        self.brush_colour_button.setFixedSize(160, 32)
        current_colour = brush.get('colour', [0.8, 0.8, 0.8])
        self._update_brush_colour_button(current_colour)
        self.brush_colour_button.clicked.connect(self._on_brush_colour_clicked)
        self.brush_colour_reset_btn = QPushButton("Reset")
        self.brush_colour_reset_btn.setFixedSize(50, 32)
        self.brush_colour_reset_btn.setToolTip("Reset to default colour (grey)")
        self.brush_colour_reset_btn.clicked.connect(self._on_brush_colour_reset)
        colour_hbox.addWidget(self.brush_colour_button)
        colour_hbox.addWidget(self.brush_colour_reset_btn)
        colour_hbox.addStretch()
        colour_layout.addRow(self.brush_colour_label, self.brush_colour_widget)
        self.main_layout.addLayout(colour_layout)
    
    def _update_brush_colour_button(self, colour_rgb):
        r = int(colour_rgb[0] * 255)
        g = int(colour_rgb[1] * 255)
        b = int(colour_rgb[2] * 255)
        self.brush_colour_button.setStyleSheet(f"background-color: rgb({r}, {g}, {b});")
    
    def _on_brush_colour_clicked(self):
        if self.current_object is None: return
        current = self.current_object.get('colour', [0.8, 0.8, 0.8])
        current_qcolor = QColor(int(current[0] * 255), int(current[1] * 255), int(current[2] * 255))
        color = QColorDialog.getColor(current_qcolor, self, "Choose Brush Colour")
        if color.isValid():
            new_colour = [color.redF(), color.greenF(), color.blueF()]
            self.current_object['colour'] = new_colour
            self._update_brush_colour_button(new_colour)
            self.editor.update_all_ui()
    
    def _on_brush_colour_reset(self):
        if self.current_object is None: return
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
        if self.current_object is None: return
        self.current_object['hurt'] = is_hurt
        if is_hurt:
            if 'hurt_amount' not in self.current_object: self.current_object['hurt_amount'] = 10
        self.update_brush_ui_state()
        self.editor.update_all_ui()

    def on_fog_color_changed(self):
        if self.current_object is None: return
        color = QColorDialog.getColor()
        if color.isValid():
            self.current_object['fog_color'] = [color.redF(), color.greenF(), color.blueF()]
            self.update_fog_color_button(self.current_object['fog_color'])
    
    def update_fog_color_button(self, color):
        if self.fog_color_button:
            r, g, b = int(color[0] * 255), int(color[1] * 255), int(color[2] * 255)
            self.fog_color_button.setStyleSheet(f"background-color: rgb({r}, {g}, {b});")

    def toggle_door_preview(self, checked):
        if self.editor:
            if checked:
                self.door_preview_btn.setText("Stop Preview")
                # Use the existing mover preview methods as door preview
                # This assumes your MainWindow has start_mover_preview and stop_mover_preview methods
                # that can handle door objects as well as mover objects
                if hasattr(self.editor, 'start_mover_preview'):
                    self.editor.start_mover_preview(self.current_object)
                else:
                    print("Warning: Editor does not have start_mover_preview method")
            else:
                self.door_preview_btn.setText("Preview Door")
                if hasattr(self.editor, 'stop_mover_preview'):
                    self.editor.stop_mover_preview()
                else:
                    print("Warning: Editor does not have stop_mover_preview method")

    def on_door_changed(self, is_door):
        if self.current_object is None: return
        self.current_object['is_door'] = is_door
        if is_door:
            if 'door_direction' not in self.current_object: self.current_object['door_direction'] = 'up'
            if 'door_distance' not in self.current_object: self.current_object['door_distance'] = 128.0
            if 'door_lip' not in self.current_object: self.current_object['door_lip'] = 8.0
            if 'door_speed' not in self.current_object: self.current_object['door_speed'] = 64.0
        self.update_brush_ui_state()
        self.editor.update_all_ui()

    def on_door_needs_key_changed(self, needs_key):
        if self.current_object is None: return
        self.current_object['door_needs_key'] = needs_key
        if needs_key:
            if 'door_key_name' not in self.current_object: self.current_object['door_key_name'] = ''
        self.update_brush_ui_state()
        self.editor.update_all_ui()

    def on_lock_changed(self, is_locked):
        if self.current_object: self.current_object['lock'] = is_locked

    def on_trigger_changed(self, is_trigger):
        if self.current_object is None: return
        self.current_object['is_trigger'] = is_trigger
        if is_trigger:
            if 'trigger_type' not in self.current_object: self.current_object['trigger_type'] = 'Once'
            for face in ['top', 'bottom', 'north', 'south', 'east', 'west']:
                if 'textures' not in self.current_object: self.current_object['textures'] = {}
                self.current_object['textures'][face] = 'trigger.jpg'
        else:
            self.current_object['hurt'] = False
        self.set_object(self.current_object)
        self.editor.update_all_ui()

    def on_mover_changed(self, is_mover):
        if self.current_object is None: return
        self.current_object['is_mover'] = is_mover
        if is_mover:
            if 'speed' not in self.current_object: self.current_object['speed'] = 64.0
            if 'distance' not in self.current_object: self.current_object['distance'] = 128.0
            if 'direction' not in self.current_object: self.current_object['direction'] = [0, 1, 0]
        self.update_brush_ui_state()
        self.editor.update_all_ui()

    def update_brush_ui_state(self):
        if self.current_object is None: return
        
        is_trigger = self.current_object.get('is_trigger', False)
        is_mover = self.current_object.get('is_mover', False)
        is_door = self.current_object.get('is_door', False)
        is_hurt = self.current_object.get('hurt', False)
        is_fog = self.current_object.get('is_fog', False) or self.current_object.get('shader') == 'Fog'
        is_glow = self.current_object.get('shader') == 'Glow'
        needs_key = self.current_object.get('door_needs_key', False)
        
        # Trigger widgets
        for w in [self.target_label, self.target_input, self.type_label, self.type_combo]:
            if w: w.setVisible(is_trigger or is_mover)
        for w in [self.hurt_label_text, self.hurt_checkbox]:
            if w: w.setVisible(is_trigger)
        for w in [self.hurt_amount_label, self.hurt_amount_input]:
            if w: w.setVisible(is_trigger and is_hurt)
        
        # Fog widgets
        for w in [self.fog_density_label, self.fog_density_input, self.fog_color_label, self.fog_color_button]:
            if w: w.setVisible(is_fog)
        
        # Mover widgets
        for w in [self.mover_speed_label, self.mover_speed_input, self.mover_distance_label, 
                  self.mover_distance_input, self.mover_direction_label, self.mover_dir_widget, 
                  self.mover_start_on_label, self.mover_start_on_checkbox, self.preview_btn]:
            if w: w.setVisible(is_mover)
        
        # Door widgets
        for w in [self.door_direction_label, self.door_direction_combo, 
                  self.door_distance_label, self.door_distance_input,
                  self.door_lip_label, self.door_lip_input,
                  self.door_speed_label, self.door_speed_input,
                  self.door_auto_open_checkbox, self.door_locked_checkbox,
                  self.door_needs_key_checkbox, self.door_preview_btn]:
            if w: w.setVisible(is_door)
        
        # Key name field - only visible when door needs key
        for w in [self.door_key_name_label, self.door_key_name_input]:
            if w: w.setVisible(is_door and needs_key)
        
        # Glow direction
        if self.glow_direction_label: self.glow_direction_label.setVisible(is_glow)
        if self.glow_direction_widget: self.glow_direction_widget.setVisible(is_glow)

    def populate_for_thing(self, thing):
        layout = QFormLayout()
        
        name_lbl = QLabel("Name:")
        name_lbl.setStyleSheet("QLabel { background-color: #6C3BAA; color: white; font-weight: bold; padding: 6px 8px; border-radius: 3px; }")
        cur_name = thing.properties.get('name', '')
        name_inp = QLineEdit(str(cur_name))
        name_inp.setStyleSheet("QLineEdit { background-color: #6C3BAA; color: white; font-weight: bold; padding: 6px; border: 2px solid #8B5AC2; border-radius: 3px; } QLineEdit:focus { border: 2px solid #A875D6; background-color: #7B4AB9; }")
        name_inp.setPlaceholderText("Enter name...")
        name_inp.editingFinished.connect(lambda: self.update_object_prop('name', name_inp.text()))
        layout.addRow(name_lbl, name_inp)
        
        thing_name = getattr(thing, 'name', '') or thing.properties.get('name', '')
        targeting_sources = self._find_targeting_sources(thing_name) if thing_name else []
        if targeting_sources:
            source_texts = [f"{name} ({stype})" for name, stype in targeting_sources]
            self.targeted_by_label = QLabel(", ".join(source_texts))
            self.targeted_by_label.setStyleSheet("QLabel { color: #00FF00; font-weight: bold; padding: 2px; background-color: #1a3d1a; border: 1px solid #00AA00; border-radius: 3px; }")
            self.targeted_by_label.setWordWrap(True)
            layout.addRow("Targeted by:", self.targeted_by_label)
        
        if isinstance(thing, Model):
            self.add_model_path_widget(layout, thing)
            self.add_vector3_widget(layout, thing, 'scale')
            self.add_vector3_widget(layout, thing, 'rotation')

        if isinstance(thing, Light):
            self.add_color_picker_widget(layout, thing, 'colour')

        # Track if we're dealing with a Pickup to handle key_name specially
        is_pickup = isinstance(thing, Pickup)
        current_item_type = thing.properties.get('item_type', 'health') if is_pickup else None
        
        for key, value in sorted(thing.properties.items()):
            if key == 'name': continue
            
            if isinstance(thing, Light) and key == 'colour': continue
            if isinstance(thing, Model) and key in ['model_path', 'scale', 'rotation', 'type']: continue
            
            # Skip key_name - we'll add it after item_type for proper ordering
            if is_pickup and key == 'key_name': continue

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
                widget.currentTextChanged.connect(self.on_pickup_item_type_changed)
                layout.addRow(label_text, widget)
                
                # Add key_name field right after item_type
                self.pickup_key_name_label = QLabel("Key Name:")
                self.pickup_key_name_input = QLineEdit(thing.properties.get('key_name', ''))
                self.pickup_key_name_input.setPlaceholderText("e.g. blue_key (must match door)")
                self.pickup_key_name_input.editingFinished.connect(
                    lambda: self.update_object_prop('key_name', self.pickup_key_name_input.text())
                )
                layout.addRow(self.pickup_key_name_label, self.pickup_key_name_input)
                
                # Show/hide based on current item_type
                is_key_type = (value == 'key')
                self.pickup_key_name_label.setVisible(is_key_type)
                self.pickup_key_name_input.setVisible(is_key_type)
                
            elif isinstance(thing, Pickup) and key == 'activation':
                widget = QComboBox()
                activation_types = ['walk_over', 'use']
                widget.addItems(activation_types)
                widget.setCurrentText(value)
                widget.currentTextChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget)
            elif isinstance(value, bool):
                widget = QCheckBox()
                widget.setStyleSheet("QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; } QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; } QCheckBox::indicator { width: 25px; height: 25px; }")
                widget.setChecked(value)
                widget.stateChanged.connect(lambda state, k=key: self.update_object_prop(k, state == Qt.Checked))
                layout.addRow(label_text, widget)
            elif isinstance(value, int):
                widget = QSpinBox(); widget.setRange(-99999, 99999); widget.setValue(value)
                widget.valueChanged.connect(lambda v, k=key: self.update_object_prop(k, v))
                layout.addRow(label_text, widget)
            elif isinstance(value, float):
                widget = QLineEdit(str(value))
                widget.editingFinished.connect(lambda le=widget, k=key: self.update_object_prop(k, float(le.text()) if le.text() and le.text().replace('.', '', 1).isdigit() else 0.0))
                layout.addRow(label_text, widget)
            else:
                widget = QLineEdit(str(value))
                widget.editingFinished.connect(lambda le=widget, k=key: self.update_object_prop(k, le.text()))
                layout.addRow(label_text, widget)
        self.main_layout.addLayout(layout)

    def on_pickup_item_type_changed(self, item_type):
        """Handle pickup item_type change to show/hide key_name field."""
        if self.current_object is None: return
        self.update_object_prop('item_type', item_type)
        
        # Show/hide key_name field based on item_type
        is_key = (item_type == 'key')
        if self.pickup_key_name_label:
            self.pickup_key_name_label.setVisible(is_key)
        if self.pickup_key_name_input:
            self.pickup_key_name_input.setVisible(is_key)

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
        if not isinstance(val, list) or len(val) != 3: val = [0, 0, 0]
        coords = ['x', 'y', 'z']
        edits = []
        for i in range(3):
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