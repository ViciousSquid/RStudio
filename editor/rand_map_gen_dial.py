# RStudio/editor/rand_map_gen_dial.py

import tkinter as tk
from tkinter import ttk, messagebox
import numpy as np

# Corrected import: Use relative import for rand_map_gen
from .rand_map_gen import generate

class RandomMapGeneratorDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Generate Random Map")
        self.geometry("300x250")
        self.grab_set() # Make the dialog modal
        self.result = False # To store if user clicked OK

        self.generated_brushes = []
        self.generated_things = []

        self._setup_ui()

    def _setup_ui(self):
        # --- Settings Frame ---
        settings_frame = ttk.LabelFrame(self, text="Map Settings")
        settings_frame.pack(padx=10, pady=10, fill="x")

        # Map Size
        ttk.Label(settings_frame, text="Map Size (e.g., 64x64):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.size_var = tk.StringVar(value="64,64")
        ttk.Entry(settings_frame, textvariable=self.size_var).grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # Density
        ttk.Label(settings_frame, text="Wall Density (0-1):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.density_var = tk.DoubleVar(value=0.5)
        ttk.Scale(settings_frame, from_=0, to=1, orient="horizontal", resolution=0.01, variable=self.density_var).grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        # Smoothing Iterations
        ttk.Label(settings_frame, text="Smoothing Iterations:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.smooth_iter_var = tk.IntVar(value=5)
        ttk.Entry(settings_frame, textvariable=self.smooth_iter_var).grid(row=2, column=1, padx=5, pady=5, sticky="ew")

        settings_frame.grid_columnconfigure(1, weight=1)

        # --- Buttons ---
        button_frame = ttk.Frame(self)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="Generate", command=self.on_generate).pack(side="left", padx=5)
        ttk.Button(button_frame, text="Cancel", command=self.on_cancel).pack(side="left", padx=5)

    def on_generate(self):
        try:
            size_str = self.size_var.get().split(',')
            map_width = int(size_str[0].strip())
            map_height = int(size_str[1].strip())
            density = self.density_var.get()
            smooth_iter = self.smooth_iter_var.get()

            if map_width <= 0 or map_height <= 0:
                messagebox.showerror("Input Error", "Map size must be positive integers.")
                return
            if not (0 <= density <= 1):
                messagebox.showerror("Input Error", "Wall density must be between 0 and 1.")
                return
            if smooth_iter < 0:
                messagebox.showerror("Input Error", "Smoothing iterations cannot be negative.")
                return

            # Generate the map using the generate function from rand_map_gen
            generated_map, player_start_pos = generate(map_width, map_height, density, smooth_iter)

            self.generated_brushes = []
            self.generated_things = []

            # Convert generated_map to brushes
            for y in range(map_height):
                for x in range(map_width):
                    if generated_map[y, x] == 1: # Assuming 1 is a wall
                        # Create a brush for each wall segment
                        # Assuming grid_size is 64 for simplicity, adjust as needed
                        brush_size = [64, 64, 64] # x, y, z size
                        brush_pos = [x * brush_size[0], 0, y * brush_size[2]] # x, y, z position
                        
                        self.generated_brushes.append({
                            'pos': brush_pos,
                            'size': brush_size,
                            'operation': 'add',
                            'properties': {}
                        })
            
            # Add player start thing
            if player_start_pos:
                # Assuming player_start_pos is in grid coordinates [x, y_grid]
                # Convert to world coordinates and adjust Y for player height
                player_world_pos = [player_start_pos[0] * 64, 128, player_start_pos[1] * 64]
                self.generated_things.append({
                    'pos': player_world_pos,
                    'type': 'PlayerStart',
                    'properties': {}
                })

            self.result = True
            self.destroy()

        except ValueError:
            messagebox.showerror("Input Error", "Please enter valid numbers for all fields.")
        except Exception as e:
            messagebox.showerror("Generation Error", f"An error occurred during map generation: {e}")

    def on_cancel(self):
        self.result = False
        self.destroy()