"""
Camera render-distance cull -- the pure, GL-free geometry of it.

The renderer's main camera pass runs this cheap broad-phase cull *before*
``_sort_objects`` (and on top of the frustum cull it already does): any object
whose centre lies farther than :data:`CAMERA_RENDER_CULL_DISTANCE` world units
from the camera on the XZ plane is dropped. Distances are compared squared, so
no square root runs per object.

The logic lives here, apart from :mod:`engine.renderer_F`, for two reasons: it
carries no OpenGL/glm/Qt dependency, so it is unit-testable headlessly; and it
keeps the renderer's per-frame path a thin call over a persistent scratch buffer
(no per-frame list allocation). The shadow and portal passes deliberately do not
call this -- they keep operating on the full scene.
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence

#: Cull radius (world units) on the XZ plane, measured from the camera centre.
CAMERA_RENDER_CULL_DISTANCE = 4096.0
#: Precomputed squared radius -- the value the per-object test actually compares.
CAMERA_RENDER_CULL_DISTANCE_SQ = CAMERA_RENDER_CULL_DISTANCE * CAMERA_RENDER_CULL_DISTANCE


def pos_of(obj):
    """The ``[x, y, z]`` of a brush dict or a Thing-like object, or ``None``."""
    if isinstance(obj, dict):
        return obj.get("pos")
    return getattr(obj, "pos", None)


def within_xz_sq(pos, cx: float, cz: float, limit_sq: float) -> bool:
    """Whether *pos* is within a squared XZ distance *limit_sq* of (cx, cz)."""
    dx = pos[0] - cx
    dz = pos[2] - cz
    return dx * dx + dz * dz <= limit_sq


def camera_xz(camera_pos):
    """(x, z) of the camera centre, accepting a glm vec or any ``[x, y, z]``."""
    if hasattr(camera_pos, "x"):
        return float(camera_pos.x), float(camera_pos.z)
    return float(camera_pos[0]), float(camera_pos[2])


def cull_by_distance(objects: Sequence, cx: float, cz: float,
                     limit_sq: float = CAMERA_RENDER_CULL_DISTANCE_SQ,
                     out: Optional[List] = None,
                     keep: Optional[Callable[[object], bool]] = None) -> List:
    """Return the subset of *objects* within *limit_sq* XZ of (cx, cz).

    Fills and returns *out* when given (cleared first), so a caller can reuse one
    persistent buffer across frames and allocate nothing; otherwise a fresh list
    is returned. An object for which *keep* returns True -- or that has no
    readable position -- is retained unconditionally (fail-open: never wrongly
    hide it).
    """
    if out is None:
        out = []
    else:
        del out[:]
    for obj in objects:
        if keep is not None and keep(obj):
            out.append(obj)
            continue
        pos = pos_of(obj)
        if pos is None or within_xz_sq(pos, cx, cz, limit_sq):
            out.append(obj)
    return out
