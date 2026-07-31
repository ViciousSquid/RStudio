"""Tiny numpy-backed matrix helpers for the player's own rendering.

The engine uses PyGLM, which has no python-for-android recipe (see
``player/README.md``). The player's *own* GL needs — a view/projection matrix, a
2D orthographic overlay, per-widget translate/scale — are small, so we express
them with numpy (which *does* have a p4a recipe) and keep PyGLM out of the
mobile render path until the full engine simulation is ported.

Matrices are returned as row-major ``float32`` 4x4 arrays. Upload them with
``glUniformMatrix4fv(loc, 1, GL_TRUE, mat)`` — the ``GL_TRUE`` transpose flag
tells GL to read our row-major data as its expected column-major layout.
"""

from __future__ import annotations

import math

import numpy as np


def identity() -> "np.ndarray":
    return np.identity(4, dtype=np.float32)


def translate(x: float, y: float, z: float = 0.0) -> "np.ndarray":
    m = identity()
    m[0, 3] = x
    m[1, 3] = y
    m[2, 3] = z
    return m


def scale(sx: float, sy: float, sz: float = 1.0) -> "np.ndarray":
    m = identity()
    m[0, 0] = sx
    m[1, 1] = sy
    m[2, 2] = sz
    return m


def rotate_z(theta: float) -> "np.ndarray":
    c, s = math.cos(theta), math.sin(theta)
    m = identity()
    m[0, 0] = c
    m[0, 1] = -s
    m[1, 0] = s
    m[1, 1] = c
    return m


def ortho(left: float, right: float, bottom: float, top: float,
          near: float = -1.0, far: float = 1.0) -> "np.ndarray":
    """Row-major orthographic projection (same formula as glm::ortho)."""
    m = identity()
    m[0, 0] = 2.0 / (right - left)
    m[1, 1] = 2.0 / (top - bottom)
    m[2, 2] = -2.0 / (far - near)
    m[0, 3] = -(right + left) / (right - left)
    m[1, 3] = -(top + bottom) / (top - bottom)
    m[2, 3] = -(far + near) / (far - near)
    return m


def perspective(fovy_rad: float, aspect: float, near: float, far: float) -> "np.ndarray":
    """Row-major perspective projection (same formula as glm::perspective)."""
    f = 1.0 / math.tan(fovy_rad / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / max(aspect, 1e-6)
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2.0 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye, center, up=(0.0, 1.0, 0.0)) -> "np.ndarray":
    """Row-major view matrix (same result as glm::lookAt)."""
    eye = np.asarray(eye, dtype=np.float64)
    center = np.asarray(center, dtype=np.float64)
    up = np.asarray(up, dtype=np.float64)
    f = _normalize(center - eye)
    s = _normalize(np.cross(f, up))
    u = np.cross(s, f)
    m = np.identity(4, dtype=np.float32)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[0, 3] = -float(np.dot(s, eye))
    m[1, 3] = -float(np.dot(u, eye))
    m[2, 3] = float(np.dot(f, eye))
    return m


def front_from_angles(yaw_deg: float, pitch_deg: float):
    """Camera forward vector from yaw/pitch in degrees (engine convention)."""
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    return (
        math.cos(yaw) * math.cos(pitch),
        math.sin(pitch),
        math.sin(yaw) * math.cos(pitch),
    )


def _normalize(v):
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else v


def mul(*mats: "np.ndarray") -> "np.ndarray":
    """Matrix product left-to-right (mul(A, B, C) == A @ B @ C)."""
    out = mats[0]
    for m in mats[1:]:
        out = out @ m
    return out.astype(np.float32)
