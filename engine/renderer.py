import glm
import numpy as np
import OpenGL.GL as gl
import ctypes
from editor.things import Thing, Light

class Renderer:
    """Handles all modern OpenGL drawing operations for the editor."""

    def __init__(self, shaders, vaos, texture_loader):
        self.shaders = shaders
        self.vaos = vaos
        self.load_texture = texture_loader
        self._create_gizmo_buffers()

    def render_scene(self, projection, view, camera_pos, brushes, things, selected_object, config):
        """Main entry point to render a complete scene."""
        print("--- Beginning render_scene ---")
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)

        # Draw Grid
        self.draw_grid(projection, view, config['grid_indices_count'])

        # --- Prepare object lists for rendering ---
        opaque_brushes, transparent_brushes, sprites = self._sort_objects(brushes, things, config)

        # --- 1. Opaque Pass ---
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        if config.get('culling_enabled', False):
            gl.glEnable(gl.GL_CULL_FACE)
        else:
            gl.glDisable(gl.GL_CULL_FACE)

        lights = [t for t in things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']
        print(f"Total lights in scene: {len(lights)}")
        
        display_mode = config.get('brush_display_mode', 'Textured')
        if display_mode == "Textured":
            self.draw_textured_brushes(projection, view, opaque_brushes, lights, config)
        else: # Lit or Wireframe
            self.draw_lit_brushes(projection, view, opaque_brushes, lights, config)

        # --- Shadow Pass ---
        shadow_casting_lights = [light for light in lights if light.properties.get('casts_shadows')]
        print(f"Found {len(shadow_casting_lights)} shadow-casting lights.")
        if shadow_casting_lights:
            print("Initiating shadow pass.")
            self.render_shadows(projection, view, opaque_brushes, shadow_casting_lights)

        # --- 2. Transparent Pass ---
        # Sort transparent objects from back to front
        transparent_brushes.sort(key=lambda b: -glm.distance(glm.vec3(b['pos']), camera_pos))
        sprites.sort(key=lambda s: -glm.distance(glm.vec3(s.pos), camera_pos))
        
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDepthMask(gl.GL_FALSE) # Don't write to depth buffer

        self.draw_sprites(projection, view, sprites, config['sprite_textures'])
        self.draw_lit_brushes(projection, view, transparent_brushes, lights, config, is_transparent_pass=True)

        # --- 3. Overlays (Gizmo, selection outline) ---
        gl.glDepthMask(gl.GL_TRUE) # Restore depth mask for gizmo/outlines
        gl.glDisable(gl.GL_DEPTH_TEST) # Draw on top of everything

        if selected_object:
            if isinstance(selected_object, dict): # It's a brush
                # Draw wireframe for textured mode, as lit mode handles selection color
                if display_mode == "Textured":
                    self.draw_selected_brush_outline(projection, view, selected_object)
                
                # Draw gizmo ONLY if the selected brush is NOT locked
                if not selected_object.get('lock', False):
                    self.render_gizmo(projection, view, selected_object['pos'])
            
            elif isinstance(selected_object, Thing): # It's a Thing
                # Things don't have a wireframe outline, just the gizmo
                self.render_gizmo(projection, view, selected_object.pos)

        # --- Reset GL State ---
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(0)
        print("--- Finished render_scene ---")

    def render_shadows(self, projection, view, brushes, lights):
        print("\n--- render_shadows called ---")
        gl.glEnable(gl.GL_STENCIL_TEST)
        gl.glEnable(gl.GL_DEPTH_CLAMP)
        gl.glDisable(gl.GL_CULL_FACE) # We need to render both front and back faces for the stencil volume

        for light in lights:
            print(f"\nProcessing shadows for light at position: {light.pos}")
            # Clear the stencil buffer for each light
            gl.glClear(gl.GL_STENCIL_BUFFER_BIT)
            
            # 1. Stencil Pass: Render shadow volumes to stencil buffer
            print("--- Stencil Pass ---")
            print("Setting stencil state for shadow volume rendering.")
            gl.glColorMask(gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE, gl.GL_FALSE)
            gl.glDepthMask(gl.GL_FALSE)
            gl.glStencilFunc(gl.GL_ALWAYS, 0, 0xFF)
            gl.glStencilOpSeparate(gl.GL_BACK, gl.GL_KEEP, gl.GL_INCR_WRAP, gl.GL_KEEP)
            gl.glStencilOpSeparate(gl.GL_FRONT, gl.GL_KEEP, gl.GL_DECR_WRAP, gl.GL_KEEP)

            shader = self.shaders['shadow_volume']
            gl.glUseProgram(shader)
            print(f"Using shadow volume shader: {shader}")
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
            
            # Correctly convert light.pos (list) to a glm.vec3 before passing to the shader
            light_pos_vec3 = glm.vec3(light.pos)
            gl.glUniform3fv(gl.glGetUniformLocation(shader, "light_pos"), 1, glm.value_ptr(light_pos_vec3))
            print(f"Light position uniform: {light.pos}")
            
            gl.glBindVertexArray(self.vaos['cube'])
            shadow_casters = [b for b in brushes if not b.get('is_trigger', False)]
            print(f"Rendering shadow volumes for {len(shadow_casters)} brushes.")
            for brush in shadow_casters:
                model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
                gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            
            # 2. Render Pass: Render shadowed areas
            print("\n--- Shadow Render Pass ---")
            print("Setting stencil state for drawing shadows.")
            gl.glDepthMask(gl.GL_TRUE)
            gl.glColorMask(gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE, gl.GL_TRUE)
            gl.glStencilFunc(gl.GL_NOTEQUAL, 0, 0xFF)
            gl.glStencilOp(gl.GL_KEEP, gl.GL_KEEP, gl.GL_KEEP)

            # NEW: Enable blending for transparent shadow color
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            # NEW: Adjust depth function to prevent z-fighting
            gl.glDepthFunc(gl.GL_LEQUAL)

            # Use the lit shader to draw the shadows
            shader = self.shaders['lit']
            gl.glUseProgram(shader)
            # Render with only ambient light to create the shadow effect
            gl.glUniform1i(gl.glGetUniformLocation(shader, "active_lights"), 0) # No lights for shadow pass
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))

            print("Drawing shadowed areas.")
            gl.glBindVertexArray(self.vaos['cube'])
            for brush in shadow_casters:
                model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
                gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
                gl.glUniform3fv(gl.glGetUniformLocation(shader, "object_color"), 1, [0.0, 0.0, 0.0]) # Black for shadows
                gl.glUniform1f(gl.glGetUniformLocation(shader, "alpha"), 0.5) # Semi-transparent shadows
                gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
                
            # NEW: Restore OpenGL state
            gl.glDepthFunc(gl.GL_LESS)
            gl.glDisable(gl.GL_BLEND)

        gl.glDisable(gl.GL_STENCIL_TEST)
        gl.glDisable(gl.GL_DEPTH_CLAMP)
        print("\n--- Finished render_shadows ---")

    def _sort_objects(self, brushes, things, config):
        """Sorts scene objects into opaque, transparent, and sprite lists."""
        opaque_brushes = []
        transparent_brushes = []
        sprites = []

        is_play_mode = config.get('play_mode', False)

        for brush in brushes:
            if brush.get('hidden', False):
                continue
            
            is_trigger = brush.get('is_trigger', False)
            if is_play_mode and is_trigger:
                continue

            if is_trigger:
                transparent_brushes.append(brush)
            else:
                opaque_brushes.append(brush)
        
        if not is_play_mode:
            sprites.extend([t for t in things if isinstance(t, Thing)])
        
        return opaque_brushes, transparent_brushes, sprites

    def draw_grid(self, projection, view, grid_indices_count):
        """Draws the editor grid."""
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
        """Draws brushes using the lit shader (solid color, triggers, wireframe)."""
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

            is_selected = (brush is config.get('selected_object'))
            is_subtract = (brush.get('operation') == 'subtract')
            
            color, alpha = [0.8, 0.8, 0.8], 1.0
            if brush.get('is_trigger', False):
                color, alpha = [0.0, 1.0, 1.0], 0.3
            elif is_selected:
                color = [1.0, 1.0, 0.0]
            elif is_subtract:
                color = [1.0, 0.0, 0.0]

            gl.glUniform3fv(gl.glGetUniformLocation(shader, "object_color"), 1, color)
            gl.glUniform1f(gl.glGetUniformLocation(shader, "alpha"), alpha)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)

        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glBindVertexArray(0)

    def draw_textured_brushes(self, projection, view, brushes, lights, config):
        """Draws brushes using the textured shader, drawing each face with its own texture."""
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
        show_caulk = config.get('show_caulk', True)
        
        face_keys = ['south', 'north', 'west', 'east', 'bottom', 'top']

        for brush in brushes:
            model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
            gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))

            textures = brush.get('textures', {})
            for i, face_key in enumerate(face_keys):
                tex_name = textures.get(face_key, 'default.png')
                if tex_name == 'caulk' and not show_caulk:
                    continue
                
                # The texture_loader (QtGameView.load_texture) handles caching
                tex_id = self.load_texture(tex_name, 'textures')
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                gl.glDrawArrays(gl.GL_TRIANGLES, i * 6, 6)

        gl.glBindVertexArray(0)

    def draw_selected_brush_outline(self, projection, view, brush):
        """Draws a yellow wireframe outline over a selected brush, ignoring depth."""
        shader = self.shaders['simple']
        gl.glUseProgram(shader)

        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        model_matrix = glm.translate(glm.mat4(1.0), glm.vec3(brush['pos'])) * glm.scale(glm.mat4(1.0), glm.vec3(brush['size']))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 1.0, 1.0, 0.0)

        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_LINE)
        gl.glLineWidth(1)
        
        gl.glBindVertexArray(self.vaos['cube'])
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
        
        gl.glLineWidth(1)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glBindVertexArray(0)

    def draw_sprites(self, projection, view, things_to_draw, sprite_textures):
        """Draws billboarded sprites for Things."""
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
        """Sets the light array uniforms for a given shader program."""
        gl.glUniform1i(gl.glGetUniformLocation(shader, "active_lights"), len(lights))
        for i, light in enumerate(lights):
            gl.glUniform3fv(gl.glGetUniformLocation(shader, f"lights[{i}].position"), 1, light.pos)
            gl.glUniform3fv(gl.glGetUniformLocation(shader, f"lights[{i}].color"), 1, light.get_color())
            gl.glUniform1f(gl.glGetUniformLocation(shader, f"lights[{i}].intensity"), light.get_intensity())
            gl.glUniform1f(gl.glGetUniformLocation(shader, f"lights[{i}].radius"), light.get_radius())

    def _create_gizmo_buffers(self):
        """Creates VAO/VBO for the transform gizmo using modern OpenGL."""
        # Axis lines
        axis_verts = np.array([
            0, 0, 0, 1, 0, 0, # Red line for X
            0, 0, 0, 0, 1, 0, # Green line for Y
            0, 0, 0, 0, 0, 1  # Blue line for Z
        ], dtype=np.float32)

        self.vao_gizmo_lines = gl.glGenVertexArrays(1)
        vbo_gizmo_lines = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao_gizmo_lines)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo_gizmo_lines)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, axis_verts.nbytes, axis_verts, gl.GL_STATIC_DRAW)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 12, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(0)

        # Cone for arrowheads
        cone_verts = []
        num_segments = 12
        radius = 0.05
        height = 0.2
        for i in range(num_segments):
            theta1 = (i / num_segments) * 2 * np.pi
            theta2 = ((i + 1) / num_segments) * 2 * np.pi
            # Base triangle
            cone_verts.extend([0, 0, 0])
            cone_verts.extend([np.cos(theta2) * radius, 0, np.sin(theta2) * radius])
            cone_verts.extend([np.cos(theta1) * radius, 0, np.sin(theta1) * radius])
            # Side triangle
            cone_verts.extend([0, height, 0])
            cone_verts.extend([np.cos(theta1) * radius, 0, np.sin(theta1) * radius])
            cone_verts.extend([np.cos(theta2) * radius, 0, np.sin(theta2) * radius])

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
        """Draws the 3-axis transform gizmo at a given position."""
        shader = self.shaders['simple']
        gl.glUseProgram(shader)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "projection"), 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "view"), 1, gl.GL_FALSE, glm.value_ptr(view))
        
        base_model = glm.translate(glm.mat4(1.0), position) * glm.scale(glm.mat4(1.0), glm.vec3(32.0))

        # Draw axis lines
        gl.glLineWidth(1)
        gl.glBindVertexArray(self.vao_gizmo_lines)
        
        # X Axis (Red)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(base_model))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 1, 0, 0)
        gl.glDrawArrays(gl.GL_LINES, 0, 2)
        
        # Y Axis (Green)
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 0, 1, 0)
        gl.glDrawArrays(gl.GL_LINES, 2, 2)
        
        # Z Axis (Blue)
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 0, 0, 1)
        gl.glDrawArrays(gl.GL_LINES, 4, 2)
        
        gl.glLineWidth(1)

        # Draw arrowheads
        gl.glBindVertexArray(self.vao_gizmo_cone)

        # X arrowhead
        model_x = base_model * glm.translate(glm.mat4(1.0), glm.vec3(1, 0, 0)) * glm.rotate(glm.mat4(1.0), glm.radians(-90), glm.vec3(0, 0, 1))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_x))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 1, 0, 0)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)

        # Y arrowhead
        model_y = base_model * glm.translate(glm.mat4(1.0), glm.vec3(0, 1, 0))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_y))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 0, 1, 0)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)
        
        # Z arrowhead
        model_z = base_model * glm.translate(glm.mat4(1.0), glm.vec3(0, 0, 1)) * glm.rotate(glm.mat4(1.0), glm.radians(90), glm.vec3(1, 0, 0))
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(shader, "model"), 1, gl.GL_FALSE, glm.value_ptr(model_z))
        gl.glUniform3f(gl.glGetUniformLocation(shader, "color"), 0, 0, 1)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, self.gizmo_cone_v_count)

        gl.glBindVertexArray(0)