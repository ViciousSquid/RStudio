"""Milestone-1 OpenGL ES renderer + engine bridge seam.

Two responsibilities:

1. **Proof-of-life ES pipeline** (implemented): create the ES viewport, compile
   the translated shader set, draw a reference triangle through the ``simple``
   program, and draw the touch-controls overlay on top. When you see the
   triangle and the on-screen controls on-device, the whole chain works: ES
   context, GLSL-ES translation, VBO/VAO, uniforms, blending, draw, present.

2. **Engine bridge** (seam): :meth:`load_scene` and :meth:`render_scene` are the
   hook points where ``engine/renderer_core.py`` — the brush/mesh/light/portal
   renderer — is driven onto ES. The desktop renderer is coupled to a QOpenGL
   context; the port replaces that context with this one and reuses its geometry
   upload and draw logic. See ``player/README.md`` for the staged plan.

PyOpenGL and numpy are imported lazily so the module stays importable without a
GL binding. Matrix math uses :mod:`player.render.glmath` (numpy) so the mobile
render path has no PyGLM dependency.
"""

from __future__ import annotations

from typing import Dict, Optional

import math

from .gles_context import build_program_set
from .overlay import OverlayRenderer
from . import glmath
from . import scene as _scene


class GLESRenderer:
    """Owns GL programs and draws each frame."""

    def __init__(self):
        self.programs: Dict[str, int] = {}
        self.width = 1
        self.height = 1
        self._triangle_vao = None
        self._triangle_vbo = None
        self._scene = None
        self._start_time = 0.0
        self.overlay = OverlayRenderer()

        # Scene geometry (Milestone 3): world-space brush mesh + map lights.
        self._scene_vao = None
        self._scene_vbo = None
        self._scene_vertex_count = 0
        self._lights = []
        self.fov_deg = 70.0
        self.near = 1.0
        self.far = 8000.0

    # ------------------------------------------------------------------
    # GL lifecycle
    # ------------------------------------------------------------------
    def on_gl_ready(self) -> None:
        """(Re)build all GL resources. Safe to call again after context loss."""
        import time

        from ..gles_shaders import build_gles_shader_set, build_gles_shader_map

        gl = _gl()
        self._start_time = time.perf_counter()

        # Any GL handles from a previous (now-lost) context are invalid; drop
        # them so fresh ones are generated below and in _upload_scene.
        self._triangle_vao = self._triangle_vbo = None
        self._scene_vao = self._scene_vbo = None

        sources = build_gles_shader_set(prefer_arm=True)
        shader_map = build_gles_shader_map()
        self.programs = build_program_set(sources, shader_map)
        print(f"[GLES] compiled {len(self.programs)} shader programs: "
              f"{sorted(self.programs)}")

        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glClearColor(0.06, 0.07, 0.09, 1.0)
        self._build_reference_triangle()
        self.overlay.on_gl_ready(self.programs)

        if self._scene is not None:
            self._upload_scene()

    def resize(self, width: int, height: int) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        _gl().glViewport(0, 0, self.width, self.height)

    # ------------------------------------------------------------------
    # Reference triangle (milestone 1)
    # ------------------------------------------------------------------
    def _build_reference_triangle(self) -> None:
        import ctypes

        import numpy as np

        gl = _gl()
        verts = np.array(
            [0.0, 0.5, 0.0, -0.5, -0.5, 0.0, 0.5, -0.5, 0.0],
            dtype=np.float32,
        )
        self._triangle_vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(self._triangle_vao)
        self._triangle_vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._triangle_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)

    def _draw_reference_triangle(self) -> None:
        import time

        gl = _gl()
        prog = self.programs.get("simple")
        if prog is None or self._triangle_vao is None:
            return
        gl.glUseProgram(prog)

        t = time.perf_counter() - self._start_time
        aspect = self.width / max(1, self.height)
        model = glmath.rotate_z(t)
        view = glmath.identity()
        proj = glmath.ortho(-aspect, aspect, -1.0, 1.0, -1.0, 1.0)

        _set_mat4(gl, prog, "model", model)
        _set_mat4(gl, prog, "view", view)
        _set_mat4(gl, prog, "projection", proj)
        _set_vec3(gl, prog, "color", (0.20, 0.85, 0.70))
        _set_float(gl, prog, "alpha", 1.0)

        gl.glBindVertexArray(self._triangle_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)
        gl.glBindVertexArray(0)

    # ------------------------------------------------------------------
    # Per-frame
    # ------------------------------------------------------------------
    def render(self, render_state=None) -> None:
        gl = _gl()
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        if self._scene is not None:
            self.render_scene(render_state)
        else:
            self._draw_reference_triangle()

    def render_overlay(self, controls, inp, w: int, h: int) -> None:
        """Draw the on-screen touch controls over the scene (call last)."""
        self.overlay.render(controls, inp, w, h)

    # ------------------------------------------------------------------
    # Engine bridge seam (Milestone 3+)
    # ------------------------------------------------------------------
    def load_scene(self, map_data: dict, package=None) -> None:
        """Prepare a parsed map for rendering.

        Integration point for the engine geometry pipeline: brush geometry
        (``engine/brush_geometry.py``), models (``engine/glb_loader.py`` /
        ``obj_loader.py``), terrain, lights and portals are built here and their
        GL buffers uploaded via :meth:`_upload_scene`. Left as a documented seam
        until the ES port of ``renderer_core`` lands.
        """
        self._scene = {"map": map_data, "package": package}
        self._upload_scene()

    def _upload_scene(self) -> None:
        """Build the brush mesh and upload it as an interleaved VBO/VAO."""
        import ctypes

        gl = _gl()
        map_data = self._scene["map"] if self._scene else {}
        vertices, count = _scene.build_brush_mesh(map_data)
        self._scene_vertex_count = count
        self._lights = _scene.extract_lights(map_data)
        if count == 0:
            return

        if self._scene_vao is None:
            self._scene_vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(self._scene_vao)
        if self._scene_vbo is None:
            self._scene_vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._scene_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)

        stride = 6 * 4  # 6 floats * 4 bytes
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(1, 3, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(12))
        gl.glEnableVertexAttribArray(1)
        gl.glBindVertexArray(0)
        print(f"[GLES] scene uploaded: {count} verts, {len(self._lights)} lights")

    def render_scene(self, render_state) -> None:
        """Draw the brush mesh with the lit shader from the player camera."""
        gl = _gl()
        prog = self.programs.get("lit")
        if prog is None or self._scene_vertex_count == 0:
            self._draw_reference_triangle()
            return

        cam_pos = (render_state or {}).get("cam_pos", (0.0, 64.0, 0.0))
        yaw = (render_state or {}).get("cam_yaw", -90.0)
        pitch = (render_state or {}).get("cam_pitch", 0.0)
        front = glmath.front_from_angles(yaw, pitch)
        center = (cam_pos[0] + front[0], cam_pos[1] + front[1], cam_pos[2] + front[2])
        aspect = self.width / max(1, self.height)
        view = glmath.look_at(cam_pos, center)
        proj = glmath.perspective(math.radians(self.fov_deg), aspect, self.near, self.far)

        gl.glUseProgram(prog)
        _set_mat4(gl, prog, "model", glmath.identity())
        _set_mat4(gl, prog, "view", view)
        _set_mat4(gl, prog, "projection", proj)
        _set_mat3(gl, prog, "normalMatrix", glmath.identity()[:3, :3].copy())
        _set_vec3(gl, prog, "object_color", (0.60, 0.62, 0.66))
        _set_float(gl, prog, "alpha", 1.0)

        self._apply_lights(gl, prog, cam_pos)

        gl.glBindVertexArray(self._scene_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self._scene_vertex_count)
        gl.glBindVertexArray(0)

    def _apply_lights(self, gl, prog, cam_pos) -> None:
        # Map lights, plus a camera "headlight" so the area around the player is
        # always lit during bring-up (bounded by the shader's 8-light array).
        lights = list(self._lights[:7])
        lights.append({
            "pos": tuple(cam_pos), "color": (1.0, 0.97, 0.92),
            "intensity": 1.0, "radius": 1400.0,
        })
        gl.glUniform1i(gl.glGetUniformLocation(prog, "active_lights"), len(lights))
        for i, lt in enumerate(lights):
            base = f"lights[{i}]"
            _set_vec3(gl, prog, f"{base}.position", lt["pos"])
            _set_vec3(gl, prog, f"{base}.color", lt["color"])
            _set_float(gl, prog, f"{base}.intensity", lt["intensity"])
            _set_float(gl, prog, f"{base}.radius", lt["radius"])
            loc = gl.glGetUniformLocation(prog, f"{base}.shadowIndex")
            if loc != -1:
                gl.glUniform1i(loc, -1)


# ----------------------------------------------------------------------
# Small uniform helpers (kept local so the module has no hard GL import)
# ----------------------------------------------------------------------
def _gl():
    import os
    if os.environ.get("ANDROID_ARGUMENT"):
        os.environ.setdefault("PYOPENGL_PLATFORM", "egl")  # GLES via EGL
    import OpenGL.GL as gl
    return gl


def _set_mat4(gl, prog, name, mat) -> None:
    loc = gl.glGetUniformLocation(prog, name)
    if loc != -1:
        gl.glUniformMatrix4fv(loc, 1, gl.GL_TRUE, mat)


def _set_mat3(gl, prog, name, mat) -> None:
    loc = gl.glGetUniformLocation(prog, name)
    if loc != -1:
        gl.glUniformMatrix3fv(loc, 1, gl.GL_TRUE, mat)


def _set_vec3(gl, prog, name, vec) -> None:
    loc = gl.glGetUniformLocation(prog, name)
    if loc != -1:
        gl.glUniform3f(loc, float(vec[0]), float(vec[1]), float(vec[2]))


def _set_float(gl, prog, name, value) -> None:
    loc = gl.glGetUniformLocation(prog, name)
    if loc != -1:
        gl.glUniform1f(loc, float(value))
