from PyQt5.QtWidgets import (
    QDialog, QCheckBox, QVBoxLayout, QDialogButtonBox, QGroupBox, QHBoxLayout,
    QLabel, QSpinBox, QPushButton
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
        self.setMinimumWidth(400)
        self.config = config
        self.binding_in_progress = None

        # --- Main Layout ---
        self.layout = QVBoxLayout(self)

        # --- Display Section ---
        display_group = QGroupBox("Display")
        display_layout = QVBoxLayout()

        self.show_fps_checkbox = QCheckBox("Show FPS in game window")
        display_layout.addWidget(self.show_fps_checkbox)
        
        self.dpi_scaling_checkbox = QCheckBox("Enable High DPI Scaling (requires restart)")
        display_layout.addWidget(self.dpi_scaling_checkbox)

        # NEW: 'Show Caulk' checkbox added
        self.show_caulk_checkbox = QCheckBox("Show Caulk textures in editor")
        display_layout.addWidget(self.show_caulk_checkbox)

        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("Font Size:"))
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 24)
        font_layout.addWidget(self.font_size_spinbox)
        display_layout.addLayout(font_layout)
        
        display_group.setLayout(display_layout)
        self.layout.addWidget(display_group)
        
        # --- Physics Section ---
        physics_group = QGroupBox("Physics (Experimental)")
        physics_layout = QVBoxLayout()
        self.physics_checkbox = QCheckBox("Enable Physics")
        physics_layout.addWidget(self.physics_checkbox)
        physics_group.setLayout(physics_layout)
        self.layout.addWidget(physics_group)

        # --- Controls Section ---
        controls_group = QGroupBox("Controls")
        controls_layout = QVBoxLayout()
        self.invert_mouse_checkbox = QCheckBox("Invert Mouse Look")
        controls_layout.addWidget(self.invert_mouse_checkbox)
        
        self.control_buttons = {}
        for control_name in ["forward", "back", "left", "right"]:
            row_layout = QHBoxLayout()
            row_layout.addWidget(QLabel(f"{control_name.capitalize()}:"))
            row_layout.addStretch()
            
            self.control_buttons[control_name] = QPushButton("...")
            self.control_buttons[control_name].setFixedWidth(120)
            self.control_buttons[control_name].clicked.connect(lambda _, c=control_name: self.change_key(c))
            row_layout.addWidget(self.control_buttons[control_name])
            controls_layout.addLayout(row_layout)
            
        controls_group.setLayout(controls_layout)
        self.layout.addWidget(controls_group)
        
        self.layout.addStretch()
        
        # --- OK and Cancel Buttons ---
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        self.layout.addWidget(button_box)
        
        self.load_settings()

    def load_settings(self):
        """Loads settings from the config object into the UI widgets."""
        self.show_fps_checkbox.setChecked(self.config.getboolean('Display', 'show_fps', fallback=False))
        self.dpi_scaling_checkbox.setChecked(self.config.getboolean('Display', 'high_dpi_scaling', fallback=False))
        self.show_caulk_checkbox.setChecked(self.config.getboolean('Display', 'show_caulk', fallback=True)) # Load caulk setting
        self.font_size_spinbox.setValue(self.config.getint('Display', 'font_size', fallback=10))
        self.physics_checkbox.setChecked(self.config.getboolean('Settings', 'physics', fallback=True))
        self.invert_mouse_checkbox.setChecked(self.config.getboolean('Controls', 'invert_mouse', fallback=False))
        
        for control, button in self.control_buttons.items():
            key = self.config.get('Controls', control, fallback='W' if control == 'forward' else 'S' if control == 'back' else 'A' if control == 'left' else 'D')
            button.setText(key)

    def accept(self):
        """Saves the current UI state back to the config object."""
        if not self.config.has_section('Display'): self.config.add_section('Display')
        self.config.set('Display', 'show_fps', str(self.show_fps_checkbox.isChecked()))
        self.config.set('Display', 'high_dpi_scaling', str(self.dpi_scaling_checkbox.isChecked()))
        self.config.set('Display', 'show_caulk', str(self.show_caulk_checkbox.isChecked())) # Save caulk setting
        self.config.set('Display', 'font_size', str(self.font_size_spinbox.value()))

        if not self.config.has_section('Settings'): self.config.add_section('Settings')
        self.config.set('Settings', 'physics', str(self.physics_checkbox.isChecked()))

        if not self.config.has_section('Controls'): self.config.add_section('Controls')
        self.config.set('Controls', 'invert_mouse', str(self.invert_mouse_checkbox.isChecked()))
        for control, button in self.control_buttons.items():
            self.config.set('Controls', control, button.text())
        
        super().accept()

    def change_key(self, control_name):
        """Prepares to capture the next key press for a specific control."""
        self.binding_in_progress = control_name
        button = self.control_buttons[control_name]
        button.setText("Press a key...")
        self.grabKeyboard()

    def keyPressEvent(self, event):
        """Captures the key press if a binding is in progress."""
        if self.binding_in_progress:
            key_name = QKeySequence(event.key() + int(event.modifiers())).toString(QKeySequence.NativeText).upper()
            
            if not key_name or len(key_name) > 1 and "F" not in key_name and "+" not in key_name:
                super().keyPressEvent(event)
                return

            button = self.control_buttons[self.binding_in_progress]
            button.setText(key_name)
            self.releaseKeyboard()
            self.binding_in_progress = None
        else:
            super().keyPressEvent(event)