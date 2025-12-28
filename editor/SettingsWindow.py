from PyQt5.QtWidgets import (
    QDialog, QCheckBox, QVBoxLayout, QDialogButtonBox, QGroupBox, QHBoxLayout,
    QLabel, QSpinBox, QPushButton, QTabWidget, QWidget, QFormLayout, QSlider
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence

class SettingsWindow(QDialog):
    """
    A dialog window for editing application settings, built with PyQt5.
    """
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(600)
        self.config = config
        self.binding_in_progress = None

        # --- Main Layout ---
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        
        # --- Display & Physics Tab ---
        display_physics_widget = QWidget()
        display_physics_layout = QVBoxLayout(display_physics_widget)
        self.tabs.addTab(display_physics_widget, "General")

        # --- Display Section ---
        display_group = QGroupBox("")
        display_layout = QVBoxLayout()

        self.show_fps_checkbox = QCheckBox("Show FPS in 3D view")
        display_layout.addWidget(self.show_fps_checkbox)
        
        self.dpi_scaling_checkbox = QCheckBox("Enable High DPI Scaling (requires restart)")
        display_layout.addWidget(self.dpi_scaling_checkbox)

        self.show_caulk_checkbox = QCheckBox("Show Caulk textures in editor")
        display_layout.addWidget(self.show_caulk_checkbox)

        self.sync_selection_checkbox = QCheckBox("Highlight selected brushes in 3D view")
        display_layout.addWidget(self.sync_selection_checkbox)

        # Selection transparency slider
        selection_trans_layout = QHBoxLayout()
        selection_trans_layout.addWidget(QLabel("Selection Transparency:"))
        self.selection_transparency_slider = QSlider(Qt.Horizontal)
        self.selection_transparency_slider.setRange(0, 100)
        self.selection_transparency_slider.setValue(50)
        self.selection_transparency_slider.setTickPosition(QSlider.TicksBelow)
        self.selection_transparency_slider.setTickInterval(10)
        selection_trans_layout.addWidget(self.selection_transparency_slider)
        self.selection_transparency_label = QLabel("50%")
        self.selection_transparency_slider.valueChanged.connect(
            lambda v: self.selection_transparency_label.setText(f"{v}%"))
        selection_trans_layout.addWidget(self.selection_transparency_label)
        display_layout.addLayout(selection_trans_layout)

        self.show_connections_checkbox = QCheckBox("Show animated connection lines in 2D views")
        display_layout.addWidget(self.show_connections_checkbox)

        self.show_hud_checkbox = QCheckBox("Show HUD in play mode (health, etc.)")
        display_layout.addWidget(self.show_hud_checkbox)

        self.disable_toasts_checkbox = QCheckBox("Disable all toast notifications")
        display_layout.addWidget(self.disable_toasts_checkbox)

        # New: Locked items not selectable in 2D views
        self.locked_not_selectable_checkbox = QCheckBox("Locked items not selectable in 2D views")
        display_layout.addWidget(self.locked_not_selectable_checkbox)

        # New: Big toolbar buttons checkbox
        self.big_toolbar_buttons_checkbox = QCheckBox("Big toolbar buttons (requires restart)")
        display_layout.addWidget(self.big_toolbar_buttons_checkbox)

        # Glow arrow scale slider
        glow_arrow_layout = QHBoxLayout()
        glow_arrow_layout.addWidget(QLabel("Glow Arrow Scale:"))
        self.glow_arrow_scale_slider = QSlider(Qt.Horizontal)
        self.glow_arrow_scale_slider.setRange(50, 300)
        self.glow_arrow_scale_slider.setValue(100)
        self.glow_arrow_scale_slider.setTickPosition(QSlider.TicksBelow)
        self.glow_arrow_scale_slider.setTickInterval(25)
        glow_arrow_layout.addWidget(self.glow_arrow_scale_slider)
        self.glow_arrow_scale_label = QLabel("100%")
        self.glow_arrow_scale_slider.valueChanged.connect(
            lambda v: self.glow_arrow_scale_label.setText(f"{v}%"))
        glow_arrow_layout.addWidget(self.glow_arrow_scale_label)
        display_layout.addLayout(glow_arrow_layout)

        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("Font Size:"))
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 24)
        font_layout.addWidget(self.font_size_spinbox)
        display_layout.addLayout(font_layout)
        
        display_group.setLayout(display_layout)
        display_physics_layout.addWidget(display_group)
        
        # --- Physics Section ---
        physics_group = QGroupBox("")
        physics_layout = QVBoxLayout()
        self.physics_checkbox = QCheckBox("Physics in Play mode")
        physics_layout.addWidget(self.physics_checkbox)
        physics_group.setLayout(physics_layout)
        display_physics_layout.addWidget(physics_group)
        display_physics_layout.addStretch()
        
        # --- Controls Tab ---
        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        self.tabs.addTab(controls_widget, "Controls")

        self.invert_mouse_checkbox = QCheckBox("Invert Mouse Look")
        controls_layout.addWidget(self.invert_mouse_checkbox)
        
        self.middle_click_drag_checkbox = QCheckBox("Enable Middle Click to Drag in 2D Views")
        controls_layout.addWidget(self.middle_click_drag_checkbox)
        controls_layout.addStretch()
        
        # --- Keyboard Shortcuts Tab ---
        shortcuts_widget = QWidget()
        shortcuts_layout = QFormLayout(shortcuts_widget)
        self.tabs.addTab(shortcuts_widget, "Keyboard")

        # Asset Browser first
        asset_browser_label = QLabel("T")
        shortcuts_layout.addRow("Asset Browser:", asset_browser_label)

        shortcut_definitions = {
            "apply_texture": "Shift+T",
            "Clone Brush": "SPACE",
            "Delete Brush": "DEL",
            "reset_layout": "Ctrl+Shift+R",
            "save_layout": "Ctrl+Shift+S",
            "Hide Brush": "H",
            "Unhide All Brushes": "Shift+H",
            "Toggle play mode": "F5",
            "Use (play mode)": "E",
            "Show connections (play)": "F1",
            "Show sprites (play)": "F3",
            "Connect trigger to target": "Ctrl+Drag",
        }
        
        self.shortcut_labels = {}
        for action_name, shortcut_text in shortcut_definitions.items():
            label_text = action_name.replace('_', ' ').title()
            shortcut_label = QLabel(shortcut_text)
            self.shortcut_labels[action_name] = shortcut_label
            shortcuts_layout.addRow(label_text, shortcut_label)

        switch_2d_views_label = QLabel("Shift+Tab")
        shortcuts_layout.addRow("Switch 2D Views:", switch_2d_views_label)
        
        # --- OK and Cancel Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.layout.addWidget(button_box)
        
        self.load_settings()

        # --- Style Sheet to make checkboxes 25px square ---
        self.setStyleSheet("""
            QCheckBox::indicator:checked {
                background-color: #F08000;
                border: 1px solid #333;
                image: none;
            }
            QCheckBox::indicator:unchecked {
                background-color: #425f5d;
                border: 1px solid #333;
            }
            QCheckBox::indicator {
                width: 25px;
                height: 25px;
            }
            QCheckBox::indicator:hover {
                border: 1px solid #555;
            }
            QCheckBox::indicator:checked:hover {
                background-color: #FF8C00;
                image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 16 16'><path fill='white' d='M6 12.5l-4-4 1.4-1.4L6 9.7l6.6-6.6L14 4.5z'/></svg>");
                image-position: center;
            }
            QCheckBox::indicator:unchecked:hover {
                background-color: #4A6B73;
            }
        """)

    def load_settings(self):
        # Display settings
        self.show_fps_checkbox.setChecked(self.config.getboolean('Display', 'show_fps', fallback=True))
        self.dpi_scaling_checkbox.setChecked(self.config.getboolean('Display', 'high_dpi_scaling', fallback=False))
        self.show_caulk_checkbox.setChecked(self.config.getboolean('Display', 'show_caulk', fallback=True))
        self.font_size_spinbox.setValue(self.config.getint('Display', 'font_size', fallback=10))
        self.sync_selection_checkbox.setChecked(self.config.getboolean('Display', 'sync_selection', fallback=True))
        # Load selection transparency
        selection_trans = self.config.getint('Display', 'selection_transparency', fallback=50)
        self.selection_transparency_slider.setValue(selection_trans)
        self.selection_transparency_label.setText(f"{selection_trans}%")
        self.show_connections_checkbox.setChecked(self.config.getboolean('Display', 'show_connections', fallback=True))
        self.show_hud_checkbox.setChecked(self.config.getboolean('Display', 'show_hud', fallback=True))
        self.disable_toasts_checkbox.setChecked(self.config.getboolean('Display', 'disable_toasts', fallback=False))
        # Load locked not selectable setting
        self.locked_not_selectable_checkbox.setChecked(self.config.getboolean('Display', 'locked_not_selectable_2d', fallback=False))
        # Load big toolbar buttons setting
        self.big_toolbar_buttons_checkbox.setChecked(self.config.getboolean('Display', 'big_toolbar_buttons', fallback=False))
        # Load glow arrow scale setting
        glow_arrow_scale = self.config.getint('Display', 'glow_arrow_scale', fallback=100)
        self.glow_arrow_scale_slider.setValue(glow_arrow_scale)
        self.glow_arrow_scale_label.setText(f"{glow_arrow_scale}%")

        # Physics settings
        self.physics_checkbox.setChecked(self.config.getboolean('Settings', 'physics', fallback=True))

        # Controls settings
        self.invert_mouse_checkbox.setChecked(self.config.getboolean('Controls', 'invert_mouse', fallback=False))
        self.middle_click_drag_checkbox.setChecked(self.config.getboolean('Controls', 'MiddleClickDrag', fallback=False))

        pass

    def accept(self):
        """Saves the current UI state back to the config object."""
        if not self.config.has_section('Display'): self.config.add_section('Display')
        self.config.set('Display', 'show_fps', str(self.show_fps_checkbox.isChecked()))
        self.config.set('Display', 'high_dpi_scaling', str(self.dpi_scaling_checkbox.isChecked()))
        self.config.set('Display', 'show_caulk', str(self.show_caulk_checkbox.isChecked()))
        self.config.set('Display', 'font_size', str(self.font_size_spinbox.value()))
        self.config.set('Display', 'sync_selection', str(self.sync_selection_checkbox.isChecked()))
        self.config.set('Display', 'selection_transparency', str(self.selection_transparency_slider.value()))
        self.config.set('Display', 'show_connections', str(self.show_connections_checkbox.isChecked()))
        self.config.set('Display', 'show_hud', str(self.show_hud_checkbox.isChecked()))
        self.config.set('Display', 'disable_toasts', str(self.disable_toasts_checkbox.isChecked()))
        self.config.set('Display', 'locked_not_selectable_2d', str(self.locked_not_selectable_checkbox.isChecked()))
        self.config.set('Display', 'big_toolbar_buttons', str(self.big_toolbar_buttons_checkbox.isChecked()))
        self.config.set('Display', 'glow_arrow_scale', str(self.glow_arrow_scale_slider.value()))

        if not self.config.has_section('Settings'): self.config.add_section('Settings')
        self.config.set('Settings', 'physics', str(self.physics_checkbox.isChecked()))

        if not self.config.has_section('Controls'): self.config.add_section('Controls')
        self.config.set('Controls', 'invert_mouse', str(self.invert_mouse_checkbox.isChecked()))
        self.config.set('Controls', 'MiddleClickDrag', str(self.middle_click_drag_checkbox.isChecked()))
        
        super().accept()

    def change_key(self, control_name):
        """Prepares to capture the next key press for a specific control."""
        # This method is here for future use
        pass

    def keyPressEvent(self, event):
        """Captures the key press if a binding is in progress."""
        # This method is here for future use
        super().keyPressEvent(event)