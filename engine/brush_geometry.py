"""
Convex brush geometry — angled brushes & clipping.

This module is the geometry foundation for *angled brushes*: brushes that are no
longer axis-aligned boxes but arbitrary **convex polyhedra**, the way classic
Radiant / Hammer brushes work.  A convex brush is stored as the intersection of
a set of half-spaces (planes).  Cutting a brush with a plane — the editor "clip"
operation — is simply *appending a plane* and recomputing the surface polygons.

Representation
--------------
A brush becomes "angled/clipped" the moment it carries a ``geometry`` dict::

    brush['geometry'] = {
        'planes': [
            {'n': [nx, ny, nz],       # outward unit normal
             'd': d,                  # plane offset:  dot(n, p) == d
             'texture': 'Dev/512.jpg' | None,
             'uv_scale': [su, sv]     | None,
             'face': 'top' | 'north' | ... | None},
            ...
        ]
    }

Sign convention: a point ``p`` is **inside** the half-space of a plane when
``dot(n, p) <= d``.  The solid is the intersection of every plane's inside
half-space, so ``p`` is inside the *solid* when that holds for all planes.
``signed_distance(p) = dot(n, p) - d`` is therefore positive *outside* the face.

The plane list is the serialised source of truth (compact, matches the Quake
``.map`` face representation used by ``tools/fio_to_map.py``).  Everything else —
render mesh, 2D silhouette, collision triangles, bounds — is *derived* from it.

This module is intentionally dependency-light (NumPy only, no PyGLM / OpenGL)
so it can be unit-tested head-less and called from any thread, including the
logic thread that builds collision meshes with no GL context current.
"""

import math
import numpy as np

# --------------------------------------------------------------------------
# Tunables
# --------------------------------------------------------------------------

# Half-size of the seed polygon used when turning a plane into a face winding.
# Must comfortably exceed the world extent of any map (Fio maps span a few
# thousand units; MAX_DEPTH is 6000).  float64 keeps precision fine at this
# scale even after many successive clips.
_BOGUS = 262144.0

# Geometric epsilon (world units).  Points closer than this are welded; a plane
# distance within this band counts as "on the plane".
EPS = 1e-4

# Canonical face tags and their outward normals for an axis-aligned box.
# Mapping matches the renderer's face->axis convention:
#   north/south = +/-Z,  east/west = +/-X,  top/down = +/-Y  (Y is up).
_BOX_FACES = (
    ('east',  (1.0, 0.0, 0.0)),
    ('west',  (-1.0, 0.0, 0.0)),
    ('top',   (0.0, 1.0, 0.0)),
    ('down',  (0.0, -1.0, 0.0)),
    ('north', (0.0, 0.0, 1.0)),
    ('south', (0.0, 0.0, -1.0)),
)

FACE_TAGS = tuple(tag for tag, _ in _BOX_FACES)


# --------------------------------------------------------------------------
# Small vector helpers (NumPy, float64)
# --------------------------------------------------------------------------

def _v(seq):
    return np.asarray(seq, dtype=np.float64).reshape(3)


def _normalize(n):
    n = _v(n)
    length = math.sqrt(float(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]))
    if length < 1e-12:
        return np.array([0.0, 1.0, 0.0])
    return n / length


def _poly_normal(verts):
    """Newell's method — robust polygon normal (unit) for a planar loop."""
    n = np.zeros(3)
    m = len(verts)
    for i in range(m):
        a = verts[i]
        b = verts[(i + 1) % m]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    length = math.sqrt(float(n @ n))
    if length < 1e-12:
        return np.array([0.0, 1.0, 0.0])
    return n / length


# --------------------------------------------------------------------------
# Plane construction
# --------------------------------------------------------------------------

def make_plane(normal, point_on_plane, texture=None, uv_scale=None, face=None):
    """Build a plane dict from an outward normal and a point on the plane."""
    n = _normalize(normal)
    d = float(n @ _v(point_on_plane))
    plane = {'n': [float(n[0]), float(n[1]), float(n[2])], 'd': d}
    if texture is not None:
        plane['texture'] = texture
    if uv_scale is not None:
        plane['uv_scale'] = [float(uv_scale[0]), float(uv_scale[1])]
    if face is not None:
        plane['face'] = face
    return plane


def plane_from_points(p1, p2, p3, **kw):
    """Plane through three points; outward normal follows CCW winding p1->p2->p3."""
    p1, p2, p3 = _v(p1), _v(p2), _v(p3)
    n = np.cross(p2 - p1, p3 - p1)
    return make_plane(n, p1, **kw)


def box_planes(pos, size, textures=None, uv_scale=None):
    """Return the six planes of an axis-aligned box (center ``pos``, ``size``).

    Per-face textures / uv scales are inherited from the box's ``textures`` and
    ``uv_scale`` dicts (keyed by face tag) so a clipped box keeps its look.
    """
    c = _v(pos)
    h = _v(size) * 0.5
    textures = textures or {}
    uv_scale = uv_scale or {}
    planes = []
    for tag, nrm in _BOX_FACES:
        nrm = _v(nrm)
        point = c + nrm * h  # a point on that face
        planes.append(make_plane(
            nrm, point,
            texture=textures.get(tag),
            uv_scale=uv_scale.get(tag),
            face=tag,
        ))
    return planes


def _plane_arrays(planes):
    """Vectorised (normals Nx3, offsets N) view of a plane list."""
    normals = np.array([p['n'] for p in planes], dtype=np.float64)
    offsets = np.array([p['d'] for p in planes], dtype=np.float64)
    return normals, offsets


# --------------------------------------------------------------------------
# Windings: planes -> face polygons  (the core CSG step)
# --------------------------------------------------------------------------

def _base_winding(n, d):
    """A large CCW quad lying on plane (n, d), oriented so its normal is +n."""
    n = _normalize(n)
    org = n * d  # closest point on the plane to the origin
    # Tangent basis: pick the world axis least aligned with n.
    axis = int(np.argmin(np.abs(n)))
    up = np.zeros(3)
    up[axis] = 1.0
    up = up - n * float(up @ n)
    up = up / math.sqrt(float(up @ up))
    right = np.cross(n, up)  # right-handed around +n
    up *= _BOGUS
    right *= _BOGUS
    return np.array([
        org - right - up,
        org + right - up,
        org + right + up,
        org - right + up,
    ])


def _clip_winding(verts, n, d, eps=EPS):
    """Sutherland-Hodgman clip: keep the ``dot(n, p) <= d`` (inside) half-space."""
    if len(verts) == 0:
        return verts
    dists = verts @ n - d
    out = []
    m = len(verts)
    for i in range(m):
        a = verts[i]
        da = dists[i]
        if da <= eps:
            out.append(a)
        b = verts[(i + 1) % m]
        db = dists[(i + 1) % m]
        # Edge straddles the plane -> add the intersection point.
        if (da < -eps and db > eps) or (da > eps and db < -eps):
            t = da / (da - db)
            out.append(a + t * (b - a))
    if not out:
        return np.zeros((0, 3))
    return np.array(out)


def _weld(points, eps=EPS):
    """Deduplicate near-coincident points; return (unique Nx3, index remap)."""
    unique = []
    index = []
    scale = 1.0 / max(eps, 1e-9)
    lookup = {}
    for p in points:
        key = (round(float(p[0]) * scale), round(float(p[1]) * scale),
               round(float(p[2]) * scale))
        idx = lookup.get(key)
        if idx is None:
            idx = len(unique)
            lookup[key] = idx
            unique.append(p)
        index.append(idx)
    return (np.array(unique) if unique else np.zeros((0, 3))), index


def compute_windings(planes, eps=EPS):
    """Turn a plane set into (verts, faces).

    ``verts`` is an ``(N, 3)`` float64 array of unique corner points.  ``faces``
    is a list of dicts::

        {'plane': i, 'indices': [...CCW outward...], 'normal': (nx, ny, nz),
         'texture': str|None, 'uv_scale': [su, sv]|None, 'face': tag|None}

    A plane that contributes no surface (redundant / outside the solid) is
    simply omitted.  Returns ``([], [])`` when the plane set encloses no volume.
    """
    raw_faces = []
    all_points = []
    counts = []
    for i, pi in enumerate(planes):
        n_i = _normalize(pi['n'])
        w = _base_winding(n_i, pi['d'])
        for j, pj in enumerate(planes):
            if i == j:
                continue
            w = _clip_winding(w, _v(pj['n']), float(pj['d']), eps)
            if len(w) < 3:
                break
        if len(w) < 3:
            continue
        # Enforce outward orientation (CCW when viewed from +n).
        if float(_poly_normal(w) @ n_i) < 0:
            w = w[::-1]
        raw_faces.append((i, w))
        all_points.append(w)
        counts.append(len(w))

    if not all_points:
        return np.zeros((0, 3)), []

    verts, remap = _weld(np.concatenate(all_points), eps)

    faces = []
    cursor = 0
    for (plane_idx, w), count in zip(raw_faces, counts):
        indices = remap[cursor:cursor + count]
        cursor += count
        # Collapse any duplicate consecutive indices produced by welding.
        dedup = []
        for idx in indices:
            if not dedup or dedup[-1] != idx:
                dedup.append(idx)
        if len(dedup) >= 2 and dedup[0] == dedup[-1]:
            dedup.pop()
        if len(dedup) < 3:
            continue
        p = planes[plane_idx]
        n = _normalize(p['n'])
        faces.append({
            'plane': plane_idx,
            'indices': dedup,
            'normal': (float(n[0]), float(n[1]), float(n[2])),
            'texture': p.get('texture'),
            'uv_scale': p.get('uv_scale'),
            'face': p.get('face'),
        })
    return verts, faces


# --------------------------------------------------------------------------
# High-level geometry object
# --------------------------------------------------------------------------

class ConvexGeometry:
    """Derived, cached surface of a convex brush (built from its plane set)."""

    __slots__ = ('planes', 'verts', 'faces', '_bounds')

    def __init__(self, planes):
        # Store copies so later mutation of the source list can't corrupt us.
        self.planes = [dict(p) for p in planes]
        self.verts, self.faces = compute_windings(self.planes)
        self._bounds = None

    # -- validity ----------------------------------------------------------
    @property
    def is_valid(self):
        """True when the plane set encloses a real (non-degenerate) volume."""
        return len(self.verts) >= 4 and len(self.faces) >= 4

    # -- bounds ------------------------------------------------------------
    @property
    def bounds(self):
        if self._bounds is None:
            if len(self.verts) == 0:
                self._bounds = (np.zeros(3), np.zeros(3))
            else:
                self._bounds = (self.verts.min(axis=0), self.verts.max(axis=0))
        return self._bounds

    def center(self):
        lo, hi = self.bounds
        return (lo + hi) * 0.5

    def extents(self):
        lo, hi = self.bounds
        return hi - lo

    # -- rendering (PR2) ---------------------------------------------------
    def triangulate(self):
        """Fan-triangulate every face.

        Returns ``(positions, normals, uvs)`` as ``float32`` arrays suitable for
        an OpenGL VBO.  UVs are planar-projected onto each face's dominant axis
        and scaled by the face's ``uv_scale`` (defaulting to 1/128, matching the
        engine's texel density).
        """
        positions, normals, uvs = [], [], []
        for face in self.faces:
            idx = face['indices']
            n = np.array(face['normal'])
            uaxis, vaxis = _uv_axes(n)
            su, sv = (face['uv_scale'] or (1.0 / 128.0, 1.0 / 128.0))
            ring = [self.verts[i] for i in idx]
            for k in range(1, len(ring) - 1):
                for p in (ring[0], ring[k], ring[k + 1]):
                    positions.append(p)
                    normals.append(n)
                    uvs.append((float(p @ uaxis) * su, float(p @ vaxis) * sv))
        return (np.array(positions, dtype=np.float32),
                np.array(normals, dtype=np.float32),
                np.array(uvs, dtype=np.float32))

    # -- 2D editor silhouette (PR2) ---------------------------------------
    def silhouette(self, axis1, axis2):
        """Convex-hull outline of the brush projected onto two world axes.

        ``axis1``/``axis2`` are 0/1/2 (x/y/z).  Returns an ordered list of 2D
        points (CCW) — the polygon the 2D views draw instead of a rectangle.
        """
        if len(self.verts) == 0:
            return []
        pts = [(float(v[axis1]), float(v[axis2])) for v in self.verts]
        return _convex_hull_2d(pts)

    # -- collision ---------------------------------------------------------
    def collision_triangles(self):
        """World-space collision triangles in the engine's mesh format::

            [((x0,y0,z0), (x1,y1,z1), (x2,y2,z2)), (nx,ny,nz)), ...]

        Feeds straight into the existing swept-sphere collide-and-slide path,
        so angled brushes collide (and let you walk up slopes) with the same
        battle-tested code that models use.
        """
        tris = []
        for face in self.faces:
            idx = face['indices']
            n = face['normal']
            ring = [self.verts[i] for i in idx]
            v0 = (float(ring[0][0]), float(ring[0][1]), float(ring[0][2]))
            for k in range(1, len(ring) - 1):
                v1 = (float(ring[k][0]), float(ring[k][1]), float(ring[k][2]))
                v2 = (float(ring[k + 1][0]), float(ring[k + 1][1]), float(ring[k + 1][2]))
                tris.append(((v0, v1, v2), n))
        return tris

    def collision_bounds(self):
        lo, hi = self.bounds
        return ([float(lo[0]), float(lo[1]), float(lo[2])],
                [float(hi[0]), float(hi[1]), float(hi[2])])

    # -- point / AABB queries ---------------------------------------------
    def contains_point(self, p, eps=EPS):
        p = _v(p)
        normals, offsets = _plane_arrays(self.planes)
        return bool(np.all(normals @ p - offsets <= eps))

    def aabb_penetration(self, box_center, box_half):
        """Separating-axis penetration of an AABB against this convex solid.

        Returns ``None`` when the box is clear, otherwise ``(normal, depth)`` —
        the minimum-translation direction (unit, pointing out of the solid) and
        the positive depth to push the box's centre to just clear the surface.

        Face planes plus the box's own axis planes (added as bevels) are used as
        candidate separating axes; because clipped boxes retain their axis-
        aligned planes this covers the cases that matter for ramps and wedges.
        """
        c = _v(box_center)
        h = np.abs(_v(box_half))
        best_normal = None
        best_depth = math.inf
        for n, d in _collision_plane_arrays(self.planes):
            # Expand the plane outward by the box's support along n (Minkowski).
            support = float(np.abs(n) @ h)
            dist = float(n @ c) - d - support
            if dist > EPS:
                return None  # a separating axis exists -> no overlap
            depth = -dist  # >= 0, how far inside this expanded plane we are
            if depth < best_depth:
                best_depth = depth
                best_normal = n
        if best_normal is None:
            return None
        return best_normal.copy(), best_depth


# --------------------------------------------------------------------------
# UV + hull helpers
# --------------------------------------------------------------------------

def _uv_axes(normal):
    """Planar UV axes for a face, chosen by its dominant world axis."""
    ax, ay, az = abs(normal[0]), abs(normal[1]), abs(normal[2])
    if az >= ax and az >= ay:            # facing +/-Z
        return np.array([1.0, 0.0, 0.0]), np.array([0.0, -1.0, 0.0])
    if ay >= ax:                          # facing +/-Y (floor/ceiling)
        return np.array([1.0, 0.0, 0.0]), np.array([0.0, 0.0, -1.0])
    return np.array([0.0, 0.0, 1.0]), np.array([0.0, -1.0, 0.0])  # +/-X


def _convex_hull_2d(points):
    """Andrew's monotone chain — CCW hull of 2D points (dedup + collinear-safe)."""
    pts = sorted(set((round(x, 4), round(y, 4)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _collision_plane_arrays(planes):
    """Face planes + the six axis-aligned bevel planes from the vertex bounds.

    The bevels give an AABB-vs-convex test the box-edge separating axes it would
    otherwise miss on the diagonal corners of a wedge.
    """
    out = [(_normalize(p['n']), float(p['d'])) for p in planes]
    verts, _ = compute_windings(planes)
    if len(verts) == 0:
        return out
    lo = verts.min(axis=0)
    hi = verts.max(axis=0)
    for axis in range(3):
        pos = np.zeros(3); pos[axis] = 1.0
        out.append((pos.copy(), float(hi[axis])))
        neg = np.zeros(3); neg[axis] = -1.0
        out.append((neg.copy(), float(-lo[axis])))
    return out


# --------------------------------------------------------------------------
# Clipping (the editor "clip" operation) & rotation
# --------------------------------------------------------------------------

def clip_planes(planes, clip_normal, clip_d, keep_positive=False, texture=None,
                uv_scale=None, face=None):
    """Cut a plane set with a plane; return the plane set of the kept half.

    By default the kept half is the *inside* (``dot(n, p) <= clip_d``) side of
    ``clip_normal``.  ``keep_positive`` keeps the other half instead.  The new
    cut face inherits ``texture`` / ``uv_scale`` (or a sensible default picked
    from the existing faces).
    """
    n = _normalize(clip_normal)
    d = float(clip_d)
    if keep_positive:
        n = -n
        d = -d
    if texture is None:
        texture = _dominant_texture(planes)
    if uv_scale is None:
        uv_scale = _dominant_uv_scale(planes)
    cut = make_plane(n, n * d, texture=texture, uv_scale=uv_scale, face=face)
    return [dict(p) for p in planes] + [cut]


def clip_by_points(planes, p1, p2, p3, keep_positive=False, **kw):
    """Clip by the plane through three points (CCW normal = p1->p2->p3)."""
    cut = plane_from_points(p1, p2, p3)
    return clip_planes(planes, cut['n'], cut['d'], keep_positive=keep_positive, **kw)


def rotate_planes(planes, angle_deg, axis, pivot):
    """Rotate every plane about ``pivot`` around ``axis`` by ``angle_deg``."""
    R = _rotation_matrix(_normalize(axis), math.radians(angle_deg))
    pivot = _v(pivot)
    rotated = []
    for p in planes:
        n = _v(p['n'])
        point = n * float(p['d'])                      # a point on the plane
        n2 = R @ n
        point2 = R @ (point - pivot) + pivot
        q = dict(p)
        q['n'] = [float(n2[0]), float(n2[1]), float(n2[2])]
        q['d'] = float(n2 @ point2)
        rotated.append(q)
    return rotated


def _rotation_matrix(axis, theta):
    x, y, z = axis
    c, s = math.cos(theta), math.sin(theta)
    C = 1.0 - c
    return np.array([
        [c + x * x * C,     x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, c + y * y * C,     y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
    ])


def _dominant_texture(planes):
    for p in planes:
        if p.get('texture'):
            return p['texture']
    return None


def _dominant_uv_scale(planes):
    for p in planes:
        if p.get('uv_scale'):
            return list(p['uv_scale'])
    return None


# --------------------------------------------------------------------------
# Brush-level convenience (operates on the brush dict's 'geometry')
# --------------------------------------------------------------------------

def brush_has_geometry(brush):
    geo = brush.get('geometry')
    return bool(geo and geo.get('planes'))


def geometry_signature(brush):
    """Cheap hashable signature of a brush's geometry, for cache invalidation."""
    geo = brush.get('geometry')
    if not geo:
        return None
    return tuple(
        (round(p['n'][0], 6), round(p['n'][1], 6), round(p['n'][2], 6),
         round(p['d'], 4))
        for p in geo.get('planes', [])
    )


def get_convex(brush):
    """Return a cached :class:`ConvexGeometry` for ``brush`` (or ``None``).

    The result is cached on the brush under the private ``_geo_cache`` key and
    rebuilt only when the plane set changes.  Callers must not serialise that
    key (see ``editor_state._RENDERER_PRIVATE_KEYS`` / ``_GEO_RUNTIME_KEYS``).
    """
    if not brush_has_geometry(brush):
        return None
    sig = geometry_signature(brush)
    cache = brush.get('_geo_cache')
    if cache is not None and brush.get('_geo_cache_sig') == sig:
        return cache
    convex = ConvexGeometry(brush['geometry']['planes'])
    brush['_geo_cache'] = convex
    brush['_geo_cache_sig'] = sig
    return convex


def box_to_geometry(brush):
    """Populate ``brush['geometry']`` from its ``pos``/``size``/textures.

    Idempotent: a brush that already has geometry is left untouched.  Returns
    the brush for chaining.
    """
    if brush_has_geometry(brush):
        return brush
    planes = box_planes(
        brush.get('pos', [0, 0, 0]),
        brush.get('size', [64, 64, 64]),
        textures=brush.get('textures'),
        uv_scale=brush.get('uv_scale'),
    )
    brush['geometry'] = {'planes': [_plane_to_json(p) for p in planes]}
    _invalidate(brush)
    return brush


def sync_brush_bounds(brush):
    """Keep ``pos``/``size`` equal to the geometry's AABB.

    Frustum culling, the spatial grid, shadow casters, the 2D fallback draw and
    ray-picking all read ``pos``/``size`` as a conservative bound; keeping them
    in sync means those systems keep working unchanged for angled brushes.
    """
    convex = get_convex(brush)
    if convex is None or not convex.is_valid:
        return
    c = convex.center()
    e = convex.extents()
    brush['pos'] = [float(c[0]), float(c[1]), float(c[2])]
    brush['size'] = [max(float(e[0]), 1e-3),
                     max(float(e[1]), 1e-3),
                     max(float(e[2]), 1e-3)]


def clip_brush(brush, clip_normal, clip_d, keep_positive=False, texture=None,
               uv_scale=None):
    """Clip ``brush`` in place with a plane, making it an angled brush.

    Converts a box brush to geometry first.  Returns ``True`` on success; leaves
    the brush untouched and returns ``False`` if the cut would empty the brush.
    """
    box_to_geometry(brush)
    new_planes = clip_planes(
        [_plane_from_json(p) for p in brush['geometry']['planes']],
        clip_normal, clip_d, keep_positive=keep_positive,
        texture=texture, uv_scale=uv_scale,
    )
    trial = ConvexGeometry(new_planes)
    if not trial.is_valid:
        return False
    brush['geometry'] = {'planes': [_plane_to_json(p) for p in new_planes]}
    _invalidate(brush)
    brush['_geo_cache'] = trial
    brush['_geo_cache_sig'] = geometry_signature(brush)
    sync_brush_bounds(brush)
    return True


def rotate_brush(brush, angle_deg, axis, pivot=None):
    """Rotate ``brush`` about ``pivot`` (defaults to its centre); makes it angled."""
    box_to_geometry(brush)
    if pivot is None:
        pivot = brush.get('pos', [0, 0, 0])
    new_planes = rotate_planes(
        [_plane_from_json(p) for p in brush['geometry']['planes']],
        angle_deg, axis, pivot,
    )
    trial = ConvexGeometry(new_planes)
    if not trial.is_valid:
        return False
    brush['geometry'] = {'planes': [_plane_to_json(p) for p in new_planes]}
    _invalidate(brush)
    brush['_geo_cache'] = trial
    brush['_geo_cache_sig'] = geometry_signature(brush)
    sync_brush_bounds(brush)
    return True


def build_collision_mesh(brush):
    """Attach mesh-collision data to an angled brush for play mode.

    Sets ``_collision_mode='mesh'`` and fills ``_mesh_triangles`` /
    ``_mesh_bounds`` in the exact format the player's collide-and-slide path
    consumes.  No-op for box brushes (they keep the fast AABB path).  Returns
    ``True`` when mesh data was attached.
    """
    convex = get_convex(brush)
    if convex is None or not convex.is_valid:
        return False
    brush['_collision_mode'] = 'mesh'
    brush['_mesh_triangles'] = convex.collision_triangles()
    brush['_mesh_bounds'] = convex.collision_bounds()
    return True


def is_axis_aligned_box(brush, eps=1e-3):
    """True if a geometry brush is really just an axis-aligned box.

    Lets callers drop redundant geometry back to the compact ``pos``/``size``
    form (e.g. after undoing every clip).
    """
    convex = get_convex(brush)
    if convex is None:
        return True
    if len(convex.faces) != 6:
        return False
    for face in convex.faces:
        n = face['normal']
        aligned = any(abs(abs(n[a]) - 1.0) < eps and
                      abs(n[(a + 1) % 3]) < eps and abs(n[(a + 2) % 3]) < eps
                      for a in range(3))
        if not aligned:
            return False
    return True


# --------------------------------------------------------------------------
# JSON (de)serialisation of a single plane
# --------------------------------------------------------------------------

def _plane_to_json(p):
    out = {'n': [float(p['n'][0]), float(p['n'][1]), float(p['n'][2])],
           'd': float(p['d'])}
    if p.get('texture') is not None:
        out['texture'] = p['texture']
    if p.get('uv_scale') is not None:
        out['uv_scale'] = [float(p['uv_scale'][0]), float(p['uv_scale'][1])]
    if p.get('face') is not None:
        out['face'] = p['face']
    return out


def _plane_from_json(p):
    return dict(p)


def _invalidate(brush):
    brush.pop('_geo_cache', None)
    brush.pop('_geo_cache_sig', None)


# Runtime-only keys written onto brush dicts by this module.  editor_state must
# strip these before serialisation / undo / deepcopy-for-JSON.
GEO_RUNTIME_KEYS = frozenset({
    '_geo_cache', '_geo_cache_sig',
    '_collision_mode', '_mesh_triangles', '_mesh_bounds',
})
