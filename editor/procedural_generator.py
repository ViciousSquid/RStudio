import sys
import random
import heapq
import os
import math
from datetime import datetime
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox, QPushButton,
    QGroupBox, QFormLayout, QTextEdit, QCheckBox, QScrollArea, QFrame,
    QComboBox
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
CELL_SIZE = 64
CORRIDOR_WIDTH = 2
GROUND_Y = -32
FLOOR_THICK = 64
FLOOR_SURFACE = GROUND_Y + FLOOR_THICK // 2   # = 0
WALL_DEFAULT_HEIGHT = 256
ENTITY_Y_OFFSET = 32
PLAYER_SPAWN_Y_OFFSET = 96       # extra clearance so player doesn't clip through the floor

# ----------------------------------------------------------------------
# Grid and map generation
# ----------------------------------------------------------------------
class RoomObj:
    def __init__(self, cell_x, cell_y, cell_w, cell_h, world_x, world_y, world_w, world_h, center):
        self.cell_x = cell_x
        self.cell_y = cell_y
        self.cell_w = cell_w
        self.cell_h = cell_h
        self.world_x = world_x
        self.world_y = world_y
        self.world_w = world_w
        self.world_h = world_h
        self.center = center
        self.ceiling_height = random.randint(192, 320)
        self.elevation = 0

class GridMap:
    def __init__(self, width_cells, height_cells):
        self.w = width_cells
        self.h = height_cells
        self.solid = [[True for _ in range(height_cells)] for __ in range(width_cells)]
        self.rooms = []

    def carve_rect(self, cx, cy, cw, ch):
        for dx in range(cw):
            for dy in range(ch):
                x = cx + dx
                y = cy + dy
                if not (0 <= x < self.w and 0 <= y < self.h):
                    return False
                if not self.solid[x][y]:
                    return False
        for dx in range(cw):
            for dy in range(ch):
                self.solid[cx+dx][cy+dy] = False
        return True

    def add_room(self, cx, cy, cw, ch):
        if not self.carve_rect(cx, cy, cw, ch):
            return None
        room = RoomObj(
            cell_x=cx, cell_y=cy,
            cell_w=cw, cell_h=ch,
            world_x=cx * CELL_SIZE,
            world_y=cy * CELL_SIZE,
            world_w=cw * CELL_SIZE,
            world_h=ch * CELL_SIZE,
            center=(cx + cw/2, cy + ch/2)
        )
        self.rooms.append(room)
        return room

    def get_neighbors(self, x, y):
        for dx, dy in [(0,1),(1,0),(0,-1),(-1,0)]:
            nx, ny = x+dx, y+dy
            if 0 <= nx < self.w and 0 <= ny < self.h:
                yield nx, ny

    def astar(self, start, goal, extra_waypoints=0):
        if start == goal:
            return [start]
        waypoints = [start]
        if extra_waypoints > 0:
            for _ in range(extra_waypoints):
                mid_x = random.randint(min(start[0], goal[0]), max(start[0], goal[0]))
                mid_y = random.randint(min(start[1], goal[1]), max(start[1], goal[1]))
                waypoints.append((mid_x, mid_y))
        waypoints.append(goal)
        full_path = []
        for i in range(len(waypoints)-1):
            sub_path = self._astar_segment(waypoints[i], waypoints[i+1])
            if not sub_path:
                return []
            if i == 0:
                full_path.extend(sub_path)
            else:
                full_path.extend(sub_path[1:])
        return full_path

    def _astar_segment(self, start, goal):
        frontier = [(0, start)]
        came_from = {start: None}
        cost_so_far = {start: 0}
        while frontier:
            _, current = heapq.heappop(frontier)
            if current == goal:
                break
            for nxt in self.get_neighbors(*current):
                new_cost = cost_so_far[current] + 1
                if nxt not in cost_so_far or new_cost < cost_so_far[nxt]:
                    cost_so_far[nxt] = new_cost
                    priority = new_cost + abs(nxt[0]-goal[0]) + abs(nxt[1]-goal[1])
                    heapq.heappush(frontier, (priority, nxt))
                    came_from[nxt] = current
        if goal not in came_from:
            return []
        path = []
        cur = goal
        while cur:
            path.append(cur)
            cur = came_from[cur]
        path.reverse()
        return path

    def carve_path(self, cells):
        for (x, y) in cells:
            if 0 <= x < self.w and 0 <= y < self.h:
                self.solid[x][y] = False
            for dx, dy in [(1,0), (-1,0), (0,1), (0,-1)]:
                nx, ny = x+dx, y+dy
                if 0 <= nx < self.w and 0 <= ny < self.h:
                    self.solid[nx][ny] = False

    def add_dead_ends(self, count=3):
        dead_end_cells = []
        attempts = 0
        while len(dead_end_cells) < count and attempts < 200:
            candidates = []
            for x in range(self.w):
                for y in range(self.h):
                    if not self.solid[x][y]:
                        for dx, dy in [(1,0), (-1,0), (0,1), (0,-1)]:
                            nx, ny = x+dx, y+dy
                            if 0 <= nx < self.w and 0 <= ny < self.h and self.solid[nx][ny]:
                                candidates.append((x, y))
                                break
            if not candidates:
                break
            start = random.choice(candidates)
            dirs = [(1,0), (-1,0), (0,1), (0,-1)]
            random.shuffle(dirs)
            path = [start]
            cur = start
            length = random.randint(2, 5)
            for _ in range(length):
                found = False
                for dx, dy in dirs:
                    nx, ny = cur[0]+dx, cur[1]+dy
                    if 0 <= nx < self.w and 0 <= ny < self.h and self.solid[nx][ny]:
                        path.append((nx, ny))
                        cur = (nx, ny)
                        found = True
                        break
                if not found:
                    break
            if len(path) > 1:
                self.carve_path(path)
                dead_end_cells.append(path[-1])
            attempts += 1

    def connect_rooms(self):
        if len(self.rooms) < 2:
            return
        centers = [(int(r.center[0]), int(r.center[1])) for r in self.rooms]
        for i in range(len(centers)-1):
            extra = random.randint(0, 2)
            path = self.astar(centers[i], centers[i+1], extra_waypoints=extra)
            if path:
                self.carve_path(path)
            else:
                x1, y1 = centers[i]
                x2, y2 = centers[i+1]
                points = []
                dx = abs(x2 - x1)
                dy = -abs(y2 - y1)
                sx = 1 if x1 < x2 else -1
                sy = 1 if y1 < y2 else -1
                err = dx + dy
                while True:
                    points.append((x1, y1))
                    if x1 == x2 and y1 == y2:
                        break
                    e2 = 2 * err
                    if e2 >= dy:
                        err += dy
                        x1 += sx
                    if e2 <= dx:
                        err += dx
                        y1 += sy
                self.carve_path(points)
        self.add_dead_ends(count=random.randint(3, 6))

# ----------------------------------------------------------------------
# Geometry generation with nodraw optimization
# ----------------------------------------------------------------------
def generate_brushes_from_grid(grid_map, wall_tex, floor_tex):
    brushes = []
    min_wx = 0
    max_wx = grid_map.w * CELL_SIZE
    min_wz = 0
    max_wz = grid_map.h * CELL_SIZE
    margin = 512
    ground_width = (max_wx - min_wx) + margin*2
    ground_depth = (max_wz - min_wz) + margin*2
    ground_center_x = (min_wx + max_wx) / 2
    ground_center_z = (min_wz + max_wz) / 2

    ground_tex = {}
    for f in ["north","south","east","west","top","down"]:
        ground_tex[f] = floor_tex if f == "top" else "nodraw.jpg"
    brushes.append({
        "pos": [ground_center_x, GROUND_Y, ground_center_z],
        "size": [ground_width, FLOOR_THICK, ground_depth],
        "operation": "add",
        "textures": ground_tex,
        "lock": True,
        "id": "ground_plane"
    })

    ceil_tex = {}
    for f in ["north","south","east","west","top","down"]:
        ceil_tex[f] = floor_tex if f == "down" else "nodraw.jpg"
    brushes.append({
        "pos": [ground_center_x, FLOOR_SURFACE + 600, ground_center_z],
        "size": [ground_width, 64, ground_depth],
        "operation": "add",
        "textures": ceil_tex,
        "lock": True,
        "id": "global_ceiling"
    })

    cell_to_room = {}
    for room in grid_map.rooms:
        for dx in range(room.cell_w):
            for dy in range(room.cell_h):
                cell_to_room[(room.cell_x + dx, room.cell_y + dy)] = room

    for x in range(grid_map.w):
        for y in range(grid_map.h):
            if not grid_map.solid[x][y]:
                room = cell_to_room.get((x, y), None)
                ceil_h = room.ceiling_height if room else WALL_DEFAULT_HEIGHT
                world_x = (x + 0.5) * CELL_SIZE
                world_z = (y + 0.5) * CELL_SIZE
                for dx, dy, face in [(0,1,'north'), (1,0,'east'), (0,-1,'south'), (-1,0,'west')]:
                    nx, ny = x+dx, y+dy
                    if 0 <= nx < grid_map.w and 0 <= ny < grid_map.h:
                        if grid_map.solid[nx][ny]:
                            tex = {f: "nodraw.jpg" for f in ["north","south","east","west","top","down"]}
                            if face == 'north':
                                tex['south'] = wall_tex
                                pos = [world_x, FLOOR_SURFACE + ceil_h/2, world_z + CELL_SIZE/2]
                                size = [CELL_SIZE, ceil_h, 64]
                            elif face == 'south':
                                tex['north'] = wall_tex
                                pos = [world_x, FLOOR_SURFACE + ceil_h/2, world_z - CELL_SIZE/2]
                                size = [CELL_SIZE, ceil_h, 64]
                            elif face == 'east':
                                tex['west'] = wall_tex
                                pos = [world_x + CELL_SIZE/2, FLOOR_SURFACE + ceil_h/2, world_z]
                                size = [64, ceil_h, CELL_SIZE]
                            else:
                                tex['east'] = wall_tex
                                pos = [world_x - CELL_SIZE/2, FLOOR_SURFACE + ceil_h/2, world_z]
                                size = [64, ceil_h, CELL_SIZE]
                            brushes.append({
                                "pos": pos,
                                "size": size,
                                "operation": "add",
                                "textures": tex,
                                "lock": True,
                                "id": f"wall_{x}_{y}_{face}"
                            })
                    else:
                        tex = {f: "nodraw.jpg" for f in ["north","south","east","west","top","down"]}
                        if face == 'north':
                            tex['south'] = wall_tex
                            pos = [world_x, FLOOR_SURFACE + ceil_h/2, world_z + CELL_SIZE/2]
                            size = [CELL_SIZE, ceil_h, 64]
                        elif face == 'south':
                            tex['north'] = wall_tex
                            pos = [world_x, FLOOR_SURFACE + ceil_h/2, world_z - CELL_SIZE/2]
                            size = [CELL_SIZE, ceil_h, 64]
                        elif face == 'east':
                            tex['west'] = wall_tex
                            pos = [world_x + CELL_SIZE/2, FLOOR_SURFACE + ceil_h/2, world_z]
                            size = [64, ceil_h, CELL_SIZE]
                        else:
                            tex['east'] = wall_tex
                            pos = [world_x - CELL_SIZE/2, FLOOR_SURFACE + ceil_h/2, world_z]
                            size = [64, ceil_h, CELL_SIZE]
                        brushes.append({
                            "pos": pos,
                            "size": size,
                            "operation": "add",
                            "textures": tex,
                            "lock": True,
                            "id": f"wall_{x}_{y}_{face}_border"
                        })

    for room in grid_map.rooms:
        cx = room.world_x
        cz = room.world_y
        w = room.world_w
        h = room.world_h
        ceil_h = room.ceiling_height
        tex = {f: "nodraw.jpg" for f in ["north","south","east","west","top","down"]}
        tex['down'] = floor_tex
        brushes.append({
            "pos": [cx + w/2, FLOOR_SURFACE + ceil_h, cz + h/2],
            "size": [w, 64, h],
            "operation": "add",
            "textures": tex,
            "lock": True,
            "id": f"room_ceil_{room.cell_x}_{room.cell_y}"
        })

    corner_info = {}
    for x in range(grid_map.w):
        for y in range(grid_map.h):
            if grid_map.solid[x][y]:
                continue
            room = cell_to_room.get((x, y), None)
            ceil_h = room.ceiling_height if room else WALL_DEFAULT_HEIGHT
            world_x = x * CELL_SIZE
            world_z = y * CELL_SIZE
            corner_cases = [
                ( 1, 0,  0, 1,  CELL_SIZE, CELL_SIZE, 'west',  'south'),
                (-1, 0,  0, 1,  0,         CELL_SIZE, 'east',  'south'),
                ( 1, 0,  0,-1,  CELL_SIZE, 0,         'west',  'north'),
                (-1, 0,  0,-1,  0,         0,         'east',  'north'),
            ]
            for dx1, dy1, dx2, dy2, cx_off, cz_off, face1, face2 in corner_cases:
                n1x, n1y = x + dx1, y + dy1
                n2x, n2y = x + dx2, y + dy2
                s1 = (0 <= n1x < grid_map.w and 0 <= n1y < grid_map.h
                      and grid_map.solid[n1x][n1y])
                s2 = (0 <= n2x < grid_map.w and 0 <= n2y < grid_map.h
                      and grid_map.solid[n2x][n2y])
                if not (s1 and s2):
                    continue
                key = (world_x + cx_off, world_z + cz_off)
                if key not in corner_info:
                    corner_info[key] = {'ceil_h': ceil_h, 'faces': set()}
                else:
                    corner_info[key]['ceil_h'] = max(corner_info[key]['ceil_h'], ceil_h)
                corner_info[key]['faces'].add(face1)
                corner_info[key]['faces'].add(face2)

    for idx, ((corner_wx, corner_wz), info) in enumerate(corner_info.items()):
        h = info['ceil_h']
        tex = {f: "nodraw.jpg" for f in ["north", "south", "east", "west", "top", "down"]}
        for face in info['faces']:
            tex[face] = wall_tex
        brushes.append({
            "pos":       [corner_wx, FLOOR_SURFACE + h / 2, corner_wz],
            "size":      [64, h, 64],
            "operation": "add",
            "textures":  tex,
            "lock":      True,
            "id":        f"corner_pillar_{idx}"
        })

    return brushes

def random_point_in_room(room, min_dist_from_wall=0):
    # Calculate safe boundaries inside the room
    min_x = room.world_x + min_dist_from_wall
    max_x = room.world_x + room.world_w - min_dist_from_wall
    min_z = room.world_y + min_dist_from_wall
    max_z = room.world_y + room.world_h - min_dist_from_wall

    # If the room is too small, use the centre
    if min_x >= max_x or min_z >= max_z:
        return room.world_x + room.world_w / 2, room.world_y + room.world_h / 2

    x = random.uniform(min_x, max_x)
    z = random.uniform(min_z, max_z)
    return x, z

def create_map_data(params):
    world_width = params.get('world_width', 4096)
    world_height = params.get('world_height', 4096)
    grid_w = world_width // CELL_SIZE
    grid_h = world_height // CELL_SIZE
    grid = GridMap(grid_w, grid_h)

    min_room_cells = max(3, params['min_room'] // CELL_SIZE)
    max_room_cells = max(min_room_cells+2, params['max_room'] // CELL_SIZE)
    target_rooms = params['room_count']
    attempts = 0
    while len(grid.rooms) < target_rooms and attempts < 300:
        rw = random.randint(min_room_cells, max_room_cells)
        rh = random.randint(min_room_cells, max_room_cells)
        rx = random.randint(1, grid_w - rw - 1)
        ry = random.randint(1, grid_h - rh - 1)
        grid.add_room(rx, ry, rw, rh)
        attempts += 1
    grid.connect_rooms()

    brushes = generate_brushes_from_grid(grid, params['wall_tex'], params['floor_tex'])

    start_room = grid.rooms[0]
    player_x = start_room.world_x + start_room.world_w / 2
    player_z = start_room.world_y + start_room.world_h / 2
    player_y = FLOOR_SURFACE + PLAYER_SPAWN_Y_OFFSET

    gun_x = player_x + CELL_SIZE//2
    gun_z = player_z
    gun_y = FLOOR_SURFACE + ENTITY_Y_OFFSET
     # Random starting weapon
    starting_gun = random.choice(["gun1", "gun2"])

    exit_room = grid.rooms[-2] if len(grid.rooms) > 2 else grid.rooms[0]
    exit_x = exit_room.world_x + exit_room.world_w / 2
    exit_z = exit_room.world_y + exit_room.world_h / 2 + 64
    exit_y = FLOOR_SURFACE + ENTITY_Y_OFFSET

    lights = []
    for i, room in enumerate(grid.rooms):
        cx = room.world_x + room.world_w / 2
        cz = room.world_y + room.world_h / 2
        light_y = FLOOR_SURFACE + 160
        lights.append({
            "type": "light",
            "pos": [cx, light_y, cz],
            "properties": {
                "type": "light",
                "name": f"Light_Room{i}",
                "colour": [255, 255, 200],
                "intensity": 1.2,
                "radius": 512.0,
                "state": "on",
                "show_radius": False,
                "casts_shadows": False,
                "id": f"light_room_{i}"
            },
            "io_connections": []
        })

    things = [
        {
            "type": "playerstart",
            "pos": [player_x, player_y, player_z],
            "properties": {
                "type": "playerstart",
                "name": "PlayerStart_1",
                "angle": 0.0,
                "id": "player_start"
            },
            "io_connections": []
        },
        {
            "type": "pickup",
            "pos": [gun_x, gun_y, gun_z],
            "properties": {
                "type": "pickup",
                "name": f"Pickup_{starting_gun.capitalize()}",
                "respawns": False,
                "respawn_time": 20.0,
                "item_type": starting_gun,
                "value": 25,
                "activation": "walk_over",
                "collected": False,
                "key_name": "",
                "custom_sprite": f"assets/sprites/{starting_gun}.png",
                "id": "gun_start"
            },
            "io_connections": []
        },
        {
            "type": "levelchanger",
            "pos": [exit_x, exit_y, exit_z],
            "properties": {
                "type": "levelchanger",
                "name": "LevelChanger_Exit",
                "target_map": "Simple_Map_Test.json",
                "delay": 0.0,
                "fade_time": 0.5,
                "show_radius": False,
                "radius": 128.0,
                "id": "exit"
            },
            "io_connections": []
        }
    ]
    things.extend(lights)

    # ------------------- MONSTER SPAWNING -------------------
    monster_positions = []          # store (x, z) of each monster
    monster_rooms = set()           # indices of rooms that contain a monster
    if params.get('spawn_monsters', False):
        candidate_rooms = [r for r in grid.rooms if r != start_room]
        if not candidate_rooms:
            candidate_rooms = grid.rooms

        monster_radius = 64   # collision radius

        # Helper: random point inside a room with wall clearance
        def rand_point_in_room(room, min_dist_from_wall):
            min_x = room.world_x + min_dist_from_wall
            max_x = room.world_x + room.world_w - min_dist_from_wall
            min_z = room.world_y + min_dist_from_wall
            max_z = room.world_y + room.world_h - min_dist_from_wall
            if min_x >= max_x or min_z >= max_z:
                return room.world_x + room.world_w / 2, room.world_y + room.world_h / 2
            x = random.uniform(min_x, max_x)
            z = random.uniform(min_z, max_z)
            return x, z

        for i in range(params['monster_count']):
            # Find a room large enough to accommodate the monster
            room = None
            for _ in range(10):
                room = random.choice(candidate_rooms)
                if (room.world_w >= 2 * monster_radius and
                    room.world_h >= 2 * monster_radius):
                    break
            else:
                room = random.choice(candidate_rooms)

            wx, wz = rand_point_in_room(room, min_dist_from_wall=monster_radius)
            monster_type = random.choice(["flying", "human"])

            if monster_type == "human":
                wy = FLOOR_SURFACE + 96
            else:
                min_fly = FLOOR_SURFACE + 64
                max_fly = room.ceiling_height - 128
                if max_fly <= min_fly:
                    max_fly = min_fly + 64
                wy = random.randint(min_fly, max_fly)

            things.append({
                "type": "monster",
                "pos": [wx, wy, wz],
                "properties": {
                    "type": "monster",
                    "name": f"Monster_{monster_type.capitalize()}_{i}",
                    "monster_type": monster_type,
                    "monster_id": i,
                    "health": 70 if monster_type == "human" else 50,
                    "damage": 12,
                    "triggered": False,
                    "wake_on_sight": True,
                    "awake": False,
                    "patrol": False,
                    "patrol_target": "",
                    "patrol_mode": "loop",
                    "variant": "variant1",
                    "sprite_width": 160,
                    "sprite_height": 160,
                    "sight": 512,
                    "non_hostile": False,
                    "dead": False,
                    "id": f"monster_{i}"
                },
                "io_connections": []
            })
            monster_positions.append((wx, wz))
            monster_rooms.add(grid.rooms.index(room))

    # ------------------- HEALTH PICKUP SPAWNING -------------------
    if params.get('spawn_health', False):
        health_count = params.get('health_count', 4)
        # Rooms that are allowed for health: no monster in them
        allowed_rooms = [room for idx, room in enumerate(grid.rooms) if idx not in monster_rooms]
        if not allowed_rooms:
            # Fallback: use all rooms except the start room (but still avoid monster rooms if any)
            allowed_rooms = [r for r in grid.rooms if r != start_room]
            allowed_rooms = [r for r in allowed_rooms if grid.rooms.index(r) not in monster_rooms]

        if allowed_rooms:
            # Minimum distance from any monster (world units)
            MIN_DIST_TO_MONSTER = 128.0
            # How many attempts to place each health pickup
            MAX_ATTEMPTS = 50

            for i in range(health_count):
                placed = False
                for _ in range(MAX_ATTEMPTS):
                    room = random.choice(allowed_rooms)
                    # Try to find a point at least 32 from walls and 128 from any monster
                    wx, wz = random_point_in_room(room, min_dist_from_wall=32)
                    # Check distance to all monsters
                    too_close = False
                    for mx, mz in monster_positions:
                        dist = math.hypot(wx - mx, wz - mz)
                        if dist < MIN_DIST_TO_MONSTER:
                            too_close = True
                            break
                    if not too_close:
                        wy = FLOOR_SURFACE + ENTITY_Y_OFFSET
                        things.append({
                            "type": "pickup",
                            "pos": [wx, wy, wz],
                            "properties": {
                                "type": "pickup",
                                "name": f"HealthPickup_{i}",
                                "item_type": "health",
                                "value": 25,
                                "activation": "walk_over",
                                "respawns": False,
                                "respawn_time": 20.0,
                                "collected": False,
                                "key_name": "",
                                "custom_sprite": "assets/sprites/health.png",
                                "id": f"health_pickup_{i}"
                            },
                            "io_connections": []
                        })
                        placed = True
                        break
                # If we couldn't place after MAX_ATTEMPTS, just skip this pickup
                if not placed:
                    print(f"Warning: Could not place health pickup #{i} after {MAX_ATTEMPTS} attempts. Skipping.")

    return {
        "version": 3,
        "brushes": brushes,
        "things": things
    }

# ----------------------------------------------------------------------
# Main widget
# ----------------------------------------------------------------------
class ProceduralMapWidget(QWidget):
    """Generator UI that replaces the properties tab widget."""
    map_generated = pyqtSignal(object)  # emits map data dict, or None = close request

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_params = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title = QLabel("Procedural Map Generator")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(0)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #555;
                color: #f0f0f0;
                border: 1px solid #666;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #F08000;
            }
            QPushButton:pressed {
                background-color: #d06000;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn, 1)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self.accept_and_load)
        self.generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #2E7D32;
                color: white;
                font-weight: bold;
                border: none;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #388E3C;
            }
            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }
        """)
        btn_row.addWidget(self.generate_btn, 1)

        layout.addLayout(btn_row)

        # Timer for button cooldown
        self._cooldown_timer = QTimer(self)
        self._cooldown_timer.setSingleShot(True)
        self._cooldown_timer.timeout.connect(self._enable_generate_button)

        # Scrollable parameters area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        params_widget = QWidget()
        params_layout = QVBoxLayout(params_widget)

        group = QGroupBox("Parameters")
        form = QFormLayout(group)

        self.map_size_combo = QComboBox()
        self.map_size_combo.addItems(["Small (1024x1024)", "Medium (2048x2048)", "Large (4096x4096)"])
        self.map_size_combo.setCurrentIndex(1)  # Medium is default
        form.addRow("Map Size:", self.map_size_combo)

        self.room_count = QSpinBox()
        self.room_count.setRange(8, 24)
        self.room_count.setValue(14)
        form.addRow("Target Rooms:", self.room_count)

        self.min_room = QSpinBox()
        self.min_room.setRange(192, 320)
        self.min_room.setValue(256)
        form.addRow("Min Room Size (world units):", self.min_room)

        self.max_room = QSpinBox()
        self.max_room.setRange(256, 512)
        self.max_room.setValue(384)
        form.addRow("Max Room Size (world units):", self.max_room)

        self.wall_tex = QTextEdit()
        self.wall_tex.setPlainText("default.png")
        self.wall_tex.setMaximumHeight(50)
        form.addRow("Wall Texture:", self.wall_tex)

        self.spawn_monsters = QCheckBox("Spawn Monsters")
        self.spawn_monsters.setChecked(True)
        self.monster_amount = QSpinBox()
        self.monster_amount.setRange(1, 64)
        self.monster_amount.setValue(4)
        form.addRow(self.spawn_monsters, self.monster_amount)

        # Health pickups
        self.spawn_health = QCheckBox("Spawn Health")
        self.spawn_health.setChecked(True)
        self.health_amount = QSpinBox()
        self.health_amount.setRange(1, 64)
        self.health_amount.setValue(6)
        form.addRow(self.spawn_health, self.health_amount)

        params_layout.addWidget(group)
        params_layout.addStretch()

        scroll.setWidget(params_widget)
        layout.addWidget(scroll)

    def get_world_size(self):
        """Return (world_width, world_height) based on selected size."""
        size_text = self.map_size_combo.currentText()
        if "Small" in size_text:
            return 1024, 1024
        elif "Large" in size_text:
            return 4096, 4096
        else:  # Medium
            return 2048, 2048

    def accept_and_load(self):
        """Generate map data and emit signal, then disable button briefly."""
        if not self.generate_btn.isEnabled():
            return

        self.generate_btn.setEnabled(False)
        self._cooldown_timer.start(1000)   # re‑enable after 1 second

        random.seed()
        seed = random.randint(0, 999999)
        random.seed(seed)

        world_width, world_height = self.get_world_size()
        params = {
            'room_count': self.room_count.value(),
            'min_room': self.min_room.value(),
            'max_room': self.max_room.value(),
            'wall_tex': self.wall_tex.toPlainText().strip(),
            'floor_tex': "default.png",
            'spawn_monsters': self.spawn_monsters.isChecked(),
            'monster_count': self.monster_amount.value(),
            'world_width': world_width,
            'world_height': world_height,
            # --- NEW ---
            'spawn_health': self.spawn_health.isChecked(),
            'health_count': self.health_amount.value(),
        }
        self.current_params = params
        map_data = create_map_data(params)
        self.map_generated.emit(map_data)

    def _enable_generate_button(self):
        self.generate_btn.setEnabled(True)

    def reject(self):
        """Request to close this widget and restore original content."""
        self.map_generated.emit(None)