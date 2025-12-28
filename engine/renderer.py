import glm
import numpy as np
import OpenGL.GL as gl
import ctypes
from editor.things import Thing, Light, Model
from engine import shaders
from OpenGL.GL.shaders import compileProgram, compileShader
from engine.constants import RENDER_MODE_LIT, RENDER_MODE_UNLIT, RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX
from .obj_loader import OBJ
from PIL import Image
import os
import time


class Renderer:
    """Handles all modern OpenGL drawing operations for the editor."""

    def __init__(self, texture_loader, initial_grid_size, initial_world_size):
        self.texture_manager = {}
        self.model_cache = {} 
        self.load_texture_callback = texture_loader
        self.render_time = 0.0  # For animated materials

        # Initialize containers immediately so they exist even if compilation fails
        self.shaders = {}
        self.vaos = {
            'cube': None,
            'line_cube': None,
            'sprite': None,
            'grid': None,
        }
        self.grid_indices_count = 0

        # 1. Compile Shaders
        try:
            shader_simple = compileProgram(compileShader(shaders.VERTEX_SHADER_SIMPLE, gl.GL_VERTEX_SHADER), compileShader(shaders.FRAGMENT_SHADER_SIMPLE, gl.GL_FRAGMENT_SHADER))
            shader_lit = compileProgram(compileShader(shaders.VERTEX_SHADER_LIT, gl.GL_VERTEX_SHADER), compileShader(shaders.FRAGMENT_SHADER_LIT, gl.GL_FRAGMENT_SHADER))
            shader_textured = compileProgram(compileShader(shaders.VERTEX_SHADER_TEXTURED, gl.GL_VERTEX_SHADER), compileShader(shaders.FRAGMENT_SHADER_TEXTURED, gl.GL_FRAGMENT_SHADER))
            shader_sprite = compileProgram(compileShader(shaders.VERTEX_SHADER_SPRITE, gl.GL_VERTEX_SHADER), compileShader(shaders.FRAGMENT_SHADER_SPRITE, gl.GL_FRAGMENT_SHADER))
            shader_shadow_volume = compileProgram(compileShader(shaders.SHADOW_VOLUME_VERTEX_SHADER, gl.GL_VERTEX_SHADER), compileShader(shaders.SHADOW_VOLUME_FRAGMENT_SHADER, gl.GL_FRAGMENT_SHADER))
            shader_fog = compileProgram(compileShader(shaders.VERTEX_SHADER_FOG, gl.GL_VERTEX_SHADER), compileShader(shaders.FRAGMENT_SHADER_FOG, gl.GL_FRAGMENT_SHADER))
            
            # Load procedural shader from the shaders/ folder alongside this script
            procedural_vert_src = self._load_shader_from_file('procedural_vert.glsl')
            procedural_frag_src = self._load_shader_from_file('procedural_frag.glsl')
            shader_procedural = compileProgram(compileShader(procedural_vert_src, gl.GL_VERTEX_SHADER), compileShader(procedural_frag_src, gl.GL_FRAGMENT_SHADER))
            
            self.shaders = {
                'simple': shader_simple,
                'lit': shader_lit,
                'textured': shader_textured,
                'sprite': shader_sprite,
                'shadow_volume': shader_shadow_volume,
                'fog': shader_fog,
                'procedural': shader_procedural,
            }
        except Exception as e:
            print(f"FATAL: Shader Compilation Error: {e}")
            return  # Safe to return now because self.vaos is initialized
        
        # 2. Create Vertex Buffers (VAOs)
        self._create_gizmo_buffers()
        
        # Populate VAOs
        self.vaos['cube'] = self._create_cube_vao()
        self.vaos['line_cube'] = self._create_line_cube_vao()
        self.vaos['sprite'] = self._create_sprite_vao()
        
        self.update_grid_buffers(initial_world_size, initial_grid_size)

        # 3. Load Essential Textures
        self.noise_texture_id = self._load_3d_texture('assets/noise_3d.bin')
        self.sprite_textures = {}
        self.load_texture('default.png', 'textures')
        self.load_texture('caulk', 'textures')

    def _load_shader_from_file(self, filename):
        """Loads shader source code from the shaders/ folder"""
        # Get directory containing renderer.py
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Construct path to shaders/filename
        path = os.path.join(current_dir, 'shaders', filename)
        
        if not os.path.exists(path):
            raise FileNotFoundError(f"ERROR! Shader file not found: {path}")
        with open(path, 'r') as f:
            return f.read()

    def get_model(self, path):
        """Loads or retrieves a cached OBJ model."""
        if path not in self.model_cache:
            self.model_cache[path] = OBJ(path)
        return self.model_cache[path]

    def update_grid_buffers(self, world_size, grid_size):
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
        tex_cache_name = os.path.join(subfolder, texture_name)
        if tex_cache_name in self.texture_manager: return self.texture_manager[tex_cache_name]
        if texture_name == 'default.png':
            tex_id = gl.glGenTextures(1); self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id); pixels = [255, 255, 255, 255]
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 1, 1, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, (gl.GLubyte * 4)(*pixels))
            return tex_id
        if texture_name == 'caulk':
            tex_id = gl.glGenTextures(1); self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id); pixels = [255,0,255,255, 0,0,0,255, 0,0,0,255, 255,0,255,255]
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 2, 2, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, (gl.GLubyte * 16)(*pixels))
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            return tex_id
        texture_path = os.path.join('assets', subfolder, texture_name)
        if not os.path.exists(texture_path): return self.load_texture('default.png', 'textures')
        try:
            img = Image.open(texture_path).convert("RGBA"); img_data = img.tobytes()
            tex_id = gl.glGenTextures(1); self.texture_manager[tex_cache_name] = tex_id
            gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT); gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR); gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, img.width, img.height, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, img_data)
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
            return tex_id
        except Exception as e: print(f"Error loading texture '{texture_name}': {e}"); return self.load_texture('default.png', 'textures')

    def _load_3d_texture(self, filepath, size=32):
        try:
            with open(filepath, 'rb') as f:
                data = f.read()
            if len(data) != size * size * size:
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
        except: return 0
    
    def render_scene(self, projection, view, camera_pos, brushes, things, selected_object, config):
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        gl.glEnable(gl.GL_PROGRAM_POINT_SIZE)
        
        # Update render time for animated materials
        self.render_time = config.get('time', time.time() % 1000.0)

        current_mode = config.get('render_mode', RENDER_MODE_LIT)

        if current_mode == RENDER_MODE_WIREFRAME:
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
        elif current_mode == RENDER_MODE_VERTEX:
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_POINT)
            gl.glPointSize(4.0)
        else:
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        self.draw_grid(projection, view, self.grid_indices_count)

        opaque_brushes, transparent_brushes, sprites, fog_volumes, models = self._sort_objects(brushes, things, config)
        lights = [t for t in things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']
        
        # Add glow brushes as light emitters
        glow_lights = self._get_glow_brush_lights(brushes)

        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        
        if current_mode == RENDER_MODE_UNLIT:
            self.draw_textured_brushes(projection, view, opaque_brushes, lights + glow_lights, config)
        else:
            # Use procedural shader for brushes with material properties
            self.draw_procedural_brushes(projection, view, camera_pos, opaque_brushes, lights + glow_lights, config)

        # Draw Models (Opaque)
        self.draw_models(projection, view, models, lights + glow_lights, config)

        if current_mode == RENDER_MODE_LIT:
            shadow_lights = [l for l in lights if l.properties.get('casts_shadows')]
            if shadow_lights:
                self.render_shadows(projection, view, opaque_brushes, shadow_lights)

        transparent_brushes.sort(key=lambda b: -glm.distance(glm.vec3(b['pos']), camera_pos))
        sprites.sort(key=lambda s: -glm.distance(glm.vec3(s.pos), camera_pos))
        
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDepthMask(gl.GL_FALSE)

        self.draw_sprites(projection, view, sprites, self.sprite_textures)
        
        if current_mode == RENDER_MODE_UNLIT:
            self.draw_textured_brushes(projection, view, transparent_brushes, lights + glow_lights, config)
        else:
            self.draw_procedural_brushes(projection, view, camera_pos, transparent_brushes, lights + glow_lights, config, is_transparent_pass=True)

        if current_mode == RENDER_MODE_LIT:
            self.draw_fog_volumes(projection, view, fog_volumes, lights + glow_lights, camera_pos, config)

        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)

        # Draw glow light direction arrows in 3D view
        self.render_glow_arrows(projection, view, brushes, config)

        if selected_object:
             if isinstance(selected_object, dict):
                 selection_transparency = config.get('selection_transparency', 0.5)
                 self.draw_selected_brush_outline(projection, view, selected_object, selection_transparency)
                 if not selected_object.get('lock', False):
                     self.render_gizmo(projection, view, selected_object['pos'])
             elif isinstance(selected_object, Thing):
                 self.render_gizmo(projection, view, selected_object.pos)

        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(0)

    def draw_procedural_brushes(self, projection, view, camera_pos, brushes, lights, config, is_transparent_pass=False):
        """Draw brushes - uses original lit shader for Default, procedural shader for others."""
        if not brushes:
            return
        
        # Separate brushes by shader type
        default_brushes = []
        procedural_brushes = []
        
        for brush in brushes:
            shader_type = brush.get('shader', 'Default')
            if shader_type == 'Default':
                default_brushes.append(brush)
            else:
                procedural_brushes.append(brush)
        
        # Draw default brushes with original lit shader
        if default_brushes:
            self.draw_lit_brushes(projection, view, default_brushes, lights, config, is_transparent_pass)
        
        # Draw procedural brushes with procedural shader
        if not procedural_brushes:
            return
        
        # Safety check: fallback to lit shader if procedural shader failed to load
        if 'procedural' not in self.shaders:
            print("WARNING: Procedural shader not available, falling back to lit shader")
            self.draw_lit_brushes(projection, view, procedural_brushes, lights, config, is_transparent_pass)
            return
            
        shader = self.shaders['procedural']
        gl.glUseProgram(shader)
        
        # Set up matrices
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniform3fv(gl.glGetUniformLocation(shader, "viewPos"), 1, glm.value_ptr(camera_pos))
        gl.glUniform1f(gl.glGetUniformLocation(shader, "time"), self.render_time)
        
        # Set up lights
        self._set_procedural_light_uniforms(shader, lights)
        
        gl.glBindVertexArray(self.vaos['cube'])
        
        display_mode = config.get('brush_display_mode', 'Textured')
        show_triggers_solid = config.get('show_triggers_as_solid', False)
        
        # Shader type mapping
        shader_type_map = {
            'Default': 0, 'Metal': 1, 'Glass': 2, 'Concrete': 3,
            'Wood': 5, 'Marble': 6,
            'Glow': 8, 'Water': 9
        }
        
        # Preset values for each shader type
        shader_presets = {
            'Default': {'roughness': 0.5, 'metallic': 0.0, 'transparency': 0.0, 'emission': 0.0, 'color': [0.8, 0.8, 0.8]},
            'Metal': {'roughness': 0.3, 'metallic': 1.0, 'transparency': 0.0, 'emission': 0.0, 'color': [0.9, 0.9, 0.95]},
            'Glass': {'roughness': 0.05, 'metallic': 0.0, 'transparency': 0.8, 'emission': 0.0, 'color': [0.9, 0.95, 1.0]},
            'Concrete': {'roughness': 0.9, 'metallic': 0.0, 'transparency': 0.0, 'emission': 0.0, 'color': [0.6, 0.6, 0.6]},
            'Wood': {'roughness': 0.7, 'metallic': 0.0, 'transparency': 0.0, 'emission': 0.0, 'color': [0.6, 0.4, 0.2]},
            'Marble': {'roughness': 0.2, 'metallic': 0.0, 'transparency': 0.0, 'emission': 0.0, 'color': [0.95, 0.95, 0.9]},
            'Glow': {'roughness': 0.5, 'metallic': 0.0, 'transparency': 0.0, 'emission': 1.5, 'color': [1.0, 0.9, 0.5]},
            'Water': {'roughness': 0.05, 'metallic': 0.0, 'transparency': 0.7, 'emission': 0.0, 'color': [0.2, 0.5, 0.8]},
        }

        for brush in procedural_brushes:
            if is_transparent_pass:
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL if show_triggers_solid else gl.GL_LINE)
            else:
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL if display_mode != "Wireframe" else gl.GL_LINE)

            model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

            # Get shader type and preset values
            shader_name = brush.get('shader', 'Default')
            preset = shader_presets.get(shader_name, shader_presets['Default'])
            mat_type = shader_type_map.get(shader_name, 0)
            
            # Check if selected
            is_selected = (brush is config.get('selected_object'))
            
            # Get brush colour tint and apply to preset colour
            brush_tint = brush.get('colour', [0.8, 0.8, 0.8])
            preset_color = preset['color']
            # Multiply tint with preset colour (normalize tint from 0.8 default to 1.0)
            tint_factor = [c / 0.8 for c in brush_tint]  # Convert from 0.8-based to multiplier
            mat_color = [preset_color[i] * tint_factor[i] for i in range(3)]
            # Clamp to 0-1 range
            mat_color = [min(1.0, max(0.0, c)) for c in mat_color]
            
            roughness = preset['roughness']
            metallic = preset['metallic']
            transparency = preset['transparency']
            emission = preset['emission']
            
            # Highlight selected brushes
            if is_selected:
                emission = max(emission, 0.3)

            gl.glUniform3fv(gl.glGetUniformLocation(shader, "material_color"), 1, mat_color)
            gl.glUniform1f(gl.glGetUniformLocation(shader, "roughness"), roughness)
            gl.glUniform1f(gl.glGetUniformLocation(shader, "metallic"), metallic)
            gl.glUniform1f(gl.glGetUniformLocation(shader, "transparency"), transparency)
            gl.glUniform1f(gl.glGetUniformLocation(shader, "emission"), emission)
            gl.glUniform1i(gl.glGetUniformLocation(shader, "material_type"), mat_type)
            
            # Disable pulse effect for glow materials (set disable_pulse = 1 for glow, 0 otherwise)
            disable_pulse = 1 if shader_name == 'Glow' else 0
            gl.glUniform1i(gl.glGetUniformLocation(shader, "disable_pulse"), disable_pulse)
            
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)

        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glBindVertexArray(0)

    def _set_procedural_light_uniforms(self, shader, lights):
        """Set light uniforms for procedural shader - matches existing lit shader."""
        num_lights = min(len(lights), 16)
        gl.glUniform1i(gl.glGetUniformLocation(shader, "active_lights"), num_lights)
        for i, light in enumerate(lights[:16]):
            # Handle both Thing lights and GlowBrushLight pseudo-lights
            if hasattr(light, 'pos'):
                pos = light.pos
            else:
                pos = light.get('pos', [0, 0, 0])
            
            if hasattr(light, 'get_color'):
                color = light.get_color()
            else:
                color = light.get('color', [1.0, 1.0, 1.0])
            
            if hasattr(light, 'get_intensity'):
                intensity = light.get_intensity()
            else:
                intensity = light.get('intensity', 1.0)
            
            if hasattr(light, 'get_radius'):
                radius = light.get_radius()
            else:
                radius = light.get('radius', 256.0)
            
            gl.glUniform3fv(gl.glGetUniformLocation(shader, f"lights[{i}].position"), 1, pos)
            gl.glUniform3fv(gl.glGetUniformLocation(shader, f"lights[{i}].color"), 1, color)
            gl.glUniform1f(gl.glGetUniformLocation(shader, f"lights[{i}].intensity"), intensity)
            gl.glUniform1f(gl.glGetUniformLocation(shader, f"lights[{i}].radius"), radius)

    def _get_glow_brush_lights(self, brushes):
        """Create pseudo-light sources from glow shader brushes."""
        glow_lights = []
        
        # Map face name to direction vector
        face_directions = {
            'top':    [0, 1, 0],
            'bottom': [0, -1, 0],
            'north':  [0, 0, 1],
            'south':  [0, 0, -1],
            'east':   [1, 0, 0],
            'west':   [-1, 0, 0],
        }
        
        for brush in brushes:
            if brush.get('hidden', False):
                continue
            if brush.get('shader') != 'Glow':
                continue
            
            brush_pos = brush.get('pos', [0, 0, 0])
            brush_size = brush.get('size', [32, 32, 32])
            light_direction = brush.get('light_direction', 'top')
            brush_colour = brush.get('colour', [1.0, 0.9, 0.5])  # Default warm glow
            
            # Get direction vector
            direction = face_directions.get(light_direction, [0, 1, 0])
            
            # Calculate light position at the center of the emitting face
            face_offsets = {
                'top':    [0, brush_size[1]/2, 0],
                'bottom': [0, -brush_size[1]/2, 0],
                'north':  [0, 0, brush_size[2]/2],
                'south':  [0, 0, -brush_size[2]/2],
                'east':   [brush_size[0]/2, 0, 0],
                'west':   [-brush_size[0]/2, 0, 0],
            }
            offset = face_offsets.get(light_direction, [0, 0, 0])
            
            light_pos = [
                brush_pos[0] + offset[0],
                brush_pos[1] + offset[1],
                brush_pos[2] + offset[2]
            ]
            
            # Calculate light radius based on brush size (larger brush = more light)
            avg_size = (brush_size[0] + brush_size[1] + brush_size[2]) / 3.0
            light_radius = max(128.0, avg_size * 3.0)
            
            # Create pseudo-light dict (compatible with _set_light_uniforms via duck typing)
            glow_light = {
                'pos': light_pos,
                'color': brush_colour,
                'intensity': 1.2,  # Slightly brighter than default
                'radius': light_radius,
            }
            
            glow_lights.append(glow_light)
        
        return glow_lights

    def draw_models(self, projection, view, models, lights, config):
        if not models: return
        
        shader = self.shaders['lit']
        gl.glUseProgram(shader)

        self._set_light_uniforms(shader, lights)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        
        for model_thing in models:
            path = model_thing.properties.get('model_path')
            if not path: continue
            
            model_obj = self.get_model(path)
            if not model_obj.is_loaded: continue
            
            # Setup Model Matrix: Translate * Rotate * Scale
            pos = model_thing.pos
            rot = model_thing.properties.get('rotation', [0, 0, 0])
            scale = model_thing.properties.get('scale', [1, 1, 1])
            
            mat = glm.translate(glm.mat4(1.0), glm.vec3(pos))
            mat = glm.rotate(mat, glm.radians(rot[0]), glm.vec3(1, 0, 0)) # Pitch
            mat = glm.rotate(mat, glm.radians(rot[1]), glm.vec3(0, 1, 0)) # Yaw
            mat = glm.rotate(mat, glm.radians(rot[2]), glm.vec3(0, 0, 1)) # Roll
            mat = glm.scale(mat, glm.vec3(scale))
            
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(mat))
            
            # Select color
            is_selected = (model_thing is config.get('selected_object'))
            color = [1.0, 1.0, 0.0] if is_selected else [0.8, 0.8, 0.8]
            
            gl.glUniform3fv(gl.glGetUniformLocation(shader, "object_color"), 1, color)
            gl.glUniform1f(gl.glGetUniformLocation(shader, "alpha"), 1.0)
            
            gl.glBindVertexArray(model_obj.vao)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, model_obj.vertex_count)
            gl.glBindVertexArray(0)

    def draw_fog_volumes(self, projection, view, brushes, lights, camera_pos, config):
        if not brushes: return
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        shader = self.shaders['fog']
        gl.glUseProgram(shader)

        self._set_light_uniforms(shader, lights)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniform3fv(gl.glGetUniformLocation(shader, "viewPos"), 1, glm.value_ptr(camera_pos))
        gl.glUniform1f(gl.glGetUniformLocation(shader, "time"), config.get('time', 0.0))

        gl.glActiveTexture(gl.GL_TEXTURE1)
        gl.glBindTexture(gl.GL_TEXTURE_3D, self.noise_texture_id)
        gl.glUniform1i(gl.glGetUniformLocation(shader, "noiseTexture"), 1)

        gl.glBindVertexArray(self.vaos['cube'])
        gl.glEnable(gl.GL_CULL_FACE)

        for brush in brushes:
            model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

            density = brush.get('fog_density', 0.01)
            fog_color = brush.get('fog_color', [0.5, 0.6, 0.7])
            noise_scale = brush.get('fog_noise_scale', 0.01)

            gl.glUniform1f(gl.glGetUniformLocation(shader, "density"), density)
            gl.glUniform3fv(gl.glGetUniformLocation(shader, "fogColor"), 1, fog_color)
            gl.glUniform1f(gl.glGetUniformLocation(shader, "noiseScale"), noise_scale)

            gl.glCullFace(gl.GL_FRONT)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            gl.glCullFace(gl.GL_BACK)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)

        gl.glDisable(gl.GL_CULL_FACE)
        gl.glBindVertexArray(0)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    def render_shadows(self, projection, view, brushes, lights):
        gl.glEnable(gl.GL_STENCIL_TEST)
        gl.glEnable(gl.GL_DEPTH_CLAMP)
        gl.glDisable(gl.GL_CULL_FACE)

        for light in lights:
            gl.glClear(gl.GL_STENCIL_BUFFER_BIT)
            gl.glColorMask(gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE)
            gl.glDepthMask(gl.GL_FALSE)
            gl.glStencilFunc(gl.GL_ALWAYS, 0, 0xFF)
            gl.glStencilOpSeparate(gl.GL_BACK, gl.GL_KEEP, gl.GL_INCR_WRAP, gl.GL_KEEP)
            gl.glStencilOpSeparate(gl.GL_FRONT, gl.GL_KEEP, gl.GL_DECR_WRAP, gl.GL_KEEP)

            shader = self.shaders['shadow_volume']
            gl.glUseProgram(shader)
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
            gl.glUniform3fv(gl.glGetUniformLocation(shader, "lightPos"), 1, light.pos)

            gl.glBindVertexArray(self.vaos['cube'])
            for brush in brushes:
                if brush.get('is_trigger'): continue
                if brush.get('shader') == 'Fog': continue # Fog doesn't cast shadows
                model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
                gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            gl.glBindVertexArray(0)

            gl.glColorMask(gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE)
            gl.glDepthMask(gl.GL_TRUE)
            gl.glStencilFunc(gl.GL_NOTEQUAL, 0, 0xFF)
            gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)

            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glDisable(gl.GL_DEPTH_TEST)

            shader_simple = self.shaders['simple']
            gl.glUseProgram(shader_simple)
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader_simple, "projection"), 1, gl.GL_FALSE, glm.value_ptr(glm.mat4(1.0)))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader_simple, "view"), 1, gl.GL_FALSE, glm.value_ptr(glm.mat4(1.0)))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader_simple, "model"), 1, gl.GL_FALSE, glm.value_ptr(glm.scale(glm.mat4(1.0), glm.vec3(2.0))))
            gl.glUniform3f(gl.glGetUniformLocation(shader_simple, "color"), 0.0, 0.0, 0.0)
            
            gl.glBindVertexArray(self.vaos['cube'])
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            gl.glBindVertexArray(0)

            gl.glEnable(gl.GL_DEPTH_TEST)
            gl.glDisable(gl.GL_BLEND)

        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glDisable(gl.GL_DEPTH_CLAMP)
        gl.glEnable(gl.GL_CULL_FACE)

    def _sort_objects(self, brushes, things, config):
        opaque_brushes, transparent_brushes, sprites, fog_volumes, models = [], [], [], [], []
        play_mode = config.get('play_mode', False)
        show_sprites_in_play_mode = config.get('show_sprites_in_play_mode', False)
        
        # Shaders that have transparency
        transparent_shaders = {'Glass', 'Water'}
        
        for b in brushes:
            if b.get('hidden', False): continue
            
            # Check for fog shader or legacy is_fog flag
            if b.get('shader') == 'Fog' or b.get('is_fog', False):
                fog_volumes.append(b)
            elif b.get('is_trigger', False):
                transparent_brushes.append(b)
            elif b.get('shader', 'Default') in transparent_shaders:
                transparent_brushes.append(b)
            else:
                opaque_brushes.append(b)

        for t in things:
            if isinstance(t, Model):
                models.append(t)
            elif isinstance(t, Thing):
                if not play_mode or show_sprites_in_play_mode:
                    sprites.append(t)
            
        return opaque_brushes, transparent_brushes, sprites, fog_volumes, models

    def draw_grid(self, projection, view, grid_indices_count):
        shader = self.shaders['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(glm.mat4(1.0)))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 0.2, 0.2, 0.2)
        gl.glBindVertexArray(self.vaos['grid'])
        gl.glDrawArrays(gl.GL_LINES, 0, grid_indices_count)
        gl.glBindVertexArray(0)

    def draw_lit_brushes(self, projection, view, brushes, lights, config, is_transparent_pass=False):
        if not brushes: return
        shader = self.shaders['lit']
        gl.glUseProgram(shader)
        self._set_light_uniforms(shader, lights)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glBindVertexArray(self.vaos['cube'])
        
        display_mode = config.get('brush_display_mode', 'Textured')
        show_triggers_solid = config.get('show_triggers_as_solid', False)

        for brush in brushes:
            if is_transparent_pass:
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL if show_triggers_solid else gl.GL_LINE)
            else:
                gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL if display_mode != "Wireframe" else gl.GL_LINE)

            model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

            is_selected, is_subtract = (brush is config.get('selected_object')), (brush.get('operation') == 'subtract')
            
            # Get brush colour tint (default grey)
            base_colour = brush.get('colour', [0.8, 0.8, 0.8])
            color, alpha = list(base_colour), 1.0
            
            if brush.get('is_trigger', False): color, alpha = [0.0, 1.0, 1.0], 0.3
            elif is_selected: color = [1.0, 1.0, 0.0]
            elif is_subtract: color = [1.0, 0.0, 0.0]

            gl.glUniform3fv(gl.glGetUniformLocation(shader, "object_color"), 1, color)
            gl.glUniform1f(gl.glGetUniformLocation(shader, "alpha"), alpha)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)

        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glBindVertexArray(0)

    def draw_textured_brushes(self, projection, view, brushes, lights, config):
        if not brushes: return
        shader = self.shaders['textured']
        gl.glUseProgram(shader)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        self._set_light_uniforms(shader, lights)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(gl.glGetUniformLocation(shader, "texture_diffuse"), 0)
        gl.glBindVertexArray(self.vaos['cube'])
        face_keys = ['south', 'north', 'west', 'east', 'bottom', 'top']
        for brush in brushes:
            model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            textures = brush.get('textures', {})
            for i, face_key in enumerate(face_keys):
                tex_name = textures.get(face_key, 'default.png')
                if tex_name == 'caulk.jpg': continue
                tex_id = self.load_texture_callback(tex_name, 'textures')
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                gl.glDrawArrays(gl.GL_TRIANGLES, i * 6, 6)
        gl.glBindVertexArray(0)

    def draw_selected_brush_outline(self, projection, view, brush, selection_transparency=0.5):
        shader = self.shaders['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        
        # Scale the brush slightly larger to avoid z-fighting
        scale_factor = 1.002
        model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']) * scale_factor)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
        
        gl.glBindVertexArray(self.vaos['cube'])
        
        # Draw semi-transparent yellow fill (clean overlay, no diagonal lines or patterns)
        if selection_transparency > 0:
            gl.glEnable(gl.GL_BLEND)
            # Use additive blending with reduced intensity based on transparency setting
            # This creates a nice glow effect without harsh diagonal artifacts
            gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE)
            gl.glDepthMask(gl.GL_FALSE)
            gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
            
            # Scale color by transparency value for additive blending
            intensity = selection_transparency * 0.3  # Scale down to avoid being too bright
            gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), intensity, intensity, 0.0)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glDepthMask(gl.GL_TRUE)
        
        # Draw yellow wireframe outline on top using LINES instead of TRIANGLES
        gl.glDisable(gl.GL_BLEND)
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 1.0, 1.0, 0.0)
        
        # Bind the line VAO that contains only the 12 edges (24 vertices)
        gl.glBindVertexArray(self.vaos['line_cube'])
        gl.glDrawArrays(gl.GL_LINES, 0, 24)
        
        gl.glBindVertexArray(0)

    def draw_sprites(self, projection, view, things_to_draw, sprite_textures):
        if not things_to_draw: return
        shader = self.shaders['sprite']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(gl.glGetUniformLocation(shader, "sprite_texture"), 0)
        gl.glBindVertexArray(self.vaos['sprite'])
        for thing in things_to_draw:
            thing_type = thing.__class__.__name__
            if thing_type in sprite_textures:
                gl.glBindTexture(gl.GL_TEXTURE_2D, sprite_textures[thing_type])
                gl.glUniform3fv(gl.glGetUniformLocation(shader, "sprite_pos_world"), 1, thing.pos)
                size = 16.0 if isinstance(thing, Light) else 32.0
                gl.glUniform2f(gl.glGetUniformLocation(shader, "sprite_size"), size, size)
                gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, 4)
        gl.glBindVertexArray(0)

    def _set_light_uniforms(self, shader, lights):
        gl.glUniform1i(gl.glGetUniformLocation(shader, "active_lights"), len(lights))
        for i, light in enumerate(lights):
            # Handle both Thing lights and GlowBrushLight pseudo-lights (dicts)
            if hasattr(light, 'pos'):
                pos = light.pos
            else:
                pos = light.get('pos', [0, 0, 0])
            
            if hasattr(light, 'get_color'):
                color = light.get_color()
            else:
                color = light.get('color', [1.0, 1.0, 1.0])
            
            if hasattr(light, 'get_intensity'):
                intensity = light.get_intensity()
            else:
                intensity = light.get('intensity', 1.0)
            
            if hasattr(light, 'get_radius'):
                radius = light.get_radius()
            else:
                radius = light.get('radius', 256.0)
            
            gl.glUniform3fv(gl.glGetUniformLocation(shader, f"lights[{i}].position"), 1, pos)
            gl.glUniform3fv(gl.glGetUniformLocation(shader, f"lights[{i}].color"), 1, color)
            gl.glUniform1f(gl.glGetUniformLocation(shader, f"lights[{i}].intensity"), intensity)
            gl.glUniform1f(gl.glGetUniformLocation(shader, f"lights[{i}].radius"), radius)

    def _create_gizmo_buffers(self):
        axis_verts = np.array([0,0,0, 1,0,0, 0,0,0, 0,1,0, 0,0,0, 0,0,1], dtype=np.float32)
        self.vao_gizmo_lines = gl.glGenVertexArrays(1)
        vbo_gizmo_lines = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo_gizmo_lines)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, axis_verts.nbytes, axis_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)

        cone_verts, num_segments, radius, height = [], 12, 0.05, 0.2
        for i in range(num_segments):
            theta1, theta2 = (i/num_segments)*2*np.pi, ((i+1)/num_segments)*2*np.pi
            cone_verts.extend([0,0,0, np.cos(theta2)*radius,0,np.sin(theta2)*radius, np.cos(theta1)*radius,0,np.sin(theta1)*radius])
            cone_verts.extend([0,height,0, np.cos(theta1)*radius,0,np.sin(theta1)*radius, np.cos(theta2)*radius,0,np.sin(theta2)*radius])

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
        shader = self.shaders['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        base_model = glm.translate(glm.mat4(1.0), position) * glm.scale(glm.mat4(1.0), glm.vec3(32.0))
        gl.glLineWidth(1)
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(base_model))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 1, 0, 0)
        gl.glDrawArrays(gl.GL_LINES, 0, 2)
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 0, 1, 0)
        gl.glDrawArrays(gl.GL_LINES, 2, 2)
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 0, 0, 1)
        gl.glDrawArrays(gl.GL_LINES, 4, 2)
        gl.glLineWidth(1)
        gl.glBindVertexArray(self.vao_gizmo_cone)
        model_x = base_model * glm.translate(glm.mat4(1.0), glm.vec3(1,0,0)) * glm.rotate(glm.mat4(1.0), glm.radians(-90), glm.vec3(0,0,1))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_x))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 1, 0, 0)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)
        model_y = base_model * glm.translate(glm.mat4(1.0), glm.vec3(0,1,0))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_y))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 0, 1, 0)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)
        model_z = base_model * glm.translate(glm.mat4(1.0), glm.vec3(0,0,1)) * glm.rotate(glm.mat4(1.0), glm.radians(90), glm.vec3(1,0,0))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_z))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 0, 0, 1)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)
        gl.glBindVertexArray(0)

    def render_glow_arrows(self, projection, view, brushes, config):
        """Render 3D arrows showing light emission direction for glow brushes."""
        # Hide arrows in play mode unless F5 toggle is enabled
        if config.get('play_mode', False) and not config.get('show_glow_arrows_in_play_mode', False):
            return
        
        # Get arrow scale from config (default 100%)
        arrow_scale = config.get('glow_arrow_scale', 100) / 100.0
        
        # Collect glow brushes
        glow_brushes = [b for b in brushes if b.get('shader') == 'Glow' and not b.get('hidden', False)]
        if not glow_brushes:
            return
        
        shader = self.shaders['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        
        # Face direction vectors and rotation matrices
        face_data = {
            'top':    {'dir': glm.vec3(0, 1, 0),  'offset': lambda s: glm.vec3(0, s[1]/2, 0),  'rot': glm.mat4(1.0)},
            'bottom': {'dir': glm.vec3(0, -1, 0), 'offset': lambda s: glm.vec3(0, -s[1]/2, 0), 'rot': glm.rotate(glm.mat4(1.0), glm.radians(180), glm.vec3(1, 0, 0))},
            'north':  {'dir': glm.vec3(0, 0, 1),  'offset': lambda s: glm.vec3(0, 0, s[2]/2),  'rot': glm.rotate(glm.mat4(1.0), glm.radians(90), glm.vec3(1, 0, 0))},
            'south':  {'dir': glm.vec3(0, 0, -1), 'offset': lambda s: glm.vec3(0, 0, -s[2]/2), 'rot': glm.rotate(glm.mat4(1.0), glm.radians(-90), glm.vec3(1, 0, 0))},
            'east':   {'dir': glm.vec3(1, 0, 0),  'offset': lambda s: glm.vec3(s[0]/2, 0, 0),  'rot': glm.rotate(glm.mat4(1.0), glm.radians(-90), glm.vec3(0, 0, 1))},
            'west':   {'dir': glm.vec3(-1, 0, 0), 'offset': lambda s: glm.vec3(-s[0]/2, 0, 0), 'rot': glm.rotate(glm.mat4(1.0), glm.radians(90), glm.vec3(0, 0, 1))},
        }
        
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(glm.mat4(1.0)))
        
        for brush in glow_brushes:
            light_direction = brush.get('light_direction', 'top')
            if light_direction not in face_data:
                continue
            
            brush_pos = glm.vec3(brush['pos'])
            brush_size = brush['size']
            brush_colour = brush.get('colour', [1.0, 0.9, 0.5])
            
            face = face_data[light_direction]
            
            # Calculate arrow base position (center of emitting face)
            face_offset = face['offset'](brush_size)
            arrow_base = brush_pos + face_offset
            
            # Arrow length based on brush size and scale
            avg_size = (brush_size[0] + brush_size[1] + brush_size[2]) / 3.0
            arrow_length = max(32.0, avg_size * 0.8) * arrow_scale
            
            # Arrow tip position
            arrow_tip = arrow_base + face['dir'] * arrow_length
            
            # Cone position - close to the emitting surface (20% along the arrow)
            cone_pos = arrow_base + face['dir'] * (arrow_length * 0.2)
            
            # Set arrow color (slightly brighter than brush colour)
            r = min(1.0, brush_colour[0] * 1.3)
            g = min(1.0, brush_colour[1] * 1.3)
            b = min(1.0, brush_colour[2] * 1.3)
            gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), r, g, b)
            
            # Draw line for arrow shaft (from cone to tip)
            line_verts = np.array([
                cone_pos.x, cone_pos.y, cone_pos.z,
                arrow_tip.x, arrow_tip.y, arrow_tip.z
            ], dtype=np.float32)
            
            line_vao = gl.glGenVertexArrays(1)
            line_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(line_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, line_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, line_verts.nbytes, line_verts, gl.GL_DYNAMIC_DRAW)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 0, None)
            gl.glEnableVertexAttribArray(0)
            gl.glDrawArrays(gl.GL_LINES, 0, 2)
            gl.glDeleteBuffers(1, [line_vbo])
            gl.glDeleteVertexArrays(1, [line_vao])
            
            # Draw cone near the emitting surface - bigger scale
            cone_scale = max(16.0, 32.0 * arrow_scale)
            cone_model = glm.translate(glm.mat4(1.0), cone_pos) * face['rot'] * glm.scale(glm.mat4(1.0), glm.vec3(cone_scale))
            
            gl.glBindVertexArray(self.vao_gizmo_cone)
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(cone_model))
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)
        
        gl.glBindVertexArray(0)

    def _create_cube_vao(self):
        # fmt: off
        vertices = np.array([
            -0.5, -0.5, -0.5,  0.0,  0.0, -1.0,  0.0, 0.0,
             0.5, -0.5, -0.5,  0.0,  0.0, -1.0,  1.0, 0.0,
             0.5,  0.5, -0.5,  0.0,  0.0, -1.0,  1.0, 1.0,
             0.5,  0.5, -0.5,  0.0,  0.0, -1.0,  1.0, 1.0,
            -0.5,  0.5, -0.5,  0.0,  0.0, -1.0,  0.0, 1.0,
            -0.5, -0.5, -0.5,  0.0,  0.0, -1.0,  0.0, 0.0,
            -0.5, -0.5,  0.5,  0.0,  0.0,  1.0,  0.0, 0.0,
             0.5,  0.5,  0.5,  0.0,  0.0,  1.0,  1.0, 1.0,
             0.5, -0.5,  0.5,  0.0,  0.0,  1.0,  1.0, 0.0,
             0.5,  0.5,  0.5,  0.0,  0.0,  1.0,  1.0, 1.0,
            -0.5, -0.5,  0.5,  0.0,  0.0,  1.0,  0.0, 0.0,
            -0.5,  0.5,  0.5,  0.0,  0.0,  1.0,  0.0, 1.0,
            -0.5,  0.5,  0.5, -1.0,  0.0,  0.0,  1.0, 0.0,
            -0.5, -0.5, -0.5, -1.0,  0.0,  0.0,  0.0, 1.0,
            -0.5,  0.5, -0.5, -1.0,  0.0,  0.0,  1.0, 1.0,
            -0.5, -0.5, -0.5, -1.0,  0.0,  0.0,  0.0, 1.0,
            -0.5,  0.5,  0.5, -1.0,  0.0,  0.0,  1.0, 0.0,
            -0.5, -0.5,  0.5, -1.0,  0.0,  0.0,  0.0, 0.0,
             0.5,  0.5,  0.5,  1.0,  0.0,  0.0,  1.0, 0.0,
             0.5,  0.5, -0.5,  1.0,  0.0,  0.0,  1.0, 1.0,
             0.5, -0.5, -0.5,  1.0,  0.0,  0.0,  0.0, 1.0,
             0.5, -0.5, -0.5,  1.0,  0.0,  0.0,  0.0, 1.0,
             0.5, -0.5,  0.5,  1.0,  0.0,  0.0,  0.0, 0.0,
             0.5,  0.5,  0.5,  1.0,  0.0,  0.0,  1.0, 0.0,
            -0.5, -0.5, -0.5,  0.0, -1.0,  0.0,  0.0, 1.0,
             0.5, -0.5,  0.5,  0.0, -1.0,  0.0,  1.0, 0.0,
             0.5, -0.5, -0.5,  0.0, -1.0,  0.0,  1.0, 1.0,
             0.5, -0.5,  0.5,  0.0, -1.0,  0.0,  1.0, 0.0,
            -0.5, -0.5, -0.5,  0.0, -1.0,  0.0,  0.0, 1.0,
            -0.5, -0.5,  0.5,  0.0, -1.0,  0.0,  0.0, 0.0,
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

    def _create_line_cube_vao(self):
        """Creates a VAO with just the 12 edges of a cube (24 vertices) for clean wireframes."""
        # fmt: off
        vertices = np.array([
            # Bottom face loop
            -0.5, -0.5, -0.5,  0.5, -0.5, -0.5,
             0.5, -0.5, -0.5,  0.5, -0.5,  0.5,
             0.5, -0.5,  0.5, -0.5, -0.5,  0.5,
            -0.5, -0.5,  0.5, -0.5, -0.5, -0.5,
            # Top face loop
            -0.5,  0.5, -0.5,  0.5,  0.5, -0.5,
             0.5,  0.5, -0.5,  0.5,  0.5,  0.5,
             0.5,  0.5,  0.5, -0.5,  0.5,  0.5,
            -0.5,  0.5,  0.5, -0.5,  0.5, -0.5,
            # Vertical edges
            -0.5, -0.5, -0.5, -0.5,  0.5, -0.5,
             0.5, -0.5, -0.5,  0.5,  0.5, -0.5,
             0.5, -0.5,  0.5,  0.5,  0.5,  0.5,
            -0.5, -0.5,  0.5, -0.5,  0.5,  0.5
        ], dtype=np.float32)
        # fmt: on
        
        vao = gl.glGenVertexArrays(1)
        gl.glBindVertexArray(vao)
        vbo = gl.glGenBuffers(1)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)
        
        # Attribute 0: Position
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)
        
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