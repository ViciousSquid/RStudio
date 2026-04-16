
import os
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QLabel, QLineEdit, QSpinBox,
                             QFormLayout, QCheckBox, QComboBox, QPushButton,
                             QHBoxLayout, QColorDialog, QFileDialog, QGridLayout,
                             QToolButton, QSlider, QTabWidget, QGroupBox, QScrollArea,
                             QFrame, QDoubleSpinBox, QSizePolicy)
from PyQt5.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QIcon, QFont
from editor.things import Thing, Light, Pickup, Monster, Model, Speaker, LogicGate

# I/O System imports
try:
    from editor.io_editor_widget import IOEditorWidget, IOInputsWidget
    from editor.io_system import get_entity_type_for_io, IO_REGISTRY
    IO_AVAILABLE = True
except ImportError:
    IO_AVAILABLE = False


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
        self._populating = False  # Flag to prevent recursion during population
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(2)
        self.setLayout(self.main_layout)
        
        # Tab widget for organized properties
        self.tab_widget = None
        
        # Store widget references for visibility updates
        self._widgets = {}
        
        self.set_object(None)
    
    def _find_targeting_sources(self, target_name):
        """Find all entities that target the given entity name (legacy + I/O)."""
        if not target_name: return []
        sources = []
        
        # Check legacy 'target' property on brushes
        for brush in self.editor.state.brushes:
            brush_target = brush.get('target', '')
            if brush_target == target_name:
                is_trigger = brush.get('is_trigger', False)
                is_mover = brush.get('is_mover', False)
                if is_trigger or is_mover:
                    source_name = brush.get('name', 'unnamed')
                    source_type = 'trigger' if is_trigger else 'mover'
                    sources.append((source_name, source_type))
            
            # Also check I/O connections (handles both OutputConnection objects and dicts)
            io_connections = brush.get('_io_connections', [])
            for conn in io_connections:
                conn_target = getattr(conn, 'target_name', None) or (conn.get('target') if isinstance(conn, dict) else None)
                conn_output = getattr(conn, 'output_name', None) or (conn.get('output', '?') if isinstance(conn, dict) else '?')
                if conn_target == target_name:
                    source_name = brush.get('name', 'unnamed')
                    sources.append((source_name, f"I/O: {conn_output}"))
        
        # Check I/O connections on Things
        for thing in self.editor.state.things:
            io_connections = thing.properties.get('_io_connections', [])
            for conn in io_connections:
                conn_target = getattr(conn, 'target_name', None) or (conn.get('target') if isinstance(conn, dict) else None)
                conn_output = getattr(conn, 'output_name', None) or (conn.get('output', '?') if isinstance(conn, dict) else '?')
                if conn_target == target_name:
                    source_name = thing.properties.get('name', 'unnamed')
                    sources.append((source_name, f"I/O: {conn_output}"))
        
        return sources
    
    def _check_target_exists(self, target_name):
        if not target_name: return False
        for brush in self.editor.state.brushes:
            if brush.get('name') == target_name: return True
        for thing in self.editor.state.things:
            thing_name = getattr(thing, 'name', '') or thing.properties.get('name', '')
            if thing_name == target_name: return True
        return False
    

    def clear_layout(self):
        while self.main_layout.count():
            child = self.main_layout.takeAt(0)
            if child.widget(): child.widget().deleteLater()
            elif child.layout():
                layout = child.layout()
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget(): item.widget().deleteLater()
        self._widgets = {}
        self.tab_widget = None

    def set_object(self, obj):
        # Preserve tab index and scroll position when refreshing the same object
        saved_tab_index = None
        saved_scroll_pos = 0
        
        if self.current_object is obj:
            # Save tab index
            if self.tab_widget is not None:
                saved_tab_index = self.tab_widget.currentIndex()
                
            # Save current scroll position before clearing
            for i in range(self.main_layout.count()):
                widget = self.main_layout.itemAt(i).widget()
                if isinstance(widget, QScrollArea):
                    saved_scroll_pos = widget.verticalScrollBar().value()
                    break
        
        self._populating = True  # Set flag to prevent recursion
        self.current_object = obj
        self.clear_layout()
        
        if obj is None:
            self.main_layout.addWidget(QLabel("Nothing selected."))
            self._populating = False
            return
            
        if isinstance(obj, dict): 
            self.populate_for_brush(obj)
        elif isinstance(obj, Thing): 
            self.populate_for_thing(obj)
        
        # Restore tab index
        if saved_tab_index is not None and self.tab_widget is not None:
            if saved_tab_index < self.tab_widget.count():
                self.tab_widget.setCurrentIndex(saved_tab_index)
                
        # Restore scroll position
        if saved_scroll_pos > 0:
            for i in range(self.main_layout.count()):
                widget = self.main_layout.itemAt(i).widget()
                if isinstance(widget, QScrollArea):
                    # A QTimer is required here because the layout needs a frame to 
                    # recalculate its new height before the scrollbar can be moved.
                    QTimer.singleShot(0, lambda w=widget, pos=saved_scroll_pos: w.verticalScrollBar().setValue(pos))
                    break
        
        self._populating = False  # Reset flag after population complete

    def _create_styled_header(self, text, color="#6C3BAA"):
        """Create a styled header label."""
        label = QLabel(text)
        label.setStyleSheet(f"""
            QLabel {{
                background-color: {color};
                color: white;
                font-weight: bold;
                padding: 8px 12px;
                border-radius: 4px;
                font-size: 12px;
            }}
        """)
        return label

    def _create_section_header(self, text):
        """Create a section header for grouping properties."""
        label = QLabel(text)
        label.setStyleSheet("""
            QLabel {
                color: #F08000;
                font-weight: bold;
                padding: 4px 0px;
                border-bottom: 1px solid #F08000;
                margin-top: 8px;
            }
        """)
        return label

    def _create_color_button(self, color_rgb, size=(100, 28)):
        """Create a color picker button with current color display."""
        btn = QPushButton()
        btn.setFixedSize(*size)
        self._update_color_button(btn, color_rgb)
        return btn

    def _update_color_button(self, btn, color_rgb):
        """Update a color button's background."""
        if isinstance(color_rgb, (list, tuple)) and len(color_rgb) >= 3:
            if any(c > 1.0 for c in color_rgb):
                r, g, b = int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2])
            else:
                r, g, b = int(color_rgb[0] * 255), int(color_rgb[1] * 255), int(color_rgb[2] * 255)
            btn.setStyleSheet(f"background-color: rgb({r}, {g}, {b}); border: 2px solid #555; border-radius: 4px;")

    def _checkbox_style(self):
        return """
            QCheckBox::indicator:checked { background-color: #F08000; border: 1px solid #333; }
            QCheckBox::indicator:unchecked { background-color: #425f5d; border: 1px solid #333; }
            QCheckBox::indicator { width: 22px; height: 22px; }
        """

    def populate_for_brush(self, brush):
        """Populate property editor for a brush with tabbed interface."""
        
        # Create scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                width: 18px;
                background: #2b2b2b;
                border: none;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #4b4d4d;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)
        
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)
        
        # === BASIC PROPERTIES (Always visible) ===
        basic_layout = QFormLayout()
        basic_layout.setSpacing(4)
        
        # Name field with styled header
        name_label = QLabel("Name:")
        name_label.setStyleSheet("QLabel { background-color: #6C3BAA; color: white; font-weight: bold; padding: 6px 8px; border-radius: 3px; }")
        name_input = QLineEdit(brush.get('name', ''))
        name_input.setStyleSheet("QLineEdit { background-color: #6C3BAA; color: white; font-weight: bold; padding: 6px; border: 2px solid #8B5AC2; border-radius: 3px; } QLineEdit:focus { border: 2px solid #A875D6; background-color: #7B4AB9; }")
        name_input.setPlaceholderText("Enter name...")
        name_input.editingFinished.connect(lambda: self.update_object_prop('name', name_input.text()))
        basic_layout.addRow(name_label, name_input)
        self._widgets['name_input'] = name_input
        
        # Targeted by indicator
        brush_name = brush.get('name', '')
        if brush_name:
            targeting_sources = self._find_targeting_sources(brush_name)
            if targeting_sources:
                source_texts = [f"{name} ({stype})" for name, stype in targeting_sources]
                targeted_label = QLabel(", ".join(source_texts))
                targeted_label.setStyleSheet("QLabel { color: #00FF00; font-weight: bold; padding: 2px; background-color: #1a3d1a; border: 1px solid #00AA00; border-radius: 3px; }")
                targeted_label.setWordWrap(True)
                basic_layout.addRow("Targeted by:", targeted_label)
        
        content_layout.addLayout(basic_layout)
        
        # === TAB WIDGET FOR ADVANCED PROPERTIES ===
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabBar::tab:selected { background: #F08000; color: white; }
            QTabBar::tab { background: #425f5d; color: #ccc; padding: 8px 16px; border: 1px solid #333; }
            QTabBar::tab:hover { background: #5a7a82; }
        """)
        
        # Determine which tabs to show
        is_trigger = brush.get('is_trigger', False)
        is_mover = brush.get('is_mover', False)
        is_door = brush.get('is_door', False)
        shader_type = brush.get('shader', '<None>')
        
        # === GENERAL TAB (Type selection) ===
        general_tab = self._create_general_tab(brush)
        self.tab_widget.addTab(general_tab, "General")
        
        # === TRIGGER TAB (conditional) ===
        self.trigger_tab = self._create_trigger_tab(brush)
        self.trigger_tab_index = self.tab_widget.addTab(self.trigger_tab, "🎯 Trigger")
        self.tab_widget.setTabVisible(self.trigger_tab_index, is_trigger)
        
        # === MOVER TAB (conditional) ===
        self.mover_tab = self._create_mover_tab(brush)
        self.mover_tab_index = self.tab_widget.addTab(self.mover_tab, "⚡ Mover")
        self.tab_widget.setTabVisible(self.mover_tab_index, is_mover)
        
        # === DOOR TAB (conditional) ===
        self.door_tab = self._create_door_tab(brush)
        self.door_tab_index = self.tab_widget.addTab(self.door_tab, "🚪 Door")
        self.tab_widget.setTabVisible(self.door_tab_index, is_door)
        
        # === SHADER TAB (conditional) ===
        self.shader_tab = self._create_shader_tab(brush)
        self.shader_tab_index = self.tab_widget.addTab(self.shader_tab, "✨ Shader")
        self.tab_widget.setTabVisible(self.shader_tab_index, shader_type not in ['<None>', 'Glow', None, ''])
        
        # === APPEARANCE TAB ===
        appearance_tab = self._create_appearance_tab(brush)
        self.tab_widget.addTab(appearance_tab, "Appearance")
        
        # === I/O TAB (for triggers, movers, doors) ===
        if IO_AVAILABLE and (is_trigger or is_mover or is_door):
            io_tab = self._create_io_tab_for_brush(brush)
            self.io_tab_index = self.tab_widget.addTab(io_tab, "⚡ I/O")
        
        content_layout.addWidget(self.tab_widget)
        content_layout.addStretch()
        
        scroll.setWidget(content_widget)
        self.main_layout.addWidget(scroll)

    def _create_io_tab_for_brush(self, brush):
        """Create I/O editor tab for brushes (triggers, movers, doors)."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        
        # Determine entity type for I/O registry lookup
        if brush.get('is_trigger'):
            entity_type = 'trigger'
        elif brush.get('is_door'):
            entity_type = 'door'
        elif brush.get('is_mover'):
            entity_type = 'mover'
        else:
            entity_type = 'brush'
        
        # Create I/O editor widget with the ACTUAL brush entity
        io_editor = IOEditorWidget(
            entity=brush,  # FIX: Pass the actual brush dict, not the Thing class
            entity_type=entity_type,
            editor_state=self.editor.state,
            editor=self.editor
        )
        io_editor.connections_changed.connect(self._on_io_connections_changed)
        layout.addWidget(io_editor)
        self._widgets['io_editor'] = io_editor
        
        # Add inputs reference section
        inputs_widget = IOInputsWidget()
        inputs_widget.set_entity(entity_type)
        layout.addWidget(inputs_widget)
        
        return tab

    def _create_io_tab_for_thing(self, thing):
        """Create I/O editor tab for Things."""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(4, 4, 4, 4)
        
        entity_type = get_entity_type_for_io(thing)
        
        io_editor = IOEditorWidget(
            entity=thing,
            entity_type=entity_type,
            editor_state=self.editor.state,
            editor=self.editor
        )
        io_editor.connections_changed.connect(self._on_io_connections_changed)
        layout.addWidget(io_editor)
        self._widgets['io_editor'] = io_editor
        
        # Add inputs reference section
        inputs_widget = IOInputsWidget()
        inputs_widget.set_entity(entity_type)
        layout.addWidget(inputs_widget)
        
        return tab

    def _on_io_connections_changed(self):
        """Called when I/O connections are modified."""
        # Save state for undo/redo
        if hasattr(self.editor.state, 'save_state'):
            self.editor.state.save_state()
        
        # Mark document as dirty
        if hasattr(self.editor, 'mark_dirty'):
            self.editor.mark_dirty()
        
        # Refresh targeting indicators
        if not self._populating:
            self.editor.update_all_ui()

    def _create_general_tab(self, brush):
        """Create the General tab with type toggles."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Type Selection Group
        type_group = QGroupBox("Brush Type")
        type_group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #F08000; 
                border: 1px solid #F08000;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        type_layout = QVBoxLayout(type_group)
        
        # Shader dropdown and Lock checkbox on same row
        shader_lock_layout = QHBoxLayout()
        shader_label = QLabel("Shader:")
        shader_combo = QComboBox()
        shader_combo.addItems(['<None>', 'Glass', 'Glow', 'Water', 'Fog'])
        shader_combo.setCurrentText(brush.get('shader', '<None>'))
        shader_combo.currentTextChanged.connect(self.on_shader_changed)
        shader_lock_layout.addWidget(shader_label)
        shader_lock_layout.addWidget(shader_combo)
        shader_lock_layout.addStretch()
        
        # Lock checkbox on the right
        lock_label = QLabel("Lock:")
        lock_cb = QCheckBox("Prevent selection/editing")
        lock_cb.setStyleSheet(self._checkbox_style())
        lock_cb.setChecked(brush.get('lock', False))
        lock_cb.toggled.connect(lambda checked: self.update_object_prop('lock', checked))
        shader_lock_layout.addWidget(lock_label)
        shader_lock_layout.addWidget(lock_cb)
        
        type_layout.addLayout(shader_lock_layout)
        self._widgets['shader_combo'] = shader_combo
        self._widgets['lock_cb'] = lock_cb
        
        type_layout.addWidget(self._create_section_header("Behaviors"))
        
        # Trigger checkbox
        trigger_cb = QCheckBox("Is Trigger (activates other objects)")
        trigger_cb.setStyleSheet(self._checkbox_style())
        trigger_cb.setChecked(brush.get('is_trigger', False))
        trigger_cb.toggled.connect(self.on_trigger_changed)
        type_layout.addWidget(trigger_cb)
        self._widgets['trigger_cb'] = trigger_cb
        
        # Mover checkbox
        mover_cb = QCheckBox("Is Mover (moves back and forth)")
        mover_cb.setStyleSheet(self._checkbox_style())
        mover_cb.setChecked(brush.get('is_mover', False))
        mover_cb.toggled.connect(self.on_mover_changed)
        type_layout.addWidget(mover_cb)
        self._widgets['mover_cb'] = mover_cb
        
        # Door checkbox
        door_cb = QCheckBox("Is Door (opens when triggered)")
        door_cb.setStyleSheet(self._checkbox_style())
        door_cb.setChecked(brush.get('is_door', False))
        door_cb.toggled.connect(self.on_door_changed)
        type_layout.addWidget(door_cb)
        self._widgets['door_cb'] = door_cb
        
        layout.addWidget(type_group)
        layout.addStretch()
        return widget

    def _create_trigger_tab(self, brush):
        """Create the Trigger properties tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        
        form = QFormLayout()
        form.setSpacing(8)
        
        # Trigger type
        type_combo = QComboBox()
        type_combo.addItems(['Once', 'Multiple'])
        type_combo.setCurrentText(brush.get('trigger_type', 'Once'))
        type_combo.currentTextChanged.connect(lambda t: self.update_object_prop('trigger_type', t))
        form.addRow("Trigger Type:", type_combo)
        self._widgets['trigger_type_combo'] = type_combo
        
        # Damage section
        damage_group = QGroupBox("Damage")
        damage_group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #F08000; 
                border: 1px solid #F08000;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        damage_layout = QVBoxLayout(damage_group)
        
        hurt_cb = QCheckBox("Hurts player on contact")
        hurt_cb.setStyleSheet(self._checkbox_style())
        hurt_cb.setChecked(brush.get('hurt', False))
        hurt_cb.toggled.connect(self.on_hurt_changed)
        damage_layout.addWidget(hurt_cb)
        self._widgets['hurt_cb'] = hurt_cb
        
        damage_amount_layout = QHBoxLayout()
        damage_amount_layout.addWidget(QLabel("Damage Amount:"))
        damage_spin = QSpinBox()
        damage_spin.setRange(1, 1000)
        damage_spin.setValue(brush.get('hurt_amount', 10))
        damage_spin.editingFinished.connect(lambda w=damage_spin: self.update_object_prop('hurt_amount', w.value()))
        damage_amount_layout.addWidget(damage_spin)
        damage_amount_layout.addStretch()
        damage_layout.addLayout(damage_amount_layout)
        self._widgets['damage_spin'] = damage_spin
        
        # Show/hide damage amount based on hurt checkbox
        damage_spin.setEnabled(brush.get('hurt', False))
        
        layout.addLayout(form)
        layout.addWidget(damage_group)
        layout.addStretch()
        return widget

    def _create_mover_tab(self, brush):
        """Create the Mover properties tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        
        form = QFormLayout()
        form.setSpacing(8)
        
        # Speed
        speed_input = QLineEdit(str(brush.get('speed', 64.0)))
        speed_input.editingFinished.connect(lambda: self.update_object_prop('speed', float(speed_input.text()) if speed_input.text() else 64.0))
        form.addRow("Speed:", speed_input)
        self._widgets['speed_input'] = speed_input
        
        # Distance
        distance_input = QLineEdit(str(brush.get('distance', 128.0)))
        distance_input.editingFinished.connect(lambda: self.update_object_prop('distance', float(distance_input.text()) if distance_input.text() else 128.0))
        form.addRow("Distance:", distance_input)
        self._widgets['distance_input'] = distance_input
        
        # Direction
        dir_widget = QWidget()
        dir_layout = QHBoxLayout(dir_widget)
        dir_layout.setContentsMargins(0, 0, 0, 0)
        dir_layout.setSpacing(4)
        
        direction = brush.get('direction', [0, 1, 0])
        dir_x = QLineEdit(str(direction[0]))
        dir_y = QLineEdit(str(direction[1]))
        dir_z = QLineEdit(str(direction[2]))
        for inp in [dir_x, dir_y, dir_z]:
            inp.setFixedWidth(50)
        
        def update_direction():
            try:
                d = [float(dir_x.text()), float(dir_y.text()), float(dir_z.text())]
                self.update_object_prop('direction', d)
            except ValueError: pass
        
        dir_x.editingFinished.connect(update_direction)
        dir_y.editingFinished.connect(update_direction)
        dir_z.editingFinished.connect(update_direction)
        
        dir_layout.addWidget(QLabel("X:")); dir_layout.addWidget(dir_x)
        dir_layout.addWidget(QLabel("Y:")); dir_layout.addWidget(dir_y)
        dir_layout.addWidget(QLabel("Z:")); dir_layout.addWidget(dir_z)
        dir_layout.addStretch()
        form.addRow("Direction:", dir_widget)
        self._widgets['dir_x'] = dir_x
        self._widgets['dir_y'] = dir_y
        self._widgets['dir_z'] = dir_z
        
        layout.addLayout(form)
        
        # Options
        options_group = QGroupBox("Options")
        options_group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #F08000; 
                border: 1px solid #F08000;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        options_layout = QVBoxLayout(options_group)
        
        start_on_cb = QCheckBox("Start moving immediately")
        start_on_cb.setStyleSheet(self._checkbox_style())
        start_on_cb.setChecked(brush.get('start_on', False))
        start_on_cb.toggled.connect(lambda checked: self.update_object_prop('start_on', checked))
        options_layout.addWidget(start_on_cb)
        self._widgets['start_on_cb'] = start_on_cb
        
        layout.addWidget(options_group)
        
        # Preview button
        preview_btn = QPushButton("▶ Preview Movement")
        preview_btn.setCheckable(True)
        preview_btn.setStyleSheet("""
            QPushButton { background-color: #425F5D; color: white; border-radius: 4px; padding: 8px; font-weight: bold; }
            QPushButton:checked { background-color: #0056b3; }
            QPushButton:hover { background-color: #5a7a82; }
        """)
        preview_btn.toggled.connect(self.toggle_mover_preview)
        layout.addWidget(preview_btn)
        self._widgets['mover_preview_btn'] = preview_btn
        
        layout.addStretch()
        return widget
        
        def update_direction():
            try:
                d = [float(dir_x.text()), float(dir_y.text()), float(dir_z.text())]
                self.update_object_prop('direction', d)
            except ValueError: pass
        
        dir_x.editingFinished.connect(update_direction)
        dir_y.editingFinished.connect(update_direction)
        dir_z.editingFinished.connect(update_direction)
        
        dir_layout.addWidget(QLabel("X:")); dir_layout.addWidget(dir_x)
        dir_layout.addWidget(QLabel("Y:")); dir_layout.addWidget(dir_y)
        dir_layout.addWidget(QLabel("Z:")); dir_layout.addWidget(dir_z)
        dir_layout.addStretch()
        form.addRow("Direction:", dir_widget)
        self._widgets['dir_x'] = dir_x
        self._widgets['dir_y'] = dir_y
        self._widgets['dir_z'] = dir_z
        
        layout.addLayout(form)
        
        # Options
        options_group = QGroupBox("Options")
        options_group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #F08000; 
                border: 1px solid #F08000;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        options_layout = QVBoxLayout(options_group)
        
        start_on_cb = QCheckBox("Start moving immediately")
        start_on_cb.setStyleSheet(self._checkbox_style())
        start_on_cb.setChecked(brush.get('start_on', False))
        start_on_cb.toggled.connect(lambda checked: self.update_object_prop('start_on', checked))
        options_layout.addWidget(start_on_cb)
        self._widgets['start_on_cb'] = start_on_cb
        
        layout.addWidget(options_group)
        
        # Preview button
        preview_btn = QPushButton("▶ Preview Movement")
        preview_btn.setCheckable(True)
        preview_btn.setStyleSheet("""
            QPushButton { background-color: #425F5D; color: white; border-radius: 4px; padding: 8px; font-weight: bold; }
            QPushButton:checked { background-color: #0056b3; }
            QPushButton:hover { background-color: #5a7a82; }
        """)
        preview_btn.toggled.connect(self.toggle_mover_preview)
        layout.addWidget(preview_btn)
        self._widgets['mover_preview_btn'] = preview_btn
        
        layout.addStretch()
        return widget

    def _create_door_tab(self, brush):
        """Create the Door properties tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        
        form = QFormLayout()
        form.setSpacing(8)
        
        # Open direction
        dir_combo = QComboBox()
        dir_combo.addItems(['up', 'down', 'north', 'south', 'east', 'west'])
        dir_combo.setCurrentText(brush.get('door_direction', 'up'))
        dir_combo.currentTextChanged.connect(lambda t: self.update_object_prop('door_direction', t))
        form.addRow("Open Direction:", dir_combo)
        self._widgets['door_dir_combo'] = dir_combo
        
        # Open distance
        dist_input = QLineEdit(str(brush.get('door_distance', 128.0)))
        dist_input.editingFinished.connect(lambda: self.update_object_prop('door_distance', float(dist_input.text()) if dist_input.text() else 128.0))
        form.addRow("Open Distance:", dist_input)
        self._widgets['door_dist_input'] = dist_input
        
        # Lip
        lip_input = QLineEdit(str(brush.get('door_lip', 8.0)))
        lip_input.editingFinished.connect(lambda: self.update_object_prop('door_lip', float(lip_input.text()) if lip_input.text() else 8.0))
        form.addRow("Lip (stay closed):", lip_input)
        self._widgets['door_lip_input'] = lip_input
        
        # Speed
        speed_input = QLineEdit(str(brush.get('door_speed', 64.0)))
        speed_input.editingFinished.connect(lambda: self.update_object_prop('door_speed', float(speed_input.text()) if speed_input.text() else 64.0))
        form.addRow("Speed:", speed_input)
        self._widgets['door_speed_input'] = speed_input
        
        layout.addLayout(form)
        
        # Options
        options_group = QGroupBox("Door Options")
        options_group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #F08000; 
                border: 1px solid #F08000;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        options_layout = QVBoxLayout(options_group)
        
        auto_open_cb = QCheckBox("Auto-open when player is near")
        auto_open_cb.setStyleSheet(self._checkbox_style())
        auto_open_cb.setChecked(brush.get('door_auto_open', False))
        auto_open_cb.toggled.connect(lambda checked: self.update_object_prop('door_auto_open', checked))
        options_layout.addWidget(auto_open_cb)
        self._widgets['door_auto_open_cb'] = auto_open_cb
        
        locked_cb = QCheckBox("Locked (requires trigger to open)")
        locked_cb.setStyleSheet(self._checkbox_style())
        locked_cb.setChecked(brush.get('door_locked', False))
        locked_cb.toggled.connect(lambda checked: self.update_object_prop('door_locked', checked))
        options_layout.addWidget(locked_cb)
        self._widgets['door_locked_cb'] = locked_cb
        
        needs_key_cb = QCheckBox("Requires key to open")
        needs_key_cb.setStyleSheet(self._checkbox_style())
        needs_key_cb.setChecked(brush.get('door_needs_key', False))
        needs_key_cb.toggled.connect(self.on_door_needs_key_changed)
        options_layout.addWidget(needs_key_cb)
        self._widgets['door_needs_key_cb'] = needs_key_cb
        
        # Create the dropdown for Key Name
        door_key_label = QLabel("Key Name:")
        door_key_combo = QComboBox()
        door_key_combo.setEditable(False)

        key_options = ['red_key', 'blue_key', 'yellow_key', 'custom']
        door_key_combo.addItems(key_options)

        # Set current value from the door's key property
        current_key = brush.get('door_key_name', 'red_key')
        if current_key in key_options:
            door_key_combo.setCurrentText(current_key)

        # Connect to update door_key_name
        door_key_combo.currentTextChanged.connect(
            lambda name: self.update_object_prop('door_key_name', name))
            
        # Initialize visibility based on the checkbox
        needs_key_init = brush.get('door_needs_key', False)
        door_key_label.setVisible(needs_key_init)
        door_key_combo.setVisible(needs_key_init)

        # Add as a horizontal row inside the options group
        key_row = QHBoxLayout()
        key_row.addWidget(door_key_label)
        key_row.addWidget(door_key_combo)
        options_layout.addLayout(key_row)
        
        # Store in _widgets so on_door_needs_key_changed can toggle it
        self._widgets['door_key_input'] = door_key_combo
        self._widgets['door_key_label'] = door_key_label

        # --- Linked Key Pickup cross-reference ---
        link_label = QLabel("")
        link_label.setWordWrap(True)
        link_label.setStyleSheet("QLabel { padding: 4px; }")
        options_layout.addWidget(link_label)
        self._widgets['door_key_link_label'] = link_label

        select_key_btn = QPushButton("Select Key Pickup ▸")
        select_key_btn.setStyleSheet("""
            QPushButton { background-color: #2a5a2a; color: #88FF88; border: 1px solid #44AA44;
                          border-radius: 3px; padding: 4px 8px; font-size: 11px; }
            QPushButton:hover { background-color: #3a6a3a; }
        """)
        select_key_btn.setVisible(False)
        select_key_btn.clicked.connect(self._select_linked_key_pickup)
        options_layout.addWidget(select_key_btn)
        self._widgets['door_key_select_btn'] = select_key_btn

        # Populate the linked key info
        self._update_door_key_link(brush)

        # Also refresh link when key name dropdown changes
        door_key_combo.currentTextChanged.connect(
            lambda _name: self._update_door_key_link(self.current_object))

        layout.addWidget(options_group)

        # Preview button
        preview_btn = QPushButton("▶ Preview Door")
        preview_btn.setCheckable(True)
        preview_btn.setStyleSheet("""
            QPushButton { background-color: #425F5D; color: white; border-radius: 4px; padding: 8px; font-weight: bold; }
            QPushButton:checked { background-color: #0056b3; }
            QPushButton:hover { background-color: #5a7a82; }
        """)
        preview_btn.toggled.connect(self.toggle_door_preview)
        layout.addWidget(preview_btn)
        self._widgets['door_preview_btn'] = preview_btn
        
        layout.addStretch()
        return widget

    def _create_shader_tab(self, brush):
        """Create the Shader properties tab with dynamic content based on shader type."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        
        shader_type = brush.get('shader', '<None>')
        
        if shader_type == 'Glass':
            layout.addWidget(self._create_glass_properties(brush))
        elif shader_type == 'Glow':
            layout.addWidget(self._create_glow_properties(brush))
        elif shader_type == 'Water':
            layout.addWidget(self._create_water_properties(brush))
        elif shader_type == 'Fog':
            layout.addWidget(self._create_fog_properties(brush))
        else:
            layout.addWidget(QLabel("No shader-specific properties."))
        
        layout.addStretch()
        return widget

    def _create_glass_properties(self, brush):
        """Create Glass shader properties for realistic glass rendering."""
        group = QGroupBox("Glass Properties")
        group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #00BFFF; 
                border: 1px solid #00BFFF;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        
        form = QFormLayout()
        form.setSpacing(6)
        
        # Glass color/tint
        color_btn = self._create_color_button(brush.get('glass_color', [0.9, 0.95, 1.0]))
        color_btn.clicked.connect(lambda: self._pick_color('glass_color', color_btn, [0.9, 0.95, 1.0]))
        form.addRow("Tint Color:", color_btn)
        self._widgets['glass_color_btn'] = color_btn
        
        # Opacity slider (0 = fully transparent, 1 = opaque)
        opacity_layout = QHBoxLayout()
        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setRange(0, 100)
        opacity_slider.setValue(int(brush.get('glass_opacity', 0.3) * 100))
        opacity_label = QLabel(f"{brush.get('glass_opacity', 0.3):.2f}")
        opacity_slider.valueChanged.connect(lambda v: (
            self.update_object_prop('glass_opacity', v / 100.0),
            opacity_label.setText(f"{v / 100.0:.2f}")
        ))
        opacity_layout.addWidget(opacity_slider)
        opacity_layout.addWidget(opacity_label)
        form.addRow("Opacity:", opacity_layout)
        self._widgets['glass_opacity_slider'] = opacity_slider
        
        layout.addLayout(form)
        
        # Distortion section
        distort_group = QGroupBox("Distortion Effects")
        distort_group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #87CEEB; 
                border: 1px solid #4a6a8a;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        distort_layout = QFormLayout(distort_group)
        distort_layout.setSpacing(6)
        
        # Distortion strength (warping effect)
        warp_layout = QHBoxLayout()
        warp_slider = QSlider(Qt.Horizontal)
        warp_slider.setRange(0, 100)
        warp_slider.setValue(int(brush.get('glass_distortion', 0.5) * 100))
        warp_label = QLabel(f"{brush.get('glass_distortion', 0.5):.2f}")
        warp_slider.setToolTip("How much the view through glass is warped/distorted")
        warp_slider.valueChanged.connect(lambda v: (
            self.update_object_prop('glass_distortion', v / 100.0),
            warp_label.setText(f"{v / 100.0:.2f}")
        ))
        warp_layout.addWidget(warp_slider)
        warp_layout.addWidget(warp_label)
        distort_layout.addRow("Warp Strength:", warp_layout)
        self._widgets['glass_distort_slider'] = warp_slider
        
        # Refraction index (how much light bends)
        refract_layout = QHBoxLayout()
        refract_slider = QSlider(Qt.Horizontal)
        refract_slider.setRange(100, 250)  # 1.0 to 2.5 (1.5 is typical glass)
        refract_slider.setValue(int(brush.get('glass_refraction', 1.5) * 100))
        refract_label = QLabel(f"{brush.get('glass_refraction', 1.5):.2f}")
        refract_slider.setToolTip("Index of refraction (1.0=air, 1.5=glass, 2.4=diamond)")
        refract_slider.valueChanged.connect(lambda v: (
            self.update_object_prop('glass_refraction', v / 100.0),
            refract_label.setText(f"{v / 100.0:.2f}")
        ))
        refract_layout.addWidget(refract_slider)
        refract_layout.addWidget(refract_label)
        distort_layout.addRow("Refraction:", refract_layout)
        self._widgets['glass_refraction_slider'] = refract_slider
        
        # Roughness (frosted glass effect)
        rough_layout = QHBoxLayout()
        rough_slider = QSlider(Qt.Horizontal)
        rough_slider.setRange(0, 100)
        rough_slider.setValue(int(brush.get('glass_roughness', 0.0) * 100))
        rough_label = QLabel(f"{brush.get('glass_roughness', 0.0):.2f}")
        rough_slider.setToolTip("Surface roughness (0=clear, 1=frosted)")
        rough_slider.valueChanged.connect(lambda v: (
            self.update_object_prop('glass_roughness', v / 100.0),
            rough_label.setText(f"{v / 100.0:.2f}")
        ))
        rough_layout.addWidget(rough_slider)
        rough_layout.addWidget(rough_label)
        distort_layout.addRow("Roughness:", rough_layout)
        self._widgets['glass_roughness_slider'] = rough_slider
        
        layout.addWidget(distort_group)
        
        # Fresnel section (edge reflection)
        fresnel_group = QGroupBox("Fresnel Effect")
        fresnel_group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #98FB98; 
                border: 1px solid #4a8a6a;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 4px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        fresnel_layout = QFormLayout(fresnel_group)
        fresnel_layout.setSpacing(6)
        
        # Fresnel strength
        fres_layout = QHBoxLayout()
        fres_slider = QSlider(Qt.Horizontal)
        fres_slider.setRange(0, 100)
        fres_slider.setValue(int(brush.get('glass_fresnel', 0.5) * 100))
        fres_label = QLabel(f"{brush.get('glass_fresnel', 0.5):.2f}")
        fres_slider.setToolTip("Edge reflection intensity (more reflective at grazing angles)")
        fres_slider.valueChanged.connect(lambda v: (
            self.update_object_prop('glass_fresnel', v / 100.0),
            fres_label.setText(f"{v / 100.0:.2f}")
        ))
        fres_layout.addWidget(fres_slider)
        fres_layout.addWidget(fres_label)
        fresnel_layout.addRow("Intensity:", fres_layout)
        self._widgets['glass_fresnel_slider'] = fres_slider
        
        layout.addWidget(fresnel_group)
        
        return group

    def _create_glow_properties(self, brush):
        """Create Glow shader properties."""
        group = QGroupBox("Glow Properties")
        group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #FFD700; 
                border: 1px solid #FFD700;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        
        form = QFormLayout()
        
        # Glow color
        color_btn = self._create_color_button(brush.get('glow_color', [1.0, 0.9, 0.7]))
        color_btn.clicked.connect(lambda: self._pick_color('glow_color', color_btn, [1.0, 0.9, 0.7]))
        form.addRow("Glow Color:", color_btn)
        self._widgets['glow_color_btn'] = color_btn
        
        # Intensity slider
        intensity_layout = QHBoxLayout()
        intensity_slider = QSlider(Qt.Horizontal)
        intensity_slider.setRange(300, 1000)
        intensity_slider.setValue(int(brush.get('glow_intensity', 3.0) * 100))
        intensity_label = QLabel(f"{brush.get('glow_intensity', 3.0):.2f}")
        intensity_slider.valueChanged.connect(lambda v: (
            self.update_object_prop('glow_intensity', v / 100.0),
            intensity_label.setText(f"{v / 100.0:.2f}")
        ))
        intensity_layout.addWidget(intensity_slider)
        intensity_layout.addWidget(intensity_label)
        form.addRow("Intensity:", intensity_layout)
        self._widgets['glow_intensity_slider'] = intensity_slider
        
        layout.addLayout(form)
        
        return group

    def _create_water_properties(self, brush):
        """Create Water shader properties."""
        group = QGroupBox("Water Properties")
        group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #00CED1; 
                border: 1px solid #00CED1;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        layout = QFormLayout(group)
        layout.setSpacing(8)
        
        # Water tint color
        color_btn = self._create_color_button(brush.get('water_tint', [0.0, 0.4, 0.6]))
        color_btn.clicked.connect(lambda: self._pick_color('water_tint', color_btn, [0.0, 0.4, 0.6]))
        layout.addRow("Water Tint:", color_btn)
        self._widgets['water_color_btn'] = color_btn
        
        # Opacity slider
        opacity_layout = QHBoxLayout()
        opacity_slider = QSlider(Qt.Horizontal)
        opacity_slider.setRange(0, 100)
        opacity_slider.setValue(int(brush.get('water_opacity', 0.5) * 100))
        opacity_label = QLabel(f"{brush.get('water_opacity', 0.5):.2f}")
        opacity_slider.valueChanged.connect(lambda v: (
            self.update_object_prop('water_opacity', v / 100.0),
            opacity_label.setText(f"{v / 100.0:.2f}")
        ))
        opacity_layout.addWidget(opacity_slider)
        opacity_layout.addWidget(opacity_label)
        layout.addRow("Opacity:", opacity_layout)
        self._widgets['water_opacity_slider'] = opacity_slider
        
        # Reflectivity slider
        reflect_layout = QHBoxLayout()
        reflect_slider = QSlider(Qt.Horizontal)
        reflect_slider.setRange(0, 100)
        reflect_slider.setValue(int(brush.get('water_reflectivity', 0.5) * 100))
        reflect_label = QLabel(f"{brush.get('water_reflectivity', 0.5):.2f}")
        reflect_slider.valueChanged.connect(lambda v: (
            self.update_object_prop('water_reflectivity', v / 100.0),
            reflect_label.setText(f"{v / 100.0:.2f}")
        ))
        reflect_layout.addWidget(reflect_slider)
        reflect_layout.addWidget(reflect_label)
        layout.addRow("Reflectivity:", reflect_layout)
        self._widgets['water_reflect_slider'] = reflect_slider

        # Wave Displacement Checkbox
        wave_cb = QCheckBox("Enable Vertex Waves")
        wave_cb.setStyleSheet(self._checkbox_style())
        wave_cb.setChecked(brush.get('water_wave_enabled', False))
        wave_cb.toggled.connect(lambda checked: self.update_object_prop('water_wave_enabled', checked))
        layout.addRow("", wave_cb)
        self._widgets['water_wave_cb'] = wave_cb

        # Wave Height Slider
        wave_h_layout = QHBoxLayout()
        wave_h_slider = QSlider(Qt.Horizontal)
        wave_h_slider.setRange(0, 200) # 0.0 to 2.0
        wave_h_slider.setValue(int(brush.get('water_wave_height', 0.5) * 100))
        wave_h_label = QLabel(f"{brush.get('water_wave_height', 0.5):.2f}")
        wave_h_slider.setToolTip("Amplitude of the waves. Keep low for realism.")
        wave_h_slider.valueChanged.connect(lambda v: (
            self.update_object_prop('water_wave_height', v / 100.0),
            wave_h_label.setText(f"{v / 100.0:.2f}")
        ))
        wave_h_layout.addWidget(wave_h_slider)
        wave_h_layout.addWidget(wave_h_label)
        layout.addRow("Wave Height:", wave_h_layout)
        self._widgets['water_wave_h_slider'] = wave_h_slider
        
        # Plane only checkbox
        plane_cb = QCheckBox("Draw top surface only")
        plane_cb.setStyleSheet(self._checkbox_style())
        plane_cb.setChecked(brush.get('water_plane', False))
        plane_cb.toggled.connect(lambda checked: self.update_object_prop('water_plane', checked))
        layout.addRow("", plane_cb)
        self._widgets['water_plane_cb'] = plane_cb
        
        return group

    def _create_fog_properties(self, brush):
        """Create Fog shader properties."""
        group = QGroupBox("Fog Properties")
        group.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; 
                color: #B0C4DE; 
                border: 1px solid #B0C4DE;
                border-radius: 4px;
                margin-top: 12px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px;
                background-color: #2b3d3b;
            }
        """)
        layout = QFormLayout(group)
        layout.setSpacing(8)
        
        # Fog color
        color_btn = self._create_color_button(brush.get('fog_color', [0.5, 0.6, 0.7]))
        color_btn.clicked.connect(lambda: self._pick_color('fog_color', color_btn, [0.5, 0.6, 0.7]))
        layout.addRow("Fog Color:", color_btn)
        self._widgets['fog_color_btn'] = color_btn
        
        # Density
        density_input = QLineEdit(str(brush.get('fog_density', 2.0)))
        density_input.editingFinished.connect(lambda: self.update_object_prop('fog_density', float(density_input.text()) if density_input.text() else 2.0))
        layout.addRow("Density:", density_input)
        self._widgets['fog_density_input'] = density_input
        
        return group

    def _create_appearance_tab(self, brush):
        """Create the Appearance tab with color controls."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        
        form = QFormLayout()
        form.setSpacing(8)
        
        # Brush colour
        colour_widget = QWidget()
        colour_layout = QHBoxLayout(colour_widget)
        colour_layout.setContentsMargins(0, 0, 0, 0)
        colour_layout.setSpacing(8)
        
        current_colour = brush.get('colour', [0.8, 0.8, 0.8])
        colour_btn = self._create_color_button(current_colour, (140, 32))
        colour_btn.clicked.connect(lambda: self._pick_color('colour', colour_btn, [0.8, 0.8, 0.8]))
        
        reset_btn = QPushButton("Reset")
        reset_btn.setFixedSize(60, 32)
        reset_btn.setToolTip("Reset to default grey")
        reset_btn.clicked.connect(lambda: self._reset_brush_colour(colour_btn))
        
        colour_layout.addWidget(colour_btn)
        colour_layout.addWidget(reset_btn)
        colour_layout.addStretch()
        
        form.addRow("Brush Colour:", colour_widget)
        self._widgets['brush_colour_btn'] = colour_btn
        
        layout.addLayout(form)
        layout.addStretch()
        return widget

    def _pick_color(self, prop_name, button, default_color):
        """Open color picker and update property."""
        if self.current_object is None: return
        
        current = self.current_object.get(prop_name, default_color)
        if any(c > 1.0 for c in current):
            current_qcolor = QColor(int(current[0]), int(current[1]), int(current[2]))
        else:
            current_qcolor = QColor(int(current[0] * 255), int(current[1] * 255), int(current[2] * 255))
        
        color = QColorDialog.getColor(current_qcolor, self, f"Choose {prop_name.replace('_', ' ').title()}")
        if color.isValid():
            new_color = [color.redF(), color.greenF(), color.blueF()]
            self.current_object[prop_name] = new_color
            self._update_color_button(button, new_color)
            self.editor.update_all_ui()

    def _reset_brush_colour(self, button):
        """Reset brush colour to default."""
        if self.current_object is None: return
        default = [0.8, 0.8, 0.8]
        self.current_object['colour'] = default
        self._update_color_button(button, default)
        self.editor.update_all_ui()

    # === Event Handlers ===

    def on_shader_changed(self, shader_type):
        if self.current_object is None: return
        self.current_object['shader'] = shader_type
        
        # Clear flags that belong to other shader types
        if shader_type != 'Fog':
            self.current_object['is_fog'] = False
        
        # Initialize shader-specific defaults
        if shader_type == 'Glass':
            if 'glass_color' not in self.current_object: self.current_object['glass_color'] = [0.9, 0.95, 1.0]
            if 'glass_opacity' not in self.current_object: self.current_object['glass_opacity'] = 0.3
            if 'glass_distortion' not in self.current_object: self.current_object['glass_distortion'] = 0.5
            if 'glass_refraction' not in self.current_object: self.current_object['glass_refraction'] = 1.5
            if 'glass_roughness' not in self.current_object: self.current_object['glass_roughness'] = 0.0
            if 'glass_fresnel' not in self.current_object: self.current_object['glass_fresnel'] = 0.5
        elif shader_type == 'Glow':
            self.current_object['glow_intensity'] = 10.0
        elif shader_type == 'Water':
            if 'water_opacity' not in self.current_object: self.current_object['water_opacity'] = 0.5
            if 'water_reflectivity' not in self.current_object: self.current_object['water_reflectivity'] = 0.5
            if 'water_tint' not in self.current_object: self.current_object['water_tint'] = [0.0, 0.4, 0.6]
            if 'water_wave_enabled' not in self.current_object: self.current_object['water_wave_enabled'] = False
            if 'water_wave_height' not in self.current_object: self.current_object['water_wave_height'] = 0.5
        elif shader_type == 'Fog':
            self.current_object['is_fog'] = True
            if 'fog_density' not in self.current_object: self.current_object['fog_density'] = 2.0
            if 'fog_color' not in self.current_object: self.current_object['fog_color'] = [0.5, 0.6, 0.7]
        
        # Disable trigger for shader brushes
        if shader_type != '<None>':
            self.current_object['is_trigger'] = False
        
        # Rebuild UI
        self.set_object(self.current_object)
        self.editor.update_all_ui()

    def on_trigger_changed(self, is_trigger):
        if self.current_object is None: return
        self.current_object['is_trigger'] = is_trigger
        
        if is_trigger:
            if 'trigger_type' not in self.current_object: self.current_object['trigger_type'] = 'Once'
            # Set trigger texture
            for face in ['top', 'bottom', 'north', 'south', 'east', 'west']:
                if 'textures' not in self.current_object: self.current_object['textures'] = {}
                self.current_object['textures'][face] = 'trigger.jpg'
        
        # Update tab visibility
        if hasattr(self, 'trigger_tab_index') and self.tab_widget:
            self.tab_widget.setTabVisible(self.trigger_tab_index, is_trigger)
            if is_trigger:
                self.tab_widget.setCurrentIndex(self.trigger_tab_index)
        
        # Rebuild to add/remove I/O tab
        self.set_object(self.current_object)
        self.editor.update_all_ui()

    def on_mover_changed(self, is_mover):
        if self.current_object is None: return
        self.current_object['is_mover'] = is_mover
        
        if is_mover:
            if 'speed' not in self.current_object: self.current_object['speed'] = 64.0
            if 'distance' not in self.current_object: self.current_object['distance'] = 128.0
            if 'direction' not in self.current_object: self.current_object['direction'] = [0, 1, 0]
        
        # Update tab visibility
        if hasattr(self, 'mover_tab_index') and self.tab_widget:
            self.tab_widget.setTabVisible(self.mover_tab_index, is_mover)
            if is_mover:
                self.tab_widget.setCurrentIndex(self.mover_tab_index)
        
        # Rebuild to add/remove I/O tab
        self.set_object(self.current_object)
        self.editor.update_all_ui()

    def on_door_changed(self, is_door):
        if self.current_object is None: return
        self.current_object['is_door'] = is_door
        
        if is_door:
            if 'door_direction' not in self.current_object: self.current_object['door_direction'] = 'up'
            if 'door_distance' not in self.current_object: self.current_object['door_distance'] = 128.0
            if 'door_lip' not in self.current_object: self.current_object['door_lip'] = 8.0
            if 'door_speed' not in self.current_object: self.current_object['door_speed'] = 64.0
        
        # Update tab visibility
        if hasattr(self, 'door_tab_index') and self.tab_widget:
            self.tab_widget.setTabVisible(self.door_tab_index, is_door)
            if is_door:
                self.tab_widget.setCurrentIndex(self.door_tab_index)
        
        # Rebuild to add/remove I/O tab
        self.set_object(self.current_object)
        self.editor.update_all_ui()

    def on_hurt_changed(self, is_hurt):
        if self.current_object is None: return
        self.current_object['hurt'] = is_hurt
        if is_hurt:
            if 'hurt_amount' not in self.current_object: self.current_object['hurt_amount'] = 10
        
        # Enable/disable damage spin
        if 'damage_spin' in self._widgets:
            self._widgets['damage_spin'].setEnabled(is_hurt)
        
        self.editor.update_all_ui()

    def on_door_needs_key_changed(self, needs_key):
        if self.current_object is None: return
        self.current_object['door_needs_key'] = needs_key
        if needs_key:
            if 'door_key_name' not in self.current_object: self.current_object['door_key_name'] = ''
        
        # Show/hide key name widgets
        if 'door_key_input' in self._widgets:
            self._widgets['door_key_input'].setVisible(needs_key)
        if 'door_key_label' in self._widgets:
            self._widgets['door_key_label'].setVisible(needs_key)
        
        # Refresh cross-reference
        self._update_door_key_link(self.current_object)
        
        self.editor.update_all_ui()

    def _update_door_key_link(self, brush):
        """Update the 'Linked Key Pickup' label on the Door tab."""
        link_label = self._widgets.get('door_key_link_label')
        select_btn = self._widgets.get('door_key_select_btn')
        if not link_label:
            return

        if not brush or not brush.get('door_needs_key', False):
            link_label.setText("")
            link_label.setVisible(False)
            if select_btn:
                select_btn.setVisible(False)
            return

        key_name = brush.get('door_key_name', '')
        if not key_name:
            link_label.setText("⚠ No key name set")
            link_label.setStyleSheet("QLabel { color: #FF8800; padding: 4px; }")
            link_label.setVisible(True)
            if select_btn:
                select_btn.setVisible(False)
            return

        # Search for matching key pickups in the map
        self._linked_key_pickup = None
        for thing in self.editor.state.things:
            if isinstance(thing, Pickup):
                if thing.properties.get('item_type') == 'key' and thing.properties.get('key_name') == key_name:
                    self._linked_key_pickup = thing
                    break

        if self._linked_key_pickup:
            name = self._linked_key_pickup.properties.get('name', 'unnamed')
            pos = self._linked_key_pickup.pos
            pos_str = f"({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})" if pos else ""
            link_label.setText(f"🔑 Linked to: {name} {pos_str}")
            link_label.setStyleSheet("QLabel { color: #88FF88; padding: 4px; }")
            link_label.setVisible(True)
            if select_btn:
                select_btn.setVisible(True)
        else:
            link_label.setText(f"⚠ No key pickup named '{key_name}' found in map")
            link_label.setStyleSheet("QLabel { color: #FF4444; padding: 4px; }")
            link_label.setVisible(True)
            if select_btn:
                select_btn.setVisible(False)

    def _select_linked_key_pickup(self):
        """Jump to the key pickup that matches this door's key requirement."""
        pickup = getattr(self, '_linked_key_pickup', None)
        if pickup:
            self.editor.select_object(pickup)

    def _update_pickup_door_link(self, thing):
        """Update the 'Doors Unlocked' label on the Pickup properties."""
        link_label = self._widgets.get('pickup_door_link_label')
        select_btn = self._widgets.get('pickup_door_select_btn')
        if not link_label:
            return

        if not isinstance(thing, Pickup) or thing.properties.get('item_type') != 'key':
            link_label.setVisible(False)
            if select_btn:
                select_btn.setVisible(False)
            return

        key_name = thing.properties.get('key_name', '')
        if not key_name:
            link_label.setText("⚠ No key name set")
            link_label.setStyleSheet("QLabel { color: #FF8800; padding: 4px; }")
            link_label.setVisible(True)
            if select_btn:
                select_btn.setVisible(False)
            return

        # Search for doors that require this key
        self._linked_door_brush = None
        matching_doors = []
        for brush in self.editor.state.brushes:
            if brush.get('is_door') and brush.get('door_needs_key') and brush.get('door_key_name') == key_name:
                matching_doors.append(brush)

        if matching_doors:
            self._linked_door_brush = matching_doors[0]
            door_name = matching_doors[0].get('name', 'unnamed door')
            pos = matching_doors[0].get('pos', [0, 0, 0])
            pos_str = f"({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})"
            if len(matching_doors) == 1:
                link_label.setText(f"🚪 Unlocks: {door_name} {pos_str}")
            else:
                link_label.setText(f"🚪 Unlocks: {door_name} {pos_str} (+{len(matching_doors)-1} more)")
            link_label.setStyleSheet("QLabel { color: #88AAFF; padding: 4px; }")
            link_label.setVisible(True)
            if select_btn:
                select_btn.setVisible(True)
        else:
            link_label.setText(f"⚠ No door requires key '{key_name}'")
            link_label.setStyleSheet("QLabel { color: #FF4444; padding: 4px; }")
            link_label.setVisible(True)
            self._linked_door_brush = None
            if select_btn:
                select_btn.setVisible(False)

    def _select_linked_door(self):
        """Jump to the door brush that this key pickup unlocks."""
        brush = getattr(self, '_linked_door_brush', None)
        if brush:
            self.editor.select_object(brush)

    def toggle_mover_preview(self, checked):
        if self.editor:
            btn = self._widgets.get('mover_preview_btn')
            if checked:
                if btn: btn.setText("■ Stop Preview")
                self.editor.start_mover_preview(self.current_object)
            else:
                if btn: btn.setText("▶ Preview Movement")
                self.editor.stop_mover_preview()

    def toggle_door_preview(self, checked):
        if self.editor:
            # Correctly retrieve the button from the internal dictionary
            btn = self._widgets.get('door_preview_btn')
            if checked:
                if btn: btn.setText("■ Stop Preview")
                # Doors use the same mover logic for the preview
                if hasattr(self.editor, 'start_mover_preview'):
                    self.editor.start_mover_preview(self.current_object)
            else:
                if btn: btn.setText("▶ Preview Door")
                if hasattr(self.editor, 'stop_mover_preview'):
                    self.editor.stop_mover_preview()

    def populate_for_thing(self, thing):
        """Populate property editor for a Thing with tabbed interface."""

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.verticalScrollBar().setStyleSheet("""
            QScrollBar:vertical {
                width: 18px;
                background: #2b2b2b;
                border: none;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #4b4d4d;
                min-height: 20px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        # === NAME FIELD (always visible above tabs, matching brush layout) ===
        name_layout = QFormLayout()
        name_layout.setSpacing(4)

        name_lbl = QLabel("Name:")
        name_lbl.setStyleSheet("QLabel { background-color: #6C3BAA; color: white; font-weight: bold; padding: 6px 8px; border-radius: 3px; }")
        cur_name = thing.properties.get('name', '')
        name_inp = QLineEdit(str(cur_name))
        name_inp.setStyleSheet("QLineEdit { background-color: #6C3BAA; color: white; font-weight: bold; padding: 6px; border: 2px solid #8B5AC2; border-radius: 3px; } QLineEdit:focus { border: 2px solid #A875D6; background-color: #7B4AB9; }")
        name_inp.setPlaceholderText("Enter name...")
        name_inp.editingFinished.connect(lambda: self.update_object_prop('name', name_inp.text()))
        name_layout.addRow(name_lbl, name_inp)

        thing_name = getattr(thing, 'name', '') or thing.properties.get('name', '')
        targeting_sources = self._find_targeting_sources(thing_name) if thing_name else []
        if targeting_sources:
            source_texts = [f"{name} ({stype})" for name, stype in targeting_sources]
            targeted_label = QLabel(", ".join(source_texts))
            targeted_label.setStyleSheet("QLabel { color: #00FF00; font-weight: bold; padding: 2px; background-color: #1a3d1a; border: 1px solid #00AA00; border-radius: 3px; }")
            targeted_label.setWordWrap(True)
            name_layout.addRow("Targeted by:", targeted_label)

        content_layout.addLayout(name_layout)

        # === TAB WIDGET ===
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabBar::tab:selected { background: #F08000; color: white; }
            QTabBar::tab { background: #425f5d; color: #ccc; padding: 8px 16px; border: 1px solid #333; }
            QTabBar::tab:hover { background: #5a7a82; }
        """)

        # Properties tab
        props_tab = self._create_thing_properties_tab(thing)
        self.tab_widget.addTab(props_tab, "Properties")

        # I/O tab (conditional)
        if IO_AVAILABLE:
            entity_type = get_entity_type_for_io(thing)
            if entity_type and entity_type in IO_REGISTRY:
                io_tab = self._create_io_tab_for_thing(thing)
                self.tab_widget.addTab(io_tab, "⚡ I/O")

        content_layout.addWidget(self.tab_widget)
        content_layout.addStretch()

        scroll.setWidget(content_widget)
        self.main_layout.addWidget(scroll)

    def _create_thing_properties_tab(self, thing):
        """Create the Properties tab content for a Thing."""
        widget = QWidget()
        tab_layout = QVBoxLayout(widget)
        tab_layout.setContentsMargins(8, 8, 8, 8)
        tab_layout.setSpacing(4)

        layout = QFormLayout()

        if isinstance(thing, Model):
            self.add_model_path_widget(layout, thing)
            self.add_vector3_widget(layout, thing, 'scale')
            self.add_vector3_widget(layout, thing, 'rotation')
            if IO_AVAILABLE:
                io_note = QLabel("💡 Use the I/O tab for advanced targeting")
                io_note.setStyleSheet("QLabel { color: #88AAFF; font-style: italic; padding: 4px; }")
                layout.addRow("", io_note)

        if isinstance(thing, Light):
            self.add_color_picker_widget(layout, thing, 'colour')

            # --- Attach to Mover: checkbox + conditional dropdown ---
            current_parent = thing.properties.get('parent_mover', '')
            is_attached = bool(current_parent)

            attach_cb = QCheckBox("Attach to Mover")
            attach_cb.setChecked(is_attached)
            layout.addRow("", attach_cb)

            mover_combo = QComboBox()
            mover_combo.addItem("(none)")
            for brush in self.editor.state.brushes:
                if brush.get('is_mover'):
                    mover_name = brush.get('name', '')
                    if mover_name:
                        mover_combo.addItem(mover_name)

            if current_parent:
                idx = mover_combo.findText(current_parent)
                if idx >= 0:
                    mover_combo.setCurrentIndex(idx)
                else:
                    # Parent name in file but mover was deleted
                    mover_combo.addItem(current_parent + " (missing)")
                    mover_combo.setCurrentIndex(mover_combo.count() - 1)

            mover_label = QLabel("Parent Mover:")
            mover_label.setVisible(is_attached)
            mover_combo.setVisible(is_attached)

            def on_attach_toggled(checked):
                mover_label.setVisible(checked)
                mover_combo.setVisible(checked)
                if not checked:
                    thing.properties['parent_mover'] = ''
                    thing.properties['parent_offset'] = [0.0, 0.0, 0.0]
                    mover_combo.setCurrentIndex(0)
                    self.editor.update_all_ui()

            attach_cb.toggled.connect(on_attach_toggled)

            def on_parent_mover_changed(text):
                clean = text.replace(" (missing)", "")
                if clean == "(none)":
                    thing.properties['parent_mover'] = ''
                    thing.properties['parent_offset'] = [0.0, 0.0, 0.0]
                else:
                    thing.properties['parent_mover'] = clean
                    # Compute offset = light pos − mover pos
                    for b in self.editor.state.brushes:
                        if b.get('is_mover') and b.get('name') == clean:
                            thing.properties['parent_offset'] = [
                                thing.pos[0] - b['pos'][0],
                                thing.pos[1] - b['pos'][1],
                                thing.pos[2] - b['pos'][2],
                            ]
                            break
                self.editor.update_all_ui()

            mover_combo.currentTextChanged.connect(on_parent_mover_changed)
            layout.addRow(mover_label, mover_combo)

        is_pickup = isinstance(thing, Pickup)
        current_item_type = thing.properties.get('item_type', 'health') if is_pickup else None

        self._pickup_value_widgets = []
        self._pickup_key_widgets = []
        self._pickup_sprite_widgets = []

        _MONSTER_ONLY_KEYS = {'awake', 'damage', 'health', 'monster_type',
                               'triggered', 'wake_on_sight', 'dead', 'non_hostile', 'sight'}

        for key, value in sorted(thing.properties.items()):
            if key == 'name': continue
            if key == '_io_connections': continue
            if key == 'type': continue
            if isinstance(thing, Light) and key in ['colour', 'parent_mover', 'parent_offset']: continue
            if isinstance(thing, Model) and key in ['model_path', 'scale', 'rotation']: continue
            if not isinstance(thing, Monster) and key in _MONSTER_ONLY_KEYS: continue
            if isinstance(thing, Monster) and key in ('triggered', 'wake_on_sight', 'dead', 'non_hostile', 'sight'): continue
            if is_pickup and key in ['key_name', 'custom_sprite', 'respawns', 'respawn_time']: continue

            label_text = key.replace('_', ' ').title() + ":"

            if isinstance(thing, Monster) and key == 'monster_type':
                widget_w = QComboBox()
                widget_w.addItems(['human', 'flying'])
                widget_w.setCurrentText(value)

                def on_monster_type_changed(new_type):
                    # Update the property
                    self.update_object_prop('monster_type', new_type)
                    # If the user hasn't manually overridden sprite dimensions, apply defaults
                    from engine.monster_constants import MONSTER_SPRITE_SIZES
                    default_w, default_h = MONSTER_SPRITE_SIZES.get(new_type, (128, 128))
                    # Only set if the current dimensions match the previous default (i.e. not custom)
                    current_w = thing.properties.get('sprite_width', 128)
                    current_h = thing.properties.get('sprite_height', 128)
                    # If both width and height match the old human defaults (128,192) or flying defaults (160,160)
                    # we consider them auto‑generated and update them.
                    self.update_object_prop('sprite_width', default_w)
                    self.update_object_prop('sprite_height', default_h)
                    # Force a refresh of the property editor to show the new values
                    self.set_object(thing)

                widget_w.currentTextChanged.connect(on_monster_type_changed)
                layout.addRow(label_text, widget_w)
            elif isinstance(thing, Light) and key == 'state':
                widget_w = QComboBox()
                widget_w.addItems(['on', 'off'])
                widget_w.setCurrentText(value)
                widget_w.currentTextChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget_w)
            elif isinstance(thing, Speaker) and key == 'sound_file':
                self.add_sound_file_widget(layout, thing, key, value)
            elif isinstance(thing, LogicGate) and key == 'logic_type':
                widget_w = QComboBox()
                widget_w.addItems(['AND', 'OR', 'XOR', 'NAND', 'NOR'])
                widget_w.setCurrentText(value)
                widget_w.currentTextChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow("Logic Type:", widget_w)
            elif isinstance(thing, Pickup) and key == 'item_type':
                widget_w = QComboBox()
                item_types = ['health', 'key', 'gun1', 'gun2']
                widget_w.addItems(item_types)
                widget_w.setCurrentText(value)
                widget_w.currentTextChanged.connect(self.on_pickup_item_type_changed)
                layout.addRow(label_text, widget_w)

                self.pickup_key_name_label = QLabel("Key Name:")
                self.pickup_key_name_combo = QComboBox()
                key_names = ['blue_key', 'red_key', 'yellow_key', 'green_key']
                self.pickup_key_name_combo.addItems(key_names)
                self.pickup_key_name_combo.setEditable(True)
                current_key = thing.properties.get('key_name', 'blue_key')
                self.pickup_key_name_combo.setCurrentText(current_key)
                self.pickup_key_name_combo.currentTextChanged.connect(self.on_pickup_key_name_changed)
                layout.addRow(self.pickup_key_name_label, self.pickup_key_name_combo)
                self._pickup_key_widgets.append((self.pickup_key_name_label, self.pickup_key_name_combo))
                is_key_type = (value == 'key')
                self.pickup_key_name_label.setVisible(is_key_type)
                self.pickup_key_name_combo.setVisible(is_key_type)

                # --- Doors Unlocked cross-reference ---
                door_link_label = QLabel("")
                door_link_label.setWordWrap(True)
                door_link_label.setStyleSheet("QLabel { padding: 4px; }")
                door_link_label.setVisible(False)
                layout.addRow("", door_link_label)
                self._widgets['pickup_door_link_label'] = door_link_label
                self._pickup_key_widgets.append((QLabel(""), door_link_label))

                door_select_btn = QPushButton("Select Door ▸")
                door_select_btn.setStyleSheet("""
                    QPushButton { background-color: #2a3a5a; color: #88AAFF; border: 1px solid #4466AA;
                                  border-radius: 3px; padding: 4px 8px; font-size: 11px; }
                    QPushButton:hover { background-color: #3a4a6a; }
                """)
                door_select_btn.setVisible(False)
                door_select_btn.clicked.connect(self._select_linked_door)
                layout.addRow("", door_select_btn)
                self._widgets['pickup_door_select_btn'] = door_select_btn
                self._pickup_key_widgets.append((QLabel(""), door_select_btn))

                # Populate cross-reference
                if is_key_type:
                    self._update_pickup_door_link(thing)

                # Refresh cross-reference when key name changes
                self.pickup_key_name_combo.currentTextChanged.connect(
                    lambda _name: self._update_pickup_door_link(self.current_object))

            elif isinstance(thing, Pickup) and key == 'activation':
                widget_w = QComboBox()
                widget_w.addItems(['walk_over', 'use'])
                widget_w.setCurrentText(value)
                widget_w.currentTextChanged.connect(lambda t, k=key: self.update_object_prop(k, t))
                layout.addRow(label_text, widget_w)
                self._pickup_activation_widget = widget_w
                if current_item_type == 'health':
                    widget_w.setCurrentText('walk_over')
                    widget_w.setEnabled(False)
                    self.update_object_prop('activation', 'walk_over')
            elif isinstance(thing, Pickup) and key == 'value':
                label = QLabel(label_text)
                widget_w = QSpinBox()
                widget_w.setRange(-99999, 99999)
                widget_w.setValue(value)
                widget_w.editingFinished.connect(lambda w=widget_w, k=key: self.update_object_prop(k, w.value()))
                layout.addRow(label, widget_w)
                self._pickup_value_widgets.append((label, widget_w))
                if current_item_type == 'key':
                    label.setVisible(False)
                    widget_w.setVisible(False)
            elif isinstance(value, bool):
                widget_w = QCheckBox()
                widget_w.setStyleSheet(self._checkbox_style())
                widget_w.setChecked(value)
                widget_w.stateChanged.connect(lambda state, k=key: self.update_object_prop(k, state == Qt.Checked))
                layout.addRow(label_text, widget_w)
            elif isinstance(value, int):
                widget_w = QSpinBox()
                widget_w.setRange(-99999, 99999)
                widget_w.setValue(value)
                widget_w.editingFinished.connect(lambda w=widget_w, k=key: self.update_object_prop(k, w.value()))
                layout.addRow(label_text, widget_w)
            elif isinstance(value, float):
                widget_w = QLineEdit(str(value))
                widget_w.editingFinished.connect(lambda le=widget_w, k=key: self.update_object_prop(k, float(le.text()) if le.text() and le.text().replace('.', '', 1).replace('-', '', 1).isdigit() else 0.0))
                layout.addRow(label_text, widget_w)
            else:
                widget_w = QLineEdit(str(value))
                widget_w.editingFinished.connect(lambda le=widget_w, k=key: self.update_object_prop(k, le.text()))
                layout.addRow(label_text, widget_w)

        # Pickup sprite controls
        if is_pickup:
            self.pickup_sprite_label = QLabel("Sprite:")
            sprite_widget = QWidget()
            sprite_layout = QHBoxLayout(sprite_widget)
            sprite_layout.setContentsMargins(0, 0, 0, 0)

            custom_sprite = thing.properties.get('custom_sprite', '')
            self.pickup_sprite_path = QLineEdit(custom_sprite)
            self.pickup_sprite_path.setReadOnly(True)
            self.pickup_sprite_path.setPlaceholderText("Default sprite")

            sprite_btn = QPushButton("Sprite...")
            sprite_btn.setFixedWidth(80)
            sprite_btn.clicked.connect(self.on_pickup_sprite_select)

            clear_btn = QPushButton("Clear")
            clear_btn.setFixedWidth(60)
            clear_btn.setToolTip("Clear custom sprite")
            clear_btn.clicked.connect(self.on_pickup_sprite_clear)

            sprite_layout.addWidget(self.pickup_sprite_path)
            sprite_layout.addWidget(sprite_btn)
            sprite_layout.addWidget(clear_btn)

            layout.addRow(self.pickup_sprite_label, sprite_widget)
            self._pickup_sprite_widgets.append((self.pickup_sprite_label, sprite_widget))

            if current_item_type == 'key':
                self.pickup_sprite_label.setVisible(False)
                sprite_widget.setVisible(False)

        # Respawn controls (Pickup only)
        if is_pickup:
            layout.addRow(self._create_section_header("Respawn"))

            respawns = thing.properties.get('respawns', False)
            respawn_time = thing.properties.get('respawn_time', 20.0)

            respawn_widget = QWidget()
            respawn_layout = QHBoxLayout(respawn_widget)
            respawn_layout.setContentsMargins(0, 0, 0, 0)

            self.respawn_checkbox = QCheckBox("Respawns")
            self.respawn_checkbox.setStyleSheet(self._checkbox_style())
            self.respawn_checkbox.setChecked(respawns)
            self.respawn_checkbox.stateChanged.connect(self.on_respawn_toggled)

            self.respawn_time_label = QLabel("after")
            self.respawn_time_spin = QDoubleSpinBox()
            self.respawn_time_spin.setRange(0.1, 9999.0)
            self.respawn_time_spin.setValue(respawn_time)
            self.respawn_time_spin.setSuffix(" sec")
            self.respawn_time_spin.editingFinished.connect(lambda: self.update_object_prop('respawn_time', self.respawn_time_spin.value()))

            self.respawn_time_label.setVisible(respawns)
            self.respawn_time_spin.setVisible(respawns)

            respawn_layout.addWidget(self.respawn_checkbox)
            respawn_layout.addWidget(self.respawn_time_label)
            respawn_layout.addWidget(self.respawn_time_spin)
            respawn_layout.addStretch()

            layout.addRow("", respawn_widget)

        tab_layout.addLayout(layout)

        # === MONSTER AI + FLAGS ===
        if isinstance(thing, Monster):
            thing.properties.setdefault('sight', 512)
            thing.properties.setdefault('triggered', False)
            thing.properties.setdefault('wake_on_sight', True)
            thing.properties.setdefault('dead', False)
            thing.properties.setdefault('non_hostile', False)

            _group_style = """
                QGroupBox {
                    font-weight: bold;
                    color: #F08000;
                    border: 1px solid #F08000;
                    border-radius: 4px;
                    margin-top: 12px;
                    padding-top: 8px;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    subcontrol-position: top left;
                    left: 8px;
                    padding: 0 4px;
                    background-color: #2b3d3b;
                }
            """

            ai_group = QGroupBox("AI")
            ai_group.setStyleSheet(_group_style)
            ai_form = QFormLayout(ai_group)
            ai_form.setSpacing(6)
            ai_form.setContentsMargins(8, 8, 8, 8)

            sight_row = QWidget()
            sight_row_layout = QHBoxLayout(sight_row)
            sight_row_layout.setContentsMargins(0, 0, 0, 0)
            sight_row_layout.setSpacing(6)

            sight_spin = QSpinBox()
            sight_spin.setRange(0, 9999)
            sight_spin.setValue(thing.properties.get('sight', 512))
            sight_spin.setSuffix(" u")
            sight_spin.setToolTip("Distance (in world units) at which this monster detects the player")
            self._widgets['monster_sight_spin'] = sight_spin

            sight_preview_btn = QToolButton()
            sight_preview_btn.setText("👁")
            sight_preview_btn.setCheckable(True)
            sight_preview_btn.setChecked(getattr(self.editor, '_sight_preview_thing', None) is thing)
            sight_preview_btn.setToolTip("Visualise sight radius in viewport")
            sight_preview_btn.setStyleSheet("""
                QToolButton {
                    background-color: #425f5d;
                    color: white;
                    border-radius: 4px;
                    padding: 3px 8px;
                    font-size: 14px;
                    border: 1px solid #555;
                }
                QToolButton:checked { background-color: #F08000; border-color: #F08000; }
                QToolButton:hover   { background-color: #5a7a82; }
            """)
            self._widgets['monster_sight_preview_btn'] = sight_preview_btn

            def _on_sight_changed(v, _thing=thing):
                _thing.properties['sight'] = v
                if hasattr(self.editor, 'mark_dirty'):
                    self.editor.mark_dirty()
                if getattr(self.editor, '_sight_preview_thing', None) is _thing:
                    self._repaint_viewport()

            def _on_sight_preview_toggled(checked, _thing=thing):
                self.editor._sight_preview_thing = _thing if checked else None
                self._repaint_viewport()

            sight_spin.valueChanged.connect(_on_sight_changed)
            sight_preview_btn.toggled.connect(_on_sight_preview_toggled)

            sight_row_layout.addWidget(sight_spin)
            sight_row_layout.addWidget(sight_preview_btn)
            sight_row_layout.addStretch()
            ai_form.addRow("Sight:", sight_row)

            tab_layout.addWidget(ai_group)

            flags_group = QGroupBox("Behaviour Flags")
            flags_group.setStyleSheet(_group_style)
            flags_layout = QVBoxLayout(flags_group)
            flags_layout.setSpacing(6)

            _flag_defs = [
                ('triggered',            'Trigger',
                 'Monster starts dormant — must be woken via an I/O input'),
                ('wake_on_sight',        'Wake when sees player',
                 'Monster wakes automatically when the player enters its sight range'),
                ('dead',                 'Dead',
                 'Monster is placed in a dead/inactive state at level start'),
                ('non_hostile',          'Non-hostile',
                 'Monster will not attack the player (passive / civilian)'),
            ]

            for prop_key, label_text, tooltip in _flag_defs:
                cb = QCheckBox(label_text)
                cb.setStyleSheet(self._checkbox_style())
                cb.setChecked(thing.properties.get(prop_key, False))
                cb.setToolTip(tooltip)
                cb.toggled.connect(lambda checked, k=prop_key: self.update_object_prop(k, checked))
                flags_layout.addWidget(cb)
                self._widgets[f'monster_flag_{prop_key}'] = cb

            tab_layout.addWidget(flags_group)

            customise_btn = QPushButton("🎨  Customise Sprites…")
            customise_btn.setFixedWidth(350)
            customise_btn.setToolTip(
                "Assign custom idle / shoot / dead PNGs and billboard size "
                "for this monster instance"
            )
            customise_btn.setStyleSheet("""
                QPushButton {
                    background-color: #3c3f41;
                    border: 1px solid #F08000;
                    color: #F08000;
                    padding: 6px;
                    font-weight: bold;
                    margin-top: 4px;
                }
                QPushButton:hover  { background-color: #4b4d4d; }
                QPushButton:pressed { background-color: #2b2b2b; }
            """)

            def _open_customise(_checked=False, _thing=thing):
                from editor.monster_customise_dialog import MonsterCustomiseDialog
                dlg = MonsterCustomiseDialog(_thing, self)
                if dlg.exec_() == MonsterCustomiseDialog.Accepted:
                    self.set_object(_thing)
                    try:
                        self.editor.view_3d.update()
                    except Exception:
                        pass

            customise_btn.clicked.connect(_open_customise)
            customise_btn_row = QHBoxLayout()
            customise_btn_row.addWidget(customise_btn)
            customise_btn_row.addStretch()
            tab_layout.addLayout(customise_btn_row)

        tab_layout.addStretch()
        return widget

    def _repaint_viewport(self):
        """Request a repaint of all viewports without rebuilding the property panel."""
        # 3D viewport
        for attr in ('gl_widget', 'viewport', 'canvas', 'render_widget', 'opengl_widget', 'view_3d'):
            widget = getattr(self.editor, attr, None)
            if widget is not None:
                widget.update()
                break
        # 2D views
        for attr in ('view_top', 'view_front', 'view_side', 'view_2d'):
            widget = getattr(self.editor, attr, None)
            if widget is not None:
                widget.update()

    def on_respawn_toggled(self, state):
        """Handle respawn checkbox toggle."""
        respawns = state == Qt.Checked
        self.update_object_prop('respawns', respawns)
        if hasattr(self, 'respawn_time_label'):
            self.respawn_time_label.setVisible(respawns)
        if hasattr(self, 'respawn_time_spin'):
            self.respawn_time_spin.setVisible(respawns)

    def on_pickup_key_name_changed(self, key_name):
        """Updates key_name property and toggles sprite visibility if 'custom' is selected."""
        self.update_object_prop('key_name', key_name)
        
        # Show sprite widgets if it's a 'custom' key
        is_custom = (key_name == 'custom')
        if hasattr(self, '_pickup_sprite_widgets'):
            for label, widget in self._pickup_sprite_widgets:
                label.setVisible(is_custom)
                widget.setVisible(is_custom)

    def on_pickup_sprite_select(self):
        """Open file dialog to select custom sprite for pickup."""
        if self.current_object is None or not isinstance(self.current_object, Pickup):
            return
        
        # Ensure the file dialog starts in the assets/sprites directory
        start_path = os.path.join(os.getcwd(), 'assets', 'sprites')
        if not os.path.exists(start_path):
            os.makedirs(start_path, exist_ok=True)
        
        filepath, _ = QFileDialog.getOpenFileName(
            self, "Select Sprite Image", start_path,
            "Image Files (*.png *.jpg *.jpeg *.bmp *.tga)"
        )
        
        if filepath:
            try:
                # Force path relative to the project root for cross-platform compatibility
                rel_path = os.path.relpath(filepath, os.getcwd()).replace('\\', '/')
            except ValueError:
                rel_path = filepath
            
            self.update_object_prop('custom_sprite', rel_path)
            if hasattr(self, 'pickup_sprite_path'):
                self.pickup_sprite_path.setText(rel_path)
            
            # Clear sprite cache to force reload in the editor view
            if hasattr(Pickup, 'clear_sprite_cache'):
                Pickup.clear_sprite_cache()
            
            self.editor.update_all_ui()

    def on_pickup_sprite_clear(self):
        """Clear custom sprite, revert to default."""
        if self.current_object is None or not isinstance(self.current_object, Pickup):
            return
        
        self.update_object_prop('custom_sprite', '')
        if hasattr(self, 'pickup_sprite_path'):
            self.pickup_sprite_path.setText('')
        
        # Clear sprite cache to force reload
        if hasattr(Pickup, 'clear_sprite_cache'):
            Pickup.clear_sprite_cache()
        
        self.editor.update_all_ui()

    def on_pickup_item_type_changed(self, item_type):
        if self.current_object is None: return
        self.update_object_prop('item_type', item_type)
        
        is_key = (item_type == 'key')
        is_health = (item_type == 'health')
        is_gun = (item_type in ['gun1', 'gun2'])
        
        # Check current key name to determine if the sprite picker should be visible
        # Defaulting to 'red_key' if not set
        current_key_name = self.current_object.properties.get('key_name', 'red_key')
        
        # Show/hide key name widgets
        if hasattr(self, '_pickup_key_widgets'):
            for label, widget in self._pickup_key_widgets:
                label.setVisible(is_key)
                widget.setVisible(is_key)
        
        # Refresh door cross-reference when switching to key type
        if is_key:
            self._update_pickup_door_link(self.current_object)
        
        # Show/hide value widgets (hide for keys)
        if hasattr(self, '_pickup_value_widgets'):
            for label, widget in self._pickup_value_widgets:
                label.setVisible(not is_key)
                widget.setVisible(not is_key)
        
        # Show/hide sprite widgets
        # Sprites are visible for all generic items, OR specifically for 'custom' keys
        show_sprite_picker = (not is_key) or (is_key and current_key_name == 'custom')
        
        if hasattr(self, '_pickup_sprite_widgets'):
            for label, widget in self._pickup_sprite_widgets:
                label.setVisible(show_sprite_picker)
                widget.setVisible(show_sprite_picker)
        
        # Handle specific item type logic
        if is_health:
            self.update_object_prop('custom_sprite', 'assets/sprites/health.png')
            if hasattr(self, 'pickup_sprite_path'):
                self.pickup_sprite_path.setText('assets/sprites/health.png')
            self.update_object_prop('activation', 'walk_over')
            if hasattr(self, '_pickup_activation_widget'):
                self._pickup_activation_widget.setCurrentText('walk_over')
                self._pickup_activation_widget.setEnabled(False)
        
        elif is_gun:
            sprite_path = f'assets/sprites/{item_type}.png'
            self.update_object_prop('custom_sprite', sprite_path)
            if hasattr(self, 'pickup_sprite_path'):
                self.pickup_sprite_path.setText(sprite_path)
            self.update_object_prop('activation', 'walk_over')
            if hasattr(self, '_pickup_activation_widget'):
                self._pickup_activation_widget.setCurrentText('walk_over')
                self._pickup_activation_widget.setEnabled(False)
                
        else:
            # Re-enable activation dropdown for generic pickups and keys
            if hasattr(self, '_pickup_activation_widget'):
                self._pickup_activation_widget.setEnabled(True)
        
        # Refresh views
        if hasattr(Pickup, 'clear_sprite_cache'):
            Pickup.clear_sprite_cache()
        
        self.editor.update_all_ui()

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
                try: relative_path = os.path.relpath(filepath, ".").replace('\\', '/')
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
        
        # Only update UI if we're not in the middle of populating
        # This prevents infinite recursion when populate calls update_object_prop
        if not self._populating:
            self.editor.update_all_ui()









