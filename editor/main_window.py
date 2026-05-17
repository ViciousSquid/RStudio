import sys
import json
import os
import subprocess
import random
import numpy as np
import configparser
import math
import copy
import time


from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QMessageBox, QFileDialog, QDialog, QWidget, QLabel, QVBoxLayout,
    QGraphicsOpacityEffect, QInputDialog, QColorDialog, QProgressDialog, QAction, QToolBar, QDockWidget
)
from PyQt5.QtWidgets import QShortcut
from PyQt5.QtCore import Qt, QByteArray, QTimer, QPropertyAnimation, QEasingCurve, QRect, QPoint, pyqtSignal
from PyQt5.QtGui import QKeySequence, QPixmap, QCursor, QColor

from editor.things import Light, PlayerStart, Thing, Pickup, Monster, Model, update_all_counters_from_entities
from editor.SettingsWindow import SettingsWindow
from editor.ui import Ui_MainWindow, GenerateTilemapDialog
from engine.constants import TILE_SIZE, WALL_TILE, FLOOR_TILE
from editor.view_2d import View2D
from editor.editor_state import EditorState
from editor.terrain_editor import TerrainEditorWindow
from engine.terrain import Terrain
from editor.debug_console import DebugConsole, CommandInput, debug_log
from editor.console_commands import ConsoleCommandHandler


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        # CRITICAL: Remove Qt.SubWindow to use parent coordinates
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAlignment(Qt.AlignCenter)
        self.hide()
        
        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        
        self.anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.anim.setDuration(600)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.fade_out)
        
        self.current_toast_id = None

    def update_position(self):
        if not self.isVisible() or not self.parentWidget():
            return
            
        parent = self.parentWidget()
        # Calculate horizontal center
        x = max(0, (parent.width() - self.width()) // 2)
        
        # FIX: Remove the -60 offset to align with the bottom status bar area.
        # parent.height() represents the absolute bottom of the MainWindow.
        y = parent.height() - self.height()
        
        self.move(x, y)
        self.raise_()  # Ensures it stays above the Status Bar widgets

    def show_message(self, text, parent_widget, is_error=False, duration=None, 
                     is_tooltip=False, toast_id=None):
        """Show toast notification with STRICT bottom-middle positioning."""
        if is_tooltip:
            bg_color = "#2b2b2b"
        elif is_error:
            bg_color = "#8B0000"
        else:
            bg_color = "#2E6F40"
        
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {bg_color};
                color: white;
                padding: 10px 20px;
                border-radius: 5px;
                font-weight: bold;
                font-size: 14px;
            }}
        """)
        
        self.setText(text)
        self.adjustSize()
        self.update_position()  # Force immediate positioning
        
        self.show()
        self.raise_()
        
        self.opacity_effect.setOpacity(0)
        self.anim.setDirection(QPropertyAnimation.Forward)
        self.anim.setStartValue(0)
        self.anim.setEndValue(1)
        self.anim.start()
        
        self.current_toast_id = toast_id
        
        if duration == 0:
            self.timer.stop()
        else:
            final_duration = duration if duration is not None else (4000 if is_error else 2500)
            self.timer.start(final_duration)

    def hide_toast(self, toast_id=None):
        """Hide toast, optionally only if matching ID."""
        if self.isVisible():
            if toast_id is not None and self.current_toast_id != toast_id:
                return
            self.current_toast_id = None
            self.fade_out()

    def fade_out(self):
        self.anim.setDirection(QPropertyAnimation.Backward)
        self.anim.setEndValue(0)
        self.anim.start()
        

class MainWindow(QMainWindow):
    load_level_signal = pyqtSignal(str)
    def __init__(self, root_dir):
        super().__init__()
        self.root_dir = root_dir
        self.debug_console = None
        self.key_bindings = {}

        self.config = configparser.ConfigParser()
        self.config_path = 'settings.ini'
        self.load_config()

        self.load_key_bindings()

        self.unsaved_changes = False
        self.file_path = None
        self.recent_files = []
        self.load_level_signal.connect(self.load_level_file)

        self.setWindowTitle("Fio")
        self.setGeometry(100, 100, 1600, 900)
        self.setMinimumSize(1280, 800)
        self.state = EditorState()
        self.load_recent_files()
        
        # Initialize selected_objects list for multi-selection support
        if not hasattr(self.state, 'selected_objects'):
            self.state.selected_objects = []
        if not hasattr(self.state, 'selected_object'):
            self.state.selected_object = None
            
        self.keys_pressed = set()
        self._brush_clipboard = None  # For Ctrl+C / Ctrl+V brush copy-paste
        self.grid_visible = True
        self.preview_timer = QTimer()
        self.preview_timer.timeout.connect(self.update_mover_preview)
        self.preview_data = {} 
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.update_recent_files_menu()
        self.setup_package_actions() 
        self.update_title()
        
        QTimer.singleShot(0, self.reposition_overlays)
        self.ctrl_tab_shortcut = QShortcut(QKeySequence("Ctrl+Tab"), self)
        self.ctrl_tab_shortcut.activated.connect(self.cycle_2d_view)
        self.setFocus()
        self.update_global_font()
        self.load_layout()
        
        self.terrain = None
        self.terrain_editor_window = None

        # debug_console is embedded in the properties tab widget (created in setupUi)
        self.debug_console = DebugConsole.get_instance(self)
        # --- Connect the command_issued signal to the command handler ---
        self.console_handler = ConsoleCommandHandler(self)
        self.debug_console.command_issued.connect(self.console_handler.handle_command)

        # --- Play-mode console overlay (Quake-style drop-down input) ---
        self._create_play_console_overlay()

        # If configured, switch to the Debug Console tab on startup
        if self.config.getboolean('Display', 'always_show_io_debug', fallback=False):
            if hasattr(self, 'properties_tab_widget'):
                idx = self.properties_tab_widget.indexOf(self.debug_console)
                self.properties_tab_widget.setCurrentIndex(idx)

        self.ui.action_asset_browser.triggered.connect(self.toggle_asset_browser)

        # Enable sysmon at launch if configured
        if self.config.getboolean('Display', 'always_show_sysmon', fallback=False):
            self.view_3d.debug_mode_active = True
            self.view_3d.sysmon_expanded = True

        self.show_logic_links = True
        
        # Tooltips
        self.camera_movement_learned = self.config.getboolean('Tooltips', 'camera_movement_learned', fallback=False)
        self.startup_tooltip_shown = False
        self.tooltip_tips = [
            "Right-click + WASD: Move camera",
            "Mouse wheel: Zoom in/out",
            "Ctrl+Tab: Cycle 2D views",
            "Space: Clone selected brush/object",
            "H: Hide selected, Shift+H: Unhide all",
            "Delete: Remove selected brush/object",
            "Add Player Start before Play Mode",
            "Shift+Wheel on Light: Adjust radius",
            "Ctrl+Wheel on Light: Adjust intensity",
            "Ctrl+Drag from Trigger to Connect",
            "Triggers activate movers, doors, etc.",
            "F5: Enter/Exit Play Mode",
            "F3: Toggle System Monitor",
            "F4: Toggle sprite visibility",
            "F1: Toggle connection lines",
            "Ctrl+Click: Multi-select",
            "Ctrl+C/V: Copy & Paste brushes",
            "T: Toggle Asset Browser",
        ]
        self.last_tooltip_time = 0
        self.tooltip_interval = 30  # Seconds between occasional tooltips
        
        # Timer for occasional tooltips
        self.tooltip_timer = QTimer(self)
        self.tooltip_timer.timeout.connect(self._check_occasional_tooltip)
        self.tooltip_timer.start(10000)  # Check every 10 seconds (tooltip_interval throttles display)
        
        # Track right-click state for camera movement detection
        self.right_mouse_held = False
        self.view_3d.installEventFilter(self)
        
        # Show startup tooltip after window is shown
        QTimer.singleShot(1500, self._show_startup_tooltip)
        
        # Autosave Timer
        self.autosave_timer = QTimer(self)
        self.autosave_timer.timeout.connect(self.autosave)
        self.setup_autosave()

    def update_title(self):
        """Updates window title with filename and dirty status."""
        fname = os.path.basename(self.file_path) if self.file_path else "Untitled"
        dirty_marker = "*" if self.unsaved_changes else ""
        self.setWindowTitle(f"Fio - {fname} {dirty_marker}")

    def load_key_bindings(self):
        if self.config.has_section('KeyBindings'):
            for key, command in self.config.items('KeyBindings'):
                self.key_bindings[key] = command

    def save_key_bindings(self):
        if not self.config.has_section('KeyBindings'):
            self.config.add_section('KeyBindings')
        else:
            self.config.remove_section('KeyBindings')
            self.config.add_section('KeyBindings')
        for key, command in self.key_bindings.items():
            self.config.set('KeyBindings', key, command)
        self.save_config()

    def set_key_binding(self, key_str, command):
        """Bind a key to a console command. Warn if key already bound and ask to overwrite."""
        from PyQt5.QtWidgets import QMessageBox

        if key_str in self.key_bindings:
            old_cmd = self.key_bindings[key_str]
            reply = QMessageBox.question(
                self,
                "Key Binding Conflict",
                f"Key '{key_str}' is already bound to:\n\n  {old_cmd}\n\nOverwrite?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return False

        self.key_bindings[key_str] = command
        self.save_key_bindings()
        return True

    def mark_as_modified(self):
        """Mark the project as having unsaved changes."""
        if not self.unsaved_changes:
            self.unsaved_changes = True
            self.update_title()

    def check_unsaved_changes(self):
        """
        Checks for unsaved changes. Returns True if it's safe to proceed 
        (changes saved, discarded, or no changes), False if canceled.
        """
        if not self.unsaved_changes:
            return True
            
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Unsaved Changes")
        msg.setText("You have unsaved changes.")
        msg.setInformativeText("Do you want to save your changes?")
        msg.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Save)
        
        ret = msg.exec_()
        
        if ret == QMessageBox.Save:
            self.save_level()
            # If save failed (user cancelled file dialog), unsaved is still True
            return not self.unsaved_changes 
        elif ret == QMessageBox.Discard:
            self.unsaved_changes = False
            return True
        else: # Cancel
            return False

    def load_recent_files(self):
        # Ensure the list exists by default (fixes AttributeError on first run)
        self.recent_files = [] 

        if self.config.has_section('History') and self.config.has_option('History', 'recent_files'):
            try:
                raw_data = self.config.get('History', 'recent_files')
                if raw_data:
                    self.recent_files = json.loads(raw_data)
            except Exception:
                # Fallback to empty list on JSON error
                self.recent_files = []

    def save_recent_files(self):
        if not self.config.has_section('History'):
            self.config.add_section('History')
        self.config.set('History', 'recent_files', json.dumps(self.recent_files))
        self.save_config()

    def add_recent_file(self, file_path):
        # Normalize path
        file_path = os.path.abspath(file_path)
        
        if file_path in self.recent_files:
            self.recent_files.remove(file_path)
        
        self.recent_files.insert(0, file_path)
        
        # Keep only last 5
        if len(self.recent_files) > 5:
            self.recent_files = self.recent_files[:5]
            
        self.save_recent_files()
        self.update_recent_files_menu()

    def update_recent_files_menu(self):
        if not hasattr(self, 'recent_menu'):
            return
        
        self.recent_menu.clear()
        
        if not self.recent_files:
            dummy = QAction("No recent files", self)
            dummy.setEnabled(False)
            self.recent_menu.addAction(dummy)
            return
            
        for path in self.recent_files:
            # Check if file still exists
            if not os.path.exists(path):
                continue
                
            fname = os.path.basename(path)
            action = QAction(fname, self)
            action.setToolTip(path)
            # Use lambda with default arg to capture variable in loop
            action.triggered.connect(lambda checked, p=path: self.load_level_file(p))
            self.recent_menu.addAction(action)

    def setup_autosave(self):
        enabled = self.config.getboolean('Editor', 'autosave_enabled', fallback=True)
        interval_min = self.config.getint('Editor', 'autosave_interval', fallback=10)
        
        if enabled:
            # Convert minutes to milliseconds
            self.autosave_timer.start(interval_min * 60 * 1000)
        else:
            self.autosave_timer.stop()

    def autosave(self):
        """Background autosave to a specific autosave file."""
        if not self.unsaved_changes:
            return # Nothing to save
            
        try:
            # Ensure maps directory exists
            autosave_dir = os.path.join(self.root_dir, "maps")
            if not os.path.exists(autosave_dir):
                os.makedirs(autosave_dir)
                
            # Use a generic autosave name or derived from current file
            if self.file_path:
                base = os.path.splitext(os.path.basename(self.file_path))[0]
                save_name = f"{base}_autosave.json"
            else:
                save_name = "untitled_autosave.json"
                
            save_path = os.path.join(autosave_dir, save_name)
            
            with open(save_path, 'w') as f:
                json.dump(self.state.get_level_data(), f, indent=4)
            
            print(f"[Autosave] Saved to {save_path}")
            # Do NOT clear unsaved_changes flag on autosave
            
        except Exception as e:
            print(f"Autosave failed: {e}")


    def moveEvent(self, event):
        """Handle window move."""
        super().moveEvent(event)

    def toggle_debug_console(self):
        # --- Play mode: use the overlay instead of switching tabs ---
        if self.view_3d.play_mode:
            if self._is_play_console_visible():
                self._hide_play_console_overlay()
            else:
                self._show_play_console_overlay()
            return

        # --- Editor mode: switch tabs as before ---
        tab = self.properties_tab_widget
        console_idx = tab.indexOf(self.debug_console)
        # Ensure the properties dock is visible
        self.properties_dock.setVisible(True)
        if tab.currentIndex() == console_idx:
            # Already on the console tab — switch back to Properties
            tab.setCurrentIndex(0)
        else:
            tab.setCurrentIndex(console_idx)

    def _clear_terrain(self):
        """Remove the terrain object and clear all references."""
        # Destroy the live terrain object
        if self.terrain is not None:
            self.terrain.cleanup()
            self.terrain = None

        # Clear terrain data from editor state
        if hasattr(self.state, 'terrain_data'):
            self.state.terrain_data = None

        # Notify the 3D view's logic thread (if any) that terrain is gone
        if hasattr(self.view_3d, 'logic_thread') and self.view_3d.logic_thread:
            self.view_3d.logic_thread.set_terrain(None)

        # Close the terrain editor window if it is open
        if self.terrain_editor_window:
            self.terrain_editor_window.close()
            self.terrain_editor_window = None

        # Force a UI refresh
        self.update_all_ui()

    # ------------------------------------------------------------------
    #  Play-mode console overlay helpers
    # ------------------------------------------------------------------

    def _create_play_console_overlay(self):
        """Create a translucent command overlay for use during play mode."""
        from PyQt5.QtWidgets import QFrame, QVBoxLayout
        from PyQt5.QtGui import QFont

        # Container frame — parented to view_3d so it draws on top of the 3D view
        self._play_console_frame = QFrame(self.view_3d)
        self._play_console_frame.setStyleSheet("""
            QFrame {
                background-color: rgba(0, 0, 0, 200);
                border-bottom: 2px solid #4CAF50;
            }
        """)
        self._play_console_frame.setFixedHeight(50)
        self._play_console_frame.hide()

        layout = QVBoxLayout(self._play_console_frame)
        layout.setContentsMargins(8, 4, 8, 4)

        self._play_console_input = CommandInput(self._play_console_frame)
        self._play_console_input.setPlaceholderText("Enter command...")
        self._play_console_input.setFont(QFont("Consolas", 12))
        self._play_console_input.setStyleSheet("""
            QLineEdit {
                background-color: rgba(30, 30, 30, 220);
                color: #00FF00;
                border: 1px solid #555;
                padding: 4px 8px;
                selection-background-color: #4CAF50;
            }
        """)
        self._play_console_input.returnPressed.connect(self._on_play_console_submit)
        layout.addWidget(self._play_console_input)

    def _show_play_console_overlay(self):
        """Show the overlay and release the mouse cursor."""
        frame = self._play_console_frame
        # Stretch to full width of the 3D view
        frame.setFixedWidth(self.view_3d.width())
        frame.move(0, 0)
        frame.show()
        frame.raise_()

        # Temporarily restore cursor so the user can see what they type
        QApplication.restoreOverrideCursor()
        self.view_3d.setCursor(Qt.ArrowCursor)

        self._play_console_input.clear()
        self._play_console_input.setFocus()

    def _hide_play_console_overlay(self):
        """Hide the overlay and re-grab the mouse."""
        self._play_console_frame.hide()

        # Re-hide cursor for FPS control
        QApplication.setOverrideCursor(Qt.BlankCursor)
        self.view_3d.setFocus()

    def _is_play_console_visible(self):
        return self._play_console_frame.isVisible()

    def _on_play_console_submit(self):
        """Submit the typed command, echo it in the debug console, then hide."""
        cmd = self._play_console_input.text().strip()
        if cmd:
            self._play_console_input.add_history(cmd)
            self.console_handler.handle_command(cmd)
        self._hide_play_console_overlay()


    def cycle_2d_view(self):
        """Cycles through the 2D view tabs (Top, Side, Front) unless in play mode."""
        if self.view_3d.play_mode:
            return
        
        # Access the tab widget created in ui.py
        if hasattr(self, 'right_tabs'):
            count = self.right_tabs.count()
            if count > 0:
                next_index = (self.right_tabs.currentIndex() + 1) % count
                self.right_tabs.setCurrentIndex(next_index)

    def resizeEvent(self, event):
        """Reposition floating UI elements on window resize."""
        super().resizeEvent(event)
        if hasattr(self, 'play_button'):
            bx = self.width() // 2 - self.play_button.width() // 2
            by = 35 
            self.play_button.move(bx, by)
            self.play_button.raise_()

    def reposition_overlays(self):
        """Positions the Play button at the top middle (where the toast used to be)."""
        if hasattr(self, 'play_button'):
            # Centered horizontally, 35 pixels from the top
            px = self.width() // 2 - self.play_button.width() // 2
            py = 35 
            self.play_button.move(px, py)
            self.play_button.raise_()

    def eventFilter(self, obj, event):
        """Track right-click state on view_3d for camera movement detection."""
        from PyQt5.QtCore import QEvent
        
        if obj == self.view_3d:
            if event.type() == QEvent.MouseButtonPress:
                if event.button() == Qt.RightButton:
                    self.right_mouse_held = True
            elif event.type() == QEvent.MouseButtonRelease:
                if event.button() == Qt.RightButton:
                    self.right_mouse_held = False
        
        return super().eventFilter(obj, event)

    def toggle_asset_browser(self):
        """Toggles the visibility of the Asset Browser dock."""
        if hasattr(self, 'asset_browser_dock'):
            is_visible = self.asset_browser_dock.isVisible()
            if is_visible:
                self.asset_browser_dock.hide()
            else:
                self.asset_browser_dock.show()
                # Ensure it is raised if tabbed or floating
                self.asset_browser_dock.raise_()

    def show_toast(self, message, is_error=False, duration=None):
        """Displays a notification"""
        if self.config.getboolean('Display', 'disable_toasts', fallback=False):
            return
        
        # Set the style based on the message type
        if is_error:
            bg = "#8B0000" # Dark Red
            fg = "white"
        else:
            bg = "#2b2b2b"
            fg = "white"

        self.ui.notification_label.setStyleSheet(f"""
            background-color: {bg};
            color: {fg};
            font-weight: bold;
            padding: 2px 10px;
            border-radius: 3px;
        """)
        
        self.ui.notification_label.setText(message.upper())
        
        # Auto-clear timer
        final_duration = duration if duration is not None else (4000 if is_error else 2500)
        if final_duration > 0:
            QTimer.singleShot(final_duration, lambda: self.ui.notification_label.setText(""))

    def show_tooltip(self, message, duration=4000, toast_id=None):
        """Displays teal-styled tooltips in the same area."""
        # Re-use the toast logic with teal styling
        self.ui.notification_label.setStyleSheet("""
            background-color: #2b2b2b;
            color: white;
            font-weight: bold;
            padding: 2px 10px;
            border-radius: 3px;
        """)
        self.ui.notification_label.setText(message.upper())
        
        if duration > 0:
            QTimer.singleShot(duration, lambda: self.ui.notification_label.setText(""))

    def _show_startup_tooltip(self):
        """Show the camera movement tooltip on startup if not yet learned."""
        if self.camera_movement_learned:
            return
        if self.startup_tooltip_shown:
            return
        self.startup_tooltip_shown = True
        # Duration 0 = persistent until dismissed
        self.show_tooltip("Hold right mouse to move camera with WASD", duration=0, toast_id="camera_tip")

    def _check_occasional_tooltip(self):
        """Periodically show helpful tooltips."""
        # Don't show tooltips in play mode
        if hasattr(self, 'view_3d') and self.view_3d.play_mode:
            return
        
        # Don't interrupt the startup tooltip
        if not self.camera_movement_learned and self.startup_tooltip_shown:
            return
        
        current_time = time.time()
        if current_time - self.last_tooltip_time < self.tooltip_interval:
            return
        
        # Pick a random tip
        if self.tooltip_tips:
            tip = random.choice(self.tooltip_tips)
            self.show_tooltip(tip, duration=5000)
            self.last_tooltip_time = current_time

    def on_camera_moved_with_wasd(self):
        """Called when user holds right-click and moves camera with WASD."""
        if self.camera_movement_learned:
            return
        
        self.camera_movement_learned = True
        
        # Save to config
        if not self.config.has_section('Tooltips'):
            self.config.add_section('Tooltips')
        self.config.set('Tooltips', 'camera_movement_learned', 'True')
        self.save_config()
        
        # FIX: Clear the notification label directly instead of using self.toast
        self.ui.notification_label.setText("")

    
    def open_terrain_editor(self):
        """Open the terrain editor floating window."""
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import Qt
        
       # Create terrain if it doesn't exist
        if self.terrain is None:
            # Show progress dialog BEFORE creating terrain
            progress = QProgressDialog("Doing the thing...", None, 0, 0, self)
            
            # REVISION: Set window flags to force the dialog to the top of the Z-order
            progress.setWindowFlags(progress.windowFlags() | Qt.WindowStaysOnTopHint | Qt.Dialog)
            
            progress.setWindowTitle("Please Wait")
            
            # REVISION: ApplicationModal is more aggressive than WindowModal for staying on top
            progress.setWindowModality(Qt.ApplicationModal)
            
            progress.setMinimumDuration(0)
            progress.setMinimumWidth(300)
            progress.setMinimumHeight(100)
            progress.setStyleSheet("""
                QProgressDialog {
                    font-size: 14px;
                }
                QLabel {
                    font-size: 14px;
                    padding: 15px;
                }
            """)
            progress.show()
            QApplication.processEvents()  # Force the dialog to appear immediately
            
            try:
                # Now create the terrain (this is the slow part)
                from engine.terrain import Terrain
                self.terrain = Terrain(seed=42)
                
                # Load from state if available
                if hasattr(self.state, 'terrain_data') and self.state.terrain_data:
                    self.terrain.from_dict(self.state.terrain_data)
                
                # Setup shader in renderer
                if hasattr(self.view_3d, 'renderer') and self.view_3d.renderer:
                    self.view_3d.renderer.setup_terrain_shader(self.terrain)
                
                # Wire up terrain to logic thread for collision
                if hasattr(self.view_3d, 'logic_thread') and self.view_3d.logic_thread:
                    self.view_3d.logic_thread.set_terrain(self.terrain)
            finally:
                # Always close the progress dialog
                progress.close()

            # Store terrain data in state so the scene hierarchy can see it
            self.state.terrain_data = self.terrain.to_dict()
            self.scene_hierarchy.refresh_list()
        
        # Create or show editor window
        if self.terrain_editor_window is None:
            from editor.terrain_editor import TerrainEditorWindow
            self.terrain_editor_window = TerrainEditorWindow(self.terrain, self)
            self.terrain_editor_window.terrain_changed.connect(self.on_terrain_changed)
        
        self.terrain_editor_window.show()
        self.terrain_editor_window.raise_()
        self.terrain_editor_window.activateWindow()
    
    def on_terrain_changed(self):
        """Handle terrain changes."""
        if self.terrain:
            if hasattr(self.state, 'terrain_data'):
                self.state.terrain_data = self.terrain.to_dict()
        self.update_all_ui()

    def clone_selected_object(self):
        """Clone the selected object with offset, identical to pressing Space."""
        if not self.state.selected_object:
            return
            
        self.save_state()
        
        # Clone the object
        if isinstance(self.state.selected_object, dict):
            new_obj = copy.deepcopy(self.state.selected_object)
            self.state.brushes.append(new_obj)
        else:
            new_obj = copy.copy(self.state.selected_object)
            self.state.things.append(new_obj)
            
        # Offset based on current 2D view (uses grid size like Space key)
        current_view = self.right_tabs.currentWidget()
        if isinstance(current_view, View2D):
            axis_map = {'top': ('x', 'z'), 'side': ('y', 'z'), 'front': ('x', 'y')}
            pos_map = {'x': 0, 'y': 1, 'z': 2}
            ax1_name, ax2_name = axis_map.get(current_view.view_type, ('x', 'z'))
            offset = self.grid_size_spinbox.value()
            pos_ref = new_obj['pos'] if isinstance(new_obj, dict) else new_obj.pos
            pos_ref[pos_map[ax1_name]] += offset
            pos_ref[pos_map[ax2_name]] += offset
            
        self.set_selected_object(new_obj)
        
        # Show toast notification
        self.show_toast("Brush cloned")
        
        # Add flash effect for brushes (hot pink highlight)
        if isinstance(new_obj, dict):
            new_obj['_flash_until'] = time.time() + 0.5  # Flash for 0.5s
            
            # Set timer to remove flash and update view
            QTimer.singleShot(500, lambda: self._clear_flash(new_obj))
            
            # Immediate repaint to show flash
            self.update_all_ui()

    def _clear_flash(self, obj):
        """Clear the flash flag from an object and refresh views."""
        if isinstance(obj, dict) and '_flash_until' in obj:
            del obj['_flash_until']
            self.update_all_ui()


    def tint_selected_brush(self):
        """Open colour picker dialog to tint the selected brush - unified with property editor."""
        if not isinstance(self.state.selected_object, dict):
            self.show_toast("Select a brush first", is_error=True)
            return
        
        self.save_state()
        brush = self.state.selected_object
        
        # Get current colour (0.0-1.0 range) and convert to 0-255
        current = brush.get('colour', [0.8, 0.8, 0.8])
        current_qcolor = QColor(int(current[0] * 255), int(current[1] * 255), int(current[2] * 255))
        
        color = QColorDialog.getColor(current_qcolor, self, "Choose Brush Colour")
        if color.isValid():
            # Store as 0.0-1.0 range
            brush['colour'] = [color.redF(), color.greenF(), color.blueF()]
            self.update_all_ui()


    def add_model_to_scene(self, filepath, rotation, scale):
        self.save_state()
        
        # Optional: Try to make path relative to project root for portability
        try:
            # Assuming self.root_dir is set, otherwise just use filepath
            if hasattr(self, 'root_dir'):
                assets_dir = os.path.join(self.root_dir, "assets")
                rel_path = os.path.relpath(filepath, assets_dir)
                if not rel_path.startswith(".."):
                    filepath = os.path.join("assets", rel_path)
        except Exception:
            pass

        # FIX: Initialize with only 'pos', then set properties
        new_model = Model(pos=[0, 0, 0])
        new_model.properties['model_path'] = filepath.replace('\\', '/') # Ensure forward slashes
        new_model.properties['rotation'] = rotation
        new_model.properties['scale'] = scale
        
        # Set a default name based on filename
        model_name = os.path.splitext(os.path.basename(filepath))[0]
        new_model.properties['name'] = model_name
        
        self.state.things.append(new_model)
        self.set_selected_object(new_model)
        self.show_toast(f"Added {model_name}")

    def set_selected_object(self, obj):
        """Set a single selected object (backwards compatibility)."""
        if obj is None:
            self.state.selected_objects = []
            self.state.selected_object = None
        else:
            self.state.selected_objects = [obj]
            self.state.selected_object = obj
        
        if self.config.getboolean('Display', 'sync_selection', fallback=True):
            self.view_3d.selected_object = self.state.selected_object
        else:
            self.view_3d.selected_object = None
        self.update_all_ui()

    def set_selected_objects(self, objects):
        """Set multiple selected objects."""
        self.state.selected_objects = objects if objects else []
        # For backwards compatibility, selected_object is the first one (or None)
        self.state.selected_object = objects[0] if objects else None
        
        if self.config.getboolean('Display', 'sync_selection', fallback=True):
            self.view_3d.selected_object = self.state.selected_object
        else:
            self.view_3d.selected_object = None
        self.update_all_ui()

    def update_all_ui(self):
        self.property_editor.set_object(self.state.selected_object)
        self.scene_hierarchy.refresh_list()
        self.update_views()

    def update_views(self):
        self.view_3d.update()
        self.view_top.reset_state()
        self.view_front.reset_state()
        self.view_side.reset_state()

    def update_scene_hierarchy(self):
        self.scene_hierarchy.refresh_list(self.state.brushes, self.state.things, self.state.selected_object)
    
    def select_object(self, obj):
        self.set_selected_object(obj)

    def highlight_in_hierarchy(self, obj):
        """Highlight an object in the scene hierarchy without selecting it.
        Used for locked objects when locked_not_selectable_2d is enabled."""
        if hasattr(self.scene_hierarchy, 'highlight_item'):
            self.scene_hierarchy.highlight_item(obj)
        elif hasattr(self.scene_hierarchy, 'scroll_to_item'):
            self.scene_hierarchy.scroll_to_item(obj)

    def update_play_button_color(self):
        """Update the Play button color based on current mode."""
        if hasattr(self, 'play_button'):
            if self.view_3d.play_mode:
                # Red for play mode
                self.play_button.setStyleSheet("""
                    QPushButton {
                        background-color: #C62828;  /* Red for play mode */
                        color: white;
                        border: 1px solid #B71C1C;
                        border-radius: 3px;
                        padding: 5px 15px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #D32F2F;
                    }
                    QPushButton:pressed {
                        background-color: #B71C1C;
                    }
                """)
                self.play_button.setText("Stop")
            else:
                # Green for editor mode
                self.play_button.setStyleSheet("""
                    QPushButton {
                        background-color: #2E7D32;  /* Green for editor mode */
                        color: white;
                        border: 1px solid #1B5E20;
                        border-radius: 3px;
                        padding: 5px 15px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #388E3C;
                    }
                    QPushButton:pressed {
                        background-color: #1B5E20;
                    }
                """)
                self.play_button.setText("Play")

    @staticmethod
    def _snap_to_power_of_two(n):
        if n <= 0: return 1
        power = round(math.log2(n))
        return int(2**power)

    def start_mover_preview(self, brush):
        if not brush or not isinstance(brush, dict):
            return
        
        is_mover = brush.get('is_mover', False)
        is_door = brush.get('is_door', False)
        if not is_mover and not is_door:
            return

        # Check for path-following preview
        path_target = brush.get('path_target', '')
        if path_target:
            # Build chain of PathNodes
            chain = []
            visited = set()
            current = path_target
            while current and current not in visited:
                node = self._find_path_node_by_name(current)
                if not node:
                    break
                visited.add(current)
                chain.append(node)
                current = node.properties.get('next_node', '')
            if not chain:
                # No valid chain – fall back to oscillation preview
                self._start_oscillation_preview(brush)
                return

            self.preview_data = {
                'obj': brush,
                'is_path': True,
                'chain': chain,
                'current_idx': 0,
                'lerp_t': 0.0,
                'speed': brush.get('speed', 64.0),
                'origin': np.array(chain[0].pos, dtype=float),
                'target': np.array(chain[0].pos, dtype=float),
                'waiting': False,
                'wait_remaining': 0.0,
                'time': 0.0,
            }
            # Position the brush at the first node to start
            brush['pos'] = list(chain[0].pos)
            self.preview_timer.start(16)
            return

        # No path – use oscillation preview (original behaviour)
        self._start_oscillation_preview(brush)

    # FIX: Map door_direction strings to vectors for preview
    _DOOR_DIR_MAP = {
        'up': [0, 1, 0], 'down': [0, -1, 0],
        'north': [0, 0, 1], 'south': [0, 0, -1],
        'east': [1, 0, 0], 'west': [-1, 0, 0],
    }

    def _start_oscillation_preview(self, brush):
        """Sine-wave oscillation preview.  Reads door_* properties and
        translates them so the preview matches what _update_doors uses."""
        # For doors, the editor stores door_speed/door_distance/door_direction.
        # Translate to the engine-expected keys for the preview.
        if brush.get('is_door'):
            speed = brush.get('door_speed', brush.get('speed', 64.0))
            distance = brush.get('door_distance', brush.get('distance', 128.0))
            lip = float(brush.get('door_lip', 0.0))
            distance = max(1.0, distance - lip)
            dir_val = brush.get('door_direction', brush.get('direction', [0, 1, 0]))
            if isinstance(dir_val, str):
                direction = self._DOOR_DIR_MAP.get(dir_val, [0, 1, 0])
            else:
                direction = dir_val
        else:
            speed = brush.get('speed', 64.0)
            distance = brush.get('distance', 128.0)
            direction = brush.get('direction', [0, 1, 0])

        self.preview_data = {
            'obj': brush,
            'is_path': False,
            'original_pos': list(brush['pos']),
            'direction': np.array(direction, dtype=float),
            'distance': distance,
            'speed': speed,
            'time': 0.0,
            'is_door': brush.get('is_door', False)
        }
        norm = np.linalg.norm(self.preview_data['direction'])
        if norm > 0:
            self.preview_data['direction'] /= norm
        self.preview_timer.start(16)

    def _find_path_node_by_name(self, name):
        """Helper to locate a PathNode by name."""
        for t in self.state.things:
            from editor.things import PathNode
            if isinstance(t, PathNode) and t.properties.get('name') == name:
                return t
        return None

    def stop_mover_preview(self):
        if self.preview_timer.isActive():
            self.preview_timer.stop()
            if self.preview_data and self.preview_data.get('obj'):
                if self.preview_data.get('is_path'):
                    # Reset to the first node's position (or original)
                    chain = self.preview_data.get('chain', [])
                    if chain:
                        self.preview_data['obj']['pos'] = list(chain[0].pos)
                    else:
                        self.preview_data['obj']['pos'] = self.preview_data.get('original_pos', [0,0,0])
                else:
                    self.preview_data['obj']['pos'] = self.preview_data['original_pos']
                self.preview_data = {}
                self.update_views()
                
                # Reset buttons
                m_btn = self.property_editor._widgets.get('mover_preview_btn')
                if m_btn:
                    m_btn.blockSignals(True)
                    m_btn.setChecked(False)
                    m_btn.setText("▶ Preview Movement")
                    m_btn.blockSignals(False)
                d_btn = self.property_editor._widgets.get('door_preview_btn')
                if d_btn:
                    d_btn.blockSignals(True)
                    d_btn.setChecked(False)
                    d_btn.setText("▶ Preview Door")
                    d_btn.blockSignals(False)

    def update_mover_preview(self):
        if not self.preview_data:
            return

        dt = 0.016  # ~60 FPS
        data = self.preview_data
        brush = data['obj']

        # ------------------------------------------------------------------
        #  Path‑following preview (when is_path is True)
        # ------------------------------------------------------------------
        if data.get('is_path'):
            chain = data['chain']
            idx = data['current_idx']
            if idx >= len(chain):
                self.stop_mover_preview()
                return

            current_node = chain[idx]
            target_pos = np.array(current_node.pos, dtype=float)

            # If waiting at a node, count down and then advance
            if data['waiting']:
                data['wait_remaining'] -= dt
                if data['wait_remaining'] <= 0.0:
                    data['waiting'] = False
                    idx += 1
                    data['current_idx'] = idx
                    if idx < len(chain):
                        data['origin'] = target_pos.copy()
                        data['target'] = np.array(chain[idx].pos, dtype=float)
                        data['lerp_t'] = 0.0
                    else:
                        # End of chain reached
                        brush['pos'] = target_pos.tolist()
                        self.update_views()
                        self.stop_mover_preview()
                        return
                else:
                    # Still waiting, no movement
                    return

            # Move toward the current target node
            origin = data['origin']
            target = data['target']
            segment_vec = target - origin
            segment_len = np.linalg.norm(segment_vec)

            if segment_len < 1.0:
                # Already at the node – snap and start waiting (or advance immediately)
                data['lerp_t'] = 1.0
                brush['pos'] = target.tolist()
                wait_time = current_node.properties.get('wait_time', 0.0)
                if wait_time > 0.0:
                    data['waiting'] = True
                    data['wait_remaining'] = wait_time
                else:
                    idx += 1
                    data['current_idx'] = idx
                    if idx < len(chain):
                        data['origin'] = target.copy()
                        data['target'] = np.array(chain[idx].pos, dtype=float)
                        data['lerp_t'] = 0.0
                    else:
                        brush['pos'] = target.tolist()
                        self.update_views()
                        self.stop_mover_preview()
                        return
            else:
                # Linear interpolation with speed multiplier
                speed = data['speed'] * current_node.properties.get('speed', 1.0)
                data['lerp_t'] += (speed * dt) / segment_len
                t = min(data['lerp_t'], 1.0)
                new_pos = origin + segment_vec * t
                brush['pos'] = new_pos.tolist()

                if t >= 1.0:
                    # Arrived at the node
                    wait_time = current_node.properties.get('wait_time', 0.0)
                    if wait_time > 0.0:
                        data['waiting'] = True
                        data['wait_remaining'] = wait_time
                    else:
                        idx += 1
                        data['current_idx'] = idx
                        if idx < len(chain):
                            data['origin'] = target.copy()
                            data['target'] = np.array(chain[idx].pos, dtype=float)
                            data['lerp_t'] = 0.0
                        else:
                            brush['pos'] = target.tolist()
                            self.update_views()
                            self.stop_mover_preview()
                            return

            self.update_views()

        # ------------------------------------------------------------------
        #  Original oscillation preview (direction‑based)
        # ------------------------------------------------------------------
        else:
            data['time'] += dt
            speed = data['speed']
            distance = data['distance']
            if distance == 0:
                return

            # Sine wave between 0 and distance
            progress = (math.sin(data['time'] * (speed / distance) * math.pi - (math.pi / 2)) + 1) / 2
            current_offset = progress * distance
            movement_vector = data['direction'] * current_offset
            original_pos = np.array(data['original_pos'])
            new_pos = original_pos + movement_vector
            brush['pos'] = new_pos.tolist()
            self.update_views()

    def load_config(self):
        self.config.read(self.config_path)

    def save_config(self):
        with open(self.config_path, 'w') as configfile:
            self.config.write(configfile)

    def update_global_font(self):
        font_size = self.config.getint('Display', 'font_size', fallback=11)
        font = QApplication.font()
        font.setPointSize(font_size)
        QApplication.setFont(font)

    def show_settings_dialog(self):
        # Store old values to check for changes
        old_dpi_setting = self.config.getboolean('Display', 'high_dpi_scaling', fallback=False)
        old_font_size = self.config.getint('Display', 'font_size', fallback=10)
        old_show_caulk = self.config.getboolean('Display', 'show_caulk', fallback=True)
        old_big_toolbar_buttons = self.config.getboolean('Display', 'big_toolbar_buttons', fallback=False)
        
        # New: Autosave setting check
        old_autosave = self.config.getboolean('Editor', 'autosave_enabled', fallback=True)
        old_autosave_interval = self.config.getint('Editor', 'autosave_interval', fallback=10)

        dialog = SettingsWindow(self.config, self)
        if dialog.exec_():
            self.save_config()
            self.update_shortcuts()
            
            # Update Autosave if changed
            new_autosave = self.config.getboolean('Editor', 'autosave_enabled', fallback=True)
            new_autosave_interval = self.config.getint('Editor', 'autosave_interval', fallback=10)
            
            if new_autosave != old_autosave or new_autosave_interval != old_autosave_interval:
                self.setup_autosave()
            
            # Track which settings require restart
            restart_required = []
            
            new_font_size = self.config.getint('Display', 'font_size', fallback=10)
            if old_font_size != new_font_size:
                self.update_global_font()
                
            new_show_caulk = self.config.getboolean('Display', 'show_caulk', fallback=True)
            if old_show_caulk != new_show_caulk:
                self.update_views()
                
            new_dpi_setting = self.config.getboolean('Display', 'high_dpi_scaling', fallback=False)
            if old_dpi_setting != new_dpi_setting:
                restart_required.append("High DPI scaling")
                
            new_big_toolbar_buttons = self.config.getboolean('Display', 'big_toolbar_buttons', fallback=False)
            if old_big_toolbar_buttons != new_big_toolbar_buttons:
                restart_required.append("Toolbar button size")
            
            # Show restart message if any settings require it
            if restart_required:
                QMessageBox.information(self, "Restart Required",
                    f"The following settings have been changed:\n\n" +
                    "\n".join(f"• {setting}" for setting in restart_required) +
                    "\n\nPlease restart the application for the changes to take effect.")

    def apply_caulk_to_brush(self):
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "No Brush Selected", "Select a brush to apply caulk to.")
            return
        self.save_state()
        if 'textures' not in self.state.selected_object:
            self.state.selected_object['textures'] = {}
        for face in ['north','south','east','west','top','down']:
            self.state.selected_object['textures'][face] = 'caulk.jpg'
        self.update_views()

    def toggle_face_mode(self, active):
        """Toggles the Face Mode in the 3D view."""
        if not hasattr(self, 'view_3d'): return

        self.view_3d.face_mode_active = active
        
        # Sync button state if triggered via ESC or other means
        if hasattr(self, 'asset_browser') and hasattr(self.asset_browser, 'face_btn'):
             self.asset_browser.face_btn.blockSignals(True)
             self.asset_browser.face_btn.setChecked(active)
             self.asset_browser.face_btn.blockSignals(False)
        
        if active:
            self.show_toast("FACE MODE: Select a face to texture (Purple)", duration=3000)
            self.set_selected_object(None) # Deselect current object to clear gizmos and allow clean hover
            
            # Change cursor to indicate mode
            self.view_3d.setCursor(Qt.CrossCursor)
        else:
            self.show_toast("FACE MODE: OFF")
            self.view_3d.hovered_face_info = None # Clear highlight
            self.view_3d.setCursor(Qt.ArrowCursor)
            
        self.view_3d.update()

    def apply_texture_to_specific_face(self, brush, face_name):
        """Applies currently selected asset texture to the specific face of a brush."""
        texture_path = self.asset_browser.get_selected_filepath()
        if not texture_path:
            self.show_toast("Select a texture first", is_error=True)
            return

        texture_name = os.path.basename(texture_path)
        self.save_state()
        
        if 'textures' not in brush:
            brush['textures'] = {}

        brush['textures'][face_name] = texture_name
        self.update_views()
        self.show_toast(f"Applied to {face_name}")

    def apply_texture_to_brush(self, texture_name=None, tiled=False):
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "No Brush Selected", "Select a brush to apply the texture to.")
            return

        # Fallback if called without argument (e.g. from shortcut)
        if texture_name is None:
            texture_path = self.asset_browser.get_selected_filepath()
            if not texture_path:
                QMessageBox.warning(self, "No Texture Selected", "Select a texture from the Asset Browser.")
                return
            texture_name = os.path.basename(texture_path)

        self.save_state()
        if 'textures' not in self.state.selected_object:
            self.state.selected_object['textures'] = {}
        for face in ['south', 'north', 'west', 'east', 'down', 'top']:
            self.state.selected_object['textures'][face] = texture_name
            
        # Update tiling property
        self.state.selected_object['texture_tiling'] = tiled
        
        self.update_views()
        
        mode_str = "Tiled" if tiled else "Stretched"
        self.show_toast(f"Applied {texture_name} ({mode_str})")

    def apply_texture_to_selected_face(self, face_name):
        if not isinstance(self.state.selected_object, dict):
            return

        texture_path = self.asset_browser.get_selected_filepath()
        if not texture_path:
            QMessageBox.warning(self, "No Texture Selected", "Select a texture from the Asset Browser.")
            return

        texture_name = os.path.basename(texture_path)
        self.save_state()
        
        if 'textures' not in self.state.selected_object:
            self.state.selected_object['textures'] = {}

        self.state.selected_object['textures'][face_name] = texture_name
        self.update_views()

    def generate_collision_map(self):
        if not self.state.brushes:
            return None

        min_x_world, max_x_world = float('inf'), float('-inf')
        min_z_world, max_z_world = float('inf'), float('-inf')

        solid_brushes_exist = False
        for brush in self.state.brushes:
            if not brush.get('is_trigger', False) and not brush.get('operation') == 'subtract':
                solid_brushes_exist = True
                pos, size = np.array(brush['pos']), np.array(brush['size'])
                half_size = size / 2.0

                min_x_world = min(min_x_world, pos[0] - half_size[0])
                max_x_world = max(max_x_world, pos[0] + half_size[0])
                min_z_world = min(min_z_world, pos[2] - half_size[2])
                max_z_world = max(max_z_world, pos[2] + half_size[2])

        if not solid_brushes_exist:
            return None

        padding = TILE_SIZE * 2
        padded_min_x = min_x_world - padding
        padded_max_x = max_x_world + padding
        padded_min_z = min_z_world - padding
        padded_max_z = max_z_world + padding

        min_x_tile_idx = int(math.floor(padded_min_x / TILE_SIZE))
        max_x_tile_idx = int(math.ceil(padded_max_x / TILE_SIZE))
        min_z_tile_idx = int(math.floor(padded_min_z / TILE_SIZE))
        max_z_tile_idx = int(math.ceil(padded_max_z / TILE_SIZE))

        map_width_tiles = max_x_tile_idx - min_x_tile_idx
        map_depth_tiles = max_z_tile_idx - min_z_tile_idx

        map_width_tiles = max(1, map_width_tiles)
        map_depth_tiles = max(1, map_depth_tiles)

        collision_tile_map = np.full((map_depth_tiles, map_width_tiles), FLOOR_TILE, dtype=int)

        for brush in self.state.brushes:
            if brush.get('is_trigger', False) or brush.get('operation') == 'subtract':
                continue

            pos, size = np.array(brush['pos']), np.array(brush['size'])
            half_size = size / 2.0

            brush_min_x_world = pos[0] - half_size[0]
            brush_max_x_world = pos[0] + half_size[0]
            brush_min_z_world = pos[2] - half_size[2]
            brush_max_z_world = pos[2] + half_size[2]

            brush_min_x_map_tile = int(math.floor(brush_min_x_world / TILE_SIZE) - min_x_tile_idx)
            brush_max_x_map_tile = int(math.ceil(brush_max_x_world / TILE_SIZE) - min_x_tile_idx)
            brush_min_z_map_tile = int(math.floor(brush_min_z_world / TILE_SIZE) - min_z_tile_idx)
            brush_max_z_map_tile = int(math.ceil(brush_max_z_world / TILE_SIZE) - min_z_tile_idx)

            min_x_idx_clamped = max(0, brush_min_x_map_tile)
            max_x_idx_clamped = min(map_width_tiles, brush_max_x_map_tile)
            min_z_idx_clamped = max(0, brush_min_z_map_tile)
            max_z_idx_clamped = min(map_depth_tiles, brush_max_z_map_tile)

            if min_x_idx_clamped < max_x_idx_clamped and min_z_idx_clamped < max_z_idx_clamped:
                collision_tile_map[min_z_idx_clamped:max_x_idx_clamped, min_x_idx_clamped:max_x_idx_clamped] = WALL_TILE

        return collision_tile_map


    def enter_play_mode(self):
        player_start = None
        for thing in self.state.things:
            if isinstance(thing, PlayerStart):
                player_start = thing
                break
        
        if not player_start:
            QMessageBox.warning(self, "No Player Start", "Add a Player Start object to the scene before entering play mode.")
            return

        if hasattr(self, 'mode_label'):
            self.mode_label.setText("PLAY MODE")
            self.mode_label.setStyleSheet("""
                QLabel {
                    background-color: #2E7D32;
                    color: white;
                    padding: 5px 10px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 14px;
                    border: 1px solid #1B5E20;
                }
            """)

        physics_enabled = self.config.getboolean('Settings', 'physics', fallback=True)
        self.view_3d.toggle_play_mode(player_start.pos, player_start.get_angle(), physics_enabled)
        self.view_3d.setFocus()
        
        # Update play button color
        self.update_play_button_color()
        
        #self.ui.notification_label.setText("ESC = EXIT PLAY MODE  |  F12 = FULLSCREEN")


    def show_generate_tilemap_dialog(self):
        if not self.file_path:
            self.save_level_as()
            if not self.file_path:
                QMessageBox.warning(self, "File Not Saved", "Please save the level before generating a tilemap.")
                return
        self.generate_and_save_tilemap(save_png=True)


    def generate_and_save_tilemap(self, save_png=False):
        self.save_level()

        generator_script_path = os.path.join(self.root_dir, 'tools', 'generate_tilemap.py')
        if not os.path.exists(generator_script_path):
            QMessageBox.critical(self, "Error", f"Tilemap generator script not found at:\n{generator_script_path}")
            return

        try:
            command = [sys.executable, generator_script_path, self.file_path]
            if save_png:
                command.append('--save-png')
            
            subprocess.run(command, check=True)
            QMessageBox.information(self, "Success", "Collision tilemap generated successfully.")
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "Error", f"Failed to generate tilemap.\n\nError: {e}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"An unexpected error occurred:\n{e}")

    def update_shortcuts(self):
        apply_texture_shortcut = self.config.get('Controls', 'apply_texture', fallback='Shift+T')
        if hasattr(self, 'apply_texture_action'):
            self.apply_texture_action.setShortcut(QKeySequence(apply_texture_shortcut))
        reset_layout_shortcut = self.config.get('Controls', 'reset_layout', fallback='Ctrl+Shift+R')
        if hasattr(self, 'reset_layout_action'):
            self.reset_layout_action.setShortcut(QKeySequence(reset_layout_shortcut))
        save_layout_shortcut = self.config.get('Controls', 'save_layout', fallback='Ctrl+Shift+S')
        if hasattr(self, 'save_layout_action'):
            self.save_layout_action.setShortcut(QKeySequence(save_layout_shortcut))

    def toggle_backface_culling(self, state):
        """Toggle OpenGL backface culling."""
        self.view_3d.set_backface_culling(state == Qt.Checked)

    def toggle_frustum_culling(self, state):
        """Toggle CPU frustum culling."""
        self.view_3d.set_frustum_culling(state == Qt.Checked)
    
    def toggle_system_monitor(self):
        """Toggles the debug system monitor overlay in the 3D view."""
        self.view_3d.debug_mode_active = not self.view_3d.debug_mode_active
        
        # If in play mode, we need to handle cursor visibility when toggling the menu
        if self.view_3d.play_mode:
            if self.view_3d.debug_mode_active:
                # Show cursor for menu interaction
                QApplication.restoreOverrideCursor()
                self.view_3d.setCursor(Qt.ArrowCursor)
            else:
                # Hide cursor to resume play
                center_pos = self.view_3d.mapToGlobal(self.view_3d.rect().center())
                QCursor.setPos(center_pos)
                self.view_3d.last_mouse_pos = self.view_3d.mapFromGlobal(center_pos)
                QApplication.setOverrideCursor(Qt.BlankCursor)
        
        self.view_3d.update()

    def set_grid_size(self, size):
        snapped_size = self._snap_to_power_of_two(size)
        self.grid_size_spinbox.blockSignals(True)       # sync the spinbox
        self.grid_size_spinbox.setValue(snapped_size)
        self.grid_size_spinbox.blockSignals(False)
        for view in [self.view_top, self.view_side, self.view_front, self.view_3d]:
            view.grid_size = snapped_size
        self.view_3d.update_grid()
        self.update_views()

    def set_world_size(self, size):
        snapped_size = self._snap_to_power_of_two(size)
        if snapped_size != size:
            self.world_size_spinbox.blockSignals(True)
            self.world_size_spinbox.setValue(snapped_size)
            self.world_size_spinbox.blockSignals(False)
        for view in [self.view_top, self.view_side, self.view_front, self.view_3d]:
            view.world_size = snapped_size
        self.view_3d.update_grid()
        self.update_views()

    def set_brush_display_mode(self, text):
        self.view_3d.brush_display_mode = text
        self.view_3d.update()

    def set_cull_distance(self, distance):
        self.view_3d.set_cull_distance(distance)

    def zoom_in_2d(self):
        current_view = self.right_tabs.currentWidget()
        if isinstance(current_view, View2D):
            current_view.zoom_in()

    def zoom_out_2d(self):
        current_view = self.right_tabs.currentWidget()
        if isinstance(current_view, View2D):
            current_view.zoom_out()

    def save_state(self):
        self.state.save_state()
        self.mark_as_modified() # Mark as dirty when state is saved for undo

    def undo(self):
        if self.state.undo():
            self.mark_as_modified() # Undo changes state
            self.update_all_ui()

    def redo(self):
        if self.state.redo():
            self.mark_as_modified() # Redo changes state
            self.update_all_ui()

    def set_render_mode(self, mode):
        self.view_3d.render_mode = mode
        self.update_views()

    def show_about(self):
        try:
            with open('editor/version.txt', 'r') as f:
                version = f.read().strip()
        except FileNotFoundError:
            version = "Version not found"

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("About Fio")
        
        container_widget = QWidget()
        layout = QVBoxLayout(container_widget)

        splash_label = QLabel()
        pixmap = QPixmap('assets/splash.png')
        splash_label.setPixmap(pixmap.scaled(512, 200, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(splash_label)

        version_label = QLabel(f"{version}<br>https://github.com/ViciousSquid/Fio")
        version_label.setTextFormat(Qt.RichText)
        version_label.setAlignment(Qt.AlignCenter)
        version_label.setOpenExternalLinks(True)
        layout.addWidget(version_label)
        
        msg_box.layout().addWidget(container_widget, 0, 0, 1, msg_box.layout().columnCount())
        
        msg_box.setStandardButtons(QMessageBox.Ok)

        msg_box.exec_()

    # ------------------------------------------------------------------
    #  .fiopak Export Integration
    # ------------------------------------------------------------------

    def setup_package_actions(self):
        """Add Export Package action to the File menu."""
        export_action = QAction("Export Game Package...", self)
        export_action.setShortcut("Ctrl+Shift+E")
        export_action.triggered.connect(self.export_game_package)
        self.file_menu.addAction(export_action)

    def export_game_package(self):
        """Trigger the full package export workflow — embeds in Properties dock."""
        from editor.package_dialog import PackageMetadataDialog
        from editor.package_exporter import PackageExporter

        # Determine current map path (fallback if unsaved)
        current_map = self.file_path or "maps/level_1.json"

        # ── Swap Properties tab widget for export dialog ──────────────────
        self._original_properties_widget = self.properties_tab_widget.currentWidget()
        
        self._export_dialog = PackageMetadataDialog(
            current_map,
            parent=self.properties_tab_widget,  # Parent to the tab widget itself
            close_callback=self._restore_properties_tabs
        )
        
        # Clear the tab widget and add the dialog as the only widget
        # We temporarily reparent the dialog to cover the tabs
        self.properties_tab_widget.setParent(None)  # Detach from dock
        
        # Create a container that fills the dock
        self._export_container = QWidget()
        self._export_container.setObjectName("ExportContainer")
        container_layout = QVBoxLayout(self._export_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(self._export_dialog)
        
        # Replace the tab widget in the dock
        self.properties_dock.setWidget(self._export_container)
        
        # Show the dialog
        self._export_dialog.show()
        
        # Replace the export button connection.
        # The dialog's default _on_export only validates and calls accept() —
        # it does NOT create the package. We override with actual export logic.
        self._export_dialog.export_btn.clicked.disconnect()
        self._export_dialog.export_btn.clicked.connect(
            lambda checked: self._run_export(self._export_dialog, current_map)
        )

    def _run_export(self, dialog, current_map):
        """Execute the export after dialog is accepted."""
        metadata = dialog.build_metadata()
        if not metadata:
            return
        
        metadata['map_path'] = current_map

        # Ask user where to save
        from PyQt5.QtWidgets import QFileDialog
        # Ensure packages directory exists
        packages_dir = os.path.join(self.root_dir, "packages")
        if not os.path.exists(packages_dir):
            os.makedirs(packages_dir)

        output_path, _ = QFileDialog.getSaveFileName(
            self._export_dialog,
            "Export Game Package",
            os.path.join(packages_dir, f"{metadata['title']}.fiopak"),
            "Game Packages (*.fiopak)"
        )
        if not output_path:
            return

        # Run the export pipeline
        from editor.package_exporter import PackageExporter
        exporter = PackageExporter(self.state, self.root_dir)
        
        # Pre-scan dependencies to show info in the dialog
        all_maps = exporter._collect_map_dependencies(current_map)
        dialog.set_dependency_info(len(all_maps), 0, exporter.errors)
        QApplication.processEvents()
        
        success, errors = exporter.export(output_path, metadata, self)

        # Update dialog with results
        if success:
            dialog.dep_label.setStyleSheet("color: #4CAF50; font-size: 12px; padding: 4px;")
            dialog.dep_label.setText(
                f"Export successful!\n"
                f"Maps: {len(all_maps)}\n"
                f"Saved to: {os.path.basename(output_path)}"
            )
            dialog.export_btn.setText("Done")
            dialog.export_btn.setEnabled(False)
            self.show_toast(f"Package exported: {os.path.basename(output_path)}")
        else:
            dialog.dep_label.setStyleSheet("color: #f44336; font-size: 12px; padding: 4px;")
            dialog.dep_label.setText("Export failed:\n" + "\n".join(errors[:5]))
            QMessageBox.critical(
                self._export_dialog,
                "Export Failed",
                "Errors occurred during export:\n\n" + "\n".join(errors)
            )

    def _restore_properties_tabs(self):
        """Restore the Properties / Debug Console tab widget."""
        # Remove the export container
        if hasattr(self, '_export_container') and self._export_container:
            self._export_container.setParent(None)
            self._export_container.deleteLater()
            self._export_container = None
        
        # Restore the original tab widget to the dock
        self.properties_dock.setWidget(self.properties_tab_widget)
        self.properties_tab_widget.setParent(self.properties_dock)
        self.properties_tab_widget.show()
        
        # Restore previous tab if we tracked it
        if hasattr(self, '_original_properties_widget') and self._original_properties_widget:
            idx = self.properties_tab_widget.indexOf(self._original_properties_widget)
            if idx >= 0:
                self.properties_tab_widget.setCurrentIndex(idx)
        
        self._export_dialog = None

    def new_map(self):
        # Check for unsaved changes
        if not self.check_unsaved_changes():
            return

        self._clear_terrain()
        self.state.clear_scene()
        update_all_counters_from_entities([])
        
        self.file_path = None
        self.unsaved_changes = False
        self.update_title()
        self.update_all_ui()
        self._refresh_logic_graph()

    def perform_subtraction(self):
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "Invalid Selection", "Select a brush for CSG Subtract")
            return

        self.save_state()
        
        self.state.selected_object['operation'] = 'subtract'
        subtract_brush = self.state.selected_object
        
        sub_pos = subtract_brush['pos']
        sub_size = subtract_brush['size']
        sub_min = [sub_pos[0] - sub_size[0]/2, sub_pos[1] - sub_size[1]/2, sub_pos[2] - sub_size[2]/2]
        sub_max = [sub_pos[0] + sub_size[0]/2, sub_pos[1] + sub_size[1]/2, sub_pos[2] + sub_size[2]/2]
        
        new_brushes = []
        for brush in self.state.brushes:
            if brush is subtract_brush:
                continue
                
            if brush.get('operation') == 'subtract':
                new_brushes.append(brush)
                continue
        
            pos = brush['pos']
            size = brush['size']
            brush_min = [pos[0] - size[0]/2, pos[1] - size[1]/2, pos[2] - size[2]/2]
            brush_max = [pos[0] + size[0]/2, pos[1] + size[1]/2, pos[2] + size[2]/2]
            
            if not (brush_min[0] < sub_max[0] and brush_max[0] > sub_min[0] and
                    brush_min[1] < sub_max[1] and brush_max[1] > sub_min[1] and
                    brush_min[2] < sub_max[2] and brush_max[2] > sub_min[2]):
                new_brushes.append(brush)
                continue
                
            fragments = []
            
            if brush_min[0] < sub_min[0]:
                left_max = min(brush_max[0], sub_min[0])
                if left_max - brush_min[0] > 0.01:
                    fragments.append({
                        'pos': [(brush_min[0] + left_max)/2, pos[1], pos[2]],
                        'size': [left_max - brush_min[0], size[1], size[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_max[0] > sub_max[0]:
                right_min = max(brush_min[0], sub_max[0])
                if brush_max[0] - right_min > 0.01:
                    fragments.append({
                        'pos': [(right_min + brush_max[0])/2, pos[1], pos[2]],
                        'size': [brush_max[0] - right_min, size[1], size[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_min[1] < sub_min[1]:
                bottom_max = min(brush_max[1], sub_min[1])
                x_min = max(brush_min[0], sub_min[0])
                x_max = min(brush_max[0], sub_max[0])
                if bottom_max - brush_min[1] > 0.01 and x_max - x_min > 0.01:
                    fragments.append({
                        'pos': [pos[0], (brush_min[1] + bottom_max)/2, pos[2]],
                        'size': [x_max - x_min, bottom_max - brush_min[1], size[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_max[1] > sub_max[1]:
                top_min = max(brush_min[1], sub_max[1])
                x_min = max(brush_min[0], sub_min[0])
                x_max = min(brush_max[0], sub_max[0])
                if brush_max[1] - top_min > 0.01 and x_max - x_min > 0.01:
                    fragments.append({
                        'pos': [pos[0], (top_min + brush_max[1])/2, pos[2]],
                        'size': [x_max - x_min, brush_max[1] - top_min, size[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_min[2] < sub_min[2]:
                front_max = min(brush_max[2], sub_min[2])
                x_min = max(brush_min[0], sub_min[0])
                x_max = min(brush_max[0], sub_max[0])
                y_min = max(brush_min[1], sub_min[1])
                y_max = min(brush_max[1], sub_max[1])
                if front_max - brush_min[2] > 0.01 and x_max - x_min > 0.01 and y_max - y_min > 0.01:
                    fragments.append({
                        'pos': [pos[0], pos[1], (brush_min[2] + front_max)/2],
                        'size': [x_max - x_min, y_max - y_min, front_max - brush_min[2]],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            if brush_max[2] > sub_max[2]:
                back_min = max(brush_min[2], sub_max[2])
                x_min = max(brush_min[0], sub_min[0])
                x_max = min(brush_max[0], sub_max[0])
                y_min = max(brush_min[1], sub_min[1])
                y_max = min(brush_max[1], sub_max[1])
                if brush_max[2] - back_min > 0.01 and x_max - x_min > 0.01 and y_max - y_min > 0.01:
                    fragments.append({
                        'pos': [pos[0], pos[1], (back_min + brush_max[2])/2],
                        'size': [x_max - x_min, y_max - y_min, brush_max[2] - back_min],
                        'operation': 'add',
                        'textures': brush['textures'].copy()
                    })
            
            new_brushes.extend(fragments)
        
        new_brushes.append(subtract_brush)
        self.state.brushes = new_brushes
        
        self.update_all_ui()

    def hollow_selected_brush(self):
        """Hollow out the selected brush by creating an inner subtraction brush."""
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "Invalid Selection", "Select a brush to hollow.")
            return

        outer_brush = self.state.selected_object
        
        # Check if brush is locked
        if outer_brush.get('lock', False):
            QMessageBox.warning(self, "Brush Locked", "Cannot hollow a locked brush.")
            return

        # Prompt for wall thickness (default 16)
        max_thickness = int(min(outer_brush['size']) // 2 - 1)
        thickness, ok = QInputDialog.getInt(
            self,
            "Hollow Brush",
            "Wall thickness (grid units):",
            value=16,
            min=8,  # Changed from 1 to 8
            max=max(8, max_thickness)  # Ensure at least 8
        )
        
        if not ok:
            return
        
        # Check if the brush is large enough to hollow
        min_size = min(outer_brush['size'])
        if min_size <= thickness * 2:
            QMessageBox.warning(
                self, 
                "Brush Too Small", 
                f"The brush is too small to hollow with thickness {thickness}.\n"
                f"Minimum dimension ({min_size}) must be greater than {thickness * 2}."
            )
            return

        self.save_state()
        
        # Get outer brush properties
        outer_pos = outer_brush['pos']
        outer_size = outer_brush['size']
        
        # Calculate inner brush size (reduced by thickness on each side = thickness * 2 total)
        inner_size = [
            outer_size[0] - thickness * 2,
            outer_size[1] - thickness * 2,
            outer_size[2] - thickness * 2
        ]
        
        # Inner brush has the same center position
        inner_pos = list(outer_pos)
        
        # Create inner brush with subtract operation
        inner_brush = {
            'pos': inner_pos,
            'size': inner_size,
            'operation': 'subtract',
            'textures': outer_brush.get('textures', {}).copy(),
            'name': f"{outer_brush.get('name', 'Brush')}_hollow_sub"  # Mark as temporary
        }
        
        # Add the inner brush to the scene
        self.state.brushes.append(inner_brush)
        
        # Now perform the subtraction using the inner brush
        # Store current selection
        original_selection = self.state.selected_object
        
        # Temporarily select the inner brush and perform subtraction
        self.state.selected_object = inner_brush
        self.perform_subtraction()
        
        # Remove the inner brush after subtraction (it's no longer needed)
        if inner_brush in self.state.brushes:
            self.state.brushes.remove(inner_brush)
        
        # Clear selection since the original brush is now replaced by fragments
        self.set_selected_object(None)
        
        self.show_toast(f"Hollowed with {thickness} unit walls")

    def create_room_from_brush(self):
        """Create a room by hollowing the brush and placing lights inside."""
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "Invalid Selection", "Please select a brush to convert to a room.")
            return

        outer_brush = self.state.selected_object
        
        # Check if brush is locked
        if outer_brush.get('lock', False):
            QMessageBox.warning(self, "Brush Locked", "Cannot modify a locked brush.")
            return

        # Prompt for wall thickness
        max_thickness = int(min(outer_brush['size']) // 2 - 1)
        thickness, ok = QInputDialog.getInt(
            self,
            "Create Room",
            "Wall thickness (grid units):",
            value=16,
            min=8,
            max=max(8, max_thickness)
        )
        
        if not ok:
            return
        
        # Check if the brush is large enough
        min_size = min(outer_brush['size'])
        if min_size <= thickness * 2:
            QMessageBox.warning(
                self, 
                "Brush Too Small", 
                f"The brush is too small to hollow with thickness {thickness}.\n"
                f"Minimum dimension ({min_size}) must be greater than {thickness * 2}."
            )
            return

        self.save_state()
        
        # Get outer brush properties
        outer_pos = outer_brush['pos']
        outer_size = outer_brush['size']
        
        # Store inner dimensions for light placement
        inner_width = outer_size[0] - thickness * 2
        inner_depth = outer_size[2] - thickness * 2
        inner_height = outer_size[1] - thickness * 2
        
        # Perform hollow operation
        inner_brush = {
            'pos': list(outer_pos),
            'size': [inner_width, inner_height, inner_depth],
            'operation': 'subtract',
            'textures': outer_brush.get('textures', {}).copy(),
            'name': f"{outer_brush.get('name', 'Brush')}_hollow_sub"
        }
        
        self.state.brushes.append(inner_brush)
        self.state.selected_object = inner_brush
        self.perform_subtraction()
        
        # Remove the inner brush 
        if inner_brush in self.state.brushes:
            self.state.brushes.remove(inner_brush)
        
        # Calculate number of lights needed (one per 1024x1024 area)
        # Using ceiling to ensure adequate lighting
        import math
        num_lights_x = max(1, math.ceil(inner_width / 1024))
        num_lights_z = max(1, math.ceil(inner_depth / 1024))
        
        # Calculate spacing between lights
        spacing_x = inner_width / num_lights_x if num_lights_x > 0 else 0
        spacing_z = inner_depth / num_lights_z if num_lights_z > 0 else 0
        
        # Place lights at the ceiling of the room (top of inner space)
        light_y = outer_pos[1] + thickness  # Top of inner space
        
        # Add lights
        for i in range(num_lights_x):
            for j in range(num_lights_z):
                # Calculate light position - centered in its grid cell
                x = outer_pos[0] - inner_width/2 + spacing_x/2 + i * spacing_x
                z = outer_pos[2] - inner_depth/2 + spacing_z/2 + j * spacing_z
                
                light_pos = [x, light_y, z]
                new_light = Light(pos=light_pos)
                self.state.things.append(new_light)
        
        # Update UI
        self.set_selected_object(None)
        
        # Show confirmation
        light_count = num_lights_x * num_lights_z
        self.show_toast(f"Created room with {thickness} unit walls and {light_count} light(s)")

    def rotate_selected_brush(self):
        if not isinstance(self.state.selected_object, dict):
            QMessageBox.warning(self, "Invalid Selection", "Please select a brush to rotate.")
            return

        current_view = self.right_tabs.currentWidget()
        if not isinstance(current_view, View2D):
            QMessageBox.warning(self, "Invalid View", "Select a 2D view (Top, Side, or Front) to define the rotation axis.")
            return

        self.save_state()
        size = self.state.selected_object['size']
        view_type = current_view.view_type

        if view_type == 'top':
            size[0], size[2] = size[2], size[0]
        elif view_type == 'side':
            size[1], size[2] = size[2], size[1]
        elif view_type == 'front':
            size[0], size[1] = size[1], size[0]

        self.update_all_ui()

    def toggle_trigger_display(self, checked):
        self.view_3d.show_triggers_as_solid = checked
        self.view_3d.update()

    def keyPressEvent(self, event):
        # ------------------------------------------------------------------
        # PLAY MODE HANDLING (hardcoded shortcuts first)
        # ------------------------------------------------------------------
        if self.view_3d.play_mode:
            # If the play console overlay is open, swallow all keys except
            # tilde (close it) and Escape (also close it).
            if self._is_play_console_visible():
                if event.key() in (Qt.Key_QuoteLeft, Qt.Key_Escape):
                    self._hide_play_console_overlay()
                # All other keys go to the overlay input — don't process as game input
                return

            if event.key() == Qt.Key_Escape:
                self.view_3d.toggle_play_mode(None, None)
                self.ui.notification_label.setText("")

                if getattr(self, 'is_kiosk_mode', False):
                    self.exit_kiosk_mode()
                    return

                if not self.camera_movement_learned:
                    QTimer.singleShot(500, lambda: self.show_tooltip(
                        "Hold right mouse to move camera with WASD", duration=0, toast_id="camera_tip"))
                if hasattr(self, 'mode_label'):
                    self.mode_label.setText("EDITOR MODE")
                    self.mode_label.setStyleSheet("""
                        QLabel {
                            background-color: #333333;
                            color: #888888;
                            padding: 5px 10px;
                            border-radius: 4px;
                            font-weight: bold;
                            font-size: 14px;
                            border: 1px solid #444;
                        }
                    """)
                self.setFocus()
                self.update_play_button_color()
                return

            elif event.key() == Qt.Key_F3:
                self.view_3d.show_sprites_in_play_mode = not self.view_3d.show_sprites_in_play_mode
                self.view_3d.update()
                return

            elif event.key() == Qt.Key_F1:
                self.view_3d.show_connections_in_play_mode = not getattr(self.view_3d, 'show_connections_in_play_mode', False)
                self.update_all_ui()
                return

            elif event.key() == Qt.Key_E:
                if hasattr(self.view_3d, 'game_state') and self.view_3d.game_state:
                    self.view_3d.game_state.set_use_key_pressed()
                self.keys_pressed.add(event.key())
                return

            elif event.key() == Qt.Key_QuoteLeft:  # Tilde/backtick
                self.toggle_debug_console()
                return

            else:
                # Check for user‑defined key bindings (only if console input does NOT have focus)
                console_input = self.debug_console.command_input
                if not console_input.hasFocus():
                    key_seq = QKeySequence(event.key() | int(event.modifiers()))
                    key_str = key_seq.toString()
                    if key_str in self.key_bindings:
                        command = self.key_bindings[key_str]
                        self.console_handler.handle_command(command)
                        return
                # If no binding, just record the key for later use (e.g., movement)
                self.keys_pressed.add(event.key())
                return

        # ------------------------------------------------------------------
        # EDITOR MODE HANDLING (including bindings)
        # ------------------------------------------------------------------

        # Tilde always toggles console (works in both modes)
        if event.key() == Qt.Key_QuoteLeft:
            self.toggle_debug_console()
            return

        # ESC: exit face mode or deselect
        if event.key() == Qt.Key_Escape:
            if getattr(self.view_3d, 'face_mode_active', False):
                self.toggle_face_mode(False)
                return
            if self.state.selected_object:
                self.set_selected_object(None)
                return

        # Ctrl+C: Copy selected brush/entity
        if event.key() == Qt.Key_C and event.modifiers() == Qt.ControlModifier:
            if self.state.selected_object:
                self._brush_clipboard = copy.deepcopy(self.state.selected_object)
                name = ''
                if isinstance(self._brush_clipboard, dict):
                    name = self._brush_clipboard.get('name', 'Brush')
                else:
                    name = self._brush_clipboard.properties.get('name', 'Entity')
                self.show_toast(f"Copied: {name}")
            return

        # Ctrl+V: Paste copied brush/entity
        if event.key() == Qt.Key_V and event.modifiers() == Qt.ControlModifier:
            if self._brush_clipboard is not None:
                self.save_state()
                pasted = copy.deepcopy(self._brush_clipboard)

                # Offset the pasted object so it doesn't sit exactly on top
                offset = self.grid_size_spinbox.value()
                if isinstance(pasted, dict):
                    # Give it a unique name
                    base_name = pasted.get('name', 'Brush')
                    pasted['name'] = f"{base_name}_copy"
                    pasted['pos'] = [
                        pasted['pos'][0] + offset,
                        pasted['pos'][1],
                        pasted['pos'][2] + offset,
                    ]
                    # Clear I/O connections on the copy so wires don't duplicate
                    pasted.pop('_io_connections', None)
                    pasted.pop('io_connections', None)
                    self.state.brushes.append(pasted)
                else:
                    base_name = pasted.properties.get('name', 'Entity')
                    pasted.properties['name'] = f"{base_name}_copy"
                    pasted.pos = [
                        pasted.pos[0] + offset,
                        pasted.pos[1],
                        pasted.pos[2] + offset,
                    ]
                    pasted.properties.pop('_io_connections', None)
                    pasted.properties.pop('io_connections', None)
                    self.state.things.append(pasted)

                self.set_selected_object(pasted)
                self.show_toast(f"Pasted: {base_name}")

                # Flash effect for brushes
                if isinstance(pasted, dict):
                    import time as _time
                    pasted['_flash_until'] = _time.time() + 0.5
                    QTimer.singleShot(500, lambda: self._clear_flash(pasted))
            else:
                self.show_toast("Nothing to paste", is_error=True)
            return

        # Delete key
        if self.state.selected_object and event.key() == Qt.Key_Delete:
            self.save_state()
            for obj in list(self.state.selected_objects):
                if isinstance(obj, dict):
                    if obj in self.state.brushes:
                        self.state.brushes.remove(obj)
                else:
                    if obj in self.state.things:
                        self.state.things.remove(obj)
            self.set_selected_objects([])
            return

        # H / Shift+H
        if self.state.selected_object and event.key() == Qt.Key_H:
            if event.modifiers() == Qt.ShiftModifier:
                self.unhide_all_brushes()
            elif isinstance(self.state.selected_object, dict):
                self.hide_selected_brush()
            return

        # Space: clone
        if self.state.selected_object and event.key() == Qt.Key_Space:
            self.clone_selected_object()
            return

        # G: toggle grid
        if event.key() == Qt.Key_G:
            new_state = not self.grid_visible
            self.toggle_grid(new_state)
            if hasattr(self, 'grid_btn'):
                self.grid_btn.blockSignals(True)
                self.grid_btn.setChecked(new_state)
                self.grid_btn.blockSignals(False)
            return

        # [  /  ] : decrease / increase grid size
        if event.key() == Qt.Key_BracketLeft:
            new_size = max(2, self.view_3d.grid_size // 2)
            self.set_grid_size(new_size)
            self.show_toast(f"Grid Size: {new_size}")
            return
        if event.key() == Qt.Key_BracketRight:
            new_size = min(128, self.view_3d.grid_size * 2)
            self.set_grid_size(new_size)
            self.show_toast(f"Grid Size: {new_size}")
            return

        # Camera movement lesson (WASD with right mouse held)
        if not self.camera_movement_learned and self.right_mouse_held:
            if event.key() in (Qt.Key_W, Qt.Key_A, Qt.Key_S, Qt.Key_D):
                self.on_camera_moved_with_wasd()

        # Check for user‑defined key bindings (only if console input does NOT have focus)
        console_input = self.debug_console.command_input
        if not console_input.hasFocus():
            key_seq = QKeySequence(event.key() | int(event.modifiers()))
            key_str = key_seq.toString()
            if key_str in self.key_bindings:
                command = self.key_bindings[key_str]
                self.console_handler.handle_command(command)
                return

        # If we reach here, no binding consumed the key – record it for normal editor use
        self.keys_pressed.add(event.key())
        super().keyPressEvent(event)

    def hide_selected_brush(self):
        if isinstance(self.state.selected_object, dict):
            self.save_state()
            self.state.selected_object['hidden'] = True
            self.update_all_ui()

    def unhide_all_brushes(self):
        self.save_state()
        for brush in self.state.brushes:
            if 'hidden' in brush:
                brush['hidden'] = False
        self.update_all_ui()

    def keyReleaseEvent(self, event):
        if self.view_3d.play_mode:
            if event.key() in self.keys_pressed:
                self.keys_pressed.remove(event.key())
            return # Consume the event completely in play mode

        # Editor mode key releases below
        if event.key() in self.keys_pressed:
            self.keys_pressed.remove(event.key())
        self.update_views()
        super().keyReleaseEvent(event)

    def toggle_snap_to_grid(self, state):
        enabled = state == Qt.Checked
        for view in [self.view_top, self.view_side, self.view_front]:
            view.snap_to_grid_enabled = enabled

    def toggle_grid(self, visible):
        """Toggle grid visibility in 3D view only."""
        self.grid_visible = visible
        # Update the 3D view grid
        if hasattr(self.view_3d, 'grid_visible'):
            self.view_3d.grid_visible = visible
            self.view_3d.update()

    def save_level_as(self):
        # Ensure 'filePath' is defined here
        filePath, _ = QFileDialog.getSaveFileName(self, "Save Level As", "maps", "JSON Files (*.json)")
        
        if filePath:
            self.file_path = filePath
            self.save_level()

    def save_level(self):
        if not self.file_path:
            self.save_level_as()
            return
        try:
            with open(self.file_path, 'w') as f:
                json.dump(self.state.get_level_data(), f, indent=4)
            print(f"Level saved to {self.file_path}")
            
            self.unsaved_changes = False
            self.update_title()
            self.add_recent_file(self.file_path)
            
            self.show_toast("Saved!")
        except Exception as e:
            self.show_toast(f"Error saving: {e}", is_error=True)
            print(f"Error saving level: {e}")

    def load_level(self):
        """Opens the file dialog to select a level, then loads it."""
        # 1. Check for unsaved changes first
        if not self.check_unsaved_changes():
            return

        # 2. Ask user for the file (Defines 'filePath')
        filePath, _ = QFileDialog.getOpenFileName(self, "Load Level", "maps", "JSON Files (*.json)")
        
        # 3. If the user selected a file (didn't cancel), load it
        if filePath:
            self.load_level_file(filePath)

    def load_level_file(self, filePath):
        """Loads a level. Used for both normal loading and LevelChanger."""
        try:
            print(f"[MainWindow] Loading level: {filePath}")

            # Capture play state BEFORE doing anything
            was_playing = hasattr(self.view_3d, 'play_mode') and self.view_3d.play_mode

            from engine.resource_manager import ResourceManager
            rm = ResourceManager()

            if rm.is_package_mode():
                map_data = rm.get_text_asset(filePath)
                if map_data is None:
                    raise FileNotFoundError(f"Map {filePath} not found in package.")
                level_data = json.loads(map_data)
            else:
                with open(filePath, 'r') as f:
                    level_data = json.load(f)

            # Clear current scene completely
            self.state.clear_scene()

            # --- Clear existing terrain BEFORE loading new data ---
            # This prevents leftover terrain from the previous map.
            self._clear_terrain()
            # Also clear any lingering references in the 3D view
            self.view_3d.terrain = None
            if self.view_3d.logic_thread:
                self.view_3d.logic_thread.set_terrain(None)

            # Load new data
            self.state.load_from_data(level_data)

            # Re-initialize terrain if present in the new map
            if hasattr(self.state, 'terrain_data') and self.state.terrain_data:
                if self.terrain is None:
                    from engine.terrain import Terrain
                    self.terrain = Terrain()
                self.terrain.from_dict(self.state.terrain_data)

                if hasattr(self.view_3d, 'renderer') and self.view_3d.renderer:
                    self.view_3d.renderer.setup_terrain_shader(self.terrain)

                if hasattr(self.view_3d, 'logic_thread') and self.view_3d.logic_thread:
                    self.view_3d.logic_thread.set_terrain(self.terrain)
            else:
                # No terrain in the new map – ensure it is absent from the scene
                self._clear_terrain()

            # Reset camera to PlayerStart
            player_start_pos = None
            for t in self.state.things:
                if isinstance(t, PlayerStart):
                    player_start_pos = t.pos
                    break

            if player_start_pos:
                self.view_3d.camera.pos = [
                    player_start_pos[0],
                    player_start_pos[1] + 80,
                    player_start_pos[2] + 200
                ]
                self.view_3d.camera.pitch = -20
                self.view_3d.camera.yaw = -90

            # Update file path and UI state
            self.file_path = filePath
            self.unsaved_changes = False
            self.update_title()
            self.add_recent_file(filePath)

            # Force full UI and view refresh
            self.set_selected_object(None)
            self.update_all_ui()

            # Proper, synchronous play mode restart
            if was_playing:
                print("[MainWindow] Restarting Play Mode with new level...")
                # Clean exit (avoid toggle)
                if hasattr(self, 'exit_play_mode'):
                    self.exit_play_mode()
                else:
                    self.view_3d.play_mode = False
                # Immediate re-entry (no QTimer!)
                self.enter_play_mode()

            print(f"[MainWindow] Successfully loaded {os.path.basename(filePath)}")
            self.show_toast(f"Loaded {os.path.basename(filePath)}")

            # Keep the Logic Graph in sync with the newly loaded map
            self._refresh_logic_graph()

            return True

        except Exception as e:
            print(f"ERROR loading level {filePath}: {e}")
            import traceback
            traceback.print_exc()
            self.show_toast(f"Failed to load level: {e}", is_error=True)
            return False

    def quicksave_and_launch(self):
        maps_dir = "maps"
        if not os.path.exists(maps_dir):
            os.makedirs(maps_dir)

        quicksave_path = os.path.join(maps_dir, "quick_save.json")
        try:
            with open(quicksave_path, 'w') as f:
                json.dump(self.state.get_level_data(), f, indent=4)
            print(f"Quicksave successful: {quicksave_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not quicksave level:\n{e}")
            return

        game_script_path = 'game.py'
        if not os.path.exists(game_script_path):
            QMessageBox.warning(self, "Warning", f"Could not find '{game_script_path}' to launch.")
            return
        try:
            subprocess.Popen([sys.executable, game_script_path, quicksave_path])
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not launch game:\n{e}")
            
    def save_layout(self):
        if not self.config.has_section('Layout'):
            self.config.add_section('Layout')
        self.config['Layout']['geometry'] = self.saveGeometry().toHex().data().decode()
        self.config['Layout']['state'] = self.saveState().toHex().data().decode()
        self.save_config()
        self.statusBar().showMessage("Layout saved.", 2000)

    def load_layout(self):
        if self.config.has_section('Layout') and self.config.has_option('Layout', 'geometry'):
            self.restoreGeometry(QByteArray.fromHex(self.config['Layout']['geometry'].encode()))
        if self.config.has_section('Layout') and self.config.has_option('Layout', 'state'):
            self.restoreState(QByteArray.fromHex(self.config['Layout']['state'].encode()))

    def reset_layout(self):
        self.scene_hierarchy_dock.setFloating(False)
        self.view_3d_dock.setFloating(False)
        self.right_dock.setFloating(False)
        self.properties_dock.setFloating(False)
        self.asset_browser_dock.setFloating(False) # CHANGE: Dock it
        
        self.addDockWidget(Qt.LeftDockWidgetArea, self.scene_hierarchy_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.view_3d_dock)
        
        # CHANGE: Add Asset Browser to bottom
        self.addDockWidget(Qt.BottomDockWidgetArea, self.asset_browser_dock)
        self.asset_browser_dock.setVisible(True)

        self.splitDockWidget(self.view_3d_dock, self.right_dock, Qt.Horizontal)
        self.splitDockWidget(self.right_dock, self.properties_dock, Qt.Vertical)
        
        # Resize logic
        self.resizeDocks([self.view_3d_dock, self.right_dock], [800, 600], Qt.Horizontal)
        self.resizeDocks([self.right_dock, self.properties_dock], [600, 300], Qt.Vertical)
        
        # Optional: Set initial height for bottom dock
        self.resizeDocks([self.view_3d_dock, self.asset_browser_dock], [600, 250], Qt.Vertical)

        self.statusBar().showMessage("Layout reset to default.", 2000)


    def play_game_package(self):
        """Import a .fiopak file and launch it in kiosk mode."""
        import zipfile
        import tempfile
        import shutil

        # Check for unsaved changes first
        if not self.check_unsaved_changes():
            return

        # Default to packages/ folder, fallback to root dir if empty
        packages_dir = os.path.join(self.root_dir, "packages")
        start_dir = packages_dir if os.path.exists(packages_dir) else self.root_dir

        filePath, _ = QFileDialog.getOpenFileName(
            self, "Select Game Package", start_dir, "Game Packages (*.fiopak)"
        )
        if not filePath:
            return

        temp_dir = None
        try:
            if not zipfile.is_zipfile(filePath):
                QMessageBox.critical(self, "Error", "Selected file is not a valid game package.")
                return

            # Extract package to temp directory
            temp_dir = tempfile.mkdtemp(prefix="fio_package_")
            with zipfile.ZipFile(filePath, 'r') as zf:
                zf.extractall(temp_dir)

            # Find the map JSON inside the package
            map_path = self._find_map_in_package(temp_dir)
            if not map_path:
                QMessageBox.critical(self, "Error", "No map file found in game package.")
                return

            # Try to configure ResourceManager for package assets
            try:
                from engine.resource_manager import ResourceManager
                rm = ResourceManager()
                if hasattr(rm, 'set_package_root'):
                    rm.set_package_root(temp_dir)
                elif hasattr(rm, 'load_package'):
                    rm.load_package(filePath)
            except Exception as e:
                print(f"[Package] ResourceManager setup warning: {e}")

            # Load level data
            with open(map_path, 'r') as f:
                level_data = json.load(f)

            # Clear current scene and load package map
            self.state.clear_scene()
            self._clear_terrain()
            self.state.load_from_data(level_data)

            # ── Re-initialize terrain if present in the package map ───────────
            if hasattr(self.state, 'terrain_data') and self.state.terrain_data:
                if self.terrain is None:
                    from engine.terrain import Terrain
                    self.terrain = Terrain()
                self.terrain.from_dict(self.state.terrain_data)

                if hasattr(self.view_3d, 'renderer') and self.view_3d.renderer:
                    self.view_3d.renderer.setup_terrain_shader(self.terrain)

                if hasattr(self.view_3d, 'logic_thread') and self.view_3d.logic_thread:
                    self.view_3d.logic_thread.set_terrain(self.terrain)
            else:
                # No terrain in the package map – ensure it is absent from the scene
                self._clear_terrain()
            # ─────────────────────────────────────────────────────────────────

            # Store temp dir for cleanup on application close
            self._package_temp_dir = temp_dir
            temp_dir = None  # Prevent cleanup in finally block

            # Update UI state
            self.file_path = filePath
            self.unsaved_changes = False
            self.update_title()
            self.set_selected_object(None)
            self.update_all_ui()

            # Check if user wants editor mode instead of kiosk
            launch_in_editor = self.config.getboolean('Kiosk', 'launch_in_editor', fallback=False)
            if launch_in_editor:
                # Just load the map in the editor — no kiosk, no play mode
                self.show_toast(f"Loaded package: {os.path.basename(filePath)}")
            else:
                # Hide editor chrome and launch play mode
                self.enter_kiosk_mode()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load game package:\n{e}")
            import traceback
            traceback.print_exc()
        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
    

    def _find_map_in_package(self, root_dir):
        """Find the first suitable .json map file in an extracted package."""
        best_match = None
        fallback = None
        for root, dirs, files in os.walk(root_dir):
            for f in files:
                if f.endswith('.json'):
                    filepath = os.path.join(root, f)
                    if fallback is None:
                        fallback = filepath
                    # Prefer files inside a 'maps' folder or with 'level' in the name
                    if 'maps' in root.lower() or 'level' in f.lower():
                        best_match = filepath
                        return best_match
        return best_match or fallback

    def enter_kiosk_mode(self):
        """Hide all editor UI and launch play mode fullscreen."""
        self.is_kiosk_mode = True

        # Save layout before hiding
        self.save_layout()

        # Hide menu bar and status bar
        if self.menuBar():
            self.menuBar().setVisible(False)
        self.statusBar().setVisible(False)

        # Hide all toolbars
        for toolbar in self.findChildren(QToolBar):
            toolbar.setVisible(False)

        # Hide all docks except the 3D view
        for dock in self.findChildren(QDockWidget):
            if dock is not self.view_3d_dock:
                dock.setVisible(False)

        # Ensure 3D view is visible
        self.view_3d_dock.setVisible(True)

        # Hide the floating play button
        if hasattr(self, 'play_button'):
            self.play_button.setVisible(False)

        # Hide sysmon overlay by default in kiosk mode (F3 to toggle back on)
        self.view_3d.debug_mode_active = False

        # Go fullscreen
        self.showFullScreen()

        # Launch play mode
        self.enter_play_mode()

    def exit_kiosk_mode(self, keep_play_mode=False, confirm=True):
        """Restore editor UI and exit play mode.

        Args:
            keep_play_mode: If True, stay in play mode (F12 toggle).
                            If False, also exit play mode (ESC quit).
            confirm: If True, show a "Quit? Are you sure?" dialog before
                     exiting. Only applies when keep_play_mode=False (ESC flow).
        """
        # Show confirmation dialog when quitting via ESC
        if confirm and not keep_play_mode:
            reply = QMessageBox.question(
                self,
                "Quit Game",
                "Quit game and return to editor?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                return  # User cancelled — stay in kiosk mode

        self.is_kiosk_mode = False

        # Exit play mode only if not keeping it (F12 toggle vs Escape)
        if not keep_play_mode and hasattr(self.view_3d, 'play_mode') and self.view_3d.play_mode:
            self.view_3d.toggle_play_mode(None, None)

        # Exit fullscreen
        self.showNormal()

        # Restore menu bar and status bar
        if self.menuBar():
            self.menuBar().setVisible(True)
        self.statusBar().setVisible(True)

        # Restore toolbars
        for toolbar in self.findChildren(QToolBar):
            toolbar.setVisible(True)

        # Restore all dock widgets
        for dock in self.findChildren(QDockWidget):
            dock.setVisible(True)

        # Restore play button
        if hasattr(self, 'play_button'):
            self.play_button.setVisible(True)

        # Restore saved layout
        self.load_layout()
        self.update_all_ui()

        # FIX: Update play button and mode label to reflect editor state
        self.update_play_button_color()
        if hasattr(self, 'mode_label'):
            self.mode_label.setText("EDITOR MODE")
            self.mode_label.setStyleSheet("""
                QLabel {
                    background-color: #333333;
                    color: #888888;
                    padding: 5px 10px;
                    border-radius: 4px;
                    font-weight: bold;
                    font-size: 14px;
                    border: 1px solid #444;
                }
            """)

        # If keeping play mode, recapture mouse for seamless FPS control
        if keep_play_mode and self.view_3d.play_mode:
            center_pos = self.view_3d.mapToGlobal(self.view_3d.rect().center())
            QCursor.setPos(center_pos)
            self.view_3d.last_mouse_pos = self.view_3d.mapFromGlobal(center_pos)
            QApplication.setOverrideCursor(Qt.BlankCursor)
            self.view_3d.setFocus()

    # =========================================================================
    # LOGIC GRAPH / WIZARD
    # =========================================================================

    def _refresh_logic_graph(self):
        """
        Rebuild the Logic Graph scene to match the current map.
        Called automatically after every map load and New Map.
        If the window is open it reloads immediately; if it is closed the
        stale window is discarded so the next open starts fresh.
        """
        win = getattr(self, '_logic_graph_win', None)
        if win is None:
            return
        if win.isVisible():
            win._reload()
        else:
            # Quietly discard the stale window — a new one will be built on
            # next open(), using the current editor_state automatically.
            win.close()
            self._logic_graph_win = None

    def open_logic_graph(self):
        """Open (or raise) the Logic Graph Editor window."""
        from editor.logic_graph_widget import LogicGraphWindow
        if not hasattr(self, '_logic_graph_win') or self._logic_graph_win is None:
            self._logic_graph_win = LogicGraphWindow(self.state, parent=self)
            self._logic_graph_win.applied.connect(self._on_logic_graph_applied)
        self._logic_graph_win.show()
        self._logic_graph_win.raise_()
        self._logic_graph_win.activateWindow()

    def _on_logic_graph_applied(self):
        """Called when the Logic Graph writes connections back to entities."""
        self.mark_as_modified()
        debug_log("IO", "Logic Graph applied connections to scene")

    def open_logic_wizard(self):
        """Open the Logic Wizard (guided I/O scenario setup)."""
        from editor.logic_graph_widget import LogicGraphWindow, LogicGraphScene
        from editor.logic_wizard import LogicWizard
        # Reuse the existing graph window's scene if it is already open,
        # so that wizard-added connections appear there immediately.
        if hasattr(self, '_logic_graph_win') and self._logic_graph_win is not None:
            scene  = self._logic_graph_win.get_scene()
            parent = self._logic_graph_win
        else:
            # Build a temporary scene — the wizard will still call apply_to_entities
            scene  = LogicGraphScene(self.state)
            parent = self
        wiz = LogicWizard(self.state, scene, parent=parent)
        if wiz.exec_():
            # If the graph window is not yet open, open it so the user can review
            # and press Apply to persist the connections.
            self.open_logic_graph()

    def validate_io_connections(self):
        """Check all entities for connections that point to missing targets."""
        all_names = set()
        for t in self.state.things:
            n = t.properties.get('name', '')
            if n:
                all_names.add(n)
        for b in self.state.brushes:
            n = b.get('name', '')
            if n:
                all_names.add(n)

        broken = []
        all_entities = list(self.state.things) + list(self.state.brushes)
        for entity in all_entities:
            if hasattr(entity, 'properties'):
                conns    = entity.properties.get('_io_connections', [])
                src_name = entity.properties.get('name', '?')
            else:
                conns    = entity.get('_io_connections', [])
                src_name = entity.get('name', '?')

            for c in conns:
                if isinstance(c, dict):
                    tgt     = c.get('target', '')
                    out_pin = c.get('output', '?')
                else:
                    tgt     = getattr(c, 'target_name', '')
                    out_pin = getattr(c, 'output_name', '?')
                if tgt and tgt not in all_names:
                    broken.append(f"  {src_name}.{out_pin}  →  \"{tgt}\"  (NOT FOUND)")

        if broken:
            QMessageBox.warning(
                self, "Validate Connections",
                "Broken connections found — target entity does not exist:\n\n"
                + "\n".join(broken)
            )
        else:
            total = sum(
                len(e.properties.get('_io_connections', [])
                    if hasattr(e, 'properties')
                    else e.get('_io_connections', []))
                for e in all_entities
            )
            QMessageBox.information(
                self, "Validate Connections",
                f"All {total} connection(s) are valid. ✔"
            )

    def closeEvent(self, event):
        try:
            if not self.check_unsaved_changes():
                event.ignore()
                return

            # Stop timers
            if hasattr(self, 'tooltip_timer'):
                self.tooltip_timer.stop()
            if hasattr(self, 'autosave_timer'):
                self.autosave_timer.stop()

            # Cleanup extracted package temp dir
            if hasattr(self, '_package_temp_dir') and self._package_temp_dir:
                import shutil
                shutil.rmtree(self._package_temp_dir, ignore_errors=True)

            try:
                self.save_layout()
            except Exception as e:
                print(f"save_layout failed: {e}")

            if hasattr(self, 'view_3d') and self.view_3d and self.view_3d.logic_thread:
                self.view_3d.logic_thread.stop()
                self.view_3d.logic_thread.join(timeout=1.0)

            event.accept()
        except Exception as e:
            import traceback
            traceback.print_exc()
            event.accept()


