"""
engine/renderer_core.py  –  Base renderer with shared logic for Forward/Deferred

Provides:
    • Texture management (load_texture, preload_level_textures)
    • Grid drawing (update_grid_buffers, draw_grid)
    • Sprite rendering (draw_sprites, with per‑instance textures)
    • Model loading & drawing (draw_models)
    • Water / Glass / Fog volume rendering
    • Terrain rendering
    • Editor helpers (gizmo, selection outline, face highlight, connection lines,
      path node cubes, portal wireframes)
    • Projected shadows
    • Sorting / splitting helpers
    • VAO creation for cube, sprite, grid, gizmo, etc.
    • Shader management (compilation, hot‑reload, light upload)

Both Renderer_F and Renderer_D inherit from BaseRenderer.
"""

import ctypes
import math
import os
from collections import defaultdict

import glm
import numpy as np
import OpenGL.GL as gl
from OpenGL.GL.shaders import compileProgram, compileShader

from engine.constants import RENDER_MODE_LIT, RENDER_MODE_UNLIT, RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX
from engine.shaders import DEFAULT_SHADERS
from engine.terrain import TERRAIN_VERTEX_SHADER, TERRAIN_FRAGMENT_SHADER
from editor.things import Thing

# Try to import OBJ and GLB loaders
try:
    from .obj_loader import OBJ
except ImportError:
    OBJ = None

try:
    from .glb_loader import GLB
except ImportError:
    GLB = None


# ---------- Utility classes ----------
class UniformCache:
    __slots__ = ('program', '_cache')
    def __init__(self, shader_program):
        self.program = shader_program
        self._cache = {}
    def __getitem__(self, name):
        loc = self._cache.get(name)
        if loc is None:
            loc = gl.glGetUniformLocation(self.program, name)
            self._cache[name] = loc
        return loc
    def preload(self, names):
        for name in names:
            if name not in self._cache:
                self._cache[name] = gl.glGetUniformLocation(self.program, name)
    def get(self, name, default=-1):
        return self._cache.get(name, default)


class ShadowBatch:
    __slots__ = ('positions', 'scales', 'rotations', 'alphas', 'count', 'capacity')
    def __init__(self, capacity=1024):
        self.capacity = capacity
        self.positions = np.zeros((capacity, 3), dtype=np.float32)
        self.scales = np.zeros((capacity, 3), dtype=np.float32)
        self.rotations = np.zeros(capacity, dtype=np.float32)
        self.alphas = np.zeros(capacity, dtype=np.float32)
        self.count = 0
    def reset(self):
        self.count = 0
    def add(self, pos, scale, rotation, alpha):
        if self.count >= self.capacity:
            return False
        i = self.count
        self.positions[i], self.scales[i], self.rotations[i], self.alphas[i] = pos, scale, rotation, alpha
        self.count += 1
        return True


class LODManager:
    __slots__ = ('full_dist_sq', 'cull_dist_sq')
    LOD_FULL, LOD_REDUCED, LOD_CULLED = 0, 1, 2
    def __init__(self, full_dist=500.0, cull_dist=2000.0):
        self.full_dist_sq = full_dist * full_dist
        self.cull_dist_sq = cull_dist * cull_dist
    def get_lod_level(self, brush_pos, camera_pos):
        if isinstance(brush_pos, (list, tuple)):
            dx, dy, dz = brush_pos[0] - camera_pos.x, brush_pos[1] - camera_pos.y, brush_pos[2] - camera_pos.z
        else:
            dx, dy, dz = brush_pos.x - camera_pos.x, brush_pos.y - camera_pos.y, brush_pos.z - camera_pos.z
        dist_sq = dx*dx + dy*dy + dz*dz
        if dist_sq < self.full_dist_sq:
            return self.LOD_FULL
        elif dist_sq < self.cull_dist_sq:
            return self.LOD_REDUCED
        return self.LOD_CULLED


class RenderStats:
    __slots__ = ('total_brushes', 'culled_brushes', 'visible_brushes', 'draw_calls',
                 'shadow_draw_calls', 'total_tris', 'visible_tris', 'batched_draws')
    def __init__(self):
        self.reset()
    def reset(self):
        self.total_brushes = self.culled_brushes = self.visible_brushes = 0
        self.draw_calls = self.shadow_draw_calls = self.batched_draws = 0
        self.total_tris = self.visible_tris = 0


class ShaderLoader:
    def __init__(self, shader_dir='assets/shaders'):
        self.shader_dir = shader_dir
        if not os.path.exists(self.shader_dir):
            try:
                os.makedirs(self.shader_dir)
            except OSError:
                if os.path.exists('shaders'):
                    self.shader_dir = 'shaders'
        self._ensure_defaults()

    def _ensure_defaults(self):
        for filename, source in DEFAULT_SHADERS.items():
            filepath = os.path.join(self.shader_dir, filename)
            try:
                with open(filepath, 'w') as f:
                    f.write(source)
            except Exception as e:
                print(f"Error generating shader {filename}: {e}")

    def _read_source(self, filename):
        filepath = os.path.join(self.shader_dir, filename)
        if not os.path.exists(filepath):
            if os.path.exists(filename):
                filepath = filename
            else:
                raise FileNotFoundError(f"Shader file not found: {filename}")
        with open(filepath, 'r') as f:
            return f.read()

    def compile_shader_program(self, vertex_file, fragment_file, geometry_file=None):
        try:
            vertex_src = self._read_source(vertex_file)
            fragment_src = self._read_source(fragment_file)
            vs = compileShader(vertex_src, gl.GL_VERTEX_SHADER)
            fs = compileShader(fragment_src, gl.GL_FRAGMENT_SHADER)
            if geometry_file:
                geometry_src = self._read_source(geometry_file)
                gs = compileShader(geometry_src, gl.GL_GEOMETRY_SHADER)
                program = compileProgram(vs, fs, gs, validate=False)
            else:
                program = compileProgram(vs, fs, validate=False)
            return program
        except Exception as e:
            print(f"Error compiling shader ({vertex_file}, {fragment_file}): {e}")
            raise

    def compile_from_source(self, vertex_src, fragment_src):
        try:
            vs = compileShader(vertex_src, gl.GL_VERTEX_SHADER)
            fs = compileShader(fragment_src, gl.GL_FRAGMENT_SHADER)
            return compileProgram(vs, fs, validate=False)
        except Exception as e:
            print(f"Error compiling shader from source: {e}")
            raise


# ---------- Helper ----------
def normalize_color(rgb, default=None):
    """Normalise an RGB colour to 0.0-1.0 floats.
    Accepts [0-255] int or [0.0-1.0] float components.
    Returns *default* (or [0.8, 0.8, 0.8]) if rgb is None or malformed.
    """
    if default is None:
        default = [0.8, 0.8, 0.8]
    if not rgb or not isinstance(rgb, (list, tuple)) or len(rgb) < 3:
        return list(default)
    return [c / 255.0 if c > 1.0 else c for c in rgb[:3]]


# ---------- Base Renderer ----------
class BaseRenderer:
    MAX_LIGHTS = 16
    MAX_PORTALS = 8      # maximum portal pairs rendered per frame

    def __init__(self, texture_loader, initial_grid_size, initial_world_size, config=None):
        self.texture_manager = {}
        self.loaded_models = {}
        self.load_texture_callback = texture_loader
        self._identity_mat4 = glm.mat4(1.0)
        self._identity_mat3 = glm.mat3(1.0)
        self.render_stats = RenderStats()
        self.lod_manager = LODManager()

        # Performance flags
        is_arm = self._detect_arm_platform()
        if config is not None:
            self.arm_mode = config.getboolean('Renderer', 'arm_mode', fallback=True)
            self.shadows_enabled = config.getboolean('Renderer', 'shadows_enabled', fallback=not is_arm)
        else:
            self.arm_mode = True
            self.shadows_enabled = not is_arm

        self.fog_quality = 'low'      # 'low' = 16 steps, 'high' = 32 steps
        self.skip_culling_in_renderer = True   # trust pre‑culled data

        self._model_matrix = glm.mat4(1.0)
        self._floor_shadow_batch = ShadowBatch(2048)
        self._wall_shadow_batch = ShadowBatch(1024)

        # Per‑frame caches
        self._frame_lights = []
        self._frame_lights_uploaded = False
        self._current_shader = None

        self._proj_ptr = None
        self._view_ptr = None

        # VAOs and buffers (initialised after shaders compile)
        self.vaos = {'cube': None, 'sprite': None, 'grid': None}
        self.grid_indices_count = 0
        self.sprite_textures = {}
        self.instance_textures = {}
        self._edge_vao = None
        self._edge_vbo = None
        self._gizmo_lines_vbo = None
        self._gizmo_cone_vbo = None
        self._portal_outline_vao = None
        self._portal_outline_vbo = None
        self._portal_normal_vao = None
        self._portal_normal_vbo = None
        self._conn_line_vao = None
        self._conn_line_vbo = None
        self.face_highlight_vao = None
        self.face_highlight_vbo = None
        self._cube_vbo = None
        self._sprite_vbo = None
        self._grid_vbo = None

        self._shader_init_failed = False

        # Shaders (will be filled by subclasses or base helpers)
        self.shaders = {}
        self.uniforms = {}

        # Portal specific GL resources (initialised later)
        self._portal_mask_shader = None
        self._portal_rim_shader = None
        self._portal_quad_vao = None
        self._portal_quad_vbo = None
        self._portal_gl_ready = False
        self._portal_mask_proj_loc = None
        self._portal_mask_view_loc = None
        self._portal_rim_proj_loc = None
        self._portal_rim_view_loc = None
        self._portal_rim_color_loc = None

        # Compile common shaders (simple, sprite, shadow_volume, water, glass, fog, terrain)
        self.shader_loader = ShaderLoader()
        self._compile_common_shaders()

        # Terrain normal map (water)
        self.water_normal_id = self.load_texture('water_normal.png', 'textures')
        self.noise_texture_id = 0

        # Create VAOs after shaders are ready
        if not self._shader_init_failed:
            self.vaos['cube'] = self._create_cube_vao()
            self.vaos['sprite'] = self._create_sprite_vao()
            self.vaos['grid'] = None
            self.update_grid_buffers(initial_world_size, initial_grid_size)
            self._create_gizmo_buffers()
            self.noise_texture_id = self._load_3d_texture('assets/noise_3d.bin')
            self.load_texture('default.png', 'textures')
            self.load_texture('caulk', 'textures')
            self._init_portal_gl()

    # --------------------------------------------------------------------------
    # Platform detection
    # --------------------------------------------------------------------------
    def _detect_arm_platform(self):
        import platform
        import sys
        machine = platform.machine().lower()
        if 'arm' in machine or 'aarch' in machine:
            return True
        if sys.platform == 'win32':
            if os.environ.get('PROCESSOR_ARCHITECTURE', '').upper() == 'ARM64':
                return True
            if os.environ.get('PROCESSOR_ARCHITEW6432', '').upper() == 'ARM64':
                return True
            proc_id = os.environ.get('PROCESSOR_IDENTIFIER', '').lower()
            if 'qualcomm' in proc_id or 'snapdragon' in proc_id or 'arm' in proc_id:
                return True
        return False

    # --------------------------------------------------------------------------
    # Shader compilation helpers
    # --------------------------------------------------------------------------
    def _compile_common_shaders(self):
        """Compile shaders that are shared by both forward and deferred paths."""
        try:
            # simple (for grid, outlines, lines)
            vs_src = DEFAULT_SHADERS.get('simple.vert', '')
            fs_src = DEFAULT_SHADERS.get('simple.frag', '')
            self.shaders['simple'] = self.shader_loader.compile_from_source(vs_src, fs_src)
            self.uniforms['simple'] = UniformCache(self.shaders['simple'])
            self.uniforms['simple'].preload(['projection', 'view', 'model', 'color', 'alpha'])

            # sprite (billboards)
            vs_src = DEFAULT_SHADERS.get('sprite.vert', '')
            fs_src = DEFAULT_SHADERS.get('sprite.frag', '')
            self.shaders['sprite'] = self.shader_loader.compile_from_source(vs_src, fs_src)
            self.uniforms['sprite'] = UniformCache(self.shaders['sprite'])
            self.uniforms['sprite'].preload(['projection', 'view', 'sprite_texture', 'sprite_pos_world', 'sprite_size'])

            # shadow_volume
            vs_src = DEFAULT_SHADERS.get('shadow_volume.vert', '')
            fs_src = DEFAULT_SHADERS.get('shadow_volume.frag', '')
            self.shaders['shadow_volume'] = self.shader_loader.compile_from_source(vs_src, fs_src)
            self.uniforms['shadow_volume'] = UniformCache(self.shaders['shadow_volume'])
            self.uniforms['shadow_volume'].preload(['projection', 'view', 'model', 'light_pos'])

            # water
            vs_src = DEFAULT_SHADERS.get('water.vert', '')
            fs_src = DEFAULT_SHADERS.get('water.frag', '')
            self.shaders['water'] = self.shader_loader.compile_from_source(vs_src, fs_src)
            self.uniforms['water'] = UniformCache(self.shaders['water'])
            self._preload_water_uniforms()

            # glass
            vs_src = DEFAULT_SHADERS.get('glass.vert', '')
            fs_src = DEFAULT_SHADERS.get('glass.frag', '')
            self.shaders['glass'] = self.shader_loader.compile_from_source(vs_src, fs_src)
            self.uniforms['glass'] = UniformCache(self.shaders['glass'])
            self.uniforms['glass'].preload(['projection', 'view', 'model', 'viewPos', 'waterColor',
                                            'distortionStrength', 'causticStrength', 'glassOpacity',
                                            'refractionIndex', 'roughness', 'normalMatrix'])

            # fog – use ARM‑optimised fragment shader (works everywhere)
            fog_vert = DEFAULT_SHADERS.get('fog.vert', '')
            fog_frag = DEFAULT_SHADERS.get('fog_arm.frag', DEFAULT_SHADERS.get('fog.frag', ''))
            self.shaders['fog'] = self.shader_loader.compile_from_source(fog_vert, fog_frag)
            self.uniforms['fog'] = UniformCache(self.shaders['fog'])
            self._preload_fog_uniforms()

            # terrain
            try:
                terrain_vs = compileShader(TERRAIN_VERTEX_SHADER, gl.GL_VERTEX_SHADER)
                terrain_fs = compileShader(TERRAIN_FRAGMENT_SHADER, gl.GL_FRAGMENT_SHADER)
                terrain_program = compileProgram(terrain_vs, terrain_fs, validate=False)
                self.shaders['terrain'] = terrain_program
                self.uniforms['terrain'] = UniformCache(terrain_program)
                self.uniforms['terrain'].preload([
                    'projection', 'view', 'active_lights',
                    'texGrass', 'texRock', 'texSand', 'texSnow',
                    'biomeWeights', 'terrainHeightScale'
                ])
                for i in range(self.MAX_LIGHTS):
                    self.uniforms['terrain'].preload([
                        f'lights[{i}].position', f'lights[{i}].color',
                        f'lights[{i}].intensity', f'lights[{i}].radius'
                    ])
                print("Terrain shader loaded")
            except Exception as e:
                print(f"Terrain shader error: {e}")
                self.shaders['terrain'] = None

            # lit and textured shaders (needed for forward fallback in Deferred)
            if self.arm_mode:
                self._compile_arm_shaders()
            else:
                self._compile_standard_shaders()

            print("Base renderer shaders compiled successfully.")
        except Exception as e:
            print(f"FATAL: Shader Error in BaseRenderer: {e}")
            self._shader_init_failed = True

    def _compile_arm_shaders(self):
        lit_vert = DEFAULT_SHADERS.get('lit_arm.vert', '')
        lit_frag = DEFAULT_SHADERS.get('lit_arm.frag', '')
        lit_shader = self.shader_loader.compile_from_source(lit_vert, lit_frag)
        self.shaders['lit'] = lit_shader
        self.uniforms['lit'] = UniformCache(lit_shader)
        self._preload_lit_uniforms('lit')
        self.uniforms['lit'].preload(['normalMatrix'])

        tex_vert = DEFAULT_SHADERS.get('textured_arm.vert', '')
        tex_frag = DEFAULT_SHADERS.get('textured_arm.frag', '')
        tex_shader = self.shader_loader.compile_from_source(tex_vert, tex_frag)
        self.shaders['textured'] = tex_shader
        self.uniforms['textured'] = UniformCache(tex_shader)
        self._preload_lit_uniforms('textured')
        self.uniforms['textured'].preload(['texture_diffuse', 'tex_scale', 'normalMatrix'])

    def _compile_standard_shaders(self):
        lit_shader = self.shader_loader.compile_shader_program('lit.vert', 'lit.frag')
        self.shaders['lit'] = lit_shader
        self.uniforms['lit'] = UniformCache(lit_shader)
        self._preload_lit_uniforms('lit')
        self.uniforms['lit'].preload(['normalMatrix'])

        tex_shader = self.shader_loader.compile_shader_program('textured.vert', 'textured.frag')
        self.shaders['textured'] = tex_shader
        self.uniforms['textured'] = UniformCache(tex_shader)
        self._preload_lit_uniforms('textured')
        self.uniforms['textured'].preload(['texture_diffuse', 'tex_scale', 'normalMatrix'])

    def _preload_lit_uniforms(self, shader_name):
        uniforms = self.uniforms[shader_name]
        uniforms.preload(['projection', 'view', 'model', 'object_color', 'alpha', 'active_lights'])
        for i in range(self.MAX_LIGHTS):
            uniforms.preload([f'lights[{i}].position', f'lights[{i}].color',
                              f'lights[{i}].intensity', f'lights[{i}].radius'])

    def _preload_water_uniforms(self):
        uniforms = self.uniforms['water']
        uniforms.preload(['projection', 'view', 'model', 'time', 'viewPos', 'normalMap', 'waterOpacity',
                          'waterReflectivity', 'waterTint', 'useWaveDisplacement', 'waveStrength'])

    def _preload_fog_uniforms(self):
        uniforms = self.uniforms['fog']
        uniforms.preload(['projection', 'view', 'model', 'viewPos', 'time', 'noiseTexture',
                          'density', 'fogColor', 'noiseScale', 'object_color', 'alpha', 'inverseModel'])

    # --------------------------------------------------------------------------
    # Texture management
    # --------------------------------------------------------------------------
    def load_texture(self, texture_name, subfolder):
        tex_cache_name = os.path.join(subfolder, texture_name)
        if tex_cache_name in self.texture_manager:
            return self.texture_manager[tex_cache_name]

        if texture_name == 'default.png':
            tex_id = gl.glGenTextures(1)
            self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 1, 1, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE,
                           (gl.GLubyte * 4)(255, 255, 255, 255))
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            return tex_id

        if texture_name == 'caulk':
            tex_id = gl.glGenTextures(1)
            self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 2, 2, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE,
                           (gl.GLubyte * 16)(255, 0, 255, 255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 0, 255, 255))
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            return tex_id

        texture_path = os.path.join('assets', subfolder, texture_name)
        if not os.path.exists(texture_path):
            return self.load_texture('default.png', 'textures')

        try:
            from PIL import Image
            img = Image.open(texture_path).convert("RGBA")
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
            tex_id = gl.glGenTextures(1)
            self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, img.width, img.height, 0,
                           gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, img.tobytes())
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            return tex_id
        except Exception as e:
            print(f"Error loading texture '{texture_name}': {e}")
            return self.load_texture('default.png', 'textures')

    def preload_level_textures(self, brushes):
        texture_set = set()
        for brush in brushes:
            for face_tex in brush.get('textures', {}).values():
                if face_tex and face_tex != 'caulk.jpg':
                    texture_set.add(face_tex)
        for tex_name in texture_set:
            self.load_texture(tex_name, 'textures')

    def _load_3d_texture(self, filepath, size=32):
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            if len(data) != size ** 3:
                return 0
            texture_id = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_3D, texture_id)
            for param in [(gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT), (gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT),
                          (gl.GL_TEXTURE_WRAP_R, gl.GL_REPEAT), (gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
                          (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)]:
                gl.glTexParameteri(gl.GL_TEXTURE_3D, *param)
            gl.glTexImage3D(gl.GL_TEXTURE_3D, 0, gl.GL_R8, size, size, size, 0,
                            gl.GL_RED, gl.GL_UNSIGNED_BYTE, data)
            return texture_id
        except Exception:
            return 0

    # --------------------------------------------------------------------------
    # Grid
    # --------------------------------------------------------------------------
    def update_grid_buffers(self, world_size, grid_size):
        if self.vaos.get('grid') is None and self.vaos.get('cube') is None:
            if grid_size <= 0 or self._shader_init_failed:
                return
        if grid_size <= 0:
            if self.vaos['grid']:
                gl.glDeleteVertexArrays(1, [self.vaos['grid']])
                if hasattr(self, '_grid_vbo') and self._grid_vbo:
                    gl.glDeleteBuffers(1, [self._grid_vbo])
                    self._grid_vbo = None
                self.vaos['grid'] = None
            return
        s, g = world_size, grid_size
        lines = [[-s, 0, i, s, 0, i, i, 0, -s, i, 0, s] for i in range(-s, s+1, g)]
        grid_vertices = np.array(lines, dtype=np.float32).flatten()
        self.grid_indices_count = len(grid_vertices) // 3
        if self.vaos['grid']:
            gl.glDeleteVertexArrays(1, [self.vaos['grid']])
        if hasattr(self, '_grid_vbo') and self._grid_vbo:
            gl.glDeleteBuffers(1, [self._grid_vbo])
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, grid_vertices.nbytes, grid_vertices, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)
        self._grid_vbo = vbo
        self.vaos['grid'] = vao

    def draw_grid(self, projection, view, grid_indices_count, play_mode=False, grid_visible=True):
        if not self.vaos['grid'] or play_mode or not grid_visible or 'simple' not in self.shaders:
            return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(self._identity_mat4))
        gl.glUniform3f(uniforms['color'], 0.2, 0.2, 0.2)
        gl.glUniform1f(uniforms['alpha'], 1.0)
        gl.glBindVertexArray(self.vaos['grid'])
        gl.glDrawArrays(gl.GL_LINES, 0, grid_indices_count)
        gl.glBindVertexArray(0)

    # --------------------------------------------------------------------------
    # Terrain
    # --------------------------------------------------------------------------
    def setup_terrain_shader(self, terrain):
        if 'terrain' not in self.shaders or not self.shaders['terrain']:
            return
        terrain.shader_program = self.shaders['terrain']
        terrain.uniforms = {
            'projection': self.uniforms['terrain']['projection'],
            'view': self.uniforms['terrain']['view'],
            'active_lights': self.uniforms['terrain']['active_lights'],
            'texGrass': self.uniforms['terrain']['texGrass'],
            'texRock': self.uniforms['terrain']['texRock'],
            'texSand': self.uniforms['terrain']['texSand'],
            'texSnow': self.uniforms['terrain']['texSnow'],
            'biomeWeights': self.uniforms['terrain']['biomeWeights'],
            'terrainHeightScale': self.uniforms['terrain']['terrainHeightScale'],
        }
        for i in range(self.MAX_LIGHTS):
            terrain.uniforms[f'lights[{i}].position'] = self.uniforms['terrain'][f'lights[{i}].position']
            terrain.uniforms[f'lights[{i}].color'] = self.uniforms['terrain'][f'lights[{i}].color']
            terrain.uniforms[f'lights[{i}].intensity'] = self.uniforms['terrain'][f'lights[{i}].intensity']
            terrain.uniforms[f'lights[{i}].radius'] = self.uniforms['terrain'][f'lights[{i}].radius']

    def _ensure_terrain_textures(self, terrain):
        mappings = [('grass_tex', 'grass.jpg'), ('rock_tex', 'rock.jpg'),
                    ('sand_tex', 'sand.jpg'), ('snow_tex', 'snow.jpg')]
        self.load_texture('default.png', 'textures')
        for attr, filename in mappings:
            current_id = getattr(terrain, attr, 0)
            if not current_id or current_id == -1:
                new_id = self.load_texture(filename, 'textures/terrain')
                setattr(terrain, attr, new_id)

    def render_terrain(self, projection, view, camera_pos, terrain, lights, frustum_planes=None):
        if terrain is None or not terrain.enabled:
            return
        self._ensure_terrain_textures(terrain)
        if not terrain.shader_program:
            self.setup_terrain_shader(terrain)
        active_lights_count = len(lights) if lights else 0
        gl.glDisable(gl.GL_CULL_FACE)
        if hasattr(terrain, 'get_tri_count'):
            self.render_stats.visible_tris += terrain.get_tri_count()
        terrain.update_and_render(projection, view, camera_pos, frustum_planes, lights, active_lights_count)

    # --------------------------------------------------------------------------
    # Models
    # --------------------------------------------------------------------------
    def load_model(self, filename):
        """Load a 3D model (OBJ or GLB)."""
        if filename in self.loaded_models:
            return self.loaded_models[filename]

        full_path = os.path.join('assets', 'models', filename)
        if not os.path.exists(full_path):
            full_path = filename

        if not os.path.exists(full_path):
            print(f"Failed to load model: {filename}")
            return None

        print(f"Loading model: {full_path}")

        # Determine format by extension
        ext = os.path.splitext(filename)[1].lower()

        if ext == '.glb':
            if GLB is None:
                print(f"[Renderer] GLB support not available (glb_loader not found)")
                return None
            model = GLB(full_path)
        elif ext in ('.obj', ''):
            if OBJ is None:
                print(f"[Renderer] OBJ support not available (obj_loader not found)")
                return None
            model = OBJ(full_path)
        else:
            print(f"[Renderer] Unsupported model format: {ext}")
            return None

        if model.is_loaded:
            self.loaded_models[filename] = model
            return model

        print(f"Failed to load model: {filename}")
        return None

    def draw_models(self, projection, view, camera_pos, models, lights, config):
        if not models:
            return

        lit_shader = self.shaders.get('lit')
        textured_shader = self.shaders.get('textured')
        current_shader = None
        gl.glDisable(gl.GL_CULL_FACE)

        for thing in models:
            model_file = thing.properties.get('model_path')
            if not model_file:
                continue
            obj = self.load_model(model_file)
            if not obj or not obj.is_loaded:
                continue

            self.render_stats.visible_tris += (obj.vertex_count // 3)

            pos = thing.pos
            scale = thing.properties.get('scale', 1.0)
            if isinstance(scale, (int, float)):
                scale = [scale, scale, scale]
            rot = thing.properties.get('rotation', [0, 0, 0])

            mat = glm.translate(self._identity_mat4, glm.vec3(*pos))
            mat = glm.rotate(mat, glm.radians(rot[1]), glm.vec3(0, 1, 0))
            mat = glm.rotate(mat, glm.radians(rot[0]), glm.vec3(1, 0, 0))
            mat = glm.rotate(mat, glm.radians(rot[2]), glm.vec3(0, 0, 1))
            mat = glm.scale(mat, glm.vec3(*scale))

            gl.glBindVertexArray(obj.vao)
            manual_texture = thing.properties.get('texture')

            if obj.groups and not manual_texture:
                for group in obj.groups:
                    mat_name = group['material']
                    material = obj.materials.get(mat_name, {'color': [0.8,0.8,0.8], 'texture': None})
                    use_texture = material.get('texture')
                    if use_texture and textured_shader:
                        if current_shader != textured_shader:
                            gl.glUseProgram(textured_shader)
                            current_shader = textured_shader
                            u = self.uniforms['textured']
                            gl.glUniformMatrix4fv(u['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
                            gl.glUniformMatrix4fv(u['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
                            self._upload_lights_once('textured', lights)
                            gl.glActiveTexture(gl.GL_TEXTURE0)
                            gl.glUniform1i(u['texture_diffuse'], 0)
                        # Resolve texture path relative to MTL directory first
                        resolved_path = self._resolve_model_texture_path(material, use_texture)
                        if resolved_path and os.path.exists(resolved_path):
                            # Load from resolved absolute path
                            tex_cache_name = f"model_tex:{resolved_path}"
                            if tex_cache_name in self.texture_manager:
                                tex_id = self.texture_manager[tex_cache_name]
                            else:
                                from PIL import Image
                                img = Image.open(resolved_path).convert("RGBA")
                                img = img.transpose(Image.FLIP_TOP_BOTTOM)
                                tex_id = gl.glGenTextures(1)
                                self.texture_manager[tex_cache_name] = tex_id
                                gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
                                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
                                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
                                gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
                                gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, img.width, img.height, 0,
                                               gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, img.tobytes())
                                gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
                        else:
                            tex_id = self.load_texture(use_texture, 'textures')
                        gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                        gl.glUniformMatrix4fv(self.uniforms['textured']['model'], 1, gl.GL_FALSE, glm.value_ptr(mat))
                    elif lit_shader:
                        if current_shader != lit_shader:
                            gl.glUseProgram(lit_shader)
                            current_shader = lit_shader
                            u = self.uniforms['lit']
                            gl.glUniformMatrix4fv(u['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
                            gl.glUniformMatrix4fv(u['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
                            self._upload_lights_once('lit', lights)
                        color = material.get('color', [0.8,0.8,0.8])
                        gl.glUniform3fv(self.uniforms['lit']['object_color'], 1, color)
                        gl.glUniform1f(self.uniforms['lit']['alpha'], 1.0)
                        gl.glUniformMatrix4fv(self.uniforms['lit']['model'], 1, gl.GL_FALSE, glm.value_ptr(mat))
                    # Draw the group - indexed or non-indexed
                    if group.get('indexed', False) and getattr(obj, 'ebo', None) is not None:
                        gl.glDrawElements(gl.GL_TRIANGLES, group['count'], gl.GL_UNSIGNED_INT,
                                          ctypes.c_void_p(group['start'] * 4))
                    else:
                        gl.glDrawArrays(gl.GL_TRIANGLES, group['start'], group['count'])
            else:
                tex_name = manual_texture
                target_shader = textured_shader if tex_name else lit_shader
                if target_shader == textured_shader:
                    if current_shader != textured_shader:
                        gl.glUseProgram(textured_shader)
                        current_shader = textured_shader
                        u = self.uniforms['textured']
                        gl.glUniformMatrix4fv(u['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
                        gl.glUniformMatrix4fv(u['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
                        self._upload_lights_once('textured', lights)
                        gl.glActiveTexture(gl.GL_TEXTURE0)
                        gl.glUniform1i(u['texture_diffuse'], 0)
                    resolved_path = self._resolve_model_texture_path({'texture': tex_name}, tex_name)
                    if resolved_path and os.path.exists(resolved_path) and not resolved_path.startswith('assets'):
                        # Load from resolved absolute path
                        tex_cache_name = f"model_tex:{resolved_path}"
                        if tex_cache_name in self.texture_manager:
                            tex_id = self.texture_manager[tex_cache_name]
                        else:
                            from PIL import Image
                            img = Image.open(resolved_path).convert("RGBA")
                            img = img.transpose(Image.FLIP_TOP_BOTTOM)
                            tex_id = gl.glGenTextures(1)
                            self.texture_manager[tex_cache_name] = tex_id
                            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
                            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
                            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
                            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
                            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, img.width, img.height, 0,
                                           gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, img.tobytes())
                            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
                    else:
                        tex_id = self.load_texture(tex_name, 'textures')
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                    gl.glUniformMatrix4fv(self.uniforms['textured']['model'], 1, gl.GL_FALSE, glm.value_ptr(mat))
                elif lit_shader:
                    if current_shader != lit_shader:
                        gl.glUseProgram(lit_shader)
                        current_shader = lit_shader
                        u = self.uniforms['lit']
                        gl.glUniformMatrix4fv(u['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
                        gl.glUniformMatrix4fv(u['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
                        self._upload_lights_once('lit', lights)
                    col = thing.properties.get('color', [0.8, 0.8, 0.8])
                    gl.glUniform3fv(self.uniforms['lit']['object_color'], 1, col)
                    gl.glUniform1f(self.uniforms['lit']['alpha'], 1.0)
                    gl.glUniformMatrix4fv(self.uniforms['lit']['model'], 1, gl.GL_FALSE, glm.value_ptr(mat))
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, obj.vertex_count)
            self.render_stats.draw_calls += 1

        gl.glBindVertexArray(0)
        gl.glEnable(gl.GL_CULL_FACE)
    def set_sprite_textures(self, textures):
        self.sprite_textures = textures

    def set_instance_textures(self, textures):
        self.instance_textures = textures

    def draw_sprites(self, projection, view, things_to_draw, sprite_textures, instance_textures=None):
        if not things_to_draw or 'sprite' not in self.shaders:
            return

        shader, uniforms = self.shaders['sprite'], self.uniforms['sprite']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(uniforms['sprite_texture'], 0)
        pos_loc, size_loc = uniforms['sprite_pos_world'], uniforms['sprite_size']
        gl.glBindVertexArray(self.vaos['sprite'])

        from editor.things import Portal, Light, LogicSpawner, LogicCamera, Monster, Pickup, LogicGate, LogicRelay, LogicTimer, LevelChanger

        current_tex = None
        for thing in things_to_draw:
            if Portal is not None and isinstance(thing, Portal):
                continue

            # Monster snapshot dict
            if isinstance(thing, dict) and 'dead' in thing:
                if thing.get('dead'):
                    custom = thing.get('custom_dead', '')
                    sprite_type = 'dead'
                elif thing.get('is_shooting'):
                    custom = thing.get('custom_shoot', '')
                    sprite_type = 'shoot'
                else:
                    custom = thing.get('custom_idle', '')
                    sprite_type = 'idle'

                mtype = thing.get('monster_type', 'human')
                variant = thing.get('variant', '<None>')
                tex_key = f"msprite_{mtype}_{variant}_{sprite_type}_{custom}"
                tex_id = sprite_textures.get(tex_key)
                if tex_id is None:
                    if custom:
                        custom_clean = custom.replace('assets/', '', 1)
                        subfolder = os.path.dirname(custom_clean)
                        filename = os.path.basename(custom_clean)
                    else:
                        if variant and variant != '<None>':
                            subfolder = f"sprites/monsters/{mtype}/{variant}"
                        else:
                            subfolder = f"sprites/monsters/{mtype}"
                        filename = f"{sprite_type}.png"
                    tex_id = self.load_texture(filename, subfolder)
                    if not tex_id and variant and variant != '<None>':
                        subfolder = f"sprites/monsters/{mtype}"
                        tex_id = self.load_texture(filename, subfolder)
                    if tex_id:
                        self.sprite_textures[tex_key] = tex_id

                if tex_id and tex_id != current_tex:
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                    current_tex = tex_id

                gl.glUniform3fv(pos_loc, 1, thing['pos'])
                w = thing.get('sprite_width', 128)
                h = thing.get('sprite_height', 128)
                gl.glUniform2f(size_loc, float(w), float(h))
                gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
                continue

            tex_id = None
            if instance_textures:
                tex_id = instance_textures.get(id(thing))

            if tex_id is None:
                class_name = thing.__class__.__name__
                tex_id = sprite_textures.get(class_name)
                if tex_id is None:
                    if isinstance(thing, LogicSpawner):
                        tex_id = self.load_texture('logic_spawner.png', 'sprites')
                        if tex_id: self.sprite_textures['LogicSpawner'] = tex_id
                    elif isinstance(thing, LogicCamera):
                        tex_id = self.load_texture('logic_camera.png', 'sprites')
                        if tex_id: self.sprite_textures['LogicCamera'] = tex_id
                    else:
                        tex_id = sprite_textures.get(class_name)

            if tex_id:
                if tex_id != current_tex:
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                    current_tex = tex_id
                gl.glUniform3fv(pos_loc, 1, thing.pos)
                if isinstance(thing, Light):
                    gl.glUniform2f(size_loc, 16.0, 16.0)
                elif isinstance(thing, (LogicSpawner, LogicCamera)):
                    gl.glUniform2f(size_loc, 32.0, 32.0)
                else:
                    gl.glUniform2f(size_loc, 32.0, 32.0)
                gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)

        gl.glBindVertexArray(0)

    # --------------------------------------------------------------------------
    # Water / Glass / Fog
    # --------------------------------------------------------------------------
    def draw_water_brushes(self, projection, view, camera_pos, brushes, lights, config):
        if not brushes or 'water' not in self.shaders:
            return
        shader, uniforms = self.shaders['water'], self.uniforms['water']
        gl.glUseProgram(shader)
        self._upload_lights_once('water', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniform3fv(uniforms['viewPos'], 1, glm.value_ptr(camera_pos))
        gl.glUniform1f(uniforms['time'], config.get('time', 0.0))
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.water_normal_id)
        gl.glUniform1i(uniforms['normalMap'], 0)

        opacity_loc = uniforms['waterOpacity']
        reflectivity_loc = uniforms['waterReflectivity']
        tint_loc, model_loc = uniforms['waterTint'], uniforms['model']
        wave_enable_loc = uniforms['useWaveDisplacement']
        wave_str_loc = uniforms['waveStrength']

        gl.glBindVertexArray(self.vaos['cube'])
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        for brush in brushes:
            model_matrix = self._brush_model_matrix(brush)
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            gl.glUniform1f(opacity_loc, brush.get('water_opacity', 0.5))
            gl.glUniform1f(reflectivity_loc, brush.get('water_reflectivity', 0.5))
            gl.glUniform3fv(tint_loc, 1, brush.get('water_tint', [0.0, 0.4, 0.6]))
            gl.glUniform1i(wave_enable_loc, int(brush.get('water_wave_enabled', False)))
            gl.glUniform1f(wave_str_loc, brush.get('water_wave_height', 0.5))

            if brush.get('water_plane', False):
                gl.glDrawArrays(gl.GL_TRIANGLES, 30, 6)
            else:
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 24)
                gl.glDrawArrays(gl.GL_TRIANGLES, 30, 6)
            self.render_stats.draw_calls += 1
        gl.glBindVertexArray(0)

    def draw_glass_brushes(self, projection, view, camera_pos, brushes, lights, config):
        if not brushes or 'glass' not in self.shaders:
            return
        shader, uniforms = self.shaders['glass'], self.uniforms['glass']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniform3fv(uniforms['viewPos'], 1, glm.value_ptr(camera_pos))

        model_loc = uniforms['model']
        water_color_loc = uniforms['waterColor']
        distortion_loc = uniforms['distortionStrength']
        caustic_loc = uniforms['causticStrength']
        opacity_loc = uniforms['glassOpacity']
        refraction_loc = uniforms['refractionIndex']
        roughness_loc = uniforms['roughness']
        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None: normal_mat_loc = -1

        gl.glBindVertexArray(self.vaos['cube'])
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glCullFace(gl.GL_BACK)

        for brush in brushes:
            model_matrix = self._brush_model_matrix(brush)
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            if normal_mat_loc > 0:
                normal_mat = self._compute_normal_matrix(model_matrix, brush)
                gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(normal_mat))
            glass_color = brush.get('glass_color', [0.7, 0.85, 0.95])
            opacity = brush.get('glass_opacity', 0.3)
            distortion = brush.get('glass_distortion', 0.5)
            refraction = brush.get('glass_refraction', 1.5)
            roughness = brush.get('glass_roughness', 0.0)
            fresnel = brush.get('glass_fresnel', 0.5)

            gl.glUniform3fv(water_color_loc, 1, glass_color)
            gl.glUniform1f(distortion_loc, distortion)
            gl.glUniform1f(caustic_loc, fresnel)
            gl.glUniform1f(opacity_loc, opacity)
            gl.glUniform1f(refraction_loc, refraction)
            gl.glUniform1f(roughness_loc, roughness)

            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            self.render_stats.draw_calls += 1

        gl.glDisable(gl.GL_CULL_FACE)
        gl.glBindVertexArray(0)

    def draw_fog_volumes(self, projection, view, camera_pos, brushes, lights, config):
        if not brushes or 'fog' not in self.shaders:
            return
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        shader, uniforms = self.shaders['fog'], self.uniforms['fog']
        gl.glUseProgram(shader)
        self._upload_lights_once('fog', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniform3fv(uniforms['viewPos'], 1, glm.value_ptr(camera_pos))
        gl.glUniform1f(uniforms['time'], config.get('time', 0.0))
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_3D, self.noise_texture_id)
        gl.glUniform1i(uniforms['noiseTexture'], 1)
        gl.glBindVertexArray(self.vaos['cube'])
        gl.glEnable(gl.GL_CULL_FACE)

        model_loc = uniforms['model']
        inv_model_loc = uniforms['inverseModel']
        density_loc = uniforms['density']
        fog_color_loc = uniforms['fogColor']
        noise_scale_loc = uniforms['noiseScale']
        object_color_loc = uniforms['object_color']
        alpha_loc = uniforms['alpha']

        for brush in brushes:
            model_matrix = self._brush_model_matrix(brush)
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            inv_matrix = glm.inverse(model_matrix)
            gl.glUniformMatrix4fv(inv_model_loc, 1, gl.GL_FALSE, glm.value_ptr(inv_matrix))
            f_color = brush.get('fog_color', [0.5, 0.6, 0.7])
            gl.glUniform1f(density_loc, brush.get('fog_density', 0.01))
            gl.glUniform3fv(fog_color_loc, 1, f_color)
            gl.glUniform1f(noise_scale_loc, brush.get('fog_noise_scale', 0.01))
            gl.glUniform3fv(object_color_loc, 1, f_color)
            gl.glUniform1f(alpha_loc, 0.4)

            gl.glCullFace(gl.GL_FRONT)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 24)
            gl.glDrawArrays(gl.GL_TRIANGLES, 30, 6)
            gl.glCullFace(gl.GL_BACK)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 24)
            gl.glDrawArrays(gl.GL_TRIANGLES, 30, 6)

        gl.glDisable(gl.GL_CULL_FACE)
        gl.glBindVertexArray(0)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    # --------------------------------------------------------------------------
    # Helpers for sorting and matrix utilities
    # --------------------------------------------------------------------------
    def _sort_objects(self, brushes, things, config):
        opaque, transparent, sprites, fog, water, glass, glow = [], [], [], [], [], [], []
        is_play, show_sprites = config.get('play_mode', False), config.get('show_sprites_in_play_mode', False)

        for brush in brushes:
            if brush.get('hidden'):
                continue
            if brush.get('is_water', False) or brush.get('shader') == 'Water' or \
               any('water' in (t or '').lower() for t in brush.get('textures', {}).values()):
                water.append(brush)
            elif brush.get('is_fog') or brush.get('shader') == 'Fog':
                fog.append(brush)
            elif brush.get('shader') == 'Glass':
                glass.append(brush)
            elif brush.get('shader') == 'Glow':
                glow.append(brush)
            elif brush.get('is_trigger'):
                if not is_play:
                    transparent.append(brush)
            else:
                opaque.append(brush)

        if not is_play:
            from editor.things import PathNode
            sprites = [t for t in things if (isinstance(t, Thing) or (isinstance(t, dict) and 'monster_type' in t))
                       and not (PathNode is not None and isinstance(t, PathNode))]
        else:
            from editor.things import PathNode, Portal, Pickup, Monster, LogicGate, LogicRelay, LogicTimer, LevelChanger
            for t in things:
                if PathNode is not None and isinstance(t, PathNode):
                    continue
                if Portal is not None and isinstance(t, Portal):
                    sprites.append(t)
                    continue
                if isinstance(t, dict) and 'monster_type' in t:
                    sprites.append(t)
                elif isinstance(t, Thing):
                    if isinstance(t, Pickup):
                        sprites.append(t)
                    elif isinstance(t, (Monster, LogicGate, LogicRelay, LogicTimer, LevelChanger)):
                        sprites.append(t)
                    elif show_sprites:
                        sprites.append(t)
        return opaque, transparent, sprites, fog, water, glass, glow

    def _split_opaque(self, brushes):
        textured, solid = [], []
        for b in brushes:
            if any(t and t not in ('default.png', 'caulk.jpg') for t in b.get('textures', {}).values()):
                textured.append(b)
            else:
                solid.append(b)
        return textured, solid

    def _brush_model_matrix(self, brush):
        pos = brush.get('pos', [0, 0, 0])
        size = brush.get('size', [64, 64, 64])
        mat = glm.translate(self._identity_mat4, glm.vec3(*pos))
        angle = brush.get('_rot_angle')
        if angle:
            axis_raw = brush.get('rot_axis', [0, 1, 0])
            axis = glm.vec3(*axis_raw)
            if glm.length(axis) > 0.001:
                mat = glm.rotate(mat, glm.radians(float(angle)), glm.normalize(axis))
        mat = glm.scale(mat, glm.vec3(*size))
        return mat

    def _compute_normal_matrix(self, model_matrix, brush=None):
        # brush parameter is accepted for API compatibility with Renderer_F's
        # caching override, but not used at the base-class level.
        mat3 = glm.mat3(model_matrix)
        try:
            return glm.transpose(glm.inverse(mat3))
        except Exception:
            return self._identity_mat3

    def _distance_sq(self, pos1, pos2):
        if isinstance(pos1, (list, tuple)):
            return (pos1[0]-pos2.x)**2 + (pos1[1]-pos2.y)**2 + (pos1[2]-pos2.z)**2
        return (pos1.x-pos2.x)**2 + (pos1.y-pos2.y)**2 + (pos1.z-pos2.z)**2

    def _upload_lights_once(self, shader_name, lights):
        if shader_name not in self.uniforms:
            return
        uniforms = self.uniforms[shader_name]
        num_lights = min(len(lights), self.MAX_LIGHTS)
        gl.glUniform1i(uniforms['active_lights'], num_lights)
        for i in range(num_lights):
            light = lights[i]
            gl.glUniform3fv(uniforms[f'lights[{i}].position'], 1, light.pos)
            gl.glUniform3fv(uniforms[f'lights[{i}].color'], 1, light.get_color())
            gl.glUniform1f(uniforms[f'lights[{i}].intensity'], light.get_intensity())
            gl.glUniform1f(uniforms[f'lights[{i}].radius'], light.get_radius())

    def _resolve_model_texture_path(self, material, texture_name):
        """
        Resolve a texture path from an MTL material.
        Checks in order:
          1. Relative to the MTL file's directory (correct for MTL references)
          2. assets/textures/ (global fallback)
          3. assets/models/ (legacy fallback)
        Returns the resolved path or None if not found.
        """
        if not texture_name:
            return None

        # 1. Try relative to the MTL file's directory (most correct for MTL refs)
        mtl_dir = material.get('mtl_dir', '')
        if mtl_dir:
            resolved = os.path.join(mtl_dir, texture_name)
            if os.path.exists(resolved):
                return resolved

        # 2. Try assets/textures/ (global fallback)
        resolved = os.path.join('assets', 'textures', texture_name)
        if os.path.exists(resolved):
            return resolved

        # 3. Try assets/models/ (legacy fallback)
        resolved = os.path.join('assets', 'models', texture_name)
        if os.path.exists(resolved):
            return resolved

        # 4. Return as-is and let the loader handle errors
        return texture_name

    # --------------------------------------------------------------------------
    # Editor helpers (outlines, gizmo, etc.)
    # --------------------------------------------------------------------------
    def draw_selected_brush_outline(self, projection, view, brush):
        if 'simple' not in self.shaders:
            return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        pos = brush.get('pos', [0, 0, 0])
        size = brush.get('size', [64, 64, 64])
        model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*pos)), glm.vec3(*size))
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
        gl.glUniform3f(uniforms['color'], 1.0, 1.0, 0.0)
        gl.glUniform1f(uniforms['alpha'], 1.0)
        if not hasattr(self, '_edge_vao') or self._edge_vao is None:
            edge_vertices = np.array([
                -0.5,-0.5,-0.5,  0.5,-0.5,-0.5,  0.5,-0.5,-0.5,  0.5,-0.5, 0.5,
                 0.5,-0.5, 0.5, -0.5,-0.5, 0.5, -0.5,-0.5, 0.5, -0.5,-0.5,-0.5,
                -0.5, 0.5,-0.5,  0.5, 0.5,-0.5,  0.5, 0.5,-0.5,  0.5, 0.5, 0.5,
                 0.5, 0.5, 0.5, -0.5, 0.5, 0.5, -0.5, 0.5, 0.5, -0.5, 0.5,-0.5,
                -0.5,-0.5,-0.5, -0.5, 0.5,-0.5,  0.5,-0.5,-0.5,  0.5, 0.5,-0.5,
                 0.5,-0.5, 0.5,  0.5, 0.5, 0.5, -0.5,-0.5, 0.5, -0.5, 0.5, 0.5,
            ], dtype=np.float32)
            self._edge_vao = gl.glGenVertexArrays(1)
            gl.glBindVertexArray(self._edge_vao)
            vbo = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, edge_vertices.nbytes, edge_vertices, gl.GL_STATIC_DRAW)
            gl.glEnableVertexAttribArray(0)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
            gl.glBindVertexArray(0)
            self._edge_vbo = vbo
        gl.glLineWidth(1.0)
        gl.glBindVertexArray(self._edge_vao)
        gl.glDrawArrays(gl.GL_LINES, 0, 24)
        gl.glBindVertexArray(0)

    def draw_face_highlight(self, projection, view, brush, face_name):
        if 'simple' not in self.shaders:
            return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(self._identity_mat4))
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glUniform3f(uniforms['color'], 0.8, 0.2, 0.9)
        gl.glUniform1f(uniforms['alpha'], 0.4)

        pos, size = brush['pos'], brush['size']
        hx, hy, hz = size[0]/2, size[1]/2, size[2]/2
        cx, cy, cz = pos[0], pos[1], pos[2]
        bias = 0.5
        verts = []
        if face_name == 'north':
            z = cz + hz + bias
            verts = [cx-hx, cy-hy, z, cx+hx, cy-hy, z, cx+hx, cy+hy, z,
                     cx-hx, cy-hy, z, cx+hx, cy+hy, z, cx-hx, cy+hy, z]
        elif face_name == 'south':
            z = cz - hz - bias
            verts = [cx+hx, cy-hy, z, cx-hx, cy-hy, z, cx-hx, cy+hy, z,
                     cx+hx, cy-hy, z, cx-hx, cy+hy, z, cx+hx, cy+hy, z]
        elif face_name == 'east':
            x = cx + hx + bias
            verts = [x, cy-hy, cz+hz, x, cy-hy, cz-hz, x, cy+hy, cz-hz,
                     x, cy-hy, cz+hz, x, cy+hy, cz-hz, x, cy+hy, cz+hz]
        elif face_name == 'west':
            x = cx - hx - bias
            verts = [x, cy-hy, cz-hz, x, cy-hy, cz+hz, x, cy+hy, cz+hz,
                     x, cy-hy, cz-hz, x, cy+hy, cz+hz, x, cy+hy, cz-hz]
        elif face_name == 'top':
            y = cy + hy + bias
            verts = [cx-hx, y, cz+hz, cx+hx, y, cz+hz, cx+hx, y, cz-hz,
                     cx-hx, y, cz+hz, cx+hx, y, cz-hz, cx-hx, y, cz-hz]
        elif face_name == 'down':
            y = cy - hy - bias
            verts = [cx-hx, y, cz-hz, cx+hx, y, cz-hz, cx+hx, y, cz+hz,
                     cx-hx, y, cz-hz, cx+hx, y, cz+hz, cx-hx, y, cz+hz]
        if not verts:
            return

        v_data = np.array(verts, dtype=np.float32)
        if self.face_highlight_vao is None:
            self.face_highlight_vao = gl.glGenVertexArrays(1)
            self.face_highlight_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self.face_highlight_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.face_highlight_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 6*3*4, None, gl.GL_DYNAMIC_DRAW)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
            gl.glEnableVertexAttribArray(0)
            gl.glBindVertexArray(0)

        gl.glBindVertexArray(self.face_highlight_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.face_highlight_vbo)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, v_data.nbytes, v_data)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)

        gl.glUniform3f(uniforms['color'], 1.0, 1.0, 1.0)
        gl.glUniform1f(uniforms['alpha'], 1.0)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        gl.glBindVertexArray(0)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(0)

    def draw_path_node_cubes(self, projection, view, things):
        if 'simple' not in self.shaders:
            return
        try:
            from editor.things import PathNode
        except ImportError:
            PathNode = None
        if PathNode is None:
            return
        nodes = [t for t in things if isinstance(t, PathNode)]
        if not nodes:
            return

        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniform3f(uniforms['color'], 1.0, 0.5, 0.0)
        gl.glUniform1f(uniforms['alpha'], 1.0)
        cube_size = 16.0
        gl.glBindVertexArray(self.vaos['cube'])
        for node in nodes:
            pos = node.pos
            model_matrix = glm.scale(glm.translate(self._identity_mat4,
                                                   glm.vec3(float(pos[0]), float(pos[1]), float(pos[2]))),
                                     glm.vec3(cube_size, cube_size, cube_size))
            gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            self.render_stats.draw_calls += 1
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

    def draw_portal_wireframes(self, projection, view, things, play_mode=False):
        try:
            from editor.things import Portal
        except ImportError:
            Portal = None
        if Portal is None or 'simple' not in self.shaders:
            return

        portal_things = [t for t in things if isinstance(t, Portal) and t.properties.get('show_rim', True)]
        if not portal_things:
            return

        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniform1f(uniforms['alpha'], 1.0)

        # Outline VAO
        if self._portal_outline_vao is None:
            self._portal_outline_vao = gl.glGenVertexArrays(1)
            self._portal_outline_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self._portal_outline_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_outline_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 4*3*4, None, gl.GL_DYNAMIC_DRAW)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
            gl.glEnableVertexAttribArray(0)
            gl.glBindVertexArray(0)
        # Normal arrow VAO
        if self._portal_normal_vao is None:
            self._portal_normal_vao = gl.glGenVertexArrays(1)
            self._portal_normal_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self._portal_normal_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_normal_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 2*3*4, None, gl.GL_DYNAMIC_DRAW)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
            gl.glEnableVertexAttribArray(0)
            gl.glBindVertexArray(0)

        gl.glLineWidth(1.0)
        model_loc = uniforms['model']
        color_loc = uniforms['color']
        gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(self._identity_mat4))

        for portal in portal_things:
            raw = portal.properties.get('color', [255, 255, 255])
            color = normalize_color(raw, default=[1.0,1.0,1.0])
            r,g,b = color
            if not portal.is_active():
                r,g,b = r*0.4, g*0.4, b*0.4

            # Red wireframe for unlinked or broken portal pairs
            target_name = portal.properties.get('portal_target', '')
            target_exists = target_name and any(
                isinstance(t, Portal) and t.properties.get('name') == target_name
                for t in things
                if t is not portal
            )
            if not target_exists:
                r, g, b = 0.86, 0.24, 0.24  # red — no valid target
            corners = portal.get_corners_world()
            vdata = np.array(corners, dtype=np.float32).flatten()
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_outline_vbo)
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, vdata.nbytes, vdata)
            gl.glUniform3f(color_loc, r, g, b)
            gl.glBindVertexArray(self._portal_outline_vao)
            gl.glDrawArrays(gl.GL_LINE_LOOP, 0, 4)

            # normal arrow
            cx = float(portal.pos[0]); cy = float(portal.pos[1]); cz = float(portal.pos[2])
            nx, ny, nz = portal.get_normal()
            arrow_len = portal.get_width() * 0.4
            nline = np.array([cx, cy, cz, cx+nx*arrow_len, cy+ny*arrow_len, cz+nz*arrow_len], dtype=np.float32)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_normal_vbo)
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, nline.nbytes, nline)
            gl.glUniform3f(color_loc, min(1.0, r*1.6), min(1.0, g*1.6), min(1.0, b*1.6))
            gl.glBindVertexArray(self._portal_normal_vao)
            gl.glDrawArrays(gl.GL_LINES, 0, 2)

        gl.glLineWidth(1.0)
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

    def draw_connection_lines(self, projection, view, connections):
        if not connections or 'simple' not in self.shaders:
            return
        line_data = []
        line_colors = []
        for conn in connections:
            sx,sy,sz = conn['src']
            dx,dy,dz = conn['dst']
            line_data.extend([float(sx), float(sy), float(sz), float(dx), float(dy), float(dz)])
            line_colors.append(conn.get('color', (0.0,1.0,1.0)))
        if not line_data:
            return
        vertices = np.array(line_data, dtype=np.float32)
        if self._conn_line_vao is None:
            self._conn_line_vao = gl.glGenVertexArrays(1)
            self._conn_line_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self._conn_line_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._conn_line_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 1024*1024, None, gl.GL_DYNAMIC_DRAW)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
            gl.glEnableVertexAttribArray(0)
            gl.glBindVertexArray(0)
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(self._identity_mat4))
        gl.glUniform1f(uniforms['alpha'], 1.0)
        gl.glBindVertexArray(self._conn_line_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._conn_line_vbo)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)
        color_loc = uniforms['color']
        for i, (r,g,b) in enumerate(line_colors):
            gl.glUniform3f(color_loc, r, g, b)
            gl.glDrawArrays(gl.GL_LINES, i*2, 2)
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

    def render_gizmo(self, projection, view, position):
        if 'simple' not in self.shaders:
            return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        pos_vec = glm.vec3(*position) if isinstance(position, (list, tuple)) else position
        base = glm.scale(glm.translate(self._identity_mat4, pos_vec), glm.vec3(32.0))
        model_loc, color_loc = uniforms['model'], uniforms['color']
        gl.glUniform1f(uniforms['alpha'], 1.0)
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(base))
        for i,c in enumerate([(1,0,0), (0,1,0), (0,0,1)]):
            gl.glUniform3f(color_loc, *c)
            gl.glDrawArrays(gl.GL_LINES, i*2, 2)
        gl.glBindVertexArray(self.vao_gizmo_cone)
        for axis, c, rot in [((1,0,0), (1,0,0), glm.rotate(base, glm.radians(-90), glm.vec3(0,0,1))),
                             ((0,1,0), (0,1,0), base),
                             ((0,0,1), (0,0,1), glm.rotate(base, glm.radians(90), glm.vec3(1,0,0)))]:
            m = glm.translate(rot if axis[1] else glm.translate(base, glm.vec3(*axis)), glm.vec3(0,1,0) if axis[1] else glm.vec3(0,0,0))
            if axis[0]: m = glm.translate(glm.rotate(base, glm.radians(-90), glm.vec3(0,0,1)), glm.vec3(0,1,0))
            if axis[2]: m = glm.translate(glm.rotate(base, glm.radians(90), glm.vec3(1,0,0)), glm.vec3(0,1,0))
            if axis[1]: m = glm.translate(base, glm.vec3(0,1,0))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(m))
            gl.glUniform3f(color_loc, *c)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)
        gl.glBindVertexArray(0)

    def render_projected_shadows_optimized(self, projection, view, camera_pos, all_brushes, shadow_lights):
        if 'shadow_volume' not in self.shaders:
            return
        shader = self.shaders['shadow_volume']
        uniforms = self.uniforms['shadow_volume']
        gl.glUseProgram(shader)
        self._current_shader = shader
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glBindVertexArray(self.vaos['cube'])
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDepthFunc(gl.GL_LEQUAL)
        gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glPolygonOffset(-1.0, -1.0)
        model_loc = uniforms['model']
        light_pos_loc = uniforms.get('light_pos', -1)
        FLOOR_Y = 0.0
        shadow_count = 0
        for light in shadow_lights:
            lpos = light.pos
            lx, ly, lz = float(lpos[0]), float(lpos[1]), float(lpos[2])
            light_radius = float(light.properties.get('radius', 512.0))
            light_radius_sq = light_radius * light_radius
            light_intensity = float(light.properties.get('intensity', 1.0))
            if light_pos_loc is not None and light_pos_loc >= 0:
                gl.glUniform3f(light_pos_loc, lx, ly, lz)
            if ly <= FLOOR_Y:
                continue
            for brush in all_brushes:
                if brush.get('hidden') or brush.get('is_trigger') or brush.get('is_fog') or \
                   brush.get('is_water') or brush.get('shader') in ('Water','Fog','Glass','Glow'):
                    continue
                bpos = brush.get('pos', [0,0,0])
                bx, by, bz = float(bpos[0]), float(bpos[1]), float(bpos[2])
                dx,dy,dz = bx-lx, by-ly, bz-lz
                dist_sq = dx*dx+dy*dy+dz*dz
                if dist_sq > light_radius_sq:
                    continue
                bsize = brush.get('size', [64,64,64])
                bsx, bsy, bsz = float(bsize[0]), float(bsize[1]), float(bsize[2])
                nx, ny, nz, nd = 0.0, 1.0, 0.0, -FLOOR_Y
                dot_val = nx*lx + ny*ly + nz*lz + nd  # = ly - FLOOR_Y
                shadow_mat = glm.mat4(
                    glm.vec4(dot_val - lx*nx, -ly*nx,       -lz*nx,       -nx),
                    glm.vec4(-lx*ny,          dot_val - ly*ny, -lz*ny,     -ny),
                    glm.vec4(-lx*nz,          -ly*nz,       dot_val - lz*nz, -nz),
                    glm.vec4(-lx*nd,          -ly*nd,       -lz*nd,       dot_val - nd)
                )
                brush_model = glm.scale(glm.translate(self._identity_mat4, glm.vec3(bx,by,bz)), glm.vec3(bsx,bsy,bsz))
                final = shadow_mat * brush_model
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(final))
                dist_ratio = min(1.0, dist_sq / light_radius_sq)
                alpha = max(0.05, (1.0 - dist_ratio) * min(light_intensity, 1.0) * 0.6)
                # currently shadow_volume.frag uses fixed alpha, ignoring this uniform
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
                shadow_count += 1
                self.render_stats.draw_calls += 1
        gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glBindVertexArray(0)
        self.render_stats.shadow_draw_calls = shadow_count

    # --------------------------------------------------------------------------
    # Portal rendering (used by deferred/forward as needed)
    # --------------------------------------------------------------------------
    def _init_portal_gl(self):
        mask_vert = DEFAULT_SHADERS.get('portal_mask.vert', '')
        mask_frag = DEFAULT_SHADERS.get('portal_mask.frag', '')
        rim_vert  = DEFAULT_SHADERS.get('portal_rim.vert', '')
        rim_frag  = DEFAULT_SHADERS.get('portal_rim.frag', '')
        try:
            self._portal_mask_shader = self.shader_loader.compile_from_source(mask_vert, mask_frag)
            self._portal_rim_shader = self.shader_loader.compile_from_source(rim_vert, rim_frag)
        except Exception as e:
            print(f"[Portal] Shader compile error: {e}")
            return
        self._portal_quad_vao = gl.glGenVertexArrays(1)
        self._portal_quad_vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self._portal_quad_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_quad_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, 4*3*4, None, gl.GL_DYNAMIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)
        self._portal_mask_proj_loc = gl.glGetUniformLocation(self._portal_mask_shader, 'projection')
        self._portal_mask_view_loc = gl.glGetUniformLocation(self._portal_mask_shader, 'view')
        self._portal_rim_proj_loc  = gl.glGetUniformLocation(self._portal_rim_shader,  'projection')
        self._portal_rim_view_loc  = gl.glGetUniformLocation(self._portal_rim_shader,  'view')
        self._portal_rim_color_loc = gl.glGetUniformLocation(self._portal_rim_shader,  'rim_color')
        self._portal_gl_ready = True
        print("[Portal] GL resources initialised")

    def draw_portals(self, portal_things, projection, main_view, camera_pos,
                     brushes, things, lights, config, draw_scene_fn):
        if not self._portal_gl_ready or not portal_things:
            return
        from editor.things import Portal
        by_name = {}
        for p in portal_things:
            name = p.properties.get('name', '')
            if name:
                by_name[name] = p
        rendered_pairs = set()
        proj_ptr = glm.value_ptr(projection)
        stencil_id = 1
        for portal_a in portal_things:
            if not portal_a.is_active():
                continue
            target_name = portal_a.properties.get('portal_target', '')
            if not target_name:
                continue
            portal_b = by_name.get(target_name)
            if portal_b is None or not portal_b.is_active():
                continue
            pair_key = frozenset({id(portal_a), id(portal_b)})
            if pair_key in rendered_pairs:
                continue
            rendered_pairs.add(pair_key)
            if stencil_id > self.MAX_PORTALS:
                break
            self._draw_one_portal(portal_a, portal_b, projection, proj_ptr, main_view, camera_pos,
                                  brushes, things, lights, config, draw_scene_fn, stencil_id)
            stencil_id += 1
        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glStencilMask(0xFF)
        gl.glColorMask(gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glClear(gl.GL_STENCIL_BUFFER_BIT)

    def _draw_one_portal(self, portal_a, portal_b, projection, proj_ptr, main_view, camera_pos,
                         brushes, things, lights, config, draw_scene_fn, stencil_id):
        corners_a = portal_a.get_corners_world()
        view_ptr = glm.value_ptr(main_view)
        gl.glDisable(gl.GL_CULL_FACE)
        # mask pass
        gl.glEnable(gl.GL_STENCIL_TEST)
        gl.glStencilMask(0xFF)
        gl.glClear(gl.GL_STENCIL_BUFFER_BIT)
        gl.glColorMask(gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glStencilFunc(gl.GL_ALWAYS, stencil_id, 0xFF)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_REPLACE)
        self._portal_upload_quad(corners_a)
        gl.glUseProgram(self._portal_mask_shader)
        gl.glUniformMatrix4fv(self._portal_mask_proj_loc, 1, gl.GL_FALSE, proj_ptr)
        gl.glUniformMatrix4fv(self._portal_mask_view_loc, 1, gl.GL_FALSE, view_ptr)
        gl.glBindVertexArray(self._portal_quad_vao)
        gl.glDrawArrays(gl.GL_TRIANGLE_FAN, 0, 4)
        # depth prime to far
        gl.glColorMask(gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDepthFunc(gl.GL_ALWAYS)
        gl.glStencilFunc(gl.GL_EQUAL, stencil_id, 0xFF)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)
        gl.glDepthRange(1.0, 1.0)
        self._portal_upload_quad(corners_a)
        gl.glUseProgram(self._portal_mask_shader)
        gl.glUniformMatrix4fv(self._portal_mask_proj_loc, 1, gl.GL_FALSE, proj_ptr)
        gl.glUniformMatrix4fv(self._portal_mask_view_loc, 1, gl.GL_FALSE, view_ptr)
        gl.glDrawArrays(gl.GL_TRIANGLE_FAN, 0, 4)
        gl.glDepthRange(0.0, 1.0)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glColorMask(gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE)
        # virtual scene
        virtual_view, virtual_cam = self._portal_build_virtual_view(portal_a, portal_b, main_view, camera_pos)
        self._portal_virtual_view = virtual_view
        self._portal_virtual_proj = projection
        gl.glStencilFunc(gl.GL_EQUAL, stencil_id, 0xFF)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)
        gl.glStencilMask(0x00)
        old_proj_ptr = self._proj_ptr
        old_view_ptr = self._view_ptr
        self._proj_ptr = glm.value_ptr(self._portal_virtual_proj)
        self._view_ptr = glm.value_ptr(self._portal_virtual_view)
        self._current_shader = None
        draw_scene_fn(projection, virtual_view, virtual_cam, brushes, things, lights, config)
        self._proj_ptr = old_proj_ptr
        self._view_ptr = old_view_ptr
        self._current_shader = None
        gl.glStencilMask(0xFF)
        # rim glow (border only)
        if portal_a.properties.get('show_rim', True):
            gl.glDisable(gl.GL_STENCIL_TEST)
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE)
            raw_col = portal_a.properties.get('color', [255,255,255])
            color = normalize_color(raw_col, default=[1.0,1.0,1.0])
            r,g,b = color
            self._portal_upload_quad(corners_a)
            gl.glUseProgram(self._portal_rim_shader)
            gl.glUniformMatrix4fv(self._portal_rim_proj_loc, 1, gl.GL_FALSE, proj_ptr)
            gl.glUniformMatrix4fv(self._portal_rim_view_loc, 1, gl.GL_FALSE, view_ptr)
            gl.glUniform4f(self._portal_rim_color_loc, r, g, b, 0.55)
            gl.glBindVertexArray(self._portal_quad_vao)
            gl.glDrawArrays(gl.GL_LINE_LOOP, 0, 4)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glBindVertexArray(0)

    def _portal_upload_quad(self, corners):
        vdata = np.array(corners, dtype=np.float32).flatten()
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_quad_vbo)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, vdata.nbytes, vdata)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

    def _portal_build_virtual_view(self, portal_a, portal_b, current_view, camera_pos):
        import math
        yaw_a = portal_a.get_yaw_radians()
        yaw_b = portal_b.get_yaw_radians()
        pos_a = glm.vec3(*portal_a.pos)
        pos_b = glm.vec3(*portal_b.pos)
        cam = glm.vec3(*camera_pos)
        normal_a = glm.vec3(*portal_a.get_normal())
        to_player = cam - pos_a
        player_side = glm.dot(to_player, normal_a)
        delta_yaw = yaw_a - yaw_b
        if player_side >= 0:
            delta_yaw += math.pi
        cos_d = math.cos(delta_yaw)
        sin_d = math.sin(delta_yaw)
        relative = cam - pos_a
        rotated_pos = glm.vec3(
            relative.x * cos_d - relative.z * sin_d,
            relative.y,
            relative.x * sin_d + relative.z * cos_d
        )
        virtual_cam = pos_b + rotated_pos
        fwd = -glm.vec3(current_view[0][2], current_view[1][2], current_view[2][2])
        new_fwd = glm.vec3(
            fwd.x * cos_d - fwd.z * sin_d,
            fwd.y,
            fwd.x * sin_d + fwd.z * cos_d
        )
        new_fwd = glm.normalize(new_fwd)
        return glm.lookAt(virtual_cam, virtual_cam + new_fwd, glm.vec3(0,1,0)), virtual_cam

    # --------------------------------------------------------------------------
    # VAO creation
    # --------------------------------------------------------------------------
    def _create_cube_vao(self):
        vertices = np.array([
            -0.5,-0.5,-0.5, 0,0,-1, 0,0,  0.5,-0.5,-0.5, 0,0,-1, 1,0,  0.5,0.5,-0.5, 0,0,-1, 1,1,
            0.5,0.5,-0.5, 0,0,-1, 1,1,  -0.5,0.5,-0.5, 0,0,-1, 0,1,  -0.5,-0.5,-0.5, 0,0,-1, 0,0,
            -0.5,-0.5,0.5, 0,0,1, 0,0,  0.5,0.5,0.5, 0,0,1, 1,1,  0.5,-0.5,0.5, 0,0,1, 1,0,
            0.5,0.5,0.5, 0,0,1, 1,1,  -0.5,-0.5,0.5, 0,0,1, 0,0,  -0.5,0.5,0.5, 0,0,1, 0,1,
            -0.5,0.5,0.5, -1,0,0, 1,0,  -0.5,-0.5,-0.5, -1,0,0, 0,1,  -0.5,0.5,-0.5, -1,0,0, 1,1,
            -0.5,-0.5,-0.5, -1,0,0, 0,1,  -0.5,0.5,0.5, -1,0,0, 1,0,  -0.5,-0.5,0.5, -1,0,0, 0,0,
            0.5,0.5,0.5, 1,0,0, 1,0,  0.5,0.5,-0.5, 1,0,0, 1,1,  0.5,-0.5,-0.5, 1,0,0, 0,1,
            0.5,-0.5,-0.5, 1,0,0, 0,1,  0.5,-0.5,0.5, 1,0,0, 0,0,  0.5,0.5,0.5, 1,0,0, 1,0,
            -0.5,-0.5,-0.5, 0,-1,0, 0,1,  0.5,-0.5,0.5, 0,-1,0, 1,0,  0.5,-0.5,-0.5, 0,-1,0, 1,1,
            0.5,-0.5,0.5, 0,-1,0, 1,0,  -0.5,-0.5,-0.5, 0,-1,0, 0,1,  -0.5,-0.5,0.5, 0,-1,0, 0,0,
            -0.5,0.5,-0.5, 0,1,0, 0,1,  0.5,0.5,-0.5, 0,1,0, 1,1,  0.5,0.5,0.5, 0,1,0, 1,0,
            0.5,0.5,0.5, 0,1,0, 1,0,  -0.5,0.5,0.5, 0,1,0, 0,0,  -0.5,0.5,-0.5, 0,1,0, 0,1
        ], dtype=np.float32)
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 32, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(1, 3, gl.GL_FLOAT, gl.GL_FALSE, 32, ctypes.c_void_p(12))
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(2, 2, gl.GL_FLOAT, gl.GL_FALSE, 32, ctypes.c_void_p(24))
        gl.glEnableVertexAttribArray(2)
        gl.glBindVertexArray(0)
        self._cube_vbo = vbo
        return vao

    def _create_sprite_vao(self):
        vertices = np.array([-0.5, -0.5, 0.5, -0.5, -0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)
        self._sprite_vbo = vbo
        return vao

    def _create_gizmo_buffers(self):
        axis_verts = np.array([0,0,0, 1,0,0, 0,0,0, 0,1,0, 0,0,0, 0,0,1], dtype=np.float32)
        self.vao_gizmo_lines = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        self._gizmo_lines_vbo = vbo
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, axis_verts.nbytes, axis_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        cone_verts = []
        for i in range(12):
            t1, t2 = (i/12)*2*np.pi, ((i+1)/12)*2*np.pi
            cone_verts.extend([0,0,0, np.cos(t2)*0.05,0,np.sin(t2)*0.05, np.cos(t1)*0.05,0,np.sin(t1)*0.05])
            cone_verts.extend([0,0.2,0, np.cos(t1)*0.05,0,np.sin(t1)*0.05, np.cos(t2)*0.05,0,np.sin(t2)*0.05])
        self.gizmo_cone_v_count = len(cone_verts)//3
        cone_verts = np.array(cone_verts, dtype=np.float32)
        self.vao_gizmo_cone = gl.glGenVertexArrays(1)
        vbo2 = gl.glGenBuffers(1)
        self._gizmo_cone_vbo = vbo2
        gl.glBindVertexArray(self.vao_gizmo_cone)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo2)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, cone_verts.nbytes, cone_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)

    # --------------------------------------------------------------------------
    # Cleanup
    # --------------------------------------------------------------------------
    def cleanup(self):
        """Release all OpenGL resources owned by the base renderer."""
        # Delete VAOs and VBOs
        for name, vao in self.vaos.items():
            if vao:
                gl.glDeleteVertexArrays(1, [vao])
        if self._edge_vao:
            gl.glDeleteVertexArrays(1, [self._edge_vao])
        if self._edge_vbo:
            gl.glDeleteBuffers(1, [self._edge_vbo])
        if self._gizmo_lines_vbo:
            gl.glDeleteBuffers(1, [self._gizmo_lines_vbo])
        if self._gizmo_cone_vbo:
            gl.glDeleteBuffers(1, [self._gizmo_cone_vbo])
        if self._portal_outline_vao:
            gl.glDeleteVertexArrays(1, [self._portal_outline_vao])
        if self._portal_outline_vbo:
            gl.glDeleteBuffers(1, [self._portal_outline_vbo])
        if self._portal_normal_vao:
            gl.glDeleteVertexArrays(1, [self._portal_normal_vao])
        if self._portal_normal_vbo:
            gl.glDeleteBuffers(1, [self._portal_normal_vbo])
        if self._conn_line_vao:
            gl.glDeleteVertexArrays(1, [self._conn_line_vao])
        if self._conn_line_vbo:
            gl.glDeleteBuffers(1, [self._conn_line_vbo])
        if self.face_highlight_vao:
            gl.glDeleteVertexArrays(1, [self.face_highlight_vao])
        if self.face_highlight_vbo:
            gl.glDeleteBuffers(1, [self.face_highlight_vbo])
        if self._cube_vbo:
            gl.glDeleteBuffers(1, [self._cube_vbo])
        if self._sprite_vbo:
            gl.glDeleteBuffers(1, [self._sprite_vbo])
        if self._grid_vbo:
            gl.glDeleteBuffers(1, [self._grid_vbo])
        # Portal resources
        if self._portal_quad_vao:
            gl.glDeleteVertexArrays(1, [self._portal_quad_vao])
        if self._portal_quad_vbo:
            gl.glDeleteBuffers(1, [self._portal_quad_vbo])
        for prog in self.shaders.values():
            if prog:
                try:
                    gl.glDeleteProgram(prog)
                except Exception:
                    pass
        self.shaders.clear()
        self.uniforms.clear()
        self._shader_init_failed = True
        print("[BaseRenderer] Cleaned up GL resources.")

    # --------------------------------------------------------------------------
    # Abstract method (must be overridden by Forward/Deferred)
    # --------------------------------------------------------------------------
    def render_scene(self, projection, view, camera_pos, brushes, things, selected_object, config):
        raise NotImplementedError("Derived renderer must implement render_scene()")