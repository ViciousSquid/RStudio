"""
Runtime behaviour for the Tidy plugin.

All per-play-session state and logic lives in :class:`TidySession`, which the
host attaches to its logic object as ``logic._tidy`` while play mode is active.
The core loop, each tick:

  * if the player is **holding** an object, keep it floating at the crosshair
    and, on a use-press, place it into the receptacle under the crosshair
    (or drop it);
  * otherwise, if the player is **looking at** a nearby object, pick it up on
    a use-press.

To stay fast with *thousands* of objects, available (not-yet-stowed) objects
are indexed in a coarse 2D :class:`SpatialHash` so the per-tick "what am I
looking at" query only touches the handful of objects in neighbouring cells,
not the whole map.

The math here is plain Python (no PyGLM/NumPy) so the plugin runs unchanged in
the editor's play mode *and* in the dependency-light ``.fiopak`` player / its
Android build. ``player.pos`` may be a ``glm.vec3`` (editor) or a list/tuple
(player) — both are handled by index access.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional


# -- interaction tuning ------------------------------------------------------
PICKUP_REACH = 110.0          # max distance to pick an object up
PICKUP_AIM_DOT = 0.86         # how tightly the crosshair must be on it
CARRY_DISTANCE = 55.0         # how far in front the held object floats
CARRY_DROP = -6.0             # slight downward offset so it sits below the eye
PLACE_AIM_DOT = 0.55          # receptacle aim tolerance (wider — it's a zone)
GRID_CELL = 160.0             # spatial-hash cell size (world units)


# -- tiny vector helpers (plain tuples; no external deps) --------------------
def _xyz(p):
    return (float(p[0]), float(p[1]), float(p[2]))


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a):
    return math.sqrt(_dot(a, a))


def _forward(player):
    """Full look direction (includes pitch), matching the engine camera."""
    a, p = player.angle, player.pitch
    return (math.sin(a) * math.cos(p), math.sin(p), math.cos(a) * math.cos(p))


def _eye(player):
    return _add(_xyz(player.pos), (0.0, getattr(player, "camera_height", 40.0), 0.0))


class SpatialHash:
    """Tiny 2D (X/Z) spatial hash of objects for nearest-in-view queries."""

    def __init__(self, cell: float = GRID_CELL):
        self.cell = cell
        self._cells: Dict[tuple, list] = {}
        self._where: Dict[int, tuple] = {}   # id(obj) -> cell key

    def _key(self, pos) -> tuple:
        return (int(math.floor(pos[0] / self.cell)),
                int(math.floor(pos[2] / self.cell)))

    def add(self, obj):
        key = self._key(obj.pos)
        self._cells.setdefault(key, []).append(obj)
        self._where[id(obj)] = key

    def remove(self, obj):
        key = self._where.pop(id(obj), None)
        if key is None:
            return
        bucket = self._cells.get(key)
        if bucket:
            try:
                bucket.remove(obj)
            except ValueError:
                pass
            if not bucket:
                self._cells.pop(key, None)

    def clear(self):
        self._cells.clear()
        self._where.clear()

    def neighbours(self, pos):
        """Yield objects in the 3x3 block of cells around *pos*."""
        cx, cz = self._key(pos)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                bucket = self._cells.get((cx + dx, cz + dz))
                if bucket:
                    yield from bucket


class TidySession:
    """Per-play-session tidy state and per-tick logic."""

    def __init__(self, logic):
        self.logic = logic
        self.objects: List = []
        self.receptacles: List = []
        self.goals: List = []
        self.grid = SpatialHash()
        self.held = None
        # id(receptacle) -> list of stowed object ids (index == slot).
        self._fill: Dict[int, list] = {}
        self._full_fired: set = set()
        self._goal_done: set = set()
        # tidy progress, overall and per category
        self.total = 0
        self.tidied = 0
        self._total_by_cat: Dict[str, int] = {}
        self._tidied_by_cat: Dict[str, int] = {}

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _is(thing, type_name: str) -> bool:
        props = getattr(thing, 'properties', None)
        return isinstance(props, dict) and props.get('type') == type_name

    def _fire(self, entity, output: str, value: Optional[str] = None):
        io = getattr(self.logic, 'io_manager', None)
        if io is not None:
            io.fire_output(entity, output, value)

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        """Snapshot the map, reset tidy state, and build the spatial index."""
        things = list(self.logic.things)
        self.objects = [t for t in things if self._is(t, 'tidyobject')]
        self.receptacles = [t for t in things if self._is(t, 'tidyreceptacle')]
        self.goals = [t for t in things if self._is(t, 'tidygoal')]

        self.grid.clear()
        self._fill.clear()
        self._full_fired.clear()
        self._goal_done.clear()
        self.held = None
        self._total_by_cat.clear()
        self._tidied_by_cat.clear()

        for obj in self.objects:
            p = obj.properties
            # Remember where the object lives so we can restore it when play
            # stops (we move objects around while playing).
            p['_home_pos'] = list(obj.pos)
            p['tidied'] = False
            cat = p.get('category', 'object')
            self._total_by_cat[cat] = self._total_by_cat.get(cat, 0) + 1
            if not p.get('disabled', False):
                self.grid.add(obj)

        self.total = len(self.objects)
        self.tidied = 0

    def stop(self):
        """Restore edited object positions/flags so the map is unchanged."""
        for obj in self.objects:
            p = obj.properties
            home = p.pop('_home_pos', None)
            if home is not None:
                obj.pos = list(home)
            p['tidied'] = False
        self.grid.clear()
        self.held = None

    # -- per-tick -----------------------------------------------------------
    def tick(self, ctx):
        logic = self.logic
        player = getattr(logic, 'player', None)
        if player is None:
            return

        eye = _eye(player)
        fwd = _forward(player)

        if self.held is not None:
            self._tick_carrying(ctx, eye, fwd)
        else:
            self._tick_looking(ctx, eye, fwd)

    def _tick_carrying(self, ctx, eye, fwd):
        held = self.held
        # Keep the held object floating at the crosshair.
        target = _add(_add(eye, _scale(fwd, CARRY_DISTANCE)), (0.0, CARRY_DROP, 0.0))
        held.pos = [target[0], target[1], target[2]]

        recept = self._receptacle_in_view(eye, fwd, held.properties.get('category', 'object'))
        if recept is not None:
            name = recept.properties.get('name', 'shelf')
            self.logic.current_hud_message = f"[E] Put away ({name})"
            if ctx and ctx.use_pressed:
                self._place(held, recept)
        else:
            self.logic.current_hud_message = "[E] Drop"
            if ctx and ctx.use_pressed:
                self._drop(held)

    def _tick_looking(self, ctx, eye, fwd):
        obj = self._object_in_view(eye, fwd)
        if obj is None:
            return
        item = str(obj.properties.get('category', 'object')).replace('_', ' ').title()
        self.logic.current_hud_message = f"[E] Pick up {item}"
        if ctx and ctx.use_pressed:
            self._pick_up(obj)

    # -- queries ------------------------------------------------------------
    def _object_in_view(self, eye, fwd):
        best = None
        best_d = PICKUP_REACH
        for obj in self.grid.neighbours(eye):
            p = obj.properties
            if p.get('tidied') or p.get('disabled'):
                continue
            to = _sub(_xyz(obj.pos), eye)
            dist = _length(to)
            if dist > PICKUP_REACH or dist < 1e-3:
                continue
            if _dot(fwd, _scale(to, 1.0 / dist)) < PICKUP_AIM_DOT:
                continue
            if dist < best_d:
                best_d = dist
                best = obj
        return best

    def _receptacle_in_view(self, eye, fwd, category):
        best = None
        best_d = None
        for r in self.receptacles:
            rp = r.properties
            if rp.get('disabled'):
                continue
            if not self._accepts(r, category):
                continue
            if self._fill_count(r) >= int(rp.get('capacity', 24)):
                continue
            reach = float(rp.get('reach', 140.0))
            to = _sub(_xyz(r.pos), eye)
            dist = _length(to)
            if dist > reach or dist < 1e-3:
                continue
            if _dot(fwd, _scale(to, 1.0 / dist)) < PLACE_AIM_DOT:
                continue
            if best_d is None or dist < best_d:
                best_d = dist
                best = r
        return best

    @staticmethod
    def _accepts(recept, category) -> bool:
        acc = str(recept.properties.get('accepts', 'any')).strip().lower()
        return acc in ('', 'any', '*') or acc == str(category).strip().lower()

    def _fill_count(self, recept) -> int:
        return len(self._fill.get(id(recept), ()))

    def _slot_world_pos(self, recept, index):
        rp = recept.properties
        cols = max(1, int(rp.get('slot_cols', 6)))
        sp = rp.get('slot_spacing', [28.0, 40.0, 0.0])
        off = rp.get('slot_offset', [0.0, 0.0, 0.0])
        try:
            sx, sy, sz = float(sp[0]), float(sp[1]), float(sp[2] if len(sp) > 2 else 0.0)
        except (TypeError, ValueError, IndexError):
            sx, sy, sz = 28.0, 40.0, 0.0
        col = index % cols
        row = index // cols
        cx = (col - (cols - 1) / 2.0) * sx
        base = recept.pos
        return [
            base[0] + float(off[0]) + cx,
            base[1] + float(off[1]) + row * sy,
            base[2] + float(off[2]) + row * sz,
        ]

    # -- actions ------------------------------------------------------------
    def _pick_up(self, obj):
        self.grid.remove(obj)
        self.held = obj
        self._fire(obj, 'OnPickedUp')

    def _drop(self, obj):
        # Release at its current (crosshair) position and make it available.
        self.held = None
        self.grid.add(obj)
        self._fire(obj, 'OnDropped')

    def _place(self, obj, recept):
        idx = self._fill_count(recept)
        obj.pos = self._slot_world_pos(recept, idx)
        obj.properties['tidied'] = True
        self._fill.setdefault(id(recept), []).append(id(obj))
        self.held = None

        # progress
        self.tidied += 1
        cat = obj.properties.get('category', 'object')
        self._tidied_by_cat[cat] = self._tidied_by_cat.get(cat, 0) + 1

        self._fire(obj, 'OnTidied')
        self._fire(recept, 'OnObjectPlaced', value=str(idx + 1))

        if self._fill_count(recept) >= int(recept.properties.get('capacity', 24)):
            if id(recept) not in self._full_fired:
                self._full_fired.add(id(recept))
                self._fire(recept, 'OnFull')

        self._check_goals()

    def reset_object(self, obj):
        """I/O 'reset' input: send a stowed/held object back to its home."""
        p = obj.properties
        if self.held is obj:
            self.held = None
        # Remove it from any receptacle fill list.
        for rid, ids in self._fill.items():
            if id(obj) in ids:
                ids.remove(id(obj))
                self._full_fired.discard(rid)
        if p.get('tidied'):
            self.tidied = max(0, self.tidied - 1)
            cat = p.get('category', 'object')
            self._tidied_by_cat[cat] = max(0, self._tidied_by_cat.get(cat, 0) - 1)
        p['tidied'] = False
        home = p.get('_home_pos')
        if home is not None:
            obj.pos = list(home)
        self.grid.remove(obj)
        if not p.get('disabled', False):
            self.grid.add(obj)

    # -- goals --------------------------------------------------------------
    def _check_goals(self):
        for goal in self.goals:
            if id(goal) in self._goal_done or goal.properties.get('disabled'):
                continue
            done, need = self._goal_progress(goal)
            self._fire(goal, 'OnProgress', value=f"{done}/{need}")
            if need > 0 and done >= need:
                self._goal_done.add(id(goal))
                self._fire(goal, 'OnComplete')

    def _goal_progress(self, goal):
        """Return ``(done, need)`` for *goal* honouring its category filter."""
        cat = str(goal.properties.get('category', 'any')).strip().lower()
        if cat in ('', 'any', '*'):
            total = self.total
            done = self.tidied
        else:
            total = self._total_by_cat.get(cat, 0)
            done = self._tidied_by_cat.get(cat, 0)
        need = goal.target_count(total) if hasattr(goal, 'target_count') else total
        return done, need

    # -- hud ----------------------------------------------------------------
    def hud_line(self) -> Optional[str]:
        """A short progress string for on-screen display, or None."""
        for goal in self.goals:
            if goal.properties.get('show_hud', True) and not goal.properties.get('disabled'):
                done, need = self._goal_progress(goal)
                label = "Tidied"
                if id(goal) in self._goal_done:
                    return f"{label}: {done}/{need}  — All done!"
                return f"{label}: {done}/{need}"
        if self.total:
            return f"Tidied: {self.tidied}/{self.total}"
        return None
