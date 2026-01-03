from PyQt5.QtWidgets import (
    QDialog, QCheckBox, QVBoxLayout, QDialogButtonBox, QGroupBox, QHBoxLayout,
    QLabel, QSpinBox, QPushButton, QTabWidget, QWidget, QFormLayout, QSlider,
    QMessageBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence
import sys
import os

class SettingsWindow(QDialog):
    """
    A dialog window for editing application settings, built with PyQt5.
    """
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(500)
        self.config = config
        self.main_window = parent
        self.binding_in_progress = None

        # --- Main Layout ---
        self.layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)
        
        # --- Create Tabs ---
        self._create_editor_tab()
        self._create_display_tab()
        self._create_play_mode_tab()
        self._create_controls_tab()
        self._create_keyboard_tab()
        
        # --- Button Row ---
        button_layout = QHBoxLayout()
        
        # Apply and Restart button
        self.restart_button = QPushButton("Apply && Restart")
        self.restart_button.setToolTip("Save settings and restart the application")
        self.restart_button.clicked.connect(self._apply_and_restart)
        self.restart_button.setStyleSheet("""
            QPushButton {
                background-color: #425f5d;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border: 1px solid #333;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #4A6B73;
                border: 1px solid #555;
            }
            QPushButton:pressed {
                background-color: #3a5250;
            }
        """)
        button_layout.addWidget(self.restart_button)
        
        button_layout.addStretch()
        
        # OK and Cancel Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        button_layout.addWidget(button_box)
        
        self.layout.addLayout(button_layout)
        
        self.load_settings()
        self._apply_stylesheet()

    def _create_editor_tab(self):
        """Editor tab: 2D/3D view settings and selection behavior."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.tabs.addTab(widget, "Editor")
        
        # --- 3D View Section ---
        view_3d_group = QGroupBox("3D View")
        view_3d_layout = QVBoxLayout()
        
        self.show_caulk_checkbox = QCheckBox("Show Caulk textures")
        view_3d_layout.addWidget(self.show_caulk_checkbox)
        
        self.sync_selection_checkbox = QCheckBox("Highlight selected brushes")
        view_3d_layout.addWidget(self.sync_selection_checkbox)
        
        self.click_select_3d_checkbox = QCheckBox("Click to select in 3D view")
        self.click_select_3d_checkbox.setToolTip("Allow selecting brushes/things by clicking in the 3D view (without Shift)")
        view_3d_layout.addWidget(self.click_select_3d_checkbox)
        
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
        view_3d_layout.addLayout(selection_trans_layout)
        
        view_3d_group.setLayout(view_3d_layout)
        layout.addWidget(view_3d_group)
        
        # --- 2D Views Section ---
        view_2d_group = QGroupBox("2D Views")
        view_2d_layout = QVBoxLayout()
        
        self.show_connections_checkbox = QCheckBox("Show animated connection lines")
        view_2d_layout.addWidget(self.show_connections_checkbox)
        
        self.locked_not_selectable_checkbox = QCheckBox("Locked items not selectable")
        view_2d_layout.addWidget(self.locked_not_selectable_checkbox)
        
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
        view_2d_layout.addLayout(glow_arrow_layout)
        
        view_2d_group.setLayout(view_2d_layout)
        layout.addWidget(view_2d_group)
        
        layout.addStretch()

    def _create_display_tab(self):
        """Display tab: Visual appearance settings."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.tabs.addTab(widget, "Display")
        
        # --- Appearance Section ---
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QVBoxLayout()
        
        self.show_fps_checkbox = QCheckBox("Show FPS in 3D view")
        appearance_layout.addWidget(self.show_fps_checkbox)
        
        self.always_show_sysmon_checkbox = QCheckBox("Always show SysMon at launch")
        appearance_layout.addWidget(self.always_show_sysmon_checkbox)
        
        self.disable_toasts_checkbox = QCheckBox("Disable toast notifications")
        appearance_layout.addWidget(self.disable_toasts_checkbox)
        
        # Font size
        font_layout = QHBoxLayout()
        font_layout.addWidget(QLabel("Font Size:"))
        self.font_size_spinbox = QSpinBox()
        self.font_size_spinbox.setRange(8, 24)
        font_layout.addWidget(self.font_size_spinbox)
        font_layout.addStretch()
        appearance_layout.addLayout(font_layout)
        
        appearance_group.setLayout(appearance_layout)
        layout.addWidget(appearance_group)
        
        # --- Requires Restart Section ---
        restart_group = QGroupBox("Requires Restart")
        restart_layout = QVBoxLayout()
        
        self.vsync_checkbox = QCheckBox("Enable VSync (Sync to Monitor)")
        self.vsync_checkbox.setToolTip("Syncs framerate to monitor refresh rate to prevent tearing.\nDisable for benchmarking.")
        restart_layout.addWidget(self.vsync_checkbox)
        
        self.dpi_scaling_checkbox = QCheckBox("Enable High DPI Scaling")
        restart_layout.addWidget(self.dpi_scaling_checkbox)
        
        self.big_toolbar_buttons_checkbox = QCheckBox("Big toolbar buttons")
        restart_layout.addWidget(self.big_toolbar_buttons_checkbox)
        
        restart_group.setLayout(restart_layout)
        layout.addWidget(restart_group)
        
        layout.addStretch()

    def _create_play_mode_tab(self):
        """Play Mode tab: Physics and gameplay settings."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.tabs.addTab(widget, "Play Mode")
        
        # --- Gameplay Section ---
        gameplay_group = QGroupBox("Gameplay")
        gameplay_layout = QVBoxLayout()
        
        self.physics_checkbox = QCheckBox("Enable physics")
        gameplay_layout.addWidget(self.physics_checkbox)
        
        self.show_hud_checkbox = QCheckBox("Show HUD (health, etc.)")
        gameplay_layout.addWidget(self.show_hud_checkbox)
        
        gameplay_group.setLayout(gameplay_layout)
        layout.addWidget(gameplay_group)
        
        layout.addStretch()

    def _create_controls_tab(self):
        """Controls tab: Mouse and input settings."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.tabs.addTab(widget, "Controls")
        
        # --- Mouse Section ---
        mouse_group = QGroupBox("Mouse")
        mouse_layout = QVBoxLayout()
        
        self.invert_mouse_checkbox = QCheckBox("Invert Mouse Look")
        mouse_layout.addWidget(self.invert_mouse_checkbox)
        
        self.middle_click_drag_checkbox = QCheckBox("Middle Click to Drag in 2D Views")
        mouse_layout.addWidget(self.middle_click_drag_checkbox)
        
        mouse_group.setLayout(mouse_layout)
        layout.addWidget(mouse_group)
        
        layout.addStretch()

    def _create_keyboard_tab(self):
        """Keyboard Shortcuts tab."""
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
            "Decrease Grid Size": "[",
            "Increase Grid Size": "]",
            "Toggle play mode": "F5",
            "Use (play mode)": "E",
            "Show connections (play)": "F1",
            "Show sprites (play)": "F3",
            "Connect trigger to target": "Ctrl+Drag",
            "Light Radius (when selected)": "Shift+Wheel",
            "Light Intensity (when selected)": "Ctrl+Wheel",
            "Free Camera (3D view)": "Right Mouse+WASD",
            "Move Camera (3D view)": "SPACE and C",
        }
        
        self.shortcut_labels = {}
        for action_name, shortcut_text in shortcut_definitions.items():
            label_text = action_name.replace('_', ' ').title()
            shortcut_label = QLabel(shortcut_text)
            self.shortcut_labels[action_name] = shortcut_label
            shortcuts_layout.addRow(label_text, shortcut_label)

        switch_2d_views_label = QLabel("Shift+Tab")
        shortcuts_layout.addRow("Switch 2D Views:", switch_2d_views_label)

    def _apply_stylesheet(self):
        """Apply the checkbox styling."""
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
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
        """)

    def load_settings(self):
        # Editor settings
        self.show_caulk_checkbox.setChecked(self.config.getboolean('Display', 'show_caulk', fallback=True))
        self.sync_selection_checkbox.setChecked(self.config.getboolean('Display', 'sync_selection', fallback=True))
        self.click_select_3d_checkbox.setChecked(self.config.getboolean('Display', 'click_select_3d', fallback=False))
        selection_trans = self.config.getint('Display', 'selection_transparency', fallback=50)
        self.selection_transparency_slider.setValue(selection_trans)
        self.selection_transparency_label.setText(f"{selection_trans}%")
        self.show_connections_checkbox.setChecked(self.config.getboolean('Display', 'show_connections', fallback=True))
        self.locked_not_selectable_checkbox.setChecked(self.config.getboolean('Display', 'locked_not_selectable_2d', fallback=True))
        glow_arrow_scale = self.config.getint('Display', 'glow_arrow_scale', fallback=100)
        self.glow_arrow_scale_slider.setValue(glow_arrow_scale)
        self.glow_arrow_scale_label.setText(f"{glow_arrow_scale}%")
        
        # Display settings
        self.show_fps_checkbox.setChecked(self.config.getboolean('Display', 'show_fps', fallback=True))
        self.always_show_sysmon_checkbox.setChecked(self.config.getboolean('Display', 'always_show_sysmon', fallback=False))
        self.disable_toasts_checkbox.setChecked(self.config.getboolean('Display', 'disable_toasts', fallback=False))
        self.font_size_spinbox.setValue(self.config.getint('Display', 'font_size', fallback=10))
        self.vsync_checkbox.setChecked(self.config.getboolean('Display', 'vsync', fallback=False))
        self.dpi_scaling_checkbox.setChecked(self.config.getboolean('Display', 'high_dpi_scaling', fallback=False))
        self.big_toolbar_buttons_checkbox.setChecked(self.config.getboolean('Display', 'big_toolbar_buttons', fallback=False))

        # Play Mode settings
        self.physics_checkbox.setChecked(self.config.getboolean('Settings', 'physics', fallback=True))
        self.show_hud_checkbox.setChecked(self.config.getboolean('Display', 'show_hud', fallback=True))

        # Controls settings
        self.invert_mouse_checkbox.setChecked(self.config.getboolean('Controls', 'invert_mouse', fallback=False))
        self.middle_click_drag_checkbox.setChecked(self.config.getboolean('Controls', 'MiddleClickDrag', fallback=False))

    def accept(self):
        """Saves the current UI state back to the config object."""
        self._save_settings()
        super().accept()

    def change_key(self, control_name):
        """Prepares to capture the next key press for a specific control."""
        # This method is here for future use
        pass

    def keyPressEvent(self, event):
        """Captures the key press if a binding is in progress."""
        # This method is here for future use
        super().keyPressEvent(event)

    def _has_unsaved_work(self):
        """Check if the main window has unsaved work."""
        if not self.main_window:
            return False
        
        # Check if there's content but no save file
        has_content = False
        if hasattr(self.main_window, 'state'):
            state = self.main_window.state
            has_content = (len(getattr(state, 'brushes', [])) > 0 or 
                          len(getattr(state, 'things', [])) > 0)
        
        # Check if there's no file path (never saved)
        no_file = not getattr(self.main_window, 'file_path', None)
        
        # Check undo stack for changes since last save
        has_undo_history = False
        if hasattr(self.main_window, 'undo_stack'):
            has_undo_history = len(self.main_window.undo_stack) > 0
        
        # Consider unsaved if: has content with no file, or has undo history
        return (has_content and no_file) or has_undo_history

    def _apply_and_restart(self):
        """Save settings and restart the application."""
        # Check for unsaved work
        if self._has_unsaved_work():
            reply = QMessageBox.warning(
                self,
                "Unsaved Work",
                "Unsaved work will be lost!\n\nAre you sure you want to restart?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return
        
        # Save the settings (calls accept's save logic)
        self._save_settings()
        
        # Save config to file
        if self.main_window and hasattr(self.main_window, 'save_config'):
            self.main_window.save_config()
        
        # Restart the application
        self._restart_application()

    def _save_settings(self):
        """Save settings without closing the dialog."""
        if not self.config.has_section('Display'): 
            self.config.add_section('Display')
        
        # Editor settings
        self.config.set('Display', 'show_caulk', str(self.show_caulk_checkbox.isChecked()))
        self.config.set('Display', 'sync_selection', str(self.sync_selection_checkbox.isChecked()))
        self.config.set('Display', 'click_select_3d', str(self.click_select_3d_checkbox.isChecked()))
        self.config.set('Display', 'selection_transparency', str(self.selection_transparency_slider.value()))
        self.config.set('Display', 'show_connections', str(self.show_connections_checkbox.isChecked()))
        self.config.set('Display', 'locked_not_selectable_2d', str(self.locked_not_selectable_checkbox.isChecked()))
        self.config.set('Display', 'glow_arrow_scale', str(self.glow_arrow_scale_slider.value()))
        
        # Display settings
        self.config.set('Display', 'show_fps', str(self.show_fps_checkbox.isChecked()))
        self.config.set('Display', 'always_show_sysmon', str(self.always_show_sysmon_checkbox.isChecked()))
        self.config.set('Display', 'disable_toasts', str(self.disable_toasts_checkbox.isChecked()))
        self.config.set('Display', 'font_size', str(self.font_size_spinbox.value()))
        self.config.set('Display', 'vsync', str(self.vsync_checkbox.isChecked()))
        self.config.set('Display', 'high_dpi_scaling', str(self.dpi_scaling_checkbox.isChecked()))
        self.config.set('Display', 'big_toolbar_buttons', str(self.big_toolbar_buttons_checkbox.isChecked()))
        
        # Play Mode settings
        self.config.set('Display', 'show_hud', str(self.show_hud_checkbox.isChecked()))
        
        if not self.config.has_section('Settings'): 
            self.config.add_section('Settings')
        self.config.set('Settings', 'physics', str(self.physics_checkbox.isChecked()))

        # Controls settings
        if not self.config.has_section('Controls'): 
            self.config.add_section('Controls')
        self.config.set('Controls', 'invert_mouse', str(self.invert_mouse_checkbox.isChecked()))
        self.config.set('Controls', 'MiddleClickDrag', str(self.middle_click_drag_checkbox.isChecked()))

    def _restart_application(self):
        """Restart the application."""
        from PyQt5.QtWidgets import QApplication
        
        # Get the executable and arguments
        python = sys.executable
        script = sys.argv[0]
        args = sys.argv[1:]
        
        # Close the main window without triggering save prompts
        if self.main_window:
            # Disconnect any close event handlers that might interfere
            self.main_window.close()
        
        # Restart using os.execl (replaces current process)
        os.execl(python, python, script, *args)