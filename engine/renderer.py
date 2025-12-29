import glm
import numpy as np
import OpenGL.GL as gl
import ctypes
from editor.things import Thing, Light
from OpenGL.GL.shaders import compileProgram, compileShader
from engine.constants import RENDER_MODE_LIT, RENDER_MODE_UNLIT, RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX
from PIL import Image
import os
import time
from collections import defaultdict


# =============================================================================
# Shader Loader - Loads shaders from files in the /shaders folder
# =============================================================================

class ShaderLoader:
    """Loads and compiles shaders from the shaders/ folder."""
    
    def __init__(self, shader_dir=None):
        if shader_dir is None:
            # Default: shaders folder at same level as this file
            self.shader_dir = os.path.join(os.path.dirname(__file__), 'shaders')
        else:
            self.shader_dir = shader_dir
    
    def load_shader_source(self, filename):
        """Load shader source code from file."""
        filepath = os.path.join(self.shader_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"Shader file not found: {filepath}")
        except Exception as e:
            raise RuntimeError(f"Error loading shader '{filepath}': {e}")
    
    def compile_shader_program(self, vertex_file, fragment_file):
        """Compile a shader program from vertex and fragment shader files."""
        vertex_source = self.load_shader_source(vertex_file)
        fragment_source = self.load_shader_source(fragment_file)
        
        try:
            program = compileProgram(
                compileShader(vertex_source, gl.GL_VERTEX_SHADER),
                compileShader(fragment_source, gl.GL_FRAGMENT_SHADER)
            )
            return program
        except Exception as e:
            raise RuntimeError(f"Shader compilation error ({vertex_file}, {fragment_file}): {e}")


# =============================================================================
# OPTIMIZATION: Frustum Culling
# =============================================================================

class Frustum:
    """
    View frustum for culling objects outside the camera's view.
    Uses plane extraction from the combined projection-view matrix.
    """
    
    LEFT, RIGHT, BOTTOM, TOP, NEAR, FAR = range(6)
    
    def __init__(self):
        self.planes = [glm.vec4(0) for _ in range(6)]
    
    def extract_from_matrix(self, proj_view: glm.mat4):
        """Extract frustum planes from combined projection-view matrix."""
        m = proj_view
        
        # Left plane: row3 + row0
        self.planes[self.LEFT] = glm.vec4(
            m[0][3] + m[0][0], m[1][3] + m[1][0], m[2][3] + m[2][0], m[3][3] + m[3][0]
        )
        # Right plane: row3 - row0
        self.planes[self.RIGHT] = glm.vec4(
            m[0][3] - m[0][0], m[1][3] - m[1][0], m[2][3] - m[2][0], m[3][3] - m[3][0]
        )
        # Bottom plane: row3 + row1
        self.planes[self.BOTTOM] = glm.vec4(
            m[0][3] + m[0][1], m[1][3] + m[1][1], m[2][3] + m[2][1], m[3][3] + m[3][1]
        )
        # Top plane: row3 - row1
        self.planes[self.TOP] = glm.vec4(
            m[0][3] - m[0][1], m[1][3] - m[1][1], m[2][3] - m[2][1], m[3][3] - m[3][1]
        )
        # Near plane: row3 + row2
        self.planes[self.NEAR] = glm.vec4(
            m[0][3] + m[0][2], m[1][3] + m[1][2], m[2][3] + m[2][2], m[3][3] + m[3][2]
        )
        # Far plane: row3 - row2
        self.planes[self.FAR] = glm.vec4(
            m[0][3] - m[0][2], m[1][3] - m[1][2], m[2][3] - m[2][2], m[3][3] - m[3][2]
        )
        
        # Normalize all planes
        for i in range(6):
            length = glm.length(glm.vec3(self.planes[i]))
            if length > 0:
                self.planes[i] /= length
    
    def is_box_visible(self, center, half_extents) -> bool:
        """
        Test if an AABB is visible within the frustum.
        Uses the "positive vertex" optimization for early rejection.
        """
        cx, cy, cz = center
        hx, hy, hz = half_extents
        
        for plane in self.planes:
            # Find the positive vertex (furthest along the plane normal)
            px = cx + hx if plane.x >= 0 else cx - hx
            py = cy + hy if plane.y >= 0 else cy - hy
            pz = cz + hz if plane.z >= 0 else cz - hz
            
            # If the positive vertex is behind the plane, the box is outside
            if plane.x * px + plane.y * py + plane.z * pz + plane.w < 0:
                return False
        
        return True


# =============================================================================
# OPTIMIZATION: Render Statistics
# =============================================================================

class RenderStats:
    """Track rendering statistics for profiling."""
    
    def __init__(self):
        self.reset()
    
    def reset(self):
        self.total_brushes = 0
        self.culled_brushes = 0
        self.visible_brushes = 0
        self.draw_calls = 0
    
    def __str__(self):
        if self.total_brushes == 0:
            return "No brushes"
        cull_pct = (self.culled_brushes / self.total_brushes) * 100
        return (f"Brushes: {self.visible_brushes}/{self.total_brushes} "
                f"({cull_pct:.1f}% culled) | Draw calls: {self.draw_calls}")


# =============================================================================
# OPTIMIZATION: LOD Manager
# =============================================================================

class LODManager:
    """Manages level of detail based on distance from camera."""
    
    LOD_FULL = 0
    LOD_REDUCED = 1
    LOD_CULLED = 2
    
    def __init__(self, full_dist=500.0, cull_dist=2000.0):
        self.full_dist_sq = full_dist * full_dist
        self.cull_dist_sq = cull_dist * cull_dist
    
    def get_lod_level(self, brush_pos, camera_pos) -> int:
        """Determine LOD level based on squared distance."""
        if isinstance(brush_pos, (list, tuple)):
            dx = brush_pos[0] - camera_pos.x
            dy = brush_pos[1] - camera_pos.y
            dz = brush_pos[2] - camera_pos.z
        else:
            dx = brush_pos.x - camera_pos.x
            dy = brush_pos.y - camera_pos.y
            dz = brush_pos.z - camera_pos.z
        
        dist_sq = dx*dx + dy*dy + dz*dz
        
        if dist_sq < self.full_dist_sq:
            return self.LOD_FULL
        elif dist_sq < self.cull_dist_sq:
            return self.LOD_REDUCED
        else:
            return self.LOD_CULLED


# =============================================================================
# Uniform Cache
# =============================================================================

class UniformCache:
    """Caches uniform locations to avoid repeated glGetUniformLocation calls."""
    
    def __init__(self, shader_program):
        self.program = shader_program
        self._cache = {}
    
    def __getitem__(self, name):
        if name not in self._cache:
            self._cache[name] = gl.glGetUniformLocation(self.program, name)
        return self._cache[name]
    
    def preload(self, names):
        """Pre-cache a list of uniform names."""
        for name in names:
            if name not in self._cache:
                self._cache[name] = gl.glGetUniformLocation(self.program, name)


# =============================================================================
# Main Renderer Class
# =============================================================================

class Renderer:
    """Optimized OpenGL renderer with frustum culling, uniform caching, and texture batching."""

    MAX_LIGHTS = 8

    def __init__(self, texture_loader, initial_grid_size, initial_world_size):
        self.texture_manager = {}
        self.load_texture_callback = texture_loader

        # Pre-allocated reusable matrices to avoid allocations in render loop
        self._identity_mat4 = glm.mat4(1.0)
        self._temp_vec3 = glm.vec3(0.0)
        
        # Cached light data to avoid re-uploading unchanged lights
        self._cached_light_hash = None
        self._cached_light_count = 0

        # === OPTIMIZATION: Frustum culling and stats ===
        self.frustum = Frustum()
        self.render_stats = RenderStats()
        self.lod_manager = LODManager()
        self._enable_frustum_culling = True
        self._enable_lod = True

        # 1. Compile Shaders from files
        try:
            self.shader_loader = ShaderLoader()
            self.shaders = {}
            self.uniforms = {}
            
            # Simple shader
            shader_simple = self.shader_loader.compile_shader_program('simple.vert', 'simple.frag')
            self.shaders['simple'] = shader_simple
            self.uniforms['simple'] = UniformCache(shader_simple)
            self.uniforms['simple'].preload(['projection', 'view', 'model', 'color'])
            
            # Lit shader
            shader_lit = self.shader_loader.compile_shader_program('lit.vert', 'lit.frag')
            self.shaders['lit'] = shader_lit
            self.uniforms['lit'] = UniformCache(shader_lit)
            self._preload_lit_uniforms('lit')
            
            # Textured shader
            shader_textured = self.shader_loader.compile_shader_program('textured.vert', 'textured.frag')
            self.shaders['textured'] = shader_textured
            self.uniforms['textured'] = UniformCache(shader_textured)
            self._preload_lit_uniforms('textured')
            self.uniforms['textured'].preload(['texture_diffuse'])
            
            # Sprite shader
            shader_sprite = self.shader_loader.compile_shader_program('sprite.vert', 'sprite.frag')
            self.shaders['sprite'] = shader_sprite
            self.uniforms['sprite'] = UniformCache(shader_sprite)
            self.uniforms['sprite'].preload(['projection', 'view', 'sprite_texture', 'sprite_pos_world', 'sprite_size'])
            
            # Shadow volume shader
            shader_shadow_volume = self.shader_loader.compile_shader_program('shadow_volume.vert', 'shadow_volume.frag')
            self.shaders['shadow_volume'] = shader_shadow_volume
            self.uniforms['shadow_volume'] = UniformCache(shader_shadow_volume)
            self.uniforms['shadow_volume'].preload(['projection', 'view', 'model', 'light_pos'])
            
            # Fog shader
            shader_fog = self.shader_loader.compile_shader_program('fog.vert', 'fog.frag')
            self.shaders['fog'] = shader_fog
            self.uniforms['fog'] = UniformCache(shader_fog)
            self._preload_lit_uniforms('fog')
            self.uniforms['fog'].preload(['viewPos', 'time', 'noiseTexture', 'density', 'fogColor', 'noiseScale'])

            print(f"Shaders loaded successfully from: {self.shader_loader.shader_dir}")

        except Exception as e:
            print(f"FATAL: Shader Compilation Error: {e}")
            return
        
        # 2. Create Vertex Buffers (VAOs)
        self.vaos = {
            'cube': self._create_cube_vao(),
            'sprite': self._create_sprite_vao(),
            'grid': None,
        }
        self.grid_indices_count = 0
        self._create_gizmo_buffers()
        self.update_grid_buffers(initial_world_size, initial_grid_size)

        # 3. Load Essential Textures
        self.noise_texture_id = self._load_3d_texture('assets/noise_3d.bin')
        self.sprite_textures = {}
        self.load_texture('default.png', 'textures')
        self.load_texture('caulk', 'textures')
        
        # 4. Pre-computed value_ptr references for matrices (avoid repeated calls)
        self._proj_ptr = None
        self._view_ptr = None

    def _preload_lit_uniforms(self, shader_name):
        """Pre-cache all uniforms for lit/textured shaders including light arrays."""
        uniforms = self.uniforms[shader_name]
        uniforms.preload(['projection', 'view', 'model', 'object_color', 'alpha', 'active_lights'])
        
        for i in range(self.MAX_LIGHTS):
            uniforms.preload([
                f'lights[{i}].position',
                f'lights[{i}].color',
                f'lights[{i}].intensity',
                f'lights[{i}].radius'
            ])

    def update_grid_buffers(self, world_size, grid_size):
        """Creates or updates the grid VAO."""
        if grid_size <= 0:
            if self.vaos['grid']:
                gl.glDeleteVertexArrays(1, [self.vaos['grid']])
                self.vaos['grid'] = None
            return

        s, g = world_size, grid_size
        lines = [[-s, 0, i, s, 0, i, i, 0, -s, i, 0, s] for i in range(-s, s + 1, g)]
        grid_vertices = np.array(lines, dtype=np.float32).flatten()
        self.grid_indices_count = len(grid_vertices) // 3
        
        if self.vaos['grid']:
            gl.glDeleteVertexArrays(1, [self.vaos['grid']])
        
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, grid_vertices.nbytes, grid_vertices, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)
        self.vaos['grid'] = vao
    
    def set_sprite_textures(self, textures):
        self.sprite_textures = textures

    def load_texture(self, texture_name, subfolder):
        """Load texture with caching."""
        tex_cache_name = os.path.join(subfolder, texture_name)
        if tex_cache_name in self.texture_manager:
            return self.texture_manager[tex_cache_name]
            
        if texture_name == 'default.png':
            tex_id = gl.glGenTextures(1)
            self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            pixels = [255, 255, 255, 255]
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 1, 1, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, (gl.GLubyte * 4)(*pixels))
            return tex_id
            
        if texture_name == 'caulk':
            tex_id = gl.glGenTextures(1)
            self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            pixels = [255, 0, 255, 255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 0, 255, 255]
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 2, 2, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, (gl.GLubyte * 16)(*pixels))
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            return tex_id
            
        texture_path = os.path.join('assets', subfolder, texture_name)
        if not os.path.exists(texture_path):
            return self.load_texture('default.png', 'textures')
            
        try:
            img = Image.open(texture_path).convert("RGBA")
            img_data = img.tobytes()
            tex_id = gl.glGenTextures(1)
            self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, img.width, img.height, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, img_data)
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            return tex_id
        except Exception as e:
            print(f"Error loading texture '{texture_name}': {e}")
            return self.load_texture('default.png', 'textures')

    def preload_level_textures(self, brushes):
        """Pre-load all textures referenced by brushes at level load time."""
        texture_set = set()
        for brush in brushes:
            textures = brush.get('textures', {})
            for face_tex in textures.values():
                if face_tex and face_tex != 'caulk.jpg':
                    texture_set.add(face_tex)
        
        print(f"Preloading {len(texture_set)} textures...")
        for tex_name in texture_set:
            self.load_texture(tex_name, 'textures')
        print("Texture preloading complete.")

    def _load_3d_texture(self, filepath, size=32):
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            
            if len(data) != size * size * size:
                print(f"Error: 3D texture data size mismatch in {filepath}.")
                return 0

            texture_id = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_3D, texture_id)
            gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_WRAP_R, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
            gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexImage3D(gl.GL_TEXTURE_3D, 0, gl.GL_R8, size, size, size, 0, gl.GL_RED, gl.GL_UNSIGNED_BYTE, data)
            return texture_id
        except FileNotFoundError:
            print(f"Error: 3D noise texture not found at '{filepath}'.")
            return 0
        except Exception as e:
            print(f"An error occurred loading the 3D texture: {e}")
            return 0

    # =========================================================================
    # OPTIMIZATION: Frustum culling helper
    # =========================================================================
    
    def _cull_brushes(self, projection, view, camera_pos, brushes):
        """
        Perform frustum culling and LOD classification on brushes.
        Returns list of visible brushes (already filtered).
        """
        self.render_stats.reset()
        self.render_stats.total_brushes = len(brushes)
        
        if not self._enable_frustum_culling:
            self.render_stats.visible_brushes = len(brushes)
            return brushes
        
        # Extract frustum planes from combined matrix
        proj_view = projection * view
        self.frustum.extract_from_matrix(proj_view)
        
        visible = []
        
        for brush in brushes:
            pos = brush['pos']
            size = brush['size']
            
            # AABB center and half-extents
            center = (pos[0], pos[1], pos[2])
            half_extents = (size[0] * 0.5, size[1] * 0.5, size[2] * 0.5)
            
            # Frustum culling
            if not self.frustum.is_box_visible(center, half_extents):
                self.render_stats.culled_brushes += 1
                continue
            
            # LOD culling (distance-based)
            if self._enable_lod:
                lod_level = self.lod_manager.get_lod_level(pos, camera_pos)
                if lod_level == LODManager.LOD_CULLED:
                    self.render_stats.culled_brushes += 1
                    continue
            
            visible.append(brush)
            self.render_stats.visible_brushes += 1
        
        return visible
    
    # =========================================================================
    # Main Render Entry Point
    # =========================================================================
    
    def render_scene(self, projection, view, camera_pos, brushes, things, selected_object, config):
        """Main entry point to render a complete scene."""
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        gl.glEnable(gl.GL_PROGRAM_POINT_SIZE)

        # Cache matrix pointers for this frame
        self._proj_ptr = glm.value_ptr(projection)
        self._view_ptr = glm.value_ptr(view)

        current_mode = config.get('render_mode', RENDER_MODE_LIT)

        if current_mode == RENDER_MODE_WIREFRAME:
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
        elif current_mode == RENDER_MODE_VERTEX:
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_POINT)
            gl.glPointSize(4.0)
        else:
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        self.draw_grid(projection, view, self.grid_indices_count)

        # Sort objects once
        opaque_brushes, transparent_brushes, sprites, fog_volumes = self._sort_objects(brushes, things, config)
        
        # Get active lights once
        lights = [t for t in things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']

        # --- 1. Opaque Pass ---
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        
        if current_mode == RENDER_MODE_UNLIT:
            self.draw_textured_brushes(projection, view, camera_pos, opaque_brushes, lights, config)
        elif current_mode == RENDER_MODE_LIT:
            self.draw_lit_brushes(projection, view, camera_pos, opaque_brushes, lights, config)
        else:
            self.draw_lit_brushes(projection, view, camera_pos, opaque_brushes, lights, config)

        # --- Shadow Pass ---
        if current_mode == RENDER_MODE_LIT:
            shadow_casting_lights = [light for light in lights if light.properties.get('casts_shadows')]
            if shadow_casting_lights:
                self.render_shadows(projection, view, camera_pos, opaque_brushes, shadow_casting_lights)

        # --- 2. Transparent Pass ---
        if transparent_brushes:
            transparent_brushes.sort(key=lambda b: -self._distance_sq(b['pos'], camera_pos))
        if sprites:
            sprites.sort(key=lambda s: -self._distance_sq(s.pos, camera_pos))
        
        gl.glEnable(gl.GL_BLEND)
        gl.glDepthMask(gl.GL_FALSE)

        self.draw_sprites(projection, view, sprites, self.sprite_textures)
        
        if current_mode == RENDER_MODE_UNLIT:
            self.draw_textured_brushes(projection, view, camera_pos, transparent_brushes, lights, config)
        else:
            self.draw_lit_brushes(projection, view, camera_pos, transparent_brushes, lights, config, is_transparent_pass=True)

        if current_mode == RENDER_MODE_LIT:
            self.draw_fog_volumes(projection, view, camera_pos, fog_volumes, lights, config)

        # --- 3. Overlays ---
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        if selected_object:
            if isinstance(selected_object, dict):
                self.draw_selected_brush_outline(projection, view, selected_object)
                if not selected_object.get('lock', False):
                    self.render_gizmo(projection, view, selected_object['pos'])
            elif isinstance(selected_object, Thing):
                self.render_gizmo(projection, view, selected_object.pos)

        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(0)

    def _distance_sq(self, pos1, pos2):
        """Calculate squared distance (faster than actual distance for sorting)."""
        if isinstance(pos1, (list, tuple)):
            dx = pos1[0] - pos2.x
            dy = pos1[1] - pos2.y
            dz = pos1[2] - pos2.z
        else:
            dx = pos1.x - pos2.x
            dy = pos1.y - pos2.y
            dz = pos1.z - pos2.z
        return dx*dx + dy*dy + dz*dz

    def _set_light_uniforms_cached(self, shader_name, lights):
        """Set light uniforms with caching to avoid redundant uploads."""
        uniforms = self.uniforms[shader_name]
        num_lights = min(len(lights), self.MAX_LIGHTS)
        
        gl.glUniform1i(uniforms['active_lights'], num_lights)
        
        for i in range(num_lights):
            light = lights[i]
            gl.glUniform3fv(uniforms[f'lights[{i}].position'], 1, light.pos)
            gl.glUniform3fv(uniforms[f'lights[{i}].color'], 1, light.get_color())
            gl.glUniform1f(uniforms[f'lights[{i}].intensity'], light.get_intensity())
            gl.glUniform1f(uniforms[f'lights[{i}].radius'], light.get_radius())

    def draw_fog_volumes(self, projection, view, camera_pos, brushes, lights, config):
        """Draws brushes as fog volumes with cached uniforms."""
        if not brushes:
            return
        
        # === OPTIMIZATION: Cull fog volumes ===
        visible_brushes = self._cull_brushes(projection, view, camera_pos, brushes)
        if not visible_brushes:
            return

        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)

        shader = self.shaders['fog']
        uniforms = self.uniforms['fog']
        gl.glUseProgram(shader)

        self._set_light_uniforms_cached('fog', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniform3fv(uniforms['viewPos'], 1, glm.value_ptr(camera_pos))
        gl.glUniform1f(uniforms['time'], config.get('time', 0.0))

        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_3D, self.noise_texture_id)
        gl.glUniform1i(uniforms['noiseTexture'], 1)

        gl.glBindVertexArray(self.vaos['cube'])
        gl.glEnable(gl.GL_CULL_FACE)

        model_loc = uniforms['model']
        density_loc = uniforms['density']
        fog_color_loc = uniforms['fogColor']
        noise_scale_loc = uniforms['noiseScale']

        for brush in visible_brushes:
            pos = brush['pos']
            size = brush['size']
            model_matrix = glm.translate(self._identity_mat4, glm.vec3(pos[0], pos[1], pos[2]))
            model_matrix = glm.scale(model_matrix, glm.vec3(size[0], size[1], size[2]))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

            gl.glUniform1f(density_loc, brush.get('fog_density', 0.01))
            gl.glUniform3fv(fog_color_loc, 1, brush.get('fog_color', [0.5, 0.6, 0.7]))
            gl.glUniform1f(noise_scale_loc, brush.get('fog_noise_scale', 0.01))

            gl.glCullFace(gl.GL_FRONT)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            gl.glCullFace(gl.GL_BACK)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)

        gl.glDisable(gl.GL_CULL_FACE)
        gl.glBindVertexArray(0)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def render_shadows(self, projection, view, camera_pos, brushes, lights):
        """Render shadow volumes with cached uniforms."""
        gl.glEnable(gl.GL_STENCIL_TEST)
        gl.glEnable(gl.GL_DEPTH_CLAMP)
        gl.glDisable(gl.GL_CULL_FACE)

        shadow_casters = [b for b in brushes if not b.get('is_trigger', False)]
        
        # === OPTIMIZATION: Cull shadow casters ===
        visible_shadow_casters = self._cull_brushes(projection, view, camera_pos, shadow_casters)
        
        shadow_uniforms = self.uniforms['shadow_volume']
        lit_uniforms = self.uniforms['lit']

        for light in lights:
            gl.glClear(gl.GL_STENCIL_BUFFER_BIT)
            
            gl.glColorMask(gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE)
            gl.glDepthMask(gl.GL_FALSE)
            gl.glStencilFunc(gl.GL_ALWAYS, 0, 0xFF)
            gl.glStencilOpSeparate(gl.GL_BACK, gl.GL_KEEP, gl.GL_INCR_WRAP, gl.GL_KEEP)
            gl.glStencilOpSeparate(gl.GL_FRONT, gl.GL_KEEP, gl.GL_DECR_WRAP, gl.GL_KEEP)

            shader = self.shaders['shadow_volume']
            gl.glUseProgram(shader)
            gl.glUniformMatrix4fv(shadow_uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
            gl.glUniformMatrix4fv(shadow_uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
            
            light_pos_vec3 = glm.vec3(light.pos[0], light.pos[1], light.pos[2])
            gl.glUniform3fv(shadow_uniforms['light_pos'], 1, glm.value_ptr(light_pos_vec3))
            
            model_loc = shadow_uniforms['model']
            gl.glBindVertexArray(self.vaos['cube'])
            
            for brush in visible_shadow_casters:
                pos, size = brush['pos'], brush['size']
                model_matrix = glm.translate(self._identity_mat4, glm.vec3(pos[0], pos[1], pos[2]))
                model_matrix = glm.scale(model_matrix, glm.vec3(size[0], size[1], size[2]))
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            
            gl.glDepthMask(gl.GL_TRUE)
            gl.glColorMask(gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE)
            gl.glStencilFunc(gl.GL_NOTEQUAL, 0, 0xFF)
            gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)

            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glDepthFunc(gl.GL_LEQUAL)

            shader = self.shaders['lit']
            gl.glUseProgram(shader)
            gl.glUniform1i(lit_uniforms['active_lights'], 0)
            gl.glUniformMatrix4fv(lit_uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
            gl.glUniformMatrix4fv(lit_uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)

            model_loc = lit_uniforms['model']
            color_loc = lit_uniforms['object_color']
            alpha_loc = lit_uniforms['alpha']
            
            gl.glBindVertexArray(self.vaos['cube'])
            for brush in visible_shadow_casters:
                pos, size = brush['pos'], brush['size']
                model_matrix = glm.translate(self._identity_mat4, glm.vec3(pos[0], pos[1], pos[2]))
                model_matrix = glm.scale(model_matrix, glm.vec3(size[0], size[1], size[2]))
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
                gl.glUniform3fv(color_loc, 1, [0.0, 0.0, 0.0])
                gl.glUniform1f(alpha_loc, 0.5)
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
                
            gl.glDepthFunc(gl.GL_LESS)
            gl.glDisable(gl.GL_BLEND)

        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glDisable(gl.GL_DEPTH_CLAMP)

    def _sort_objects(self, brushes, things, config):
        """Sorts scene objects into opaque, transparent, and sprite lists."""
        opaque_brushes = []
        transparent_brushes = []
        sprites = []
        fog_volumes = []
        is_play_mode = config.get('play_mode', False)
        show_sprites_in_play_mode = config.get('show_sprites_in_play_mode', False)

        for brush in brushes:
            if brush.get('hidden', False):
                continue
            if brush.get('is_fog', False):
                fog_volumes.append(brush)
            elif brush.get('is_trigger', False):
                if not is_play_mode:
                    transparent_brushes.append(brush)
            else:
                opaque_brushes.append(brush)
        
        if not is_play_mode or show_sprites_in_play_mode:
            for t in things:
                if isinstance(t, Thing):
                    sprites.append(t)
            
        return opaque_brushes, transparent_brushes, sprites, fog_volumes

    def draw_grid(self, projection, view, grid_indices_count):
        """Draw the grid with cached uniforms."""
        if not self.vaos['grid']:
            return
            
        shader = self.shaders['simple']
        uniforms = self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(self._identity_mat4))
        gl.glUniform3f(uniforms['color'], 0.2, 0.2, 0.2)
        
        gl.glBindVertexArray(self.vaos['grid'])
        gl.glDrawArrays(gl.GL_LINES, 0, grid_indices_count)
        gl.glBindVertexArray(0)

    def draw_lit_brushes(self, projection, view, camera_pos, brushes, lights, config, is_transparent_pass=False):
        """Draw lit brushes with frustum culling, cached uniforms, and batched state changes."""
        if not brushes:
            return
        
        # === OPTIMIZATION: Frustum culling ===
        visible_brushes = self._cull_brushes(projection, view, camera_pos, brushes)
        if not visible_brushes:
            return
            
        shader = self.shaders['lit']
        uniforms = self.uniforms['lit']
        gl.glUseProgram(shader)

        self._set_light_uniforms_cached('lit', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        
        gl.glBindVertexArray(self.vaos['cube'])
        
        display_mode = config.get('brush_display_mode', 'Textured')
        show_triggers_solid = config.get('show_triggers_as_solid', False)
        selected_object = config.get('selected_object')

        model_loc = uniforms['model']
        color_loc = uniforms['object_color']
        alpha_loc = uniforms['alpha']

        if is_transparent_pass:
            fill_mode = gl.GL_FILL if show_triggers_solid else gl.GL_LINE
        else:
            fill_mode = gl.GL_FILL if display_mode != "Wireframe" else gl.GL_LINE

        current_poly_mode = None

        for brush in visible_brushes:
            target_mode = fill_mode
            if target_mode != current_poly_mode:
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, target_mode)
                current_poly_mode = target_mode

            pos, size = brush['pos'], brush['size']
            model_matrix = glm.translate(self._identity_mat4, glm.vec3(pos[0], pos[1], pos[2]))
            model_matrix = glm.scale(model_matrix, glm.vec3(size[0], size[1], size[2]))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

            is_selected = brush is selected_object
            is_subtract = brush.get('operation') == 'subtract'
            
            if brush.get('is_trigger', False):
                color, alpha = [0.0, 1.0, 1.0], 0.3
            elif is_selected:
                color, alpha = [1.0, 1.0, 0.0], 1.0
            elif is_subtract:
                color, alpha = [1.0, 0.0, 0.0], 1.0
            else:
                color, alpha = [0.8, 0.8, 0.8], 1.0

            gl.glUniform3fv(color_loc, 1, color)
            gl.glUniform1f(alpha_loc, alpha)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            self.render_stats.draw_calls += 1

        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glBindVertexArray(0)

    def draw_textured_brushes(self, projection, view, camera_pos, brushes, lights, config):
        """Draw textured brushes with frustum culling and texture batching."""
        if not brushes:
            return
        
        # === OPTIMIZATION: Frustum culling ===
        visible_brushes = self._cull_brushes(projection, view, camera_pos, brushes)
        if not visible_brushes:
            return
            
        shader = self.shaders['textured']
        uniforms = self.uniforms['textured']
        gl.glUseProgram(shader)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        self._set_light_uniforms_cached('textured', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)

        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(uniforms['texture_diffuse'], 0)

        gl.glBindVertexArray(self.vaos['cube'])
        
        model_loc = uniforms['model']
        face_keys = ['south', 'north', 'west', 'east', 'bottom', 'top']

        # Batch brushes by texture to minimize texture switches
        texture_batches = defaultdict(list)
        
        for brush in visible_brushes:
            textures = brush.get('textures', {})
            for i, face_key in enumerate(face_keys):
                tex_name = textures.get(face_key, 'default.png')
                if tex_name == 'caulk.jpg':
                    continue
                tex_cache_name = os.path.join('textures', tex_name)
                if tex_cache_name in self.texture_manager:
                    tex_id = self.texture_manager[tex_cache_name]
                else:
                    tex_id = self.load_texture_callback(tex_name, 'textures')
                texture_batches[tex_id].append((brush, i))

        # Render batched by texture
        current_tex = None
        for tex_id, brush_faces in texture_batches.items():
            if tex_id != current_tex:
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                current_tex = tex_id
            
            for brush, face_index in brush_faces:
                pos, size = brush['pos'], brush['size']
                model_matrix = glm.translate(self._identity_mat4, glm.vec3(pos[0], pos[1], pos[2]))
                model_matrix = glm.scale(model_matrix, glm.vec3(size[0], size[1], size[2]))
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
                gl.glDrawArrays(gl.GL_TRIANGLES, face_index * 6, 6)
                self.render_stats.draw_calls += 1
        
        gl.glBindVertexArray(0)

    def draw_selected_brush_outline(self, projection, view, brush):
        """Draw selection outline with cached uniforms."""
        shader = self.shaders['simple']
        uniforms = self.uniforms['simple']
        gl.glUseProgram(shader)

        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        
        pos, size = brush['pos'], brush['size']
        model_matrix = glm.translate(self._identity_mat4, glm.vec3(pos[0], pos[1], pos[2]))
        model_matrix = glm.scale(model_matrix, glm.vec3(size[0], size[1], size[2]))
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
        gl.glUniform3f(uniforms['color'], 1.0, 1.0, 0.0)

        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
        gl.glLineWidth(1)
        
        gl.glBindVertexArray(self.vaos['cube'])
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
        
        gl.glLineWidth(1)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glBindVertexArray(0)

    def draw_sprites(self, projection, view, things_to_draw, sprite_textures):
        """Draw sprites with cached uniforms."""
        if not things_to_draw:
            return
            
        shader = self.shaders['sprite']
        uniforms = self.uniforms['sprite']
        gl.glUseProgram(shader)

        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(uniforms['sprite_texture'], 0)
        
        pos_loc = uniforms['sprite_pos_world']
        size_loc = uniforms['sprite_size']
        
        gl.glBindVertexArray(self.vaos['sprite'])
        
        current_tex = None
        for thing in things_to_draw:
            thing_type = thing.__class__.__name__
            if thing_type in sprite_textures:
                tex_id = sprite_textures[thing_type]
                if tex_id != current_tex:
                    gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                    current_tex = tex_id
                gl.glUniform3fv(pos_loc, 1, thing.pos)
                size = 16.0 if isinstance(thing, Light) else 32.0
                gl.glUniform2f(size_loc, size, size)
                gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
                
        gl.glBindVertexArray(0)

    def _set_light_uniforms(self, shader, lights):
        """Legacy method for compatibility."""
        gl.glUniform1i(gl.glGetUniformLocation(shader, "active_lights"), len(lights))
        for i, light in enumerate(lights):
            gl.glUniform3fv(gl.glGetUniformLocation(shader, f"lights[{i}].position"), 1, light.pos)
            gl.glUniform3fv(gl.glGetUniformLocation(shader, f"lights[{i}].color"), 1, light.get_color())
            gl.glUniform1f(gl.glGetUniformLocation(shader, f"lights[{i}].intensity"), light.get_intensity())
            gl.glUniform1f(gl.glGetUniformLocation(shader, f"lights[{i}].radius"), light.get_radius())

    def _create_cube_vao(self):
        # fmt: off
        vertices = np.array([
            # Positions           # Normals           # Tex Coords
            # Back Face (-Z) - South
            -0.5, -0.5, -0.5,  0.0,  0.0, -1.0,  0.0, 0.0,
             0.5, -0.5, -0.5,  0.0,  0.0, -1.0,  1.0, 0.0,
             0.5,  0.5, -0.5,  0.0,  0.0, -1.0,  1.0, 1.0,
             0.5,  0.5, -0.5,  0.0,  0.0, -1.0,  1.0, 1.0,
            -0.5,  0.5, -0.5,  0.0,  0.0, -1.0,  0.0, 1.0,
            -0.5, -0.5, -0.5,  0.0,  0.0, -1.0,  0.0, 0.0,
            # Front Face (+Z) - North
            -0.5, -0.5,  0.5,  0.0,  0.0,  1.0,  0.0, 0.0,
             0.5,  0.5,  0.5,  0.0,  0.0,  1.0,  1.0, 1.0,
             0.5, -0.5,  0.5,  0.0,  0.0,  1.0,  1.0, 0.0,
             0.5,  0.5,  0.5,  0.0,  0.0,  1.0,  1.0, 1.0,
            -0.5, -0.5,  0.5,  0.0,  0.0,  1.0,  0.0, 0.0,
            -0.5,  0.5,  0.5,  0.0,  0.0,  1.0,  0.0, 1.0,
            # Left Face (-X) - West
            -0.5,  0.5,  0.5, -1.0,  0.0,  0.0,  1.0, 0.0,
            -0.5, -0.5, -0.5, -1.0,  0.0,  0.0,  0.0, 1.0,
            -0.5,  0.5, -0.5, -1.0,  0.0,  0.0,  1.0, 1.0,
            -0.5, -0.5, -0.5, -1.0,  0.0,  0.0,  0.0, 1.0,
            -0.5,  0.5,  0.5, -1.0,  0.0,  0.0,  1.0, 0.0,
            -0.5, -0.5,  0.5, -1.0,  0.0,  0.0,  0.0, 0.0,
            # Right Face (+X) - East
             0.5,  0.5,  0.5,  1.0,  0.0,  0.0,  1.0, 0.0,
             0.5,  0.5, -0.5,  1.0,  0.0,  0.0,  1.0, 1.0,
             0.5, -0.5, -0.5,  1.0,  0.0,  0.0,  0.0, 1.0,
             0.5, -0.5, -0.5,  1.0,  0.0,  0.0,  0.0, 1.0,
             0.5, -0.5,  0.5,  1.0,  0.0,  0.0,  0.0, 0.0,
             0.5,  0.5,  0.5,  1.0,  0.0,  0.0,  1.0, 0.0,
            # Bottom Face (-Y)
            -0.5, -0.5, -0.5,  0.0, -1.0,  0.0,  0.0, 1.0,
             0.5, -0.5,  0.5,  0.0, -1.0,  0.0,  1.0, 0.0,
             0.5, -0.5, -0.5,  0.0, -1.0,  0.0,  1.0, 1.0,
             0.5, -0.5,  0.5,  0.0, -1.0,  0.0,  1.0, 0.0,
            -0.5, -0.5, -0.5,  0.0, -1.0,  0.0,  0.0, 1.0,
            -0.5, -0.5,  0.5,  0.0, -1.0,  0.0,  0.0, 0.0,
            # Top Face (+Y)
            -0.5,  0.5, -0.5,  0.0,  1.0,  0.0,  0.0, 1.0,
             0.5,  0.5, -0.5,  0.0,  1.0,  0.0,  1.0, 1.0,
             0.5,  0.5,  0.5,  0.0,  1.0,  0.0,  1.0, 0.0,
             0.5,  0.5,  0.5,  0.0,  1.0,  0.0,  1.0, 0.0,
            -0.5,  0.5,  0.5,  0.0,  1.0,  0.0,  0.0, 0.0,
            -0.5,  0.5, -0.5,  0.0,  1.0,  0.0,  0.0, 1.0
        ], dtype=np.float32)
        # fmt: on
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
        return vao

    def _create_gizmo_buffers(self):
        axis_verts = np.array([0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 1], dtype=np.float32)
        self.vao_gizmo_lines = gl.glGenVertexArrays(1)
        vbo_gizmo_lines = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo_gizmo_lines)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, axis_verts.nbytes, axis_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)

        cone_verts = []
        num_segments, radius, height = 12, 0.05, 0.2
        for i in range(num_segments):
            theta1 = (i / num_segments) * 2 * np.pi
            theta2 = ((i + 1) / num_segments) * 2 * np.pi
            cone_verts.extend([0, 0, 0, np.cos(theta2) * radius, 0, np.sin(theta2) * radius, np.cos(theta1) * radius, 0, np.sin(theta1) * radius])
            cone_verts.extend([0, height, 0, np.cos(theta1) * radius, 0, np.sin(theta1) * radius, np.cos(theta2) * radius, 0, np.sin(theta2) * radius])

        self.gizmo_cone_v_count = len(cone_verts) // 3
        cone_verts = np.array(cone_verts, dtype=np.float32)
        
        self.vao_gizmo_cone = gl.glGenVertexArrays(1)
        vbo_gizmo_cone = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao_gizmo_cone)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo_gizmo_cone)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, cone_verts.nbytes, cone_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glEnableVertexAttribArray(0)

        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)

    def render_gizmo(self, projection, view, position):
        """Render gizmo with cached uniforms."""
        shader = self.shaders['simple']
        uniforms = self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        
        if isinstance(position, (list, tuple)):
            pos_vec = glm.vec3(position[0], position[1], position[2])
        else:
            pos_vec = position
            
        base_model = glm.translate(self._identity_mat4, pos_vec)
        base_model = glm.scale(base_model, glm.vec3(32.0))

        model_loc = uniforms['model']
        color_loc = uniforms['color']

        gl.glLineWidth(1)
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(base_model))
        gl.glUniform3f(color_loc, 1, 0, 0)
        gl.glDrawArrays(gl.GL_LINES, 0, 2)
        gl.glUniform3f(color_loc, 0, 1, 0)
        gl.glDrawArrays(gl.GL_LINES, 2, 2)
        gl.glUniform3f(color_loc, 0, 0, 1)
        gl.glDrawArrays(gl.GL_LINES, 4, 2)
        gl.glLineWidth(1)

        gl.glBindVertexArray(self.vao_gizmo_cone)
        
        model_x = glm.translate(base_model, glm.vec3(1, 0, 0))
        model_x = glm.rotate(model_x, glm.radians(-90.0), glm.vec3(0, 0, 1))
        gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_x))
        gl.glUniform3f(color_loc, 1, 0, 0)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)

        model_y = glm.translate(base_model, glm.vec3(0, 1, 0))
        gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_y))
        gl.glUniform3f(color_loc, 0, 1, 0)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)
        
        model_z = glm.translate(base_model, glm.vec3(0, 0, 1))
        model_z = glm.rotate(model_z, glm.radians(90.0), glm.vec3(1, 0, 0))
        gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_z))
        gl.glUniform3f(color_loc, 0, 0, 1)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)

        gl.glBindVertexArray(0)
