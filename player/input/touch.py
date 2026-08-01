"""On-screen touch controls: two floating virtual sticks + action buttons.

Layout (resolution-independent, expressed as fractions of the surface):

    +---------------------------------------------------+
    |                                          [PAUSE]  |
    |                                     [ USE ]        |
    |                                  [JUMP] [FIRE]     |
    |   (left half:                     (right half:     |
    |    floating MOVE stick)            floating LOOK   |
    |                                    stick)          |
    +---------------------------------------------------+

* The **left half** is a floating movement stick: the first finger down there
  sets the stick centre; dragging yields move_x/move_y.
* The **right half** is a floating look stick: dragging turns/pitches the camera
  by the stick's *deflection* (a rate, like a console right thumbstick) — not a
  one-shot drag delta, so you can hold a turn.
* Action buttons are fixed circular hit regions; they take priority over the
  look stick, so a second finger can fire/jump while the right stick is held.

Pure math: it takes a snapshot of currently-down pointers
(``{finger_id: (x_px, y_px)}``) and writes into an :class:`InputState`, and it
records each stick's current deflection so the overlay can draw the knobs. No
pygame, no GL — unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .state import (
    InputState,
    ACTION_JUMP,
    ACTION_FIRE,
    ACTION_USE,
    ACTION_PAUSE,
)


@dataclass
class TouchButton:
    """A circular button in screen-fraction coordinates."""

    action: str
    cx: float          # centre x as a fraction of width  [0, 1]
    cy: float          # centre y as a fraction of height [0, 1]
    radius: float      # radius as a fraction of the smaller screen dimension

    def contains(self, x: float, y: float, w: float, h: float) -> bool:
        s = min(w, h)
        dx = x - self.cx * w
        dy = y - self.cy * h
        return (dx * dx + dy * dy) <= (self.radius * s) ** 2


@dataclass
class TouchStick:
    """A floating analog stick that appears where a finger first lands."""

    # Region (fractions of the surface) in which a new touch grabs this stick.
    region_x0: float
    region_y0: float
    region_x1: float
    region_y1: float
    # A resting "home" position (fractions) drawn as a hint when idle.
    home_x: float
    home_y: float
    radius: float = 0.16   # travel radius as a fraction of the smaller dim

    origin: Optional[Tuple[float, float]] = None  # px, set on grab

    def in_region(self, x: float, y: float, w: float, h: float) -> bool:
        return (
            self.region_x0 * w <= x <= self.region_x1 * w
            and self.region_y0 * h <= y <= self.region_y1 * h
        )

    def value(self, x: float, y: float, w: float, h: float) -> Tuple[float, float]:
        if self.origin is None:
            return 0.0, 0.0
        r = self.radius * min(w, h)
        vx = (x - self.origin[0]) / r
        vy = -(y - self.origin[1]) / r      # screen Y grows down; up is +y
        return _clamp(vx), _clamp(vy)


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if v < lo else hi if v > hi else v


class TouchControls:
    """Multi-touch overlay: a move stick, a look stick, and action buttons."""

    def __init__(self, look_gain: float = 2.2, dead_zone: float = 0.08):
        # Left half -> movement; right half -> look. Homes sit bottom-left /
        # bottom-right so the resting hints don't collide.
        self.move_stick = TouchStick(0.0, 0.0, 0.5, 1.0, home_x=0.16, home_y=0.80)
        self.look_stick = TouchStick(0.5, 0.0, 1.0, 1.0, home_x=0.84, home_y=0.80)
        self.look_gain = look_gain
        self.dead_zone = dead_zone

        # Action buttons cluster at the right edge, above the look-stick home.
        self.buttons = [
            TouchButton(ACTION_FIRE, cx=0.92, cy=0.55, radius=0.085),
            TouchButton(ACTION_JUMP, cx=0.78, cy=0.50, radius=0.075),
            TouchButton(ACTION_USE, cx=0.92, cy=0.38, radius=0.065),
            TouchButton(ACTION_PAUSE, cx=0.96, cy=0.07, radius=0.045),
        ]

        # role per pointer: "move", "look", or "button:<action>".
        self._roles: Dict[int, str] = {}

        # Current deflection of each stick (for the overlay to draw the knobs).
        self.move_value: Tuple[float, float] = (0.0, 0.0)
        self.look_value: Tuple[float, float] = (0.0, 0.0)

    # ------------------------------------------------------------------
    def apply(
        self,
        state: InputState,
        pointers: Dict[int, Tuple[float, float]],
        w: float,
        h: float,
    ) -> None:
        """Fold a snapshot of down pointers into ``state``."""
        # 1. Retire pointers that lifted; free the stick they held.
        for pid in list(self._roles.keys()):
            if pid not in pointers:
                role = self._roles.pop(pid)
                if role == "move":
                    self.move_stick.origin = None
                elif role == "look":
                    self.look_stick.origin = None

        # 2. Assign roles to newly-arrived pointers by where they landed.
        for pid, (x, y) in pointers.items():
            if pid not in self._roles:
                self._roles[pid] = self._classify(x, y, w, h)

        # 3. Evaluate active pointers.
        self.move_value = (0.0, 0.0)
        self.look_value = (0.0, 0.0)
        for pid, (x, y) in pointers.items():
            role = self._roles.get(pid)
            if role == "move":
                mx, my = self._dead_zone(*self.move_stick.value(x, y, w, h))
                self.move_value = (mx, my)
                state.add_move(mx, my)
            elif role == "look":
                lx, ly = self._dead_zone(*self.look_stick.value(x, y, w, h))
                self.look_value = (lx, ly)
                # +lx = turn right, +ly = look up (rate scaled by look_gain).
                state.add_look(lx * self.look_gain, ly * self.look_gain)
            elif role and role.startswith("button:"):
                state.set_button(role.split(":", 1)[1], True)

    # ------------------------------------------------------------------
    def _classify(self, x: float, y: float, w: float, h: float) -> str:
        # Buttons win over sticks so a finger on a button never grabs a stick.
        for btn in self.buttons:
            if btn.contains(x, y, w, h):
                return f"button:{btn.action}"
        # Left half grabs the move stick; right half grabs the look stick. Each
        # stick can only be held by one finger at a time.
        left = self.move_stick.in_region(x, y, w, h)
        if left and self.move_stick.origin is None:
            self.move_stick.origin = (x, y)
            return "move"
        if self.look_stick.origin is None:
            self.look_stick.origin = (x, y)
            return "look"
        if self.move_stick.origin is None:
            self.move_stick.origin = (x, y)
            return "move"
        return "idle"  # both sticks already held by other fingers

    def _dead_zone(self, x: float, y: float) -> Tuple[float, float]:
        mag = (x * x + y * y) ** 0.5
        if mag <= self.dead_zone or mag == 0.0:
            return 0.0, 0.0
        # Rescale so there's no jump at the dead-zone threshold.
        scale = (mag - self.dead_zone) / (1.0 - self.dead_zone) / mag
        return _clamp(x * scale), _clamp(y * scale)

    def reset(self) -> None:
        """Drop all pointer assignments (call on focus loss / resume)."""
        self._roles.clear()
        self.move_stick.origin = None
        self.look_stick.origin = None
        self.move_value = (0.0, 0.0)
        self.look_value = (0.0, 0.0)
