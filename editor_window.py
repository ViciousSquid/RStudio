# RStudio/editor_window.py

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import numpy as np

from editor.view_2d import View2D
from engine.qt_game_view import QtGameView
from editor.property_editor import PropertyEditor
from editor.map_launcher import MapLauncher
from editor.rand_map_gen_dial import RandomMapGeneratorDialog
from editor.lights import LightsFrame
from editor.things import Thing, Light, PlayerStart
from editor.SettingsWindow import SettingsWindow

class EditorWindow(tk.Toplevel):
    def __init__(self, master=None):
        super().__init__(master)
        self.title("R-Studio Editor")
        self.geometry("1200x800")

        self.brushes = []
        self.things = []
        self.lights = []
        self.selected_object = None # Can be a brush or a thing
        self.selected_light_index = -1 # Used for lights list management, not part of selected_object

        self.last_saved_map_path = None

        self._setup_ui()
        self._setup_key_bindings()

        self.game_view.set_editor(self) # Pass self (EditorWindow) to QtGameView
        self.property_editor.set_editor(self) # Pass self to PropertyEditor
        self.map_launcher.set_editor(self) # Pass self to MapLauncher
        self.lights_frame.editor = self # Ensure lights frame has editor reference
        self.things_frame.editor = self # Ensure things frame has editor reference

        self.load_default_map()
        self.update_views()

    def _setup_ui(self):
        # Create a main pane for horizontal division
        self.main_pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True)

        # Left pane for 2D views and property editor
        self.left_pane = ttk.PanedWindow(self.main_pane, orient=tk.VERTICAL)
        self.main_pane.add(self.left_pane, weight=1)

        # Notebook for 2D views
        self.view_notebook = ttk.Notebook(self.left_pane)
        self.left_pane.add(self.view_notebook, weight=3)

        self.view_top = View2D(self.view_notebook, self, 'top')
        self.view_front = View2D(self.view_notebook, self, 'front')
        self.view_side = View2D(self.view_notebook, self, 'side')

        self.view_notebook.add(self.view_top, text="Top (X-Z)")
        self.view_notebook.add(self.view_front, text="Front (Z-Y)")
        self.view_notebook.add(self.view_side, text="Side (X-Y)")

        # Property Editor and Object List
        self.property_editor_frame = ttk.Frame(self.left_pane)
        self.left_pane.add(self.property_editor_frame, weight=2)

        self.property_editor_notebook = ttk.Notebook(self.property_editor_frame)
        self.property_editor_notebook.pack(fill="both", expand=True)

        # Brushes/Things List
        self.object_list_frame = ttk.LabelFrame(self.property_editor_notebook, text="Objects")
        self.property_editor_notebook.add(self.object_list_frame, text="Objects")
        
        self.object_listbox = tk.Listbox(self.object_list_frame, exportselection=False)
        self.object_listbox.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        self.object_listbox.bind("<<ListboxSelect>>", self.on_object_selection)

        obj_button_frame = ttk.Frame(self.object_list_frame)
        obj_button_frame.pack(side="right", fill="y", padx=(0, 5))
        ttk.Button(obj_button_frame, text="+Brush", command=self.add_brush).pack(pady=2)
        ttk.Button(obj_button_frame, text="+Thing", command=self.add_thing).pack(pady=2)
        ttk.Button(obj_button_frame, text="-", command=self.delete_selected_object).pack(pady=2)

        # Property Editor
        self.property_editor = PropertyEditor(self.property_editor_notebook, self)
        self.property_editor_notebook.add(self.property_editor, text="Properties")

        # Lights Editor
        self.lights_frame = LightsFrame(self.property_editor_notebook, self)
        self.property_editor_notebook.add(self.lights_frame, text="Lights")

        # Things Editor (for specific things properties)
        self.things_frame = ThingsFrame(self.property_editor_notebook, self)
        self.property_editor_notebook.add(self.things_frame, text="Things")


        # Right pane for 3D view and tools
        self.right_pane = ttk.PanedWindow(self.main_pane, orient=tk.VERTICAL)
        self.main_pane.add(self.right_pane, weight=1)

        # 3D Game View
        self.game_view = QtGameView(self)
        self.right_pane.add(self.game_view, weight=3)

        # Map Launcher (Tools)
        self.map_launcher = MapLauncher(self.right_pane, self)
        self.right_pane.add(self.map_launcher, weight=1)

        self._create_menu()

    def _create_menu(self):
        self.menubar = tk.Menu(self)
        self.config(menu=self.menubar)

        file_menu = tk.Menu(self.menubar, tearoff=0)
        file_menu.add_command(label="New Map", command=self.new_map)
        file_menu.add_command(label="Open Map...", command=self.open_map)
        file_menu.add_command(label="Save Map", command=self.save_map)
        file_menu.add_command(label="Save Map As...", command=self.save_map_as)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.quit)
        self.menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = tk.Menu(self.menubar, tearoff=0)
        edit_menu.add_command(label="Undo", command=self.undo, accelerator="Ctrl+Z")
        edit_menu.add_command(label="Redo", command=self.redo, accelerator="Ctrl+Y")
        self.menubar.add_cascade(label="Edit", menu=edit_menu)

        tools_menu = tk.Menu(self.menubar, tearoff=0)
        tools_menu.add_command(label="Generate Random Map...", command=self.open_random_map_generator)
        self.menubar.add_cascade(label="Tools", menu=tools_menu)

        view_menu = tk.Menu(self.menubar, tearoff=0)
        view_menu.add_command(label="Settings...", command=self.open_settings)
        self.menubar.add_cascade(label="View", menu=view_menu)

    def _setup_key_bindings(self):
        self.bind("<Control-z>", lambda event: self.undo())
        self.bind("<Control-y>", lambda event: self.redo())

    def update_views(self):
        self.view_top.update()
        self.view_side.update()
        if self.game_view:
            self.game_view.repaint() # Changed from .update() to .repaint()
        self.update_object_list()
        self.property_editor.update_properties_ui()
        self.lights_frame.update_light_list() # Ensure lights list is updated on view refresh
        self.things_frame.update_thing_list() # Ensure things list is updated on view refresh

    def update_object_list(self):
        self.object_listbox.delete(0, tk.END)
        for i, brush in enumerate(self.brushes):
            self.object_listbox.insert(tk.END, f"Brush {i+1}")
            if brush == self.selected_object:
                self.object_listbox.selection_set(i)
                self.object_listbox.activate(i)
        
        # Add things after brushes, adjusting index
        brush_count = len(self.brushes)
        for i, thing in enumerate(self.things):
            self.object_listbox.insert(tk.END, f"Thing {i+1} ({thing['type']})")
            if thing == self.selected_object:
                self.object_listbox.selection_set(brush_count + i)
                self.object_listbox.activate(brush_count + i)

    def on_object_selection(self, event):
        selected_indices = self.object_listbox.curselection()
        if selected_indices:
            index = selected_indices[0]
            if index < len(self.brushes):
                self.set_selected_object(self.brushes[index])
            else:
                self.set_selected_object(self.things[index - len(self.brushes)])
        else:
            self.set_selected_object(None)

    def set_selected_object(self, obj):
        self.selected_object = obj
        self.game_view.selected_object = obj # Inform game_view about selected object
        self.view_top.selected_object = obj
        self.view_front.selected_object = obj
        self.view_side.selected_object = obj
        self.update_views()

    def select_light(self, index):
        if 0 <= index < len(self.lights):
            self.selected_light_index = index
            self.game_view.selected_light_index = index # Inform game_view about selected light
        else:
            self.selected_light_index = -1
            self.game_view.selected_light_index = -1
        self.update_views() # This should cause redraw for highlighting

    def add_brush(self):
        new_brush = {'pos': [0, 0, 0], 'size': [64, 64, 64], 'operation': 'add', 'properties': {}}
        self.brushes.append(new_brush)
        self.set_selected_object(new_brush)
        self.update_views()

    def add_thing(self):
        new_thing = {'pos': [0,0,0], 'type': 'PlayerStart', 'properties': {}}
        self.things.append(new_thing)
        self.set_selected_object(new_thing)
        self.update_views()

    def add_light(self):
        new_light = {'pos': [0, 200, 0], 'color': [1.0, 1.0, 1.0], 'intensity': 1.0}
        self.lights.append(new_light)
        self.lights_frame.update_light_list() # Update listbox specifically
        self.update_views()

    def delete_selected_object(self):
        if self.selected_object:
            if self.selected_object in self.brushes:
                self.brushes.remove(self.selected_object)
            elif self.selected_object in self.things:
                self.things.remove(self.selected_object)
            self.set_selected_object(None)
            self.update_views()

    def delete_light(self, index):
        if 0 <= index < len(self.lights):
            del self.lights[index]
            self.lights_frame.update_light_list() # Update listbox specifically
            self.update_views()

    def new_map(self):
        if messagebox.askyesno("New Map", "Are you sure you want to create a new map? Unsaved changes will be lost."):
            self.brushes = []
            self.things = []
            self.lights = []
            self.selected_object = None
            self.last_saved_map_path = None
            self.game_view.reset_camera() # Reset camera for new map
            self.update_views()

    def load_map_from_path(self, path):
        try:
            with open(path, 'r') as f:
                data = json.load(f)
                self.brushes = data.get('brushes', [])
                self.things = data.get('things', [])
                self.lights = data.get('lights', [])
                # Convert light colors from hex to float RGB if needed (for older formats)
                for light in self.lights:
                    if isinstance(light['color'], str) and light['color'].startswith('#'):
                        hex_color = light['color'].lstrip('#')
                        light['color'] = [int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4)]
                
                self.last_saved_map_path = path
                self.set_selected_object(None) # Deselect anything previously selected
                self.lights_frame.update_light_list() # Reload lights list
                self.things_frame.update_thing_list() # Reload things list
                self.game_view.reset_camera() # Reset camera for new map
                self.update_views()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load map: {e}")

    def load_default_map(self):
        # This will assume a default.json is present, used at startup
        # You might want to make this path configurable or more robust
        default_map_path = "maps/default.json" 
        self.load_map_from_path(default_map_path)


    def open_map(self):
        path = filedialog.askopenfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if path:
            self.load_map_from_path(path)

    def save_map(self):
        if self.last_saved_map_path:
            self._do_save(self.last_saved_map_path)
        else:
            self.save_map_as()

    def save_map_as(self):
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")])
        if path:
            self._do_save(path)
            self.last_saved_map_path = path

    def _do_save(self, path):
        try:
            # Ensure light colors are saved as float RGB
            serializable_lights = []
            for light in self.lights:
                serializable_lights.append({
                    'pos': light['pos'],
                    'color': light['color'],
                    'intensity': light['intensity']
                })

            data = {
                'brushes': self.brushes,
                'things': self.things,
                'lights': serializable_lights
            }
            with open(path, 'w') as f:
                json.dump(data, f, indent=4)
            messagebox.showinfo("Save Map", f"Map saved to {path}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save map: {e}")

    def undo(self):
        # Placeholder for undo logic
        messagebox.showinfo("Undo", "Undo functionality not yet implemented.")

    def redo(self):
        # Placeholder for redo logic
        messagebox.showinfo("Redo", "Redo functionality not yet implemented.")

    def open_random_map_generator(self):
        dialog = RandomMapGeneratorDialog(self)
        if dialog.result: # If user clicked OK
            # Replace current brushes/things with generated ones
            self.brushes = dialog.generated_brushes
            self.things = dialog.generated_things
            self.lights = [] # Clear lights for new random map
            self.set_selected_object(None)
            self.last_saved_map_path = None
            self.game_view.reset_camera()
            self.update_views()

    def open_settings(self):
        settings_window = SettingsWindow(self)
        settings_window.grab_set() # Make it modal
        self.wait_window(settings_window)
        # Settings might affect rendering (e.g., brush display mode), so update
        self.update_views()