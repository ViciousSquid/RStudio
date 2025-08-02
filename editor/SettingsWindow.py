from PyQt5.QtWidgets import (
    QDialog, QCheckBox, QVBoxLayout, QDialogButtonBox, QGroupBox, QHBoxLayout,
    QLabel, QSpinBox, QPushButton, QTabWidget, QWidget, QFormLayout
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
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        
        # --- Display & Physics Tab ---
        display_physics_widget = QWidget()
        display_physics_layout = QVBoxLayout(display_physics_widget)
        self.tabs.addTab(display_physics_widget, "Display & Physics")

        # --- Display Section ---
        display_group = QGroupBox("")
        display_layout = QVBoxLayout()

        self.show_fps_checkbox = QCheckBox("Show FPS in 3D view")
        display_layout.addWidget(self.show_fps_checkbox)
        
        self.dpi_scaling_checkbox = QCheckBox("Enable High DPI Scaling (requires restart)")
        display_layout.addWidget(self.dpi_scaling_checkbox)

        self.show_caulk_checkbox = QCheckBox("Show Caulk textures in editor")
        display_layout.addWidget(self.show_caulk_checkbox)

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
        self.physics_checkbox = QCheckBox("Enable Physics (not working yet)")
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

        self.shortcut_buttons = {}
        shortcut_actions = [
            "apply_texture", "Clone Brush", "Delete Brush",
            "reset_layout", "save_layout"
        ]
        for action_name in shortcut_actions:
            label_text = action_name.replace('_', ' ').title()
            self.shortcut_buttons[action_name] = QPushButton("...")
            self.shortcut_buttons[action_name].setFixedWidth(120)
            self.shortcut_buttons[action_name].clicked.connect(lambda _, a=action_name: self.change_key(a))
            shortcuts_layout.addRow(label_text, self.shortcut_buttons[action_name])

        asset_browser_label = QLabel("T")
        shortcuts_layout.addRow("Asset Browser:", asset_browser_label)
        
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
        self.show_caulk_checkbox.setChecked(self.config.getboolean('Display', 'show_caulk', fallback=True))
        self.font_size_spinbox.setValue(self.config.getint('Display', 'font_size', fallback=10))
        self.physics_checkbox.setChecked(self.config.getboolean('Settings', 'physics', fallback=True))
        self.invert_mouse_checkbox.setChecked(self.config.getboolean('Controls', 'invert_mouse', fallback=False))
        self.middle_click_drag_checkbox.setChecked(self.config.getboolean('Controls', 'MiddleClickDrag', fallback=False))
        
        for action, button in self.shortcut_buttons.items():
            fallback_key = ''
            if action == 'apply_texture':
                fallback_key = 'Shift+T'
            elif action == 'Clone Brush':
                fallback_key = 'Space'
            elif action == 'Delete Brush':
                fallback_key = 'Del'
            elif action == 'reset_layout':
                fallback_key = 'Ctrl+Shift+R'
            elif action == 'save_layout':
                fallback_key = 'Ctrl+Shift+S'
            shortcut = self.config.get('Controls', action, fallback=fallback_key)
            button.setText(shortcut)


    def accept(self):
        """Saves the current UI state back to the config object."""
        if not self.config.has_section('Display'): self.config.add_section('Display')
        self.config.set('Display', 'show_fps', str(self.show_fps_checkbox.isChecked()))
        self.config.set('Display', 'high_dpi_scaling', str(self.dpi_scaling_checkbox.isChecked()))
        self.config.set('Display', 'show_caulk', str(self.show_caulk_checkbox.isChecked()))
        self.config.set('Display', 'font_size', str(self.font_size_spinbox.value()))

        if not self.config.has_section('Settings'): self.config.add_section('Settings')
        self.config.set('Settings', 'physics', str(self.physics_checkbox.isChecked()))

        if not self.config.has_section('Controls'): self.config.add_section('Controls')
        self.config.set('Controls', 'invert_mouse', str(self.invert_mouse_checkbox.isChecked()))
        self.config.set('Controls', 'MiddleClickDrag', str(self.middle_click_drag_checkbox.isChecked()))

        for action, button in self.shortcut_buttons.items():
            self.config.set('Controls', action, button.text())
        
        super().accept()

    def change_key(self, control_name):
        """Prepares to capture the next key press for a specific control."""
        self.binding_in_progress = control_name
        button = self.shortcut_buttons[control_name]
        button.setText("Press a key...")
        self.grabKeyboard()

    def keyPressEvent(self, event):
        """Captures the key press if a binding is in progress."""
        if self.binding_in_progress:
            key_sequence = QKeySequence(event.key() + int(event.modifiers()))
            key_name = key_sequence.toString(QKeySequence.NativeText)

            if not key_name or key_name in ["Shift", "Ctrl", "Alt"]:
                 super().keyPressEvent(event)
                 return

            if self.binding_in_progress in self.shortcut_buttons:
                button = self.shortcut_buttons[self.binding_in_progress]
                button.setText(key_name)


            self.releaseKeyboard()
            self.binding_in_progress = None
        else:
            super().keyPressEvent(event)