"""
Headless tests for the native Overhead ("top-down") camera + player sprite.

Runs without a display or OpenGL. Covers:

  1. the overhead camera geometry and mode toggle (LogicThread),
  2. overhead frustum-culling correctness — the view is non-degenerate (a
     straight-down camera would corrupt every plane without the horizontal up
     hint) and culls in/out correctly,
  3. the sprite animation controller (idle vs. walk cycle + facing),
  4. the sprite renderer's facing convention and its no-GL safety.

Run with:  python -m engine.tests.test_overhead   (from the project root)
"""

import math
import os
import sys
import types

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _check(cond, msg):
    if not cond:
        raise AssertionError(msg)
    print(f"  ok: {msg}")


def test_overhead_camera_and_frustum():
    print("[1] native overhead camera geometry + correct frustum")
    import glm
    from engine.logic_thread import LogicThread

    lt = types.SimpleNamespace(camera_mode="Overhead", overhead_height=800.0,
                               overhead_tilt=0.0, overhead_orientation="north",
                               _safe_up=LogicThread._safe_up)
    _check(LogicThread.is_overhead(lt), "is_overhead() true for 'Overhead'")
    _check(not LogicThread.is_overhead(types.SimpleNamespace(camera_mode="First Person")),
           "is_overhead() false for 'First Person'")

    cam, direction, up = LogicThread._overhead_camera(lt, glm.vec3(10, 0, 20), 0.0)
    _check(abs(cam.y - 800.0) < 1e-6 and abs(cam.x - 10) < 1e-6 and abs(cam.z - 20) < 1e-6,
           f"camera floats overhead_height above the player (y={cam.y})")
    _check(direction.y < -0.99, "view points straight down")
    _check(abs(up.y) < 1e-6, "up hint is horizontal (non-degenerate)")

    view = glm.lookAt(cam, cam + direction, up)
    proj = glm.perspective(glm.radians(90.0), 16.0 / 9.0, 1.0, 10000.0)
    fp = types.SimpleNamespace()
    fp._normalize_plane = types.MethodType(LogicThread._normalize_plane, fp)
    planes = LogicThread._extract_frustum_planes(fp, proj * view)
    _check(all(all(math.isfinite(x) for x in p) for p in planes),
           "overhead frustum planes are finite (view not degenerate)")
    _check(LogicThread._aabb_in_frustum(lt, planes, (10, 0, 20), (32, 32, 32)),
           "brush under the player is visible")
    _check(not LogicThread._aabb_in_frustum(lt, planes, (9000, 0, 20), (32, 32, 32)),
           "far brush is culled")


def test_sprite_controller():
    print("[2] sprite controller: idle vs. walk-cycle + facing")
    from engine.overhead_sprite import SpriteController

    sc = SpriteController(walk_fps=6.0, move_epsilon=0.75)
    sc.update((0.0, 0.0, 0.0), facing=0.0, now=0.0)
    _check(sc.frame() == SpriteController.IDLE, "starts idle")
    sc.update((0.2, 0.0, 0.1), facing=1.23, now=0.1)
    _check(not sc.moving and sc.frame() == SpriteController.IDLE, "jitter under epsilon stays idle")
    _check(abs(sc.facing - 1.23) < 1e-9, "facing carried through")

    sc.update((10.0, 0.0, 0.0), facing=0.0, now=0.20)
    _check(sc.moving, "large step counts as moving")
    f1 = sc.frame()
    sc.update((20.0, 0.0, 0.0), facing=0.0, now=0.20 + 1.0 / 6.0 + 1e-3)
    f2 = sc.frame()
    _check({f1, f2} == {SpriteController.WALK_A, SpriteController.WALK_B},
           f"walk frames alternate over time ({f1} -> {f2})")
    sc.update((20.0, 0.0, 0.0), facing=0.0, now=1.0)
    _check(sc.frame() == SpriteController.IDLE, "returns to idle when motion stops")


def test_sprite_facing_and_safety():
    print("[3] sprite facing convention + no-GL safety")
    from engine.overhead_sprite import OverheadSpriteRenderer, SpriteController

    r = OverheadSpriteRenderer()  # no GL needed for the pure angle math
    for deg in (0, 45, 90, 180, 270):
        a = math.radians(deg)
        t = r.facing_theta(a)
        want = (round(math.sin(a), 6), round(math.cos(a), 6))
        got = (round(math.sin(t), 6), round(math.cos(t), 6))
        _check(got == want, f"facing {deg}° points along the heading, not reversed")

    r2 = OverheadSpriteRenderer(frame_files={SpriteController.IDLE: "/nonexistent.png"})
    r2.draw(None, None, (0.0, 0.0, 0.0), 0.0, SpriteController.IDLE)  # must not raise
    _check(r2._ok is False, "renderer disables itself cleanly without GL/assets")


def main():
    test_overhead_camera_and_frustum()
    test_sprite_controller()
    test_sprite_facing_and_safety()
    print("\nALL OVERHEAD TESTS PASSED")


if __name__ == "__main__":
    main()
