import glm
import math
import numpy as np
import OpenGL.GL as gl
import ctypes 
from editor.things import Thing, Light, Model, LogicSpawner, LogicCamera
try:
    from editor.things import PathNode
except ImportError:
    PathNode = None

try:
    from editor.things import Pickup, Monster, LogicGate, LogicRelay, LogicTimer, LevelChanger
except ImportError:
    Pickup = Monster = LogicGate = LogicRelay = LogicTimer = LevelChanger = None

try:
    from editor.things import Portal
except ImportError:
    Portal = None

from OpenGL.GL.shaders import compileProgram, compileShader 
from engine.constants import RENDER_MODE_LIT, RENDER_MODE_UNLIT, RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX
from engine.monster_constants import MONSTER_SPRITE_SIZES, MONSTER_SPRITE_SIZE_DEFAULT 
from engine.shaders import DEFAULT_SHADERS
from PIL import Image 
import os
from collections import defaultdict
from engine.terrain import TERRAIN_VERTEX_SHADER, TERRAIN_FRAGMENT_SHADER

# Try to import OBJ loader
try:
    from .obj_loader import OBJ
except ImportError:
    OBJ = None


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



# Pre-compute normal matrix on CPU, pass it to shader
ARM_LIT_VERT = """#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
out vec3 FragPos;
out vec3 Normal;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;  // Pre-computed on CPU
void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = normalMatrix * aNormal;  // No inverse() call!
    gl_Position = projection * view * vec4(FragPos, 1.0);
}"""

ARM_LIT_FRAG = """#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
uniform vec3 object_color;
uniform float alpha;
struct Light { vec3 position; vec3 color; float intensity; float radius; };
uniform Light lights[16];
uniform int active_lights;
void main() {
    vec3 norm = normalize(Normal);
    vec3 result = vec3(0.12) * object_color;
    for(int i = 0; i < active_lights && i < 16; i++) {
        vec3 toLight = lights[i].position - FragPos;
        float distSq = dot(toLight, toLight);
        float radiusSq = lights[i].radius * lights[i].radius;
        if(distSq < radiusSq) {
            float dist = sqrt(distSq);
            vec3 lightDir = toLight / dist;
            float diff = max(dot(norm, lightDir), 0.0);
            float att = 1.0 - (dist / lights[i].radius);
            att = att * att;
            result += (diff * lights[i].color * lights[i].intensity * att) * object_color;
        }
    }
    FragColor = vec4(result, alpha);
}"""

ARM_TEXTURED_VERT = """#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;
out vec3 FragPos;
out vec3 Normal;
out vec2 TexCoords;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;
uniform vec2 tex_scale;
void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = normalMatrix * aNormal;
    TexCoords = aTexCoords * tex_scale;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}"""

ARM_TEXTURED_FRAG = """#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
in vec2 TexCoords;
uniform sampler2D texture_diffuse;
struct Light { vec3 position; vec3 color; float intensity; float radius; };
uniform Light lights[16];
uniform int active_lights;
void main() {
    vec4 texColor = texture(texture_diffuse, TexCoords);
    if(texColor.a < 0.1) discard;
    vec3 norm = normalize(Normal);
    vec3 result = vec3(0.12) * texColor.rgb;
    for(int i = 0; i < active_lights && i < 16; i++) {
        vec3 toLight = lights[i].position - FragPos;
        float distSq = dot(toLight, toLight);
        float radiusSq = lights[i].radius * lights[i].radius;
        if(distSq < radiusSq) {
            float dist = sqrt(distSq);
            vec3 lightDir = toLight / dist;
            float diff = max(dot(norm, lightDir), 0.0);
            float att = 1.0 - (dist / lights[i].radius);
            att = att * att;
            result += (diff * lights[i].color * lights[i].intensity * att) * texColor.rgb;
        }
    }
    FragColor = vec4(result, texColor.a);
}"""

# Simplified fog with 16 steps instead of 32
ARM_FOG_FRAG = """#version 330 core
out vec4 FragColor;
in vec3 localPos;
uniform mat4 model;
uniform mat4 inverseModel;   // FIX: pre-computed on CPU, replaces inverse(model) per-fragment
uniform vec3 viewPos;
uniform float density;
uniform vec3 fogColor;
uniform sampler3D noiseTexture;
uniform float noiseScale;
uniform float time;

vec2 intersectBox(vec3 rayOrigin, vec3 rayDir) {
    vec3 tMin = (-0.5 - rayOrigin) / rayDir;
    vec3 tMax = ( 0.5 - rayOrigin) / rayDir;
    vec3 t1 = min(tMin, tMax);
    vec3 t2 = max(tMin, tMax);
    float tNear = max(max(t1.x, t1.y), t1.z);
    float tFar  = min(min(t2.x, t2.y), t2.z);
    return vec2(tNear, tFar);
}

void main() {
    vec3 fragWorldPos   = vec3(model * vec4(localPos, 1.0));
    vec3 rayDirWorld    = normalize(fragWorldPos - viewPos);
    // FIX: inverseModel is a uniform -- no per-fragment inverse() call on GPU.
    vec3 rayOriginLocal = (inverseModel * vec4(viewPos,       1.0)).xyz;
    vec3 rayDirLocal    = normalize((inverseModel * vec4(rayDirWorld, 0.0)).xyz);
    vec2 t = intersectBox(rayOriginLocal, rayDirLocal);
    float tNear = t.x;
    float tFar  = t.y;
    if (tNear >= tFar) discard;
    tNear = max(0.0, tNear);

    // ARM OPTIMIZATION: 16 ray-march steps
    int   num_steps = 16;
    float stepSize  = (tFar - tNear) / float(num_steps);
    vec4  accumulatedColor = vec4(0.0);

    for (int i = 0; i < num_steps; ++i) {
        float currentT   = tNear + float(i) * stepSize;
        vec3  samplePos  = rayOriginLocal + rayDirLocal * currentT;
        vec3  noiseCoord = samplePos * noiseScale + vec3(0.0, 0.0, time * 0.1);
        float noiseValue = texture(noiseTexture, noiseCoord).r;
        float stepDensity   = density * noiseValue;
        float transmittance = exp(-stepDensity * stepSize);
        accumulatedColor.rgb += fogColor * (1.0 - transmittance) * (1.0 - accumulatedColor.a);
        accumulatedColor.a   += (1.0 - transmittance);
        if (accumulatedColor.a > 0.95) break;
    }
    accumulatedColor.a = clamp(accumulatedColor.a, 0.0, 1.0);
    FragColor = accumulatedColor;
}"""

# ── Portal shaders ────────────────────────────────────────────────────────────
# Minimal shaders used exclusively for the stencil-mask and rim-glow passes.
# They declare only aPos (location 0) so they can share the portal quad VAO.

_PORTAL_MASK_VERT = """#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 projection;
uniform mat4 view;
void main() {
    gl_Position = projection * view * vec4(aPos, 1.0);
}"""

_PORTAL_MASK_FRAG = """#version 330 core
out vec4 FragColor;
void main() {
    FragColor = vec4(0.0);
}"""

_PORTAL_RIM_VERT = """#version 330 core
layout(location = 0) in vec3 aPos;
uniform mat4 projection;
uniform mat4 view;
void main() {
    gl_Position = projection * view * vec4(aPos, 1.0);
}"""

_PORTAL_RIM_FRAG = """#version 330 core
out vec4 FragColor;
uniform vec4 rim_color;
void main() {
    FragColor = rim_color;
}"""


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
        """Compile shader from source strings directly."""
        try:
            vs = compileShader(vertex_src, gl.GL_VERTEX_SHADER)
            fs = compileShader(fragment_src, gl.GL_FRAGMENT_SHADER)
            return compileProgram(vs, fs, validate=False)
        except Exception as e:
            print(f"Error compiling shader from source: {e}")
            raise


class RenderStats:
    __slots__ = ('total_brushes', 'culled_brushes', 'visible_brushes', 'draw_calls', 
                 'shadow_draw_calls', 'total_tris', 'visible_tris', 'batched_draws')
    def __init__(self): 
        self.reset()
    def reset(self): 
        self.total_brushes = self.culled_brushes = self.visible_brushes = 0
        self.draw_calls = self.shadow_draw_calls = self.batched_draws = 0
        self.total_tris = self.visible_tris = 0


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
        if dist_sq < self.full_dist_sq: return self.LOD_FULL
        elif dist_sq < self.cull_dist_sq: return self.LOD_REDUCED
        return self.LOD_CULLED


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
        if self.count >= self.capacity: return False
        i = self.count
        self.positions[i], self.scales[i], self.rotations[i], self.alphas[i] = pos, scale, rotation, alpha
        self.count += 1
        return True


class Renderer:
    MAX_LIGHTS = 16
    # Maximum portal pairs rendered per frame.  Keep low for ARM budget.
    MAX_PORTALS = 8
    
    def __init__(self, texture_loader, initial_grid_size, initial_world_size, config=None):
        self.texture_manager = {}
        self.loaded_models = {} 
        self.load_texture_callback = texture_loader
        self._identity_mat4 = glm.mat4(1.0)
        self._identity_mat3 = glm.mat3(1.0)
        self.render_stats = RenderStats()
        self.lod_manager = LODManager()
        
        # PERFORMANCE FLAGS - Read from config with auto-detected defaults
        is_arm = self._detect_arm_platform()
        
        if config is not None:
            self.arm_mode = config.getboolean('Renderer', 'arm_mode', fallback=True)
            self.shadows_enabled = config.getboolean('Renderer', 'shadows_enabled', fallback=not is_arm)
        else:
            # No config provided - use auto-detected defaults
            self.arm_mode = True  # Always beneficial
            self.shadows_enabled = not is_arm  # Off on ARM, On otherwise
        
        self.fog_quality = 'low'  # 'low' = 16 steps, 'high' = 32 steps
        self.skip_culling_in_renderer = True  # Trust pre-culled data from logic thread
        
        self._model_matrix = glm.mat4(1.0)
        self._floor_shadow_batch = ShadowBatch(2048)
        self._wall_shadow_batch = ShadowBatch(1024)
        
        # Cached per-frame data
        self._frame_lights = []
        self._frame_lights_uploaded = False
        self._current_shader = None
        
        # Pre-allocated arrays for batching
        self._batch_matrices = []
        self._batch_colors = []

        # FIX: Initialise vaos/post-shader state BEFORE the try block so they
        # always exist even when shader compilation fails (e.g. macOS ARM
        # framebuffer-validation error).  The real VAOs are created below only
        # when shaders succeed, but having safe defaults prevents the
        # AttributeError crash in paintGL → update_grid_buffers.
        self._shader_init_failed = False
        self.vaos = {'cube': None, 'sprite': None, 'grid': None}
        self.grid_indices_count = 0
        self.sprite_textures = {}
        self.instance_textures = {}
        self._proj_ptr = None
        self._view_ptr = None
        self._edge_vao = None
        self.use_deferred = False  # Reserved for future deferred rendering implementation

        # Portal rendering state — initialised in _init_portal_gl()
        self._portal_mask_shader  = None
        self._portal_rim_shader   = None
        self._portal_quad_vao     = None
        self._portal_quad_vbo     = None
        self._portal_gl_ready     = False

        try:
            self.shader_loader = ShaderLoader()
            self.shaders = {}
            self.uniforms = {}
            
            # Compile ARM-optimized shaders if arm_mode is enabled
            if self.arm_mode:
                print("ARM Mode: Compiling optimized shaders...")
                self._compile_arm_shaders()
            else:
                self._compile_standard_shaders()
            
            # Common shaders (always use file-based)
            for name, files in [('simple', ('simple.vert', 'simple.frag')),
                                ('sprite', ('sprite.vert', 'sprite.frag')),
                                ('shadow_volume', ('shadow_volume.vert', 'shadow_volume.frag')),
                                ('water', ('water.vert', 'water.frag')),
                                ('glass', ('glass.vert', 'glass.frag'))]:
                shader = self.shader_loader.compile_shader_program(*files)
                self.shaders[name] = shader
                self.uniforms[name] = UniformCache(shader)

            self.uniforms['simple'].preload(['projection', 'view', 'model', 'color', 'alpha'])
            self.uniforms['sprite'].preload(['projection', 'view', 'sprite_texture', 'sprite_pos_world', 'sprite_size'])
            self.uniforms['shadow_volume'].preload(['projection', 'view', 'model', 'light_pos'])
            
            self._preload_lit_uniforms('water')
            self.uniforms['water'].preload(['time', 'viewPos', 'normalMap', 'waterOpacity', 'waterReflectivity', 
                                           'waterTint', 'useWaveDisplacement', 'waveStrength'])
            self.water_normal_id = self.load_texture('water_normal.png', 'textures')
            
            # glass.vert declares normalMatrix - preload it so draw_glass_brushes can upload it.
            self.uniforms['glass'].preload(['projection', 'view', 'model', 'viewPos', 'waterColor', 
                                           'distortionStrength', 'causticStrength', 'glassOpacity', 
                                           'refractionIndex', 'roughness', 'normalMatrix'])

            # Terrain shader
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
            
            print(f"Shaders loaded from: {self.shader_loader.shader_dir}")
            print(f"ARM Mode: {self.arm_mode}, Shadows: {self.shadows_enabled}")
        except Exception as e:
            print(f"FATAL: Shader Error: {e}")
            self._shader_init_failed = True
        
        # Create GPU resources only when shaders compiled successfully
        if not self._shader_init_failed:
            self.vaos = {'cube': self._create_cube_vao(), 'sprite': self._create_sprite_vao(), 'grid': None}
            self.grid_indices_count = 0
            self._create_gizmo_buffers()
            self.update_grid_buffers(initial_world_size, initial_grid_size)
            self.noise_texture_id = self._load_3d_texture('assets/noise_3d.bin')
            self.sprite_textures = {}
            self.instance_textures = {}
            self.load_texture('default.png', 'textures')
            self.load_texture('caulk', 'textures')
            # Compile portal-specific shaders after the main GL context is ready
            self._init_portal_gl()

    def _detect_arm_platform(self):
        """Detect if running on ARM or under x64 emulation."""
        import platform
        import sys
        machine = platform.machine().lower()
        
        # Direct ARM detection
        if 'arm' in machine or 'aarch' in machine:
            return True
        
        # Check for Windows ARM emulation markers
        if sys.platform == 'win32':
            if os.environ.get('PROCESSOR_ARCHITECTURE', '').upper() == 'ARM64':
                return True
            if os.environ.get('PROCESSOR_ARCHITEW6432', '').upper() == 'ARM64':
                return True
            proc_id = os.environ.get('PROCESSOR_IDENTIFIER', '').lower()
            if 'qualcomm' in proc_id or 'snapdragon' in proc_id or 'arm' in proc_id:
                return True
        
        return False

    def _compile_arm_shaders(self):
        """Compile ARM-optimized shaders with pre-computed normal matrices."""
        # Lit shader (ARM optimized)
        lit_shader = self.shader_loader.compile_from_source(ARM_LIT_VERT, ARM_LIT_FRAG)
        self.shaders['lit'] = lit_shader
        self.uniforms['lit'] = UniformCache(lit_shader)
        self._preload_lit_uniforms('lit')
        self.uniforms['lit'].preload(['normalMatrix'])
        
        # Textured shader (ARM optimized)
        textured_shader = self.shader_loader.compile_from_source(ARM_TEXTURED_VERT, ARM_TEXTURED_FRAG)
        self.shaders['textured'] = textured_shader
        self.uniforms['textured'] = UniformCache(textured_shader)
        self._preload_lit_uniforms('textured')
        self.uniforms['textured'].preload(['texture_diffuse', 'tex_scale', 'normalMatrix'])
        
        # Fog shader (ARM optimized with fewer ray march steps)
        fog_vert = DEFAULT_SHADERS.get('fog.vert', '')
        fog_shader = self.shader_loader.compile_from_source(fog_vert, ARM_FOG_FRAG)
        self.shaders['fog'] = fog_shader
        self.uniforms['fog'] = UniformCache(fog_shader)
        self._preload_lit_uniforms('fog')
        self.uniforms['fog'].preload(['viewPos', 'time', 'noiseTexture', 'density', 'fogColor',
                                      'noiseScale', 'object_color', 'alpha', 'inverseModel'])
        print("ARM-optimized shaders compiled successfully")

    def _compile_standard_shaders(self):
        """Compile standard file-based shaders."""
        for name, files in [('lit', ('lit.vert', 'lit.frag')),
                            ('textured', ('textured.vert', 'textured.frag')),
                            ('fog', ('fog.vert', 'fog.frag'))]:
            shader = self.shader_loader.compile_shader_program(*files)
            self.shaders[name] = shader
            self.uniforms[name] = UniformCache(shader)
        
        self._preload_lit_uniforms('lit')
        self.uniforms['lit'].preload(['normalMatrix'])
        self._preload_lit_uniforms('textured')
        self.uniforms['textured'].preload(['texture_diffuse', 'tex_scale', 'normalMatrix'])
        self._preload_lit_uniforms('fog')
        self.uniforms['fog'].preload(['viewPos', 'time', 'noiseTexture', 'density', 'fogColor',
                                      'noiseScale', 'object_color', 'alpha', 'inverseModel'])

    def _preload_lit_uniforms(self, shader_name):
        uniforms = self.uniforms[shader_name]
        uniforms.preload(['projection', 'view', 'model', 'object_color', 'alpha', 'active_lights'])
        for i in range(self.MAX_LIGHTS):
            uniforms.preload([f'lights[{i}].position', f'lights[{i}].color', 
                            f'lights[{i}].intensity', f'lights[{i}].radius'])

    def _compute_normal_matrix(self, model_matrix):
        """Pre-compute normal matrix on CPU to avoid expensive inverse() in shader."""
        # Extract the upper-left 3x3 and compute transpose of inverse
        mat3 = glm.mat3(model_matrix)
        # For uniform scaling, we can just use the mat3 directly
        # For non-uniform scaling, we need the full inverse transpose
        try:
            return glm.transpose(glm.inverse(mat3))
        except Exception:
            return self._identity_mat3

    # =========================================================================
    # TEXTURE MANAGEMENT
    # =========================================================================

    def update_grid_buffers(self, world_size, grid_size):
        # FIX: Guard against vaos not being fully initialised (shader init failure)
        if self.vaos.get('grid') is None and self.vaos.get('cube') is None:
            # Shaders failed — no GPU resources available, skip silently
            if grid_size <= 0:
                return
            # Can't create grid VAO without a working GL context, bail out
            if self._shader_init_failed:
                return
        if grid_size <= 0:
            if self.vaos['grid']: 
                gl.glDeleteVertexArrays(1, [self.vaos['grid']])
                # FIX#4: also delete the VBO
                if hasattr(self, '_grid_vbo') and self._grid_vbo:
                    gl.glDeleteBuffers(1, [self._grid_vbo])
                    self._grid_vbo = None
                self.vaos['grid'] = None
            return
        s, g = world_size, grid_size
        lines = [[-s, 0, i, s, 0, i, i, 0, -s, i, 0, s] for i in range(-s, s + 1, g)]
        grid_vertices = np.array(lines, dtype=np.float32).flatten()
        self.grid_indices_count = len(grid_vertices) // 3
        if self.vaos['grid']: 
            gl.glDeleteVertexArrays(1, [self.vaos['grid']])
        # FIX#4: Delete old VBO before creating new one to prevent GPU memory leak
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
    
    def set_sprite_textures(self, textures): 
        self.sprite_textures = textures
    
    def set_instance_textures(self, textures): 
        self.instance_textures = textures

    def load_model(self, filename):
        if OBJ is None:
            return None
        if filename in self.loaded_models:
            return self.loaded_models[filename]
        full_path = os.path.join('assets', 'models', filename)
        if not os.path.exists(full_path):
            full_path = filename
        if os.path.exists(full_path):
            print(f"Loading model: {full_path}")
            model = OBJ(full_path)
            if model.is_loaded:
                self.loaded_models[filename] = model
                return model
        print(f"Failed to load model: {filename}")
        return None

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
            gl.glTexImage3D(gl.GL_TEXTURE_3D, 0, gl.GL_R8, size, size, size, 0, gl.GL_RED, gl.GL_UNSIGNED_BYTE, data)
            return texture_id
        except Exception: 
            return 0

    # =========================================================================
    # LIGHT MANAGEMENT - UPLOAD ONCE PER FRAME
    # =========================================================================

    def _upload_lights_once(self, shader_name, lights):
        """Upload light uniforms once per frame, track which shader they're uploaded to."""
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

    # =========================================================================
    # TERRAIN
    # =========================================================================

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

    # =========================================================================
    # PORTAL RENDERING  (stencil-buffer, Prey 2006-style)
    # =========================================================================

    def _init_portal_gl(self):
        """
        Compile the portal mask/rim shaders and create the shared quad VAO.
        Called once after the main GL context is ready.
        Portal shaders are tiny (no lights, no textures) so compilation is fast.
        """
        try:
            self._portal_mask_shader = self.shader_loader.compile_from_source(
                _PORTAL_MASK_VERT, _PORTAL_MASK_FRAG)
            self._portal_rim_shader = self.shader_loader.compile_from_source(
                _PORTAL_RIM_VERT, _PORTAL_RIM_FRAG)
        except Exception as e:
            print(f"[Portal] Shader compile error: {e}")
            return

        self._portal_quad_vao = gl.glGenVertexArrays(1)
        self._portal_quad_vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self._portal_quad_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_quad_vbo)
        # Reserve space for 4 vertices × 3 floats; updated per-portal each frame
        gl.glBufferData(gl.GL_ARRAY_BUFFER, 4 * 3 * 4, None, gl.GL_DYNAMIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)
        self._portal_gl_ready = True
        print("[Portal] GL resources initialised")

    def _portal_upload_quad(self, corners):
        """Upload 4 world-space corner positions to the dynamic portal quad VBO."""
        vdata = np.array(corners, dtype=np.float32).flatten()
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_quad_vbo)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, vdata.nbytes, vdata)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

    def _portal_build_virtual_view(self, portal_a, portal_b, current_view, camera_pos):
        """
        Build a virtual camera view matrix for rendering through portal_b
        as seen from portal_a.
        """
        yaw_a = portal_a.get_yaw_radians()
        yaw_b = portal_b.get_yaw_radians()

        pos_a = glm.vec3(*portal_a.pos)
        pos_b = glm.vec3(*portal_b.pos)
        cam = glm.vec3(*camera_pos)

        # Determine which side of portal A the player is on
        normal_a = glm.vec3(*portal_a.get_normal())
        to_player = cam - pos_a
        player_side = glm.dot(to_player, normal_a)  # positive = front, negative = back

        # ---- Delta yaw ----
        # Base rotation: difference between portal orientations.
        # When viewing from the FRONT of portal A, we need to look OUT of
        # portal B's front face. This requires an extra 180° flip because
        # the player is looking INTO portal A but needs to see what comes
        # OUT of portal B.
        delta_yaw = yaw_a - yaw_b
        if player_side >= 0:
            # Front side: flip 180° so we look out of portal B, not into it
            delta_yaw += math.pi

        cos_d = math.cos(delta_yaw)
        sin_d = math.sin(delta_yaw)

        # ---- Position ----
        relative = cam - pos_a
        rotated_pos = glm.vec3(
            relative.x * cos_d - relative.z * sin_d,
            relative.y,
            relative.x * sin_d + relative.z * cos_d,
        )
        virtual_cam = pos_b + rotated_pos

        # ---- Direction ----
        fwd = -glm.vec3(current_view[0][2], current_view[1][2], current_view[2][2])

        new_fwd = glm.vec3(
            fwd.x * cos_d - fwd.z * sin_d,
            fwd.y,
            fwd.x * sin_d + fwd.z * cos_d,
        )
        new_fwd = glm.normalize(new_fwd)

        return glm.lookAt(virtual_cam, virtual_cam + new_fwd, glm.vec3(0, 1, 0)), virtual_cam

    def draw_portals(self, portal_things, projection, main_view, camera_pos,
                     brushes, things, lights, config, draw_scene_fn):
        """
        Render all active portal pairs using the stencil buffer.

        This must be called BEFORE the main scene draw in render_scene so that
        the portal views are "behind" all this-side geometry.

        Parameters
        ----------
        portal_things : list[Portal]
            All Portal entities in the current frame's visible set.
        projection    : glm.mat4
        main_view     : glm.mat4
        camera_pos    : sequence or glm.vec3
        brushes, things, lights, config
            Forwarded verbatim to draw_scene_fn.
        draw_scene_fn : callable(proj, view, cam, brushes, things,
                                  selected, config)
            Renders the full scene (brushes + sprites).  The portal renderer
            calls this once per visible portal pair to generate the other-side
            view, masked by the stencil aperture.
        """
        if not self._portal_gl_ready or not portal_things:
            return

        # Build a name → Portal lookup for target resolution
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

            self._draw_one_portal(
                portal_a, portal_b,
                projection, proj_ptr, main_view, camera_pos,
                brushes, things, lights, config, draw_scene_fn,
                stencil_id,
            )
            stencil_id += 1

        # Guarantee clean state for the main scene pass that follows
        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glStencilMask(0xFF)
        gl.glColorMask(gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glClear(gl.GL_STENCIL_BUFFER_BIT)

    def _draw_one_portal(self, portal_a, portal_b,
                        projection, proj_ptr, main_view, camera_pos,
                        brushes, things, lights, config, draw_scene_fn,
                        stencil_id):
        corners_a = portal_a.get_corners_world()
        view_ptr = glm.value_ptr(main_view)

        # FIX: Portal mask must render from both sides
        gl.glDisable(gl.GL_CULL_FACE)

        # Cache uniform locations once per call (avoids repeated string lookups)
        mask_proj_loc = gl.glGetUniformLocation(self._portal_mask_shader, 'projection')
        mask_view_loc = gl.glGetUniformLocation(self._portal_mask_shader, 'view')

        # ----- Pass 1: write stencil mask (colour + depth writes OFF) -----
        gl.glEnable(gl.GL_STENCIL_TEST)
        gl.glStencilMask(0xFF)
        gl.glClear(gl.GL_STENCIL_BUFFER_BIT)   # clear stencil before this portal

        gl.glColorMask(gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE)
        gl.glDepthMask(gl.GL_FALSE)

        gl.glStencilFunc(gl.GL_ALWAYS, stencil_id, 0xFF)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_REPLACE)

        self._portal_upload_quad(corners_a)
        gl.glUseProgram(self._portal_mask_shader)
        gl.glUniformMatrix4fv(mask_proj_loc, 1, gl.GL_FALSE, proj_ptr)
        gl.glUniformMatrix4fv(mask_view_loc, 1, gl.GL_FALSE, view_ptr)
        gl.glBindVertexArray(self._portal_quad_vao)
        gl.glDrawArrays(gl.GL_TRIANGLE_FAN, 0, 4)

        # ----- Pass 2: prime depth to FAR (1.0) inside aperture -----
        # Write depth=1.0 into aperture pixels so Pass 3's GL_LESS test passes
        # for all virtual scene geometry (any real depth < 1.0 wins).
        # Old code wrote 0.0 (near plane) which made GL_LESS impossible to pass.
        gl.glColorMask(gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDepthFunc(gl.GL_ALWAYS)
        gl.glStencilFunc(gl.GL_EQUAL, stencil_id, 0xFF)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)

        gl.glDepthRange(1.0, 1.0)          # collapse all depth output to 1.0 (far)
        self._portal_upload_quad(corners_a)
        gl.glUseProgram(self._portal_mask_shader)
        gl.glUniformMatrix4fv(mask_proj_loc, 1, gl.GL_FALSE, proj_ptr)
        gl.glUniformMatrix4fv(mask_view_loc, 1, gl.GL_FALSE, view_ptr)
        gl.glBindVertexArray(self._portal_quad_vao)
        gl.glDrawArrays(gl.GL_TRIANGLE_FAN, 0, 4)
        gl.glDepthRange(0.0, 1.0)          # restore normal depth range

        gl.glDepthFunc(gl.GL_LESS)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glColorMask(gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE)

        # ----- Pass 3: render virtual scene through stencil aperture -----
        virtual_view, virtual_cam = self._portal_build_virtual_view(
            portal_a, portal_b, main_view, camera_pos)

        # Pin virtual matrices on self before calling glm.value_ptr() so the
        # matrix memory stays alive for the duration of the draw calls.
        self._portal_virtual_view = virtual_view
        self._portal_virtual_proj = projection

        # Gate rendering to aperture pixels only; lock stencil writes so the
        # virtual scene draw cannot corrupt the mask written in Pass 1.
        gl.glStencilFunc(gl.GL_EQUAL, stencil_id, 0xFF)
        gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)
        gl.glStencilMask(0x00)

        # Override proj/view pointers so every draw path uses the virtual camera.
        old_proj_ptr = self._proj_ptr
        old_view_ptr = self._view_ptr
        self._proj_ptr = glm.value_ptr(self._portal_virtual_proj)
        self._view_ptr = glm.value_ptr(self._portal_virtual_view)
        self._current_shader = None   # invalidate shader cache

        draw_scene_fn(projection, virtual_view, virtual_cam, brushes, things, lights, config)

        # Restore original pointers; re-open stencil writes for Pass 4 / next portal.
        self._proj_ptr = old_proj_ptr
        self._view_ptr = old_view_ptr
        self._current_shader = None
        gl.glStencilMask(0xFF)

        # ----- Pass 4: rim glow -----
        # The portal color ONLY affects this rim glow border.
        if portal_a.properties.get('show_rim', True):
            gl.glDisable(gl.GL_STENCIL_TEST)
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE)

            # FIX: Use normalize_color for safe parsing of int/float/string values
            raw_col = portal_a.properties.get('color', [255, 255, 255])
            color = normalize_color(raw_col, default=[1.0, 1.0, 1.0])
            r, g, b = color

            self._portal_upload_quad(corners_a)
            gl.glUseProgram(self._portal_rim_shader)
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(self._portal_rim_shader, 'projection'),
                                1, gl.GL_FALSE, proj_ptr)
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(self._portal_rim_shader, 'view'),
                                1, gl.GL_FALSE, view_ptr)
            gl.glUniform4f(gl.glGetUniformLocation(self._portal_rim_shader, 'rim_color'),
                        r, g, b, 0.55)

            gl.glBindVertexArray(self._portal_quad_vao)
            # FIX: Only draw the border outline (LINE_LOOP), not a filled quad.
            # The GL_TRIANGLE_FAN was filling the entire aperture with semi-transparent
            # color, which tinted the scene rendered behind it in Pass 3.
            gl.glDrawArrays(gl.GL_LINE_LOOP, 0, 4)      # border only
            # REMOVED: gl.glDrawArrays(gl.GL_TRIANGLE_FAN, 0, 4) — this was causing the tint

            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glDisable(gl.GL_BLEND)

        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glBindVertexArray(0)

    # =========================================================================
    # MAIN RENDER SCENE - OPTIMIZED
    # =========================================================================

    # =========================================================================
    # BRUSH SPLIT HELPER
    # =========================================================================

    def _split_opaque(self, brushes):
        """Split opaque brushes into (textured, solid) lists."""
        textured, solid = [], []
        for b in brushes:
            if any(t and t not in ('default.png', 'caulk.jpg')
                   for t in b.get('textures', {}).values()):
                textured.append(b)
            else:
                solid.append(b)
        return textured, solid

    def render_scene(self, projection, view, camera_pos, brushes, things, selected_object, config):
        current_mode = config.get('render_mode', RENDER_MODE_LIT)

        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        self._proj_ptr = glm.value_ptr(projection)
        self._view_ptr = glm.value_ptr(view)

        # Reset per-frame stats
        self.render_stats.reset()
        self.render_stats.total_brushes = len(brushes)
        self._frame_lights_uploaded = False
        self._current_shader = None

        if current_mode == RENDER_MODE_WIREFRAME: 
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
        elif current_mode == RENDER_MODE_VERTEX: 
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_POINT)
            gl.glPointSize(4.0)
        else: 
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        self.draw_grid(projection, view, self.grid_indices_count, 
                      config.get('play_mode', False), config.get('grid_visible', True))
        
        # Sort objects ONCE
        opaque_brushes, transparent_brushes, sprite_things, fog_volumes, water_brushes, glass_brushes, glow_brushes = \
            self._sort_objects(brushes, things, config)
        
        textured_opaque, solid_opaque = self._split_opaque(opaque_brushes)

        # Separate models from sprites
        models_to_render = []
        final_sprites = []
        for thing in sprite_things:
            if isinstance(thing, Thing) and thing.properties.get('model_path'):
                models_to_render.append(thing)
            else:
                final_sprites.append(thing)

        # Get active lights ONCE
        lights = [t for t in things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']
        self._frame_lights = lights

        # Terrain
        terrain = config.get('terrain', None)
        if terrain and terrain.enabled:
            self.render_terrain(projection, view, camera_pos, terrain, lights)

        # ── Portal pre-pass ──────────────────────────────────────────────────
        # Must run before the main opaque pass so portal views are painted
        # into the stencil apertures before this-side geometry occludes them.
        # Only active in play mode (portals are editor-placed entities).
        if config.get('play_mode', False) and Portal is not None and self._portal_gl_ready:
            portal_things = [t for t in things if isinstance(t, Portal) and t.is_active()]
            if portal_things:
                try:
                    def _portal_draw_scene(proj, vw, cam, br, th, sel, cfg):
                        # FIX: Use the FULL brush list, not the main-camera-culled one
                        all_br = cfg.get('all_brushes', br)
                        _t_opaque, _solid = self._split_opaque(all_br)
                        _t_brush_mode = cfg.get('brush_display_mode', 'Textured')
                        _lights = [t for t in th
                                   if isinstance(t, Light)
                                   and t.properties.get('state', 'on') == 'on']
                        if _t_brush_mode in ('Textured', 'Solid Lit'):
                            self.draw_textured_brushes_optimized(proj, vw, cam, _t_opaque, _lights, cfg)
                            self.draw_lit_brushes_optimized(proj, vw, cam, _solid, _lights, cfg)
                        else:
                            # FIX: Also use full list in the fallback branch
                            self.draw_lit_brushes_optimized(proj, vw, cam, all_br, _lights, cfg)
                        # Sprites (monsters, pickups etc.) in the virtual view
                        _sprites = [t for t in th
                                    if not (PathNode is not None and isinstance(t, PathNode))
                                    and not (Portal is not None and isinstance(t, Portal))]
                        self.draw_sprites(proj, vw, _sprites,
                                          self.sprite_textures, self.instance_textures)

                    self.draw_portals(
                        portal_things,
                        projection, view, camera_pos,
                        brushes, things, lights, config,
                        _portal_draw_scene,
                    )
                    # Restore our proj/view ptrs in case the portal pass clobbered them
                    self._proj_ptr = glm.value_ptr(projection)
                    self._view_ptr = glm.value_ptr(view)
                except Exception as _pe:
                    # Never let a portal error crash the main frame
                    print(f"[Portal] render error: {_pe}")

        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        
        brush_display_mode = config.get('brush_display_mode', 'Textured')

        if current_mode == RENDER_MODE_UNLIT: 
            self.draw_textured_brushes_optimized(projection, view, camera_pos, textured_opaque, lights, config)
            self.draw_lit_brushes_optimized(projection, view, camera_pos, solid_opaque, lights, config)
        elif current_mode == RENDER_MODE_LIT:
            if brush_display_mode == 'Textured' or brush_display_mode == 'Solid Lit':
                self.draw_textured_brushes_optimized(projection, view, camera_pos, textured_opaque, lights, config)
                self.draw_lit_brushes_optimized(projection, view, camera_pos, solid_opaque, lights, config)
            else:
                self.draw_lit_brushes_optimized(projection, view, camera_pos, opaque_brushes, lights, config)
        else:
            self.draw_lit_brushes_optimized(projection, view, camera_pos, opaque_brushes, lights, config)

        # Glow brushes — draw overbright in the opaque pass (depth writes ON)
        if glow_brushes:
            self.draw_glow_brushes(projection, view, camera_pos, glow_brushes, lights, config)

        # Models
        if models_to_render:
            self.draw_models(projection, view, camera_pos, models_to_render, lights, config)

        # Shadows
        if current_mode == RENDER_MODE_LIT and self.shadows_enabled:
            shadow_lights = [l for l in lights if l.properties.get('casts_shadows')]
            if shadow_lights:
                all_brushes = config.get('all_brushes', brushes)
                self.render_projected_shadows_optimized(projection, view, camera_pos, all_brushes, shadow_lights)

        # Sort transparent objects by distance ONCE - FIX: Use .get() to prevent crash on missing 'pos'
        if transparent_brushes: 
            transparent_brushes.sort(key=lambda b: -self._distance_sq(b.get('pos', [0,0,0]), camera_pos))
        if water_brushes: 
            water_brushes.sort(key=lambda b: -self._distance_sq(b.get('pos', [0,0,0]), camera_pos))
        if glass_brushes: 
            glass_brushes.sort(key=lambda b: -self._distance_sq(b.get('pos', [0,0,0]), camera_pos))
        if final_sprites: 
            final_sprites.sort(key=lambda s: -self._distance_sq(s['pos'] if isinstance(s, dict) else s.pos, camera_pos))
            
        # PathNode cubes — solid opaque geometry, drawn before the
        # transparency pass so they are proper depth-tested objects.
        # Never shown during play mode — they are editor-only helpers.
        if not config.get('play_mode', False):
            self.draw_path_node_cubes(projection, view, things)

        # Portal aperture outlines — always drawn in both editor and play mode
        # so portals are always visible and selectable.  The stencil view-through
        # pass (draw_portals) is separate and only fires in play mode.
        self.draw_portal_wireframes(projection, view, things)

        gl.glEnable(gl.GL_BLEND)
        gl.glDepthMask(gl.GL_FALSE)
        
        self.draw_sprites(projection, view, final_sprites, self.sprite_textures, self.instance_textures)
        
        # Transparent pass
        if current_mode == RENDER_MODE_UNLIT:
            self.draw_textured_brushes_optimized(projection, view, camera_pos, transparent_brushes, lights, config)
        elif current_mode == RENDER_MODE_LIT:
            self.draw_lit_brushes_optimized(projection, view, camera_pos, transparent_brushes, lights, config, is_transparent_pass=True)
        else:
            self.draw_lit_brushes_optimized(projection, view, camera_pos, transparent_brushes, lights, config, is_transparent_pass=True)
            
        if current_mode == RENDER_MODE_LIT:
            self.draw_water_brushes(projection, view, camera_pos, water_brushes, lights, config)
            self.draw_glass_brushes(projection, view, camera_pos, glass_brushes, lights, config)
            self.draw_fog_volumes(projection, view, camera_pos, fog_volumes, lights, config)

        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        
        # FIX: Safe Gizmo Rendering
        if selected_object:
            if isinstance(selected_object, dict):
                # draw_selected_brush_outline has already been patched to use .get()
                self.draw_selected_brush_outline(projection, view, selected_object)
                
                # Check for 'pos' before rendering gizmo
                pos = selected_object.get('pos')
                if pos is not None and not selected_object.get('lock', False): 
                    self.render_gizmo(projection, view, pos)
            elif isinstance(selected_object, Thing): 
                self.render_gizmo(projection, view, selected_object.pos)
        
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(0)

    # =========================================================================
    # OPTIMIZED DRAWING METHODS - NO DOUBLE CULLING
    # =========================================================================

    def draw_lit_brushes_optimized(self, projection, view, camera_pos, brushes, lights, config, is_transparent_pass=False):
        """Optimized lit brush drawing - trusts pre-culled data, batches where possible."""
        if not brushes or 'lit' not in self.shaders:
            return

        # OPTIMIZATION: Skip culling if data is pre-culled from logic thread
        visible = brushes  # Trust pre-culled data
        self.render_stats.visible_brushes += len(visible)

        if not visible:
            return

        shader, uniforms = self.shaders['lit'], self.uniforms['lit']

        # Always ensure correct shader is active
        gl.glUseProgram(shader)
        self._current_shader = shader
        self._upload_lights_once('lit', lights)

        # FIX: Use the passed projection and view matrices, not the stale class pointers
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))

        gl.glBindVertexArray(self.vaos['cube'])

        display_mode = config.get('brush_display_mode', 'Textured')
        show_triggers_solid = config.get('show_triggers_as_solid', False)
        selected = config.get('selected_object')
        model_loc, color_loc, alpha_loc = uniforms['model'], uniforms['object_color'], uniforms['alpha']

        # normalMatrix: upload unconditionally - all lit/ARM shaders declare it
        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None:
            normal_mat_loc = -1

        fill_mode = (gl.GL_FILL if show_triggers_solid else gl.GL_LINE) if is_transparent_pass else \
                    (gl.GL_FILL if display_mode != "Wireframe" else gl.GL_LINE)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, fill_mode)

        for brush in visible:
            self.render_stats.visible_tris += 12

            # Build model matrix
            pos = brush.get('pos', [0, 0, 0])
            size = brush.get('size', [64, 64, 64])
            model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*pos)), glm.vec3(*size))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

            # Upload pre-computed normal matrix
            if normal_mat_loc > 0:
                normal_mat = self._compute_normal_matrix(model_matrix)
                gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(normal_mat))

            # Determine color
            if brush.get('is_trigger'):
                color, alpha = [0.0, 1.0, 1.0], 0.3
            elif brush is selected:
                color, alpha = [1.0, 1.0, 0.0], 1.0
            elif brush.get('operation') == 'subtract':
                color, alpha = [1.0, 0.0, 0.0], 1.0
            else:
                # Use shared normalize_color helper
                brush_tint = brush.get('tint')
                brush_colour = brush.get('colour')
                color = normalize_color(brush_tint) if brush_tint else normalize_color(brush_colour)
                alpha = 1.0

            gl.glUniform3fv(color_loc, 1, color)
            gl.glUniform1f(alpha_loc, alpha)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            self.render_stats.draw_calls += 1

        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glBindVertexArray(0)

    def draw_textured_brushes_optimized(self, projection, view, camera_pos, brushes, lights, config):
        """Optimized textured brush drawing with better batching."""
        if not brushes or 'textured' not in self.shaders:
            return

        # OPTIMIZATION: Skip culling - trust pre-culled data
        visible = brushes
        self.render_stats.visible_brushes += len(visible)

        if not visible:
            return

        shader, uniforms = self.shaders['textured'], self.uniforms['textured']

        # Always ensure correct shader is active
        gl.glUseProgram(shader)
        self._current_shader = shader
        self._upload_lights_once('textured', lights)

        # FIX: Use the passed projection and view matrices
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))

        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(uniforms['texture_diffuse'], 0)

        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glBindVertexArray(self.vaos['cube'])

        model_loc = uniforms['model']
        tex_scale_loc = uniforms.get('tex_scale', -1)
        if tex_scale_loc == -1:
            tex_scale_loc = gl.glGetUniformLocation(shader, "tex_scale")

        # normalMatrix: upload unconditionally
        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None:
            normal_mat_loc = -1

        # OPTIMIZATION: Batch by texture to minimize state changes
        batches = defaultdict(list)
        is_play = config.get('play_mode', False)

        for brush in visible:
            for i, key in enumerate(['south', 'north', 'west', 'east', 'down', 'top']):
                tex_name = brush.get('textures', {}).get(key, 'default.png')
                if tex_name == 'caulk.jpg':
                    continue
                if is_play and tex_name == 'nodraw.jpg':
                    continue
                tex_id = self.texture_manager.get(os.path.join('textures', tex_name)) or \
                        self.load_texture_callback(tex_name, 'textures')
                batches[tex_id].append((brush, i))

        current_tex = None
        for tex_id, items in batches.items():
            if tex_id != current_tex:
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                current_tex = tex_id
                self.render_stats.batched_draws += 1

            for brush, face_idx in items:
                self.render_stats.visible_tris += 2

                pos = brush.get('pos', [0, 0, 0])
                size = brush.get('size', [64, 64, 64])
                model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*pos)), glm.vec3(*size))
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

                if normal_mat_loc > 0:
                    normal_mat = self._compute_normal_matrix(model_matrix)
                    gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(normal_mat))

                if tex_scale_loc != -1:
                    if brush.get('texture_tiling', False):
                        tex_unit_size = 128.0
                        if face_idx == 0 or face_idx == 1:
                            scale_x, scale_y = size[0] / tex_unit_size, size[1] / tex_unit_size
                        elif face_idx == 2 or face_idx == 3:
                            scale_x, scale_y = size[2] / tex_unit_size, size[1] / tex_unit_size
                        else:
                            scale_x, scale_y = size[0] / tex_unit_size, size[2] / tex_unit_size
                        gl.glUniform2f(tex_scale_loc, scale_x, scale_y)
                    else:
                        gl.glUniform2f(tex_scale_loc, 1.0, 1.0)

                gl.glDrawArrays(gl.GL_TRIANGLES, face_idx * 6, 6)
                self.render_stats.draw_calls += 1

        gl.glBindVertexArray(0)

    # =========================================================================
    # OTHER DRAWING METHODS (water, glass, fog, models, sprites)
    # =========================================================================

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
                    material = obj.materials.get(mat_name, {'color': [0.8, 0.8, 0.8], 'texture': None})
                    use_texture = material.get('texture')
                    
                    if use_texture and textured_shader:
                        if current_shader != textured_shader:
                            gl.glUseProgram(textured_shader)
                            current_shader = textured_shader
                            u = self.uniforms['textured']
                            gl.glUniformMatrix4fv(u['projection'], 1, gl.GL_FALSE, self._proj_ptr)
                            gl.glUniformMatrix4fv(u['view'], 1, gl.GL_FALSE, self._view_ptr)
                            self._upload_lights_once('textured', lights)
                            gl.glActiveTexture(gl.GL_TEXTURE0)
                            gl.glUniform1i(u['texture_diffuse'], 0)
                        
                        tex_id = 0
                        path_in_textures = os.path.join('assets', 'textures', use_texture)
                        if os.path.exists(path_in_textures):
                            tex_id = self.load_texture(use_texture, 'textures')
                        else:
                            tex_id = self.load_texture(use_texture, 'models')
                        
                        gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                        gl.glUniformMatrix4fv(self.uniforms['textured']['model'], 1, gl.GL_FALSE, glm.value_ptr(mat))
                        
                    elif lit_shader:
                        if current_shader != lit_shader:
                            gl.glUseProgram(lit_shader)
                            current_shader = lit_shader
                            u = self.uniforms['lit']
                            gl.glUniformMatrix4fv(u['projection'], 1, gl.GL_FALSE, self._proj_ptr)
                            gl.glUniformMatrix4fv(u['view'], 1, gl.GL_FALSE, self._view_ptr)
                            self._upload_lights_once('lit', lights)

                        color = material.get('color', [0.8, 0.8, 0.8])
                        gl.glUniform3fv(self.uniforms['lit']['object_color'], 1, color)
                        gl.glUniform1f(self.uniforms['lit']['alpha'], 1.0)
                        gl.glUniformMatrix4fv(self.uniforms['lit']['model'], 1, gl.GL_FALSE, glm.value_ptr(mat))

                    gl.glDrawArrays(gl.GL_TRIANGLES, group['start'], group['count'])
            else:
                tex_name = manual_texture
                target_shader = textured_shader if tex_name else lit_shader
                
                if target_shader == textured_shader:
                    if current_shader != textured_shader:
                        gl.glUseProgram(textured_shader)
                        current_shader = textured_shader
                        u = self.uniforms['textured']
                        gl.glUniformMatrix4fv(u['projection'], 1, gl.GL_FALSE, self._proj_ptr)
                        gl.glUniformMatrix4fv(u['view'], 1, gl.GL_FALSE, self._view_ptr)
                        self._upload_lights_once('textured', lights)
                        gl.glActiveTexture(gl.GL_TEXTURE0)
                        gl.glUniform1i(u['texture_diffuse'], 0)
                    
                    tex_id = self.load_texture(tex_name, 'textures')
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                    gl.glUniformMatrix4fv(self.uniforms['textured']['model'], 1, gl.GL_FALSE, glm.value_ptr(mat))
                    
                elif lit_shader:
                    if current_shader != lit_shader:
                        gl.glUseProgram(lit_shader)
                        current_shader = lit_shader
                        u = self.uniforms['lit']
                        gl.glUniformMatrix4fv(u['projection'], 1, gl.GL_FALSE, self._proj_ptr)
                        gl.glUniformMatrix4fv(u['view'], 1, gl.GL_FALSE, self._view_ptr)
                        self._upload_lights_once('lit', lights)
                    
                    col = thing.properties.get('color', [0.8, 0.8, 0.8])
                    gl.glUniform3fv(self.uniforms['lit']['object_color'], 1, col)
                    gl.glUniform1f(self.uniforms['lit']['alpha'], 1.0)
                    gl.glUniformMatrix4fv(self.uniforms['lit']['model'], 1, gl.GL_FALSE, glm.value_ptr(mat))

                gl.glDrawArrays(gl.GL_TRIANGLES, 0, obj.vertex_count)
            
            self.render_stats.draw_calls += 1
            
        gl.glBindVertexArray(0)
        gl.glEnable(gl.GL_CULL_FACE)

    def _distance_sq(self, pos1, pos2):
        if isinstance(pos1, (list, tuple)): 
            return (pos1[0]-pos2.x)**2 + (pos1[1]-pos2.y)**2 + (pos1[2]-pos2.z)**2
        return (pos1.x-pos2.x)**2 + (pos1.y-pos2.y)**2 + (pos1.z-pos2.z)**2

    # =========================================================================
    # GLOW BRUSH SUPPORT
    # =========================================================================

    def draw_glow_brushes(self, projection, view, camera_pos, brushes, lights, config):
        """Render glow brushes as overbright solid geometry.

        Uses the standard 'lit' shader but overrides object_color to
        tint_colour * glow_intensity so the surface appears self-illuminated.
        Falls back to white when no tint/colour is set on the brush.
        """
        if not brushes or 'lit' not in self.shaders:
            return

        shader, uniforms = self.shaders['lit'], self.uniforms['lit']
        gl.glUseProgram(shader)
        self._current_shader = shader
        self._upload_lights_once('lit', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)

        gl.glBindVertexArray(self.vaos['cube'])
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        model_loc = uniforms['model']
        color_loc = uniforms['object_color']
        alpha_loc = uniforms['alpha']
        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None:
            normal_mat_loc = -1

        for brush in brushes:
            self.render_stats.visible_tris += 12

            pos = brush.get('pos', [0, 0, 0])
            size = brush.get('size', [64, 64, 64])
            model_matrix = glm.scale(
                glm.translate(self._identity_mat4, glm.vec3(*pos)),
                glm.vec3(*size))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

            if normal_mat_loc > 0:
                normal_mat = self._compute_normal_matrix(model_matrix)
                gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(normal_mat))

            # FIX#13: Use shared normalize_color helper
            tint = brush.get('tint') or brush.get('colour')
            base_color = normalize_color(tint, default=[1.0, 1.0, 1.0])

            intensity = float(brush.get('glow_intensity', 10.0))
            overbright = [min(c * intensity, 10.0) for c in base_color]

            gl.glUniform3fv(color_loc, 1, overbright)
            gl.glUniform1f(alpha_loc, 1.0)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            self.render_stats.draw_calls += 1

        gl.glBindVertexArray(0)


    # ── Projected Shadows ────────────────────────────────────────────

    def render_projected_shadows_optimized(self, projection, view, camera_pos, all_brushes, shadow_lights):
        """Render projected floor shadows for brushes lit by shadow-casting lights.

        For each light with casts_shadows=True, every opaque brush within the
        light's radius gets a flattened shadow volume projected onto the floor
        plane (y = 0).  Uses the pre-compiled 'shadow_volume' shader and the
        existing cube VAO.

        The projection squashes brush geometry onto y=0 from the light position
        using a standard planar-projection matrix, then draws with additive-safe
        blending so overlapping shadows darken correctly without double-blend
        artifacts.
        """
        if 'shadow_volume' not in self.shaders:
            return

        shader = self.shaders['shadow_volume']
        uniforms = self.uniforms['shadow_volume']

        gl.glUseProgram(shader)
        self._current_shader = shader
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)

        gl.glBindVertexArray(self.vaos['cube'])

        # Blend: multiply-style darkening — avoids harsh double-shadows
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        # Write to colour buffer only; leave depth as-is so shadows sit on
        # top of already-rendered floor geometry without z-fighting.
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDepthFunc(gl.GL_LEQUAL)

        # Slight polygon offset to prevent z-fighting with the floor
        gl.glEnable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glPolygonOffset(-1.0, -1.0)

        model_loc = uniforms['model']
        light_pos_loc = uniforms.get('light_pos', -1)

        FLOOR_Y = 0.0  # Shadow receiver plane
        shadow_count = 0

        for light in shadow_lights:
            lpos = light.pos  # [x, y, z]
            lx, ly, lz = float(lpos[0]), float(lpos[1]), float(lpos[2])
            light_radius = float(light.properties.get('radius', 512.0))
            light_radius_sq = light_radius * light_radius
            light_intensity = float(light.properties.get('intensity', 1.0))

            # Upload light position for this pass
            if light_pos_loc is not None and light_pos_loc >= 0:
                gl.glUniform3f(light_pos_loc, lx, ly, lz)

            # Only cast shadows downward (light must be above the floor plane)
            if ly <= FLOOR_Y:
                continue

            for brush in all_brushes:
                # Skip non-opaque brush types
                if brush.get('hidden') or brush.get('is_trigger') or brush.get('is_fog') or \
                   brush.get('is_water') or brush.get('shader') in ('Water', 'Fog', 'Glass', 'Glow'):
                    continue

                bpos = brush.get('pos', [0, 0, 0])
                bx, by, bz = float(bpos[0]), float(bpos[1]), float(bpos[2])

                # Quick range check (squared distance, centre-to-centre)
                dx, dy, dz = bx - lx, by - ly, bz - lz
                dist_sq = dx * dx + dy * dy + dz * dz
                if dist_sq > light_radius_sq:
                    continue

                bsize = brush.get('size', [64, 64, 64])
                bsx, bsy, bsz = float(bsize[0]), float(bsize[1]), float(bsize[2])

                # ── Planar-projection shadow matrix ──
                # Projects brush geometry onto y=FLOOR_Y from the light.
                # Plane: y = FLOOR_Y  →  normal (0,1,0), d = -FLOOR_Y
                nx, ny, nz, nd = 0.0, 1.0, 0.0, -FLOOR_Y
                dot_val = nx * lx + ny * ly + nz * lz + nd  # = ly - FLOOR_Y

                # Standard planar-projection shadow matrix (column-major for glm)
                shadow_mat = glm.mat4(
                    glm.vec4(dot_val - lx * nx, -ly * nx,       -lz * nx,       -nx),
                    glm.vec4(-lx * ny,          dot_val - ly * ny, -lz * ny,     -ny),
                    glm.vec4(-lx * nz,          -ly * nz,       dot_val - lz * nz, -nz),
                    glm.vec4(-lx * nd,          -ly * nd,       -lz * nd,       dot_val - nd)
                )

                # Brush model matrix (same as opaque rendering)
                brush_model = glm.scale(
                    glm.translate(self._identity_mat4, glm.vec3(bx, by, bz)),
                    glm.vec3(bsx, bsy, bsz)
                )

                # Combined: project the brush onto the floor plane
                final = shadow_mat * brush_model

                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(final))

                # Alpha fades with distance from light
                dist_ratio = min(1.0, (dist_sq / light_radius_sq))
                # Stronger shadow near light, fading to nothing at radius edge
                # Also scale by light intensity (brighter light = sharper shadow)
                alpha = max(0.05, (1.0 - dist_ratio) * min(light_intensity, 1.0) * 0.6)

                # The shadow_volume.frag hard-codes FragColor alpha to 0.5,
                # so we modulate via glBlendColor if needed.  For simplicity
                # the current shader is fine — the 0.5 base alpha gives a
                # reasonable look.  If you want per-shadow alpha, add a
                # uniform float shadow_alpha to the frag shader later.

                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
                shadow_count += 1
                self.render_stats.draw_calls += 1

        # Restore state
        gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glBindVertexArray(0)

        self.render_stats.shadow_draw_calls = shadow_count

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
            sprites = [t for t in things if (isinstance(t, Thing) or (isinstance(t, dict) and 'monster_type' in t))
                       and not (PathNode is not None and isinstance(t, PathNode))]
        else:
            # FIX#5: entity classes now imported at module level — no per-frame import
            for t in things:
                # PathNode entities are never rendered as sprites
                if PathNode is not None and isinstance(t, PathNode):
                    continue
                # Portal entities are drawn by draw_portal_wireframes, not as billboards,
                # but we still include them in visible_things so hit-testing works.
                if Portal is not None and isinstance(t, Portal):
                    sprites.append(t)
                    continue
                # Monster dict snapshots (from get_render_snapshot) — always visible
                if isinstance(t, dict) and 'monster_type' in t:
                    sprites.append(t)
                elif isinstance(t, Thing):
                    if isinstance(t, Pickup):
                        sprites.append(t)
                    elif isinstance(t, (Monster, LogicGate, LogicRelay, LogicTimer, LevelChanger)):
                        sprites.append(t)      # Always visible in play mode
                    elif show_sprites:
                        sprites.append(t)      # Optional sprites (lights, speakers, etc.)
        
        return opaque, transparent, sprites, fog, water, glass, glow

    def draw_water_brushes(self, projection, view, camera_pos, brushes, lights, config):
        if not brushes: 
            return
        shader, uniforms = self.shaders['water'], self.uniforms['water']
        gl.glUseProgram(shader)
        self._upload_lights_once('water', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
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
            pos = brush.get('pos', [0, 0, 0])
            size = brush.get('size', [64, 64, 64])
            model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*pos)), glm.vec3(*size))
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
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniform3fv(uniforms['viewPos'], 1, glm.value_ptr(camera_pos))
        
        model_loc = uniforms['model']
        water_color_loc = uniforms['waterColor']
        distortion_loc = uniforms['distortionStrength']
        caustic_loc = uniforms['causticStrength']
        opacity_loc = uniforms['glassOpacity']
        refraction_loc = uniforms['refractionIndex']
        roughness_loc = uniforms['roughness']
        # glass.vert declares normalMatrix - fetch the location once before the loop.
        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None: normal_mat_loc = -1
        
        gl.glBindVertexArray(self.vaos['cube'])
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_CULL_FACE)
        gl.glCullFace(gl.GL_BACK)
        
        for brush in brushes:
            pos = brush.get('pos', [0, 0, 0])
            size = brush.get('size', [64, 64, 64])
            model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*pos)), glm.vec3(*size))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            
            # Upload pre-computed normal matrix - was missing entirely before this fix.
            if normal_mat_loc > 0:
                normal_mat = self._compute_normal_matrix(model_matrix)
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
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniform3fv(uniforms['viewPos'], 1, glm.value_ptr(camera_pos))
        gl.glUniform1f(uniforms['time'], config.get('time', 0.0))
        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_3D, self.noise_texture_id)
        gl.glUniform1i(uniforms['noiseTexture'], 1)
        gl.glBindVertexArray(self.vaos['cube'])
        gl.glEnable(gl.GL_CULL_FACE)
        model_loc        = uniforms['model']
        inv_model_loc    = uniforms['inverseModel']  # FIX: upload CPU-computed inverse
        density_loc      = uniforms['density']
        fog_color_loc    = uniforms['fogColor']
        noise_scale_loc  = uniforms['noiseScale']
        object_color_loc = uniforms['object_color']
        alpha_loc        = uniforms['alpha']

        for brush in brushes:
            pos = brush.get('pos', [0, 0, 0])
            size = brush.get('size', [64, 64, 64])
            model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*pos)), glm.vec3(*size))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            # FIX: compute matrix inverse on CPU once per brush, not per-fragment on GPU.
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

    def draw_grid(self, projection, view, grid_indices_count, play_mode=False, grid_visible=True):
        if not self.vaos['grid'] or play_mode or not grid_visible or 'simple' not in self.shaders: 
            return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(self._identity_mat4))
        gl.glUniform3f(uniforms['color'], 0.2, 0.2, 0.2)
        gl.glUniform1f(uniforms['alpha'], 1.0)
        gl.glBindVertexArray(self.vaos['grid'])
        gl.glDrawArrays(gl.GL_LINES, 0, grid_indices_count)
        gl.glBindVertexArray(0)

    def draw_path_node_cubes(self, projection, view, things):
        """
        Draw each PathNode as a small solid orange cube ("fake brush").
        Uses the 'simple' shader with the unit-cube VAO.
        """
        if 'simple' not in self.shaders or PathNode is None:
            return

        nodes = [t for t in things if isinstance(t, PathNode)]
        if not nodes:
            return

        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)

        # Orange colour  (r=1.0, g=0.5, b=0.0)
        gl.glUniform3f(uniforms['color'], 1.0, 0.5, 0.0)
        gl.glUniform1f(uniforms['alpha'], 1.0)

        cube_size = 16.0   # world units — small marker cube

        gl.glBindVertexArray(self.vaos['cube'])

        for node in nodes:
            pos = node.pos
            model_matrix = glm.scale(
                glm.translate(self._identity_mat4, glm.vec3(float(pos[0]), float(pos[1]), float(pos[2]))),
                glm.vec3(cube_size, cube_size, cube_size)
            )
            gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            self.render_stats.draw_calls += 1

        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

    def draw_portal_wireframes(self, projection, view, things):
        """
        Draw every Portal entity as a coloured rectangle outline in the 3D
        view using the 'simple' shader.  Works in both editor and play mode —
        this is purely a visual representation of the aperture so the level
        designer can see, select and position portals.

        In play mode the stencil pass (draw_portals) renders the actual portal
        view.  In editor mode the stencil pass is skipped, but this outline is
        always drawn so portals are never invisible.
        """
        if Portal is None or 'simple' not in self.shaders:
            return

        portal_things = [t for t in things if isinstance(t, Portal)]
        if not portal_things:
            return

        shader   = self.shaders['simple']
        uniforms = self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'],       1, gl.GL_FALSE, self._view_ptr)
        gl.glUniform1f(uniforms['alpha'], 1.0)

        # Build a simple quad outline VAO on first use
        if not hasattr(self, '_portal_outline_vao') or self._portal_outline_vao is None:
            # 4 vertices of a unit quad, drawn as LINE_LOOP — updated per portal
            self._portal_outline_vao = gl.glGenVertexArrays(1)
            self._portal_outline_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self._portal_outline_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_outline_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 4 * 3 * 4, None, gl.GL_DYNAMIC_DRAW)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
            gl.glEnableVertexAttribArray(0)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
            gl.glBindVertexArray(0)

        # Also a cross-hair line for the normal direction (2 verts)
        if not hasattr(self, '_portal_normal_vao') or self._portal_normal_vao is None:
            self._portal_normal_vao = gl.glGenVertexArrays(1)
            self._portal_normal_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self._portal_normal_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_normal_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 2 * 3 * 4, None, gl.GL_DYNAMIC_DRAW)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
            gl.glEnableVertexAttribArray(0)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
            gl.glBindVertexArray(0)

        gl.glLineWidth(1.0)
        model_loc = uniforms['model']
        color_loc = uniforms['color']

        # Upload identity model matrix once — corners are already in world space
        gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE,
                              glm.value_ptr(self._identity_mat4))

        for portal in portal_things:
            # FIX: Use normalize_color helper to safely handle both [0-255] ints
            # and [0.0-1.0] floats, as well as string values that may come from
            # property editor text fields.
            raw = portal.properties.get('color', [255, 255, 255])
            color = normalize_color(raw, default=[1.0, 1.0, 1.0])
            r, g, b = color

            if not portal.is_active():
                # Inactive portals drawn dimmed
                r, g, b = r * 0.4, g * 0.4, b * 0.4

            corners = portal.get_corners_world()   # 4 × [x,y,z], CCW from front
            vdata = np.array(corners, dtype=np.float32).flatten()

            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_outline_vbo)
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, vdata.nbytes, vdata)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

            gl.glUniform3f(color_loc, r, g, b)
            gl.glBindVertexArray(self._portal_outline_vao)
            gl.glDrawArrays(gl.GL_LINE_LOOP, 0, 4)

            # Draw a short normal arrow from the centre so the facing direction
            # is obvious in the editor
            import math as _math
            cx = float(portal.pos[0])
            cy = float(portal.pos[1])
            cz = float(portal.pos[2])
            nx, ny, nz = portal.get_normal()
            arrow_len = portal.get_width() * 0.4
            nline = np.array([
                cx, cy, cz,
                cx + nx * arrow_len, cy + ny * arrow_len, cz + nz * arrow_len,
            ], dtype=np.float32)

            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._portal_normal_vbo)
            gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, nline.nbytes, nline)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)

            # Draw normal slightly brighter
            gl.glUniform3f(color_loc, min(1.0, r * 1.6), min(1.0, g * 1.6), min(1.0, b * 1.6))
            gl.glBindVertexArray(self._portal_normal_vao)
            gl.glDrawArrays(gl.GL_LINES, 0, 2)

        gl.glLineWidth(1.0)
        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

    def draw_connection_lines(self, projection, view, connections):
        """Draw connection lines between entities in the 3D viewport.

        *connections* is a list of dicts, each with:
            'src':   [x, y, z]      — source entity position
            'dst':   [x, y, z]      — target entity position
            'color': (r, g, b)      — line colour as 0-1 floats

        Uses the 'simple' shader to draw GL_LINES with depth-testing disabled
        so the lines are always visible (like the gizmo).
        """
        if not connections or 'simple' not in self.shaders:
            return

        # Build vertex data:  6 floats per line  (src xyz, dst xyz)
        line_data = []
        line_colors = []   # parallel list of (r, g, b) per line
        for conn in connections:
            sx, sy, sz = conn['src']
            dx, dy, dz = conn['dst']
            line_data.extend([float(sx), float(sy), float(sz),
                              float(dx), float(dy), float(dz)])
            line_colors.append(conn.get('color', (0.0, 1.0, 1.0)))

        if not line_data:
            return

        vertices = np.array(line_data, dtype=np.float32)

        # Lazy-create a reusable dynamic VAO/VBO for connection lines
        if not hasattr(self, '_conn_line_vao') or self._conn_line_vao is None:
            self._conn_line_vao = gl.glGenVertexArrays(1)
            self._conn_line_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self._conn_line_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._conn_line_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 1024 * 1024, None, gl.GL_DYNAMIC_DRAW)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
            gl.glEnableVertexAttribArray(0)
            gl.glBindVertexArray(0)

        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE,
                              glm.value_ptr(self._identity_mat4))
        gl.glUniform1f(uniforms['alpha'], 1.0)

        # Depth test stays enabled so lines are occluded by walls
        gl.glBindVertexArray(self._conn_line_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._conn_line_vbo)
        gl.glBufferSubData(gl.GL_ARRAY_BUFFER, 0, vertices.nbytes, vertices)

        color_loc = uniforms['color']
        for i, (r, g, b) in enumerate(line_colors):
            gl.glUniform3f(color_loc, r, g, b)
            gl.glDrawArrays(gl.GL_LINES, i * 2, 2)

        gl.glBindVertexArray(0)
        gl.glUseProgram(0)

    def draw_sprites(self, projection, view, things_to_draw, sprite_textures, instance_textures=None):
        if not things_to_draw or 'sprite' not in self.shaders:
            return

        shader, uniforms = self.shaders['sprite'], self.uniforms['sprite']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(uniforms['sprite_texture'], 0)
        pos_loc, size_loc = uniforms['sprite_pos_world'], uniforms['sprite_size']
        gl.glBindVertexArray(self.vaos['sprite'])

        from editor.things import Monster, Light, LogicSpawner, LogicCamera

        current_tex = None
        for thing in things_to_draw:
            # FIX: Do not draw Portal entities as flat billboard sprites
            if Portal is not None and isinstance(thing, Portal):
                continue
                
            # ---- MONSTER SNAPSHOT (dictionary) ----
            if isinstance(thing, dict) and 'dead' in thing:
                # Build a texture key from custom sprite paths and monster type
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
                tex_id = self.sprite_textures.get(tex_key)
                if tex_id is None:
                    # load_texture(name, subfolder) builds: assets/{subfolder}/{name}
                    if custom:
                        custom_clean = custom.replace('assets/', '', 1)
                        subfolder = os.path.dirname(custom_clean)
                        filename  = os.path.basename(custom_clean)
                    else:
                        if variant and variant != '<None>':
                            subfolder = f"sprites/monsters/{mtype}/{variant}"
                        else:
                            subfolder = f"sprites/monsters/{mtype}"
                        filename  = f"{sprite_type}.png"
                    tex_id = self.load_texture(filename, subfolder)
                    # If variant file missing, fall back to base type folder
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

            # ---- REGULAR THINGS (Light, Pickup, LogicSpawner, etc.) ----
            tex_id = None
            if instance_textures:
                tex_id = instance_textures.get(id(thing))
            
            if tex_id is None:
                # Check for cached texture by class name
                class_name = thing.__class__.__name__
                tex_id = self.sprite_textures.get(class_name)
                
                # If not cached, load specifically for the new logic types
                if tex_id is None:
                    if isinstance(thing, LogicSpawner):
                        tex_id = self.load_texture('logic_spawner.png', 'sprites')
                        if tex_id: self.sprite_textures['LogicSpawner'] = tex_id
                    elif isinstance(thing, LogicCamera):
                        tex_id = self.load_texture('logic_camera.png', 'sprites')
                        if tex_id: self.sprite_textures['LogicCamera'] = tex_id
                    else:
                        # Fallback for other standard things
                        tex_id = sprite_textures.get(class_name)

            if tex_id:
                if tex_id != current_tex:
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                    current_tex = tex_id
                
                gl.glUniform3fv(pos_loc, 1, thing.pos)
                
                # Assign appropriate sizes for editor icons
                if isinstance(thing, Light):
                    gl.glUniform2f(size_loc, 16.0, 16.0)
                elif isinstance(thing, (LogicSpawner, LogicCamera)):
                    gl.glUniform2f(size_loc, 32.0, 32.0)
                else:
                    gl.glUniform2f(size_loc, 32.0, 32.0)
                
                gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)

        gl.glBindVertexArray(0)

    # =========================================================================
    # SELECTION / GIZMO / FACE HIGHLIGHT
    # =========================================================================

    def draw_face_highlight(self, projection, view, brush, face_name):
        if 'simple' not in self.shaders: 
            return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
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
            verts = [cx-hx, cy-hy, z,  cx+hx, cy-hy, z,  cx+hx, cy+hy, z,
                     cx-hx, cy-hy, z,  cx+hx, cy+hy, z,  cx-hx, cy+hy, z]
        elif face_name == 'south':
            z = cz - hz - bias
            verts = [cx+hx, cy-hy, z,  cx-hx, cy-hy, z,  cx-hx, cy+hy, z,
                     cx+hx, cy-hy, z,  cx-hx, cy+hy, z,  cx+hx, cy+hy, z]
        elif face_name == 'east':
            x = cx + hx + bias
            verts = [x, cy-hy, cz+hz,  x, cy-hy, cz-hz,  x, cy+hy, cz-hz,
                     x, cy-hy, cz+hz,  x, cy+hy, cz-hz,  x, cy+hy, cz+hz]
        elif face_name == 'west':
            x = cx - hx - bias
            verts = [x, cy-hy, cz-hz,  x, cy-hy, cz+hz,  x, cy+hy, cz+hz,
                     x, cy-hy, cz-hz,  x, cy+hy, cz+hz,  x, cy+hy, cz-hz]
        elif face_name == 'top':
            y = cy + hy + bias
            verts = [cx-hx, y, cz+hz,  cx+hx, y, cz+hz,  cx+hx, y, cz-hz,
                     cx-hx, y, cz+hz,  cx+hx, y, cz-hz,  cx-hx, y, cz-hz]
        elif face_name == 'down':
            y = cy - hy - bias
            verts = [cx-hx, y, cz-hz,  cx+hx, y, cz-hz,  cx+hx, y, cz+hz,
                     cx-hx, y, cz-hz,  cx+hx, y, cz+hz,  cx-hx, y, cz+hz]
            
        if not verts: 
            return

        v_data = np.array(verts, dtype=np.float32)
        
        if not hasattr(self, 'face_highlight_vao'):
            self.face_highlight_vao = gl.glGenVertexArrays(1)
            self.face_highlight_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self.face_highlight_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.face_highlight_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 6 * 3 * 4, None, gl.GL_DYNAMIC_DRAW) 
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

    def draw_selected_brush_outline(self, projection, view, brush):
        if 'simple' not in self.shaders: 
            return
        
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        
        # FIX: Use .get() to provide defaults if 'pos' or 'size' keys are missing
        pos = brush.get('pos', [0, 0, 0])
        size = brush.get('size', [64, 64, 64])
        
        model_matrix = glm.scale(
            glm.translate(self._identity_mat4, glm.vec3(*pos)), 
            glm.vec3(*size)
        )
        
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
        gl.glUniform3f(uniforms['color'], 1.0, 1.0, 0.0)
        gl.glUniform1f(uniforms['alpha'], 1.0)
        
        if not hasattr(self, '_edge_vao') or self._edge_vao is None:
            edge_vertices = np.array([
                -0.5, -0.5, -0.5,  0.5, -0.5, -0.5,  0.5, -0.5, -0.5,  0.5, -0.5,  0.5,
                 0.5, -0.5,  0.5, -0.5, -0.5,  0.5, -0.5, -0.5,  0.5, -0.5, -0.5, -0.5,
                -0.5,  0.5, -0.5,  0.5,  0.5, -0.5,  0.5,  0.5, -0.5,  0.5,  0.5,  0.5,
                 0.5,  0.5,  0.5, -0.5,  0.5,  0.5, -0.5,  0.5,  0.5, -0.5,  0.5, -0.5,
                -0.5, -0.5, -0.5, -0.5,  0.5, -0.5,  0.5, -0.5, -0.5,  0.5,  0.5, -0.5,
                 0.5, -0.5,  0.5,  0.5,  0.5,  0.5, -0.5, -0.5,  0.5, -0.5,  0.5,  0.5,
            ], dtype=np.float32)
            self._edge_vao = gl.glGenVertexArrays(1)
            gl.glBindVertexArray(self._edge_vao)
            vbo = gl.glGenBuffers(1)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, edge_vertices.nbytes, edge_vertices, gl.GL_STATIC_DRAW)
            gl.glEnableVertexAttribArray(0)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
            gl.glBindVertexArray(0)
            self._edge_vbo = vbo  # Store to prevent GPU memory leak
        
        gl.glLineWidth(1.0)
        gl.glBindVertexArray(self._edge_vao)
        gl.glDrawArrays(gl.GL_LINES, 0, 24) 
        gl.glBindVertexArray(0)

    # =========================================================================
    # VAO CREATION
    # =========================================================================

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
        self._cube_vbo = vbo  # FIX: store to prevent GPU memory leak
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
        self._sprite_vbo = vbo  # FIX: store to prevent GPU memory leak
        return vao

    def reload_shaders(self):
        """Hot-reload all shaders. Called from console command r_reloadshaders."""
        try:
            print("Hot-reloading shaders...")

            # Recompile ARM or standard shaders
            if self.arm_mode:
                self._compile_arm_shaders()
            else:
                self._compile_standard_shaders()

            # Recompile common shaders
            for name, files in [('simple', ('simple.vert', 'simple.frag')),
                                ('sprite', ('sprite.vert', 'sprite.frag')),
                                ('shadow_volume', ('shadow_volume.vert', 'shadow_volume.frag')),
                                ('water', ('water.vert', 'water.frag')),
                                ('glass', ('glass.vert', 'glass.frag'))]:
                shader = self.shader_loader.compile_shader_program(*files)
                self.shaders[name] = shader
                self.uniforms[name] = UniformCache(shader)

            # Recompile portal shaders
            self._init_portal_gl()

            print("All shaders reloaded successfully.")
            return True
        except Exception as e:
            print(f"Shader reload failed: {e}")
            return False

    def _create_gizmo_buffers(self):
        axis_verts = np.array([0,0,0, 1,0,0, 0,0,0, 0,1,0, 0,0,0, 0,0,1], dtype=np.float32)
        self.vao_gizmo_lines = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        self._gizmo_lines_vbo = vbo  # FIX: store to prevent GPU memory leak
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
        self._gizmo_cone_vbo = vbo2  # FIX: store to prevent GPU memory leak
        gl.glBindVertexArray(self.vao_gizmo_cone)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo2)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, cone_verts.nbytes, cone_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)

    def render_gizmo(self, projection, view, position):
        if 'simple' not in self.shaders: 
            return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        pos_vec = glm.vec3(*position) if isinstance(position, (list, tuple)) else position
        base = glm.scale(glm.translate(self._identity_mat4, pos_vec), glm.vec3(32.0))
        model_loc, color_loc = uniforms['model'], uniforms['color']
        gl.glUniform1f(uniforms['alpha'], 1.0)
        
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(base))
        for i, c in enumerate([(1,0,0), (0,1,0), (0,0,1)]):
            gl.glUniform3f(color_loc, *c)
            gl.glDrawArrays(gl.GL_LINES, i*2, 2)
        gl.glBindVertexArray(self.vao_gizmo_cone)
        for axis, c, rot in [((1,0,0), (1,0,0), glm.rotate(base, glm.radians(-90), glm.vec3(0,0,1))), 
                            ((0,1,0), (0,1,0), base), 
                            ((0,0,1), (0,0,1), glm.rotate(base, glm.radians(90), glm.vec3(1,0,0)))]:
            m = glm.translate(rot if axis[1] else glm.translate(base, glm.vec3(*axis)), 
                             glm.vec3(0,1,0) if axis[1] else glm.vec3(0,0,0))
            if axis[0]: 
                m = glm.translate(glm.rotate(base, glm.radians(-90), glm.vec3(0,0,1)), glm.vec3(0,1,0))
            if axis[2]: 
                m = glm.translate(glm.rotate(base, glm.radians(90), glm.vec3(1,0,0)), glm.vec3(0,1,0))
            if axis[1]: 
                m = glm.translate(base, glm.vec3(0,1,0))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(m))
            gl.glUniform3f(color_loc, *c)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)
        gl.glBindVertexArray(0)