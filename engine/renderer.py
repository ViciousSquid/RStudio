import glm
import numpy as np
import OpenGL.GL as gl
import ctypes 
from editor.things import Thing, Light 
from OpenGL.GL.shaders import compileProgram, compileShader 
from engine.constants import RENDER_MODE_LIT, RENDER_MODE_UNLIT, RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX 
from engine.shaders import DEFAULT_SHADERS
from PIL import Image 
import os
from collections import defaultdict

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
            if not os.path.exists(filepath):
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
                program = compileProgram(vs, fs, gs)
            else:
                program = compileProgram(vs, fs)
            return program
        except Exception as e:
            print(f"Error compiling shader ({vertex_file}, {fragment_file}): {e}")
            raise

class Frustum:
    __slots__ = ('planes', '_plane_normals', '_plane_distances')
    def __init__(self):
        self.planes = [glm.vec4(0) for _ in range(6)]
        self._plane_normals = np.zeros((6, 3), dtype=np.float32)
        self._plane_distances = np.zeros(6, dtype=np.float32)
    
    def extract_from_matrix(self, proj_view):
        m = proj_view
        self.planes[0] = glm.vec4(m[0][3] + m[0][0], m[1][3] + m[1][0], m[2][3] + m[2][0], m[3][3] + m[3][0])
        self.planes[1] = glm.vec4(m[0][3] - m[0][0], m[1][3] - m[1][0], m[2][3] - m[2][0], m[3][3] - m[3][0])
        self.planes[2] = glm.vec4(m[0][3] + m[0][1], m[1][3] + m[1][1], m[2][3] + m[2][1], m[3][3] + m[3][1])
        self.planes[3] = glm.vec4(m[0][3] - m[0][1], m[1][3] - m[1][1], m[2][3] - m[2][1], m[3][3] - m[3][1])
        self.planes[4] = glm.vec4(m[0][3] + m[0][2], m[1][3] + m[1][2], m[2][3] + m[2][2], m[3][3] + m[3][2])
        self.planes[5] = glm.vec4(m[0][3] - m[0][2], m[1][3] - m[1][2], m[2][3] - m[2][2], m[3][3] - m[3][2])
        for i in range(6):
            length = glm.length(glm.vec3(self.planes[i]))
            if length > 0: self.planes[i] /= length
            self._plane_normals[i] = [self.planes[i].x, self.planes[i].y, self.planes[i].z]
            self._plane_distances[i] = self.planes[i].w
    
    def is_box_visible(self, center, half_extents):
        cx, cy, cz = center
        hx, hy, hz = half_extents
        signs = np.sign(self._plane_normals)
        p_vertices = np.array([cx + signs[:, 0] * hx, cy + signs[:, 1] * hy, cz + signs[:, 2] * hz]).T
        dots = np.sum(self._plane_normals * p_vertices, axis=1) + self._plane_distances
        return np.all(dots >= 0)

class RenderStats:
    __slots__ = ('total_brushes', 'culled_brushes', 'visible_brushes', 'draw_calls', 'shadow_draw_calls')
    def __init__(self): self.reset()
    def reset(self): self.total_brushes = self.culled_brushes = self.visible_brushes = self.draw_calls = self.shadow_draw_calls = 0

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
            if name not in self._cache: self._cache[name] = gl.glGetUniformLocation(self.program, name)

class ShadowBatch:
    __slots__ = ('positions', 'scales', 'rotations', 'alphas', 'count', 'capacity')
    def __init__(self, capacity=1024):
        self.capacity = capacity
        self.positions = np.zeros((capacity, 3), dtype=np.float32)
        self.scales = np.zeros((capacity, 3), dtype=np.float32)
        self.rotations = np.zeros(capacity, dtype=np.float32)
        self.alphas = np.zeros(capacity, dtype=np.float32)
        self.count = 0
    def reset(self): self.count = 0
    def add(self, pos, scale, rotation, alpha):
        if self.count >= self.capacity: return False
        i = self.count
        self.positions[i], self.scales[i], self.rotations[i], self.alphas[i] = pos, scale, rotation, alpha
        self.count += 1
        return True

class Renderer:
    MAX_LIGHTS = 16
    def __init__(self, texture_loader, initial_grid_size, initial_world_size):
        self.texture_manager = {}
        self.load_texture_callback = texture_loader
        self._identity_mat4 = glm.mat4(1.0)
        self.frustum = Frustum()
        self.render_stats = RenderStats()
        self.lod_manager = LODManager()
        self._enable_frustum_culling = True
        self._enable_lod = True
        self._model_matrix = glm.mat4(1.0)
        self._floor_shadow_batch = ShadowBatch(2048)
        self._wall_shadow_batch = ShadowBatch(1024)

        try:
            self.shader_loader = ShaderLoader()
            self.shaders = {}
            self.uniforms = {}
            for name, files in [('simple', ('simple.vert', 'simple.frag')),
                                ('lit', ('lit.vert', 'lit.frag')),
                                ('textured', ('textured.vert', 'textured.frag')),
                                ('sprite', ('sprite.vert', 'sprite.frag')),
                                ('shadow_volume', ('shadow_volume.vert', 'shadow_volume.frag')),
                                ('fog', ('fog.vert', 'fog.frag')),
                                ('water', ('water.vert', 'water.frag'))]:
                shader = self.shader_loader.compile_shader_program(*files)
                self.shaders[name] = shader
                self.uniforms[name] = UniformCache(shader)
            
            self.uniforms['simple'].preload(['projection', 'view', 'model', 'color'])
            self._preload_lit_uniforms('lit')
            self._preload_lit_uniforms('textured')
            self.uniforms['textured'].preload(['texture_diffuse'])
            self.uniforms['sprite'].preload(['projection', 'view', 'sprite_texture', 'sprite_pos_world', 'sprite_size'])
            self.uniforms['shadow_volume'].preload(['projection', 'view', 'model', 'light_pos'])
            self._preload_lit_uniforms('fog')
            self.uniforms['fog'].preload(['viewPos', 'time', 'noiseTexture', 'density', 'fogColor', 'noiseScale', 'object_color', 'alpha'])
            
            self._preload_lit_uniforms('water')
            # Updated preloads for Water to include new uniforms for Opacity and Reflectivity
            self.uniforms['water'].preload(['time', 'viewPos', 'normalMap', 'waterOpacity', 'waterReflectivity', 'waterTint'])
            self.water_normal_id = self.load_texture('water_normal.png', 'textures')
            print(f"Shaders loaded from: {self.shader_loader.shader_dir}")
        except Exception as e:
            print(f"FATAL: Shader Error: {e}")
            return
        
        self.vaos = {'cube': self._create_cube_vao(), 'sprite': self._create_sprite_vao(), 'grid': None}
        self.grid_indices_count = 0
        self._create_gizmo_buffers()
        self.update_grid_buffers(initial_world_size, initial_grid_size)
        self.noise_texture_id = self._load_3d_texture('assets/noise_3d.bin')
        self.sprite_textures = {}
        self.load_texture('default.png', 'textures')
        self.load_texture('caulk', 'textures')
        self._proj_ptr = None
        self._view_ptr = None

    def _preload_lit_uniforms(self, shader_name):
        uniforms = self.uniforms[shader_name]
        uniforms.preload(['projection', 'view', 'model', 'object_color', 'alpha', 'active_lights'])
        for i in range(self.MAX_LIGHTS):
            uniforms.preload([f'lights[{i}].position', f'lights[{i}].color', f'lights[{i}].intensity', f'lights[{i}].radius'])

    def update_grid_buffers(self, world_size, grid_size):
        if grid_size <= 0:
            if self.vaos['grid']: gl.glDeleteVertexArrays(1, [self.vaos['grid']]); self.vaos['grid'] = None
            return
        s, g = world_size, grid_size
        lines = [[-s, 0, i, s, 0, i, i, 0, -s, i, 0, s] for i in range(-s, s + 1, g)]
        grid_vertices = np.array(lines, dtype=np.float32).flatten()
        self.grid_indices_count = len(grid_vertices) // 3
        if self.vaos['grid']: gl.glDeleteVertexArrays(1, [self.vaos['grid']])
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, grid_vertices.nbytes, grid_vertices, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
        gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)
        self.vaos['grid'] = vao
    
    def set_sprite_textures(self, textures): self.sprite_textures = textures

    def load_texture(self, texture_name, subfolder):
        tex_cache_name = os.path.join(subfolder, texture_name)
        if tex_cache_name in self.texture_manager: return self.texture_manager[tex_cache_name]
        if texture_name == 'default.png':
            tex_id = gl.glGenTextures(1)
            self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 1, 1, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, (gl.GLubyte * 4)(255, 255, 255, 255))
            return tex_id
        if texture_name == 'caulk':
            tex_id = gl.glGenTextures(1)
            self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 2, 2, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, (gl.GLubyte * 16)(255, 0, 255, 255, 0, 0, 0, 255, 0, 0, 0, 255, 255, 0, 255, 255))
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            return tex_id
        texture_path = os.path.join('assets', subfolder, texture_name)
        if not os.path.exists(texture_path): return self.load_texture('default.png', 'textures')
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
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, img.width, img.height, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, img.tobytes())
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            return tex_id
        except Exception as e:
            print(f"Error loading texture '{texture_name}': {e}")
            return self.load_texture('default.png', 'textures')

    def preload_level_textures(self, brushes):
        texture_set = set()
        for brush in brushes:
            for face_tex in brush.get('textures', {}).values():
                if face_tex and face_tex != 'caulk.jpg': texture_set.add(face_tex)
        for tex_name in texture_set: self.load_texture(tex_name, 'textures')

    def _load_3d_texture(self, filepath, size=32):
        try:
            with open(filepath, 'rb') as f: data = f.read()
            if len(data) != size ** 3: return 0
            texture_id = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_3D, texture_id)
            for param in [(gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT), (gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT), 
                          (gl.GL_TEXTURE_WRAP_R, gl.GL_REPEAT), (gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR), 
                          (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)]:
                gl.glTexParameteri(gl.GL_TEXTURE_3D, *param)
            gl.glTexImage3D(gl.GL_TEXTURE_3D, 0, gl.GL_R8, size, size, size, 0, gl.GL_RED, gl.GL_UNSIGNED_BYTE, data)
            return texture_id
        except: return 0

    def _cull_brushes(self, projection, view, camera_pos, brushes):
        self.render_stats.reset()
        self.render_stats.total_brushes = len(brushes)
        if not self._enable_frustum_culling:
            self.render_stats.visible_brushes = len(brushes)
            return brushes
        self.frustum.extract_from_matrix(projection * view)
        visible = []
        for brush in brushes:
            pos, size = brush['pos'], brush['size']
            half = (size[0]*0.5, size[1]*0.5, size[2]*0.5)
            if not self.frustum.is_box_visible(pos, half):
                self.render_stats.culled_brushes += 1
                continue
            if self._enable_lod and self.lod_manager.get_lod_level(pos, camera_pos) == LODManager.LOD_CULLED:
                self.render_stats.culled_brushes += 1
                continue
            visible.append(brush)
            self.render_stats.visible_brushes += 1
        return visible

    def render_scene(self, projection, view, camera_pos, brushes, things, selected_object, config):
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        self._proj_ptr = glm.value_ptr(projection)
        self._view_ptr = glm.value_ptr(view)
        current_mode = config.get('render_mode', RENDER_MODE_LIT)

        if current_mode == RENDER_MODE_WIREFRAME: gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
        elif current_mode == RENDER_MODE_VERTEX: gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_POINT); gl.glPointSize(4.0)
        else: gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        self.draw_grid(projection, view, self.grid_indices_count, config.get('play_mode', False))
        
        opaque_brushes, transparent_brushes, sprites, fog_volumes, water_brushes = self._sort_objects(brushes, things, config)
        lights = [t for t in things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']

        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        if current_mode == RENDER_MODE_UNLIT: self.draw_textured_brushes(projection, view, camera_pos, opaque_brushes, lights, config)
        else: self.draw_lit_brushes(projection, view, camera_pos, opaque_brushes, lights, config)

        if current_mode == RENDER_MODE_LIT:
            shadow_lights = [l for l in lights if l.properties.get('casts_shadows')]
            if shadow_lights:
                all_brushes = config.get('all_brushes', brushes)
                self.render_projected_shadows_optimized(projection, view, camera_pos, all_brushes, shadow_lights)

        if transparent_brushes: transparent_brushes.sort(key=lambda b: -self._distance_sq(b['pos'], camera_pos))
        if water_brushes: water_brushes.sort(key=lambda b: -self._distance_sq(b['pos'], camera_pos))
        if sprites: sprites.sort(key=lambda s: -self._distance_sq(s.pos, camera_pos))
            
        gl.glEnable(gl.GL_BLEND)
        gl.glDepthMask(gl.GL_FALSE)
        
        self.draw_sprites(projection, view, sprites, self.sprite_textures)
        if current_mode == RENDER_MODE_UNLIT: self.draw_textured_brushes(projection, view, camera_pos, transparent_brushes, lights, config)
        else: self.draw_lit_brushes(projection, view, camera_pos, transparent_brushes, lights, config, is_transparent_pass=True)
            
        if current_mode == RENDER_MODE_LIT:
            self.draw_water_brushes(projection, view, camera_pos, water_brushes, lights, config)
            self.draw_fog_volumes(projection, view, camera_pos, fog_volumes, lights, config)

        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        if selected_object:
            if isinstance(selected_object, dict):
                self.draw_selected_brush_outline(projection, view, selected_object)
                if not selected_object.get('lock', False): self.render_gizmo(projection, view, selected_object['pos'])
            elif isinstance(selected_object, Thing): self.render_gizmo(projection, view, selected_object.pos)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(0)

    def _distance_sq(self, pos1, pos2):
        if isinstance(pos1, (list, tuple)): return (pos1[0]-pos2.x)**2 + (pos1[1]-pos2.y)**2 + (pos1[2]-pos2.z)**2
        return (pos1.x-pos2.x)**2 + (pos1.y-pos2.y)**2 + (pos1.z-pos2.z)**2

    def _set_light_uniforms_cached(self, shader_name, lights):
        if shader_name not in self.uniforms: return
        uniforms = self.uniforms[shader_name]
        num_lights = min(len(lights), self.MAX_LIGHTS)
        gl.glUniform1i(uniforms['active_lights'], num_lights)
        for i in range(num_lights):
            light = lights[i]
            gl.glUniform3fv(uniforms[f'lights[{i}].position'], 1, light.pos)
            gl.glUniform3fv(uniforms[f'lights[{i}].color'], 1, light.get_color())
            gl.glUniform1f(uniforms[f'lights[{i}].intensity'], light.get_intensity())
            gl.glUniform1f(uniforms[f'lights[{i}].radius'], light.get_radius())

    def render_projected_shadows_optimized(self, projection, view, camera_pos, brushes, shadow_lights):
        if not brushes or not shadow_lights or 'lit' not in self.shaders: return
        shader, uniforms = self.shaders['lit'], self.uniforms['lit']
        gl.glUseProgram(shader)
        gl.glUniform1i(uniforms['active_lights'], 0)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glBindVertexArray(self.vaos['cube'])
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        model_loc, color_loc, alpha_loc = uniforms['model'], uniforms['object_color'], uniforms['alpha']
        solid_brushes = [b for b in brushes if not b.get('is_trigger')]
        
        for light in shadow_lights:
            lx, ly, lz = light.pos[0], light.pos[1], light.pos[2]
            light_radius, light_radius_sq = light.get_radius(), light.get_radius()**2
            floor_y = None
            for b in solid_brushes:
                top_y = b['pos'][1] + b['size'][1] * 0.5
                if top_y < ly and (floor_y is None or top_y > floor_y): floor_y = top_y
            if floor_y is None: continue
            shadow_y, light_height = floor_y + 0.1, ly - floor_y
            if light_height <= 0: continue
            
            shadow_casters = []
            for brush in solid_brushes:
                bx, by, bz = brush['pos']
                sx, sy, sz = brush['size']
                brush_top = by + sy * 0.5
                if abs(brush_top - floor_y) < 0.1 or brush_top <= floor_y or sx > 500 or sz > 500: continue
                if (bx-lx)**2 + (by-ly)**2 + (bz-lz)**2 > light_radius_sq * 1.5: continue
                shadow_casters.append(brush)
            if not shadow_casters: continue
            
            self._floor_shadow_batch.reset()
            gl.glEnable(gl.GL_STENCIL_TEST); gl.glStencilMask(0xFF); gl.glClear(gl.GL_STENCIL_BUFFER_BIT)
            gl.glStencilFunc(gl.GL_ALWAYS, 1, 0xFF); gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_REPLACE)
            gl.glColorMask(gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE)
            gl.glDepthMask(gl.GL_FALSE); gl.glDisable(gl.GL_DEPTH_TEST)
            
            for brush in shadow_casters:
                bx, by, bz = brush['pos']
                sx, sy, sz = brush['size']
                brush_diag = ((sx*sx + sz*sz) ** 0.5) * 0.5
                footprint_size = brush_diag * 2.5 + 2.0
                footprint_mat = glm.translate(self._identity_mat4, glm.vec3(bx, shadow_y, bz))
                footprint_mat = glm.scale(footprint_mat, glm.vec3(footprint_size, 0.01, footprint_size))
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(footprint_mat))
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            
            gl.glColorMask(gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE)
            gl.glStencilFunc(gl.GL_EQUAL, 0, 0xFF); gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP); gl.glStencilMask(0x00)
            gl.glEnable(gl.GL_BLEND); gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glEnable(gl.GL_DEPTH_TEST); gl.glDepthFunc(gl.GL_LEQUAL); gl.glEnable(gl.GL_POLYGON_OFFSET_FILL); gl.glPolygonOffset(-1.0, -1.0)
            gl.glUniform3f(color_loc, 0.0, 0.0, 0.0)
            
            for brush in shadow_casters:
                bx, by, bz = brush['pos']
                sx, sy, sz = brush['size']
                ratio = (by + sy * 0.5 - floor_y) / light_height
                dir_x, dir_z = bx - lx, bz - lz
                dir_len = (dir_x**2 + dir_z**2)**0.5
                if dir_len > 0.001: dir_x /= dir_len; dir_z /= dir_len
                else: dir_x, dir_z = 1, 0
                total_len = ((bx + dir_x * dir_len * ratio - bx)**2 + (bz + dir_z * dir_len * ratio - bz)**2) ** 0.5
                if total_len < 0.1: continue
                total_len = min(total_len, light_radius * 0.75)
                brush_diagonal = ((sx*sx + sz*sz) ** 0.5) * 0.5
                shadow_len = total_len + brush_diagonal * 3
                shadow_cx, shadow_cz = bx + dir_x * (shadow_len * 0.5 - brush_diagonal), bz + dir_z * (shadow_len * 0.5 - brush_diagonal)
                dist = ((bx-lx)**2 + (by-ly)**2 + (bz-lz)**2)**0.5
                shadow_alpha = max(0.4, min(0.7, 0.6 * (1.0 - (dist / light_radius) * 0.3)))
                self._floor_shadow_batch.add((shadow_cx, shadow_y, shadow_cz), (brush_diagonal * 2.5, 0.01, shadow_len), glm.atan(dir_x, dir_z), shadow_alpha)
            
            for i in range(self._floor_shadow_batch.count):
                pos, scale, rot, alpha = self._floor_shadow_batch.positions[i], self._floor_shadow_batch.scales[i], self._floor_shadow_batch.rotations[i], self._floor_shadow_batch.alphas[i]
                final_mat = glm.translate(self._identity_mat4, glm.vec3(*pos))
                final_mat = glm.rotate(final_mat, rot, glm.vec3(0, 1, 0))
                final_mat = glm.scale(final_mat, glm.vec3(*scale))
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(final_mat))
                gl.glUniform1f(alpha_loc, alpha)
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
                self.render_stats.shadow_draw_calls += 1
            
            gl.glDisable(gl.GL_POLYGON_OFFSET_FILL); gl.glDisable(gl.GL_STENCIL_TEST)
            self._render_wall_shadows_optimized(solid_brushes, shadow_casters, lx, ly, lz, light_radius, light_radius_sq, floor_y, model_loc, color_loc, alpha_loc)
        
        gl.glDepthFunc(gl.GL_LESS); gl.glDepthMask(gl.GL_TRUE); gl.glDisable(gl.GL_BLEND); gl.glBindVertexArray(0)

    def _render_wall_shadows_optimized(self, solid_brushes, shadow_casters, lx, ly, lz, light_radius, light_radius_sq, floor_y, model_loc, color_loc, alpha_loc):
        walls = []
        for brush in solid_brushes:
            bx, by, bz, sx, sy, sz = *brush['pos'], *brush['size']
            if by + sy * 0.5 <= floor_y + 1 or (bx-lx)**2 + (by-ly)**2 + (bz-lz)**2 > light_radius_sq * 4: continue
            fxp, fxn, fzp, fzn = bx+sx*0.5, bx-sx*0.5, bz+sz*0.5, bz-sz*0.5
            vr = (max(by-sy*0.5, floor_y), by+sy*0.5)
            if lx > fxp: walls.append((brush, '+x', fxp, (bz-sz*0.5, bz+sz*0.5), vr))
            if lx < fxn: walls.append((brush, '-x', fxn, (bz-sz*0.5, bz+sz*0.5), vr))
            if lz > fzp: walls.append((brush, '+z', fzp, (bx-sx*0.5, bx+sx*0.5), vr))
            if lz < fzn: walls.append((brush, '-z', fzn, (bx-sx*0.5, bx+sx*0.5), vr))
        if not walls: return
        
        gl.glEnable(gl.GL_BLEND); gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(gl.GL_DEPTH_TEST); gl.glDepthFunc(gl.GL_LEQUAL); gl.glDepthMask(gl.GL_FALSE)
        gl.glEnable(gl.GL_POLYGON_OFFSET_FILL); gl.glPolygonOffset(-1.0, -1.0)
        gl.glUniform3f(color_loc, 0.0, 0.0, 0.0)
        
        for wall_brush, face_dir, face_coord, (lmin, lmax), (vmin, vmax) in walls:
            for caster in shadow_casters:
                if caster is wall_brush: continue
                cx, cy, cz, csx, csy, csz = *caster['pos'], *caster['size']
                ctop, cbot = cy + csy * 0.5, cy - csy * 0.5
                if face_dir in ('+x', '-x'):
                    if abs(cx - lx) < 0.001: continue
                    t = (face_coord - lx) / (cx - lx)
                    if t <= 1.0: continue
                    sz, syt, syb = lz + (cz - lz) * t, ly + (ctop - ly) * t, ly + (cbot - ly) * t
                    sw = csz * (1.0 + (t - 1.0) * 0.2)
                    if sz + sw * 0.5 < lmin or sz - sw * 0.5 > lmax: continue
                    spos, svec = glm.vec3(face_coord + (0.1 if face_dir == '+x' else -0.1), 0, sz), glm.vec3(0.01, 1, sw)
                else:
                    if abs(cz - lz) < 0.001: continue
                    t = (face_coord - lz) / (cz - lz)
                    if t <= 1.0: continue
                    sx, syt, syb = lx + (cx - lx) * t, ly + (ctop - ly) * t, ly + (cbot - ly) * t
                    sw = csx * (1.0 + (t - 1.0) * 0.2)
                    if sx + sw * 0.5 < lmin or sx - sw * 0.5 > lmax: continue
                    spos, svec = glm.vec3(sx, 0, face_coord + (0.1 if face_dir == '+z' else -0.1)), glm.vec3(sw, 1, 0.01)
                
                syt, syb = min(syt, vmax), max(syb, vmin)
                if syt <= syb or (cx-lx)**2 + (cy-ly)**2 + (cz-lz)**2 > light_radius_sq: continue
                spos.y, svec.y = (syt + syb) * 0.5, syt - syb
                alpha = max(0.4, min(0.7, 0.6 * (1.0 - (((cx-lx)**2 + (cy-ly)**2 + (cz-lz)**2)**0.5 / light_radius) * 0.3)))
                final_mat = glm.scale(glm.translate(self._identity_mat4, spos), svec)
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(final_mat))
                gl.glUniform1f(alpha_loc, alpha)
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
                self.render_stats.shadow_draw_calls += 1
        gl.glDisable(gl.GL_POLYGON_OFFSET_FILL)

    def draw_fog_volumes(self, projection, view, camera_pos, brushes, lights, config):
        if not brushes: return
        if 'fog' not in self.shaders: return
        visible_brushes = self._cull_brushes(projection, view, camera_pos, brushes)
        if not visible_brushes: return
        gl.glEnable(gl.GL_BLEND); gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        shader, uniforms = self.shaders['fog'], self.uniforms['fog']
        gl.glUseProgram(shader)
        self._set_light_uniforms_cached('fog', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniform3fv(uniforms['viewPos'], 1, glm.value_ptr(camera_pos))
        gl.glUniform1f(uniforms['time'], config.get('time', 0.0))
        gl.glActiveTexture(gl.GL_TEXTURE1); gl.glBindTexture(gl.GL_TEXTURE_3D, self.noise_texture_id); gl.glUniform1i(uniforms['noiseTexture'], 1)
        gl.glBindVertexArray(self.vaos['cube']); gl.glEnable(gl.GL_CULL_FACE)
        model_loc, density_loc, fog_color_loc, noise_scale_loc, object_color_loc, alpha_loc = uniforms['model'], uniforms['density'], uniforms['fogColor'], uniforms['noiseScale'], uniforms['object_color'], uniforms['alpha']
        
        for brush in visible_brushes:
            model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*brush['pos'])), glm.vec3(*brush['size']))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            f_color = brush.get('fog_color', [0.5, 0.6, 0.7])
            gl.glUniform1f(density_loc, brush.get('fog_density', 0.01))
            gl.glUniform3fv(fog_color_loc, 1, f_color)
            gl.glUniform1f(noise_scale_loc, brush.get('fog_noise_scale', 0.01))
            gl.glUniform3fv(object_color_loc, 1, f_color)
            gl.glUniform1f(alpha_loc, 0.4)
            
            # Draw Front/Back face culling passes
            # IMPORTANT: Skipping Bottom Face (Indices 24-30)
            
            # Pass 1: Cull Front (Draw Inside Back faces)
            gl.glCullFace(gl.GL_FRONT)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 24)  # Sides
            gl.glDrawArrays(gl.GL_TRIANGLES, 30, 6)  # Top Only
            
            # Pass 2: Cull Back (Draw Outside Front faces)
            gl.glCullFace(gl.GL_BACK)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 24)  # Sides
            gl.glDrawArrays(gl.GL_TRIANGLES, 30, 6)  # Top Only

        gl.glDisable(gl.GL_CULL_FACE); gl.glBindVertexArray(0); gl.glActiveTexture(gl.GL_TEXTURE0)

    def _sort_objects(self, brushes, things, config):
        opaque, transparent, sprites, fog, water = [], [], [], [], []
        is_play, show_sprites = config.get('play_mode', False), config.get('show_sprites_in_play_mode', False)
        for brush in brushes:
            if brush.get('hidden'): continue
            if brush.get('is_water', False) or brush.get('shader') == 'Water' or any('water' in (t or '').lower() for t in brush.get('textures', {}).values()): water.append(brush)
            elif brush.get('is_fog') or brush.get('shader') == 'Fog': fog.append(brush)
            elif brush.get('is_trigger'): 
                if not is_play: transparent.append(brush)
            else: opaque.append(brush)
        if not is_play or show_sprites: sprites = [t for t in things if isinstance(t, Thing)]
        return opaque, transparent, sprites, fog, water

    def draw_water_brushes(self, projection, view, camera_pos, brushes, lights, config):
        if not brushes: return
        visible = self._cull_brushes(projection, view, camera_pos, brushes)
        if not visible: return
        shader, uniforms = self.shaders['water'], self.uniforms['water']
        gl.glUseProgram(shader)
        self._set_light_uniforms_cached('water', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniform3fv(uniforms['viewPos'], 1, glm.value_ptr(camera_pos))
        gl.glUniform1f(uniforms['time'], config.get('time', 0.0))
        gl.glActiveTexture(gl.GL_TEXTURE0); gl.glBindTexture(gl.GL_TEXTURE_2D, self.water_normal_id); gl.glUniform1i(uniforms['normalMap'], 0)
        
        opacity_loc = uniforms['waterOpacity']
        reflectivity_loc = uniforms['waterReflectivity']
        tint_loc, model_loc = uniforms['waterTint'], uniforms['model']
        
        gl.glBindVertexArray(self.vaos['cube'])
        gl.glEnable(gl.GL_BLEND); gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        
        for brush in visible:
            model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*brush['pos'])), glm.vec3(*brush['size']))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            
            gl.glUniform1f(opacity_loc, brush.get('water_opacity', 0.5))
            gl.glUniform1f(reflectivity_loc, brush.get('water_reflectivity', 0.5))
            gl.glUniform3fv(tint_loc, 1, brush.get('water_tint', [0.0, 0.4, 0.6]))
            
            if brush.get('water_plane', False):
                # Draw ONLY the top face (indices 30-36)
                gl.glDrawArrays(gl.GL_TRIANGLES, 30, 6)
            else:
                # Draw everything EXCEPT the bottom face (indices 24-30)
                # Draw sides (0-24)
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 24)
                # Draw top (30-36)
                gl.glDrawArrays(gl.GL_TRIANGLES, 30, 6)
                
            self.render_stats.draw_calls += 1
        gl.glBindVertexArray(0)

    def draw_grid(self, projection, view, grid_indices_count, play_mode=False):
        if not self.vaos['grid'] or play_mode or 'simple' not in self.shaders: return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(self._identity_mat4))
        gl.glUniform3f(uniforms['color'], 0.2, 0.2, 0.2)
        gl.glBindVertexArray(self.vaos['grid']); gl.glDrawArrays(gl.GL_LINES, 0, grid_indices_count); gl.glBindVertexArray(0)

    def draw_lit_brushes(self, projection, view, camera_pos, brushes, lights, config, is_transparent_pass=False):
        if not brushes or 'lit' not in self.shaders: return
        visible = self._cull_brushes(projection, view, camera_pos, brushes)
        if not visible: return
        shader, uniforms = self.shaders['lit'], self.uniforms['lit']
        gl.glUseProgram(shader)
        self._set_light_uniforms_cached('lit', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glBindVertexArray(self.vaos['cube'])
        display_mode, show_triggers_solid, selected = config.get('brush_display_mode', 'Textured'), config.get('show_triggers_as_solid', False), config.get('selected_object')
        model_loc, color_loc, alpha_loc = uniforms['model'], uniforms['object_color'], uniforms['alpha']
        fill_mode = (gl.GL_FILL if show_triggers_solid else gl.GL_LINE) if is_transparent_pass else (gl.GL_FILL if display_mode != "Wireframe" else gl.GL_LINE)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, fill_mode)
        for brush in visible:
            model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*brush['pos'])), glm.vec3(*brush['size']))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            if brush.get('is_trigger'): color, alpha = [0.0, 1.0, 1.0], 0.3
            elif brush is selected: color, alpha = [1.0, 1.0, 0.0], 1.0
            elif brush.get('operation') == 'subtract': color, alpha = [1.0, 0.0, 0.0], 1.0
            else:
                brush_colour = brush.get('colour')
                if brush_colour and isinstance(brush_colour, (list, tuple)) and len(brush_colour) >= 3:
                    color = [c / 255.0 if c > 1.0 else c for c in brush_colour[:3]]
                else: color = [0.8, 0.8, 0.8]
                alpha = 1.0
            gl.glUniform3fv(color_loc, 1, color); gl.glUniform1f(alpha_loc, alpha)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            self.render_stats.draw_calls += 1
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL); gl.glBindVertexArray(0)

    def draw_textured_brushes(self, projection, view, camera_pos, brushes, lights, config):
        if not brushes or 'textured' not in self.shaders: return
        visible = self._cull_brushes(projection, view, camera_pos, brushes)
        if not visible: return
        shader, uniforms = self.shaders['textured'], self.uniforms['textured']
        gl.glUseProgram(shader); gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        self._set_light_uniforms_cached('textured', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glActiveTexture(gl.GL_TEXTURE0); gl.glUniform1i(uniforms['texture_diffuse'], 0)
        gl.glBindVertexArray(self.vaos['cube'])
        model_loc = uniforms['model']
        batches = defaultdict(list)
        for brush in visible:
            for i, key in enumerate(['south', 'north', 'west', 'east', 'bottom', 'top']):
                tex_name = brush.get('textures', {}).get(key, 'default.png')
                if tex_name == 'caulk.jpg': continue
                tex_id = self.texture_manager.get(os.path.join('textures', tex_name)) or self.load_texture_callback(tex_name, 'textures')
                batches[tex_id].append((brush, i))
        current_tex = None
        for tex_id, items in batches.items():
            if tex_id != current_tex: gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id); current_tex = tex_id
            for brush, face_idx in items:
                model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*brush['pos'])), glm.vec3(*brush['size']))
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
                gl.glDrawArrays(gl.GL_TRIANGLES, face_idx * 6, 6)
                self.render_stats.draw_calls += 1
        gl.glBindVertexArray(0)

    def draw_selected_brush_outline(self, projection, view, brush):
        if 'simple' not in self.shaders: return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        model_matrix = glm.scale(glm.translate(self._identity_mat4, glm.vec3(*brush['pos'])), glm.vec3(*brush['size']))
        gl.glUniformMatrix4fv(uniforms['model'], 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
        gl.glUniform3f(uniforms['color'], 1.0, 1.0, 0.0)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE); gl.glBindVertexArray(self.vaos['cube']); gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL); gl.glBindVertexArray(0)

    def draw_sprites(self, projection, view, things_to_draw, sprite_textures):
        if not things_to_draw or 'sprite' not in self.shaders: return
        shader, uniforms = self.shaders['sprite'], self.uniforms['sprite']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        gl.glActiveTexture(gl.GL_TEXTURE0); gl.glUniform1i(uniforms['sprite_texture'], 0)
        pos_loc, size_loc = uniforms['sprite_pos_world'], uniforms['sprite_size']
        gl.glBindVertexArray(self.vaos['sprite'])
        current_tex = None
        for thing in things_to_draw:
            tex_id = sprite_textures.get(thing.__class__.__name__)
            if tex_id:
                if tex_id != current_tex: gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id); current_tex = tex_id
                gl.glUniform3fv(pos_loc, 1, thing.pos)
                gl.glUniform2f(size_loc, 16.0 if isinstance(thing, Light) else 32.0, 16.0 if isinstance(thing, Light) else 32.0)
                gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)

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
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 32, ctypes.c_void_p(0)); gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(1, 3, gl.GL_FLOAT, gl.GL_FALSE, 32, ctypes.c_void_p(12)); gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(2, 2, gl.GL_FLOAT, gl.GL_FALSE, 32, ctypes.c_void_p(24)); gl.glEnableVertexAttribArray(2)
        gl.glBindVertexArray(0)
        return vao

    def _create_sprite_vao(self):
        vertices = np.array([-0.5, -0.5, 0.5, -0.5, -0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, 0, None); gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)
        return vao

    def _create_gizmo_buffers(self):
        axis_verts = np.array([0,0,0, 1,0,0, 0,0,0, 0,1,0, 0,0,0, 0,0,1], dtype=np.float32)
        self.vao_gizmo_lines = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, axis_verts.nbytes, axis_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0)); gl.glEnableVertexAttribArray(0)
        cone_verts = []
        for i in range(12):
            t1, t2 = (i/12)*2*np.pi, ((i+1)/12)*2*np.pi
            cone_verts.extend([0,0,0, np.cos(t2)*0.05,0,np.sin(t2)*0.05, np.cos(t1)*0.05,0,np.sin(t1)*0.05])
            cone_verts.extend([0,0.2,0, np.cos(t1)*0.05,0,np.sin(t1)*0.05, np.cos(t2)*0.05,0,np.sin(t2)*0.05])
        self.gizmo_cone_v_count = len(cone_verts)//3
        cone_verts = np.array(cone_verts, dtype=np.float32)
        self.vao_gizmo_cone = gl.glGenVertexArrays(1)
        vbo2 = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao_gizmo_cone)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo2)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, cone_verts.nbytes, cone_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None); gl.glEnableVertexAttribArray(0)
        gl.glBindVertexArray(0)

    def render_gizmo(self, projection, view, position):
        if 'simple' not in self.shaders: return
        shader, uniforms = self.shaders['simple'], self.uniforms['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, self._proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, self._view_ptr)
        pos_vec = glm.vec3(*position) if isinstance(position, (list, tuple)) else position
        base = glm.scale(glm.translate(self._identity_mat4, pos_vec), glm.vec3(32.0))
        model_loc, color_loc = uniforms['model'], uniforms['color']
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(base))
        for i, c in enumerate([(1,0,0), (0,1,0), (0,0,1)]):
            gl.glUniform3f(color_loc, *c); gl.glDrawArrays(gl.GL_LINES, i*2, 2)
        gl.glBindVertexArray(self.vao_gizmo_cone)
        for axis, c, rot in [((1,0,0), (1,0,0), glm.rotate(base, glm.radians(-90), glm.vec3(0,0,1))), ((0,1,0), (0,1,0), base), ((0,0,1), (0,0,1), glm.rotate(base, glm.radians(90), glm.vec3(1,0,0)))]:
            m = glm.translate(rot if axis[1] else glm.translate(base, glm.vec3(*axis)), glm.vec3(0,1,0) if axis[1] else glm.vec3(0,0,0))
            if axis[0]: m = glm.translate(glm.rotate(base, glm.radians(-90), glm.vec3(0,0,1)), glm.vec3(0,1,0))
            if axis[2]: m = glm.translate(glm.rotate(base, glm.radians(90), glm.vec3(1,0,0)), glm.vec3(0,1,0))
            if axis[1]: m = glm.translate(base, glm.vec3(0,1,0))
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(m))
            gl.glUniform3f(color_loc, *c); gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)
        gl.glBindVertexArray(0)