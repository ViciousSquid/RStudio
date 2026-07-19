"""
engine/renderer_F.py  –  Forward renderer, inherits shared logic from BaseRenderer
"""

import glm
import OpenGL.GL as gl
import numpy as np
from collections import defaultdict
import os

from .renderer_core import BaseRenderer, normalize_color
from engine.constants import RENDER_MODE_LIT, RENDER_MODE_UNLIT, RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX
from editor.things import Thing, Light, PathNode, Portal, Pickup, Monster, LogicGate, LogicRelay, LogicTimer, LevelChanger


def _light_casts_shadows(light):
    """True if a light should cast depth cube-map shadows.

    Robust to the flag being stored as a real bool or as a string
    (``"true"``/``"false"``) in saved maps."""
    val = light.properties.get('casts_shadows', False)
    if isinstance(val, str):
        return val.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(val)


class Renderer_F(BaseRenderer):
    def __init__(self, texture_loader, initial_grid_size, initial_world_size, config=None):
        super().__init__(texture_loader, initial_grid_size, initial_world_size, config)
        self._current_shader = None
        self._frame_lights_uploaded = False

        # Texture batch cache for draw_textured_brushes_optimized.
        # Key: tuple of (brush_id, sorted_tex_items) per brush.
        # Storing None initially forces a build on the first frame.
        self._tex_batch_cache     = None   # defaultdict(list) | None
        self._tex_batch_cache_key = None   # last key tuple | None

    # ------------------------------------------------------------------
    # Matrix helpers – cached on the brush dict itself
    # ------------------------------------------------------------------

    def _brush_model_matrix(self, brush):
        """Return the model matrix for *brush*, recomputing only when the
        brush transform actually changes.  Result is stored directly on the
        brush dict so it survives across frames with zero extra bookkeeping.
        """
        pos   = brush.get('pos',  [0, 0, 0])
        size  = brush.get('size', [64, 64, 64])
        angle = brush.get('_rot_angle')
        axis  = tuple(brush.get('rot_axis', [0, 1, 0])) if angle else None
        key   = (pos[0], pos[1], pos[2],
                 size[0], size[1], size[2],
                 angle, axis)

        if brush.get('_mat_cache_key') == key:
            return brush['_mat_cache']

        mat = glm.translate(self._identity_mat4, glm.vec3(*pos))
        if angle:
            av = glm.vec3(*axis)
            if glm.length(av) > 0.001:
                mat = glm.rotate(mat, glm.radians(float(angle)), glm.normalize(av))
        mat = glm.scale(mat, glm.vec3(*size))
        brush['_mat_cache_key'] = key
        brush['_mat_cache']     = mat
        return mat

    def set_sprite_textures(self, textures):
        self.sprite_textures = textures

    def set_instance_textures(self, textures):
        self.instance_textures = textures

    def _compute_normal_matrix(self, model_matrix, brush=None):
        """Compute the normal matrix.

        If *brush* is provided the result is cached under the same cache
        key as the model matrix, so it is only recomputed when the brush
        transform changes.  Falls back to uncached behaviour when brush is
        None (e.g. calls from base-class code that don't have a brush ref).
        """
        if brush is not None:
            mk = brush.get('_mat_cache_key')
            if mk is not None and brush.get('_nmat_cache_key') == mk:
                return brush['_nmat_cache']
            try:
                nmat = glm.transpose(glm.inverse(glm.mat3(model_matrix)))
            except Exception:
                nmat = self._identity_mat3
            brush['_nmat_cache_key'] = mk
            brush['_nmat_cache']     = nmat
            return nmat
        # No brush supplied – uncached path (should be rare)
        try:
            return glm.transpose(glm.inverse(glm.mat3(model_matrix)))
        except Exception:
            return self._identity_mat3

    # ------------------------------------------------------------------

    def _upload_lights_once(self, shader_name, lights):
        super()._upload_lights_once(shader_name, lights)

    def draw_lit_brushes_optimized(self, projection, view, camera_pos, brushes, lights, config, is_transparent_pass=False):
        if not brushes or 'lit' not in self.shaders:
            return
        visible = brushes
        self.render_stats.visible_brushes += len(visible)
        shader, uniforms = self.shaders['lit'], self.uniforms['lit']
        gl.glUseProgram(shader)
        self._current_shader = shader
        self._upload_lights_once('lit', lights)
        # Cache value_ptr results – avoids redundant ctypes work per draw call
        proj_ptr = glm.value_ptr(projection)
        view_ptr = glm.value_ptr(view)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'],       1, gl.GL_FALSE, view_ptr)
        gl.glBindVertexArray(self.vaos['cube'])
        display_mode        = config.get('brush_display_mode', 'Textured')
        show_triggers_solid = config.get('show_triggers_as_solid', False)
        selected            = config.get('selected_object')
        model_loc      = uniforms['model']
        color_loc      = uniforms['object_color']
        alpha_loc      = uniforms['alpha']
        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None:
            normal_mat_loc = -1

        if is_transparent_pass:
            fill_mode = gl.GL_FILL if show_triggers_solid else gl.GL_LINE
        else:
            fill_mode = gl.GL_FILL if display_mode != "Wireframe" else gl.GL_LINE
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, fill_mode)

        for brush in visible:
            self.render_stats.visible_tris += 12
            model_matrix = self._brush_model_matrix(brush)
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            if normal_mat_loc > 0:
                nmat = self._compute_normal_matrix(model_matrix, brush)
                gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(nmat))
            if brush.get('is_trigger'):
                color, alpha = [0.0, 1.0, 1.0], 0.3
            elif brush is selected:
                color, alpha = [1.0, 1.0, 0.0], 1.0
            elif brush.get('operation') == 'subtract':
                color, alpha = [1.0, 0.0, 0.0], 1.0
            else:
                brush_tint   = brush.get('tint')
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
        if not brushes or 'textured' not in self.shaders:
            return
        visible = brushes
        self.render_stats.visible_brushes += len(visible)
        shader, uniforms = self.shaders['textured'], self.uniforms['textured']
        gl.glUseProgram(shader)
        self._current_shader = shader
        self._upload_lights_once('textured', lights)
        proj_ptr = glm.value_ptr(projection)
        view_ptr = glm.value_ptr(view)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'],       1, gl.GL_FALSE, view_ptr)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(uniforms['texture_diffuse'], 0)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        gl.glBindVertexArray(self.vaos['cube'])
        model_loc = uniforms['model']

        # Ensure tex_scale_loc is permanently stored in the UniformCache so
        # we never call glGetUniformLocation on the hot path again.
        tex_scale_loc = uniforms.get('tex_scale', -1)
        if tex_scale_loc == -1:
            loc = gl.glGetUniformLocation(shader, "tex_scale")
            uniforms._cache['tex_scale'] = loc   # write straight into the cache
            tex_scale_loc = loc

        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None:
            normal_mat_loc = -1

        is_play = config.get('play_mode', False)

        # ---- Texture batch cache -----------------------------------------
        cache_key = None if is_play else tuple(
            (id(b), tuple(sorted(b.get('textures', {}).items())))
            for b in visible
        )

        if not is_play and cache_key == self._tex_batch_cache_key and self._tex_batch_cache is not None:
            batches = self._tex_batch_cache
        else:
            batches = defaultdict(list)
            for brush in visible:
                for i, face_key in enumerate(['south', 'north', 'west', 'east', 'down', 'top']):
                    tex_name = brush.get('textures', {}).get(face_key, 'default.png')
                    if tex_name == 'caulk.jpg':
                        continue
                    if is_play and tex_name == 'nodraw.jpg':
                        continue
                    tex_id = self.texture_manager.get(os.path.join('textures', tex_name)) or \
                             self.load_texture_callback(tex_name, 'textures')
                    batches[tex_id].append((brush, i, face_key))
            if not is_play:
                self._tex_batch_cache     = batches
                self._tex_batch_cache_key = cache_key
        # ------------------------------------------------------------------

        current_tex = None
        for tex_id, items in batches.items():
            if tex_id != current_tex:
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id)
                current_tex = tex_id
                self.render_stats.batched_draws += 1
            for brush, face_idx, face_key in items:
                self.render_stats.visible_tris += 2
                model_matrix = self._brush_model_matrix(brush)
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
                if normal_mat_loc > 0:
                    nmat = self._compute_normal_matrix(model_matrix, brush)
                    gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(nmat))
                if tex_scale_loc != -1:
                    size = brush.get('size', [64, 64, 64])
                    # --- PRIORITY 1: Use pre-computed uv_scale from editor ---
                    uv_scale = brush.get('uv_scale', {}).get(face_key)
                    if uv_scale is not None:
                        gl.glUniform2f(tex_scale_loc, uv_scale[0], uv_scale[1])
                    # --- PRIORITY 2: Fallback to texture_tiling with actual dimensions ---
                    elif brush.get('texture_tiling', False):
                        tex_name = brush.get('textures', {}).get(face_key, 'default.png')
                        tex_cache_name = os.path.join('textures', tex_name)
                        tex_w, tex_h = getattr(self, '_texture_dimensions', {}).get(tex_cache_name, (128, 128))
                        tex_w = max(tex_w, 1)
                        tex_h = max(tex_h, 1)
                        
                        fi = face_idx
                        if fi == 0 or fi == 1:   # south, north
                            scale_x, scale_y = size[0] / tex_w, size[1] / tex_h
                        elif fi == 2 or fi == 3:  # west, east
                            scale_x, scale_y = size[2] / tex_w, size[1] / tex_h
                        else:                      # down, top
                            scale_x, scale_y = size[0] / tex_w, size[2] / tex_h
                        gl.glUniform2f(tex_scale_loc, scale_x, scale_y)
                    # --- PRIORITY 3: FIT mode (stretch 0→1) ---
                    else:
                        gl.glUniform2f(tex_scale_loc, 1.0, 1.0)
                gl.glDrawArrays(gl.GL_TRIANGLES, face_idx * 6, 6)
                self.render_stats.draw_calls += 1
        gl.glBindVertexArray(0)

    def draw_glow_brushes(self, projection, view, camera_pos, brushes, lights, config):
        if not brushes or 'lit' not in self.shaders:
            return
        shader, uniforms = self.shaders['lit'], self.uniforms['lit']
        gl.glUseProgram(shader)
        self._current_shader = shader
        self._upload_lights_once('lit', lights)
        proj_ptr = glm.value_ptr(projection)
        view_ptr = glm.value_ptr(view)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, proj_ptr)
        gl.glUniformMatrix4fv(uniforms['view'],       1, gl.GL_FALSE, view_ptr)
        gl.glBindVertexArray(self.vaos['cube'])
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, gl.GL_FILL)
        model_loc      = uniforms['model']
        color_loc      = uniforms['object_color']
        alpha_loc      = uniforms['alpha']
        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None:
            normal_mat_loc = -1
        for brush in brushes:
            self.render_stats.visible_tris += 12
            model_matrix = self._brush_model_matrix(brush)
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            if normal_mat_loc > 0:
                nmat = self._compute_normal_matrix(model_matrix, brush)
                gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(nmat))
            tint = brush.get('tint') or brush.get('colour')
            base_color = normalize_color(tint, default=[1.0, 1.0, 1.0])
            intensity  = float(brush.get('glow_intensity', 10.0))
            overbright = [min(c * intensity, 10.0) for c in base_color]
            gl.glUniform3fv(color_loc, 1, overbright)
            gl.glUniform1f(alpha_loc, 1.0)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            self.render_stats.draw_calls += 1
        gl.glBindVertexArray(0)

    def render_scene(self, projection, view, camera_pos, brushes, things, selected_object, config, clear=True):
        current_mode = config.get('render_mode', RENDER_MODE_LIT)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        if clear:
            # FIX: Don't clear color when rendering a portal virtual view
            if getattr(self, '_portal_virtual_view', None) is not None:
                gl.glClear(gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
            else:
                gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        self._proj_ptr = glm.value_ptr(projection)
        self._view_ptr = glm.value_ptr(view)
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
        opaque_brushes, transparent_brushes, sprite_things, fog_volumes, water_brushes, glass_brushes, glow_brushes = \
            self._sort_objects(brushes, things, config)
        textured_opaque, solid_opaque = self._split_opaque(opaque_brushes)
        models_to_render, final_sprites = [], []
        for thing in sprite_things:
            if isinstance(thing, Thing) and thing.properties.get('model_path'):
                models_to_render.append(thing)
            else:
                final_sprites.append(thing)
        lights = [t for t in things if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']
        self._frame_lights = lights

        # --- Depth cube-map shadow pass -------------------------------------
        # Render shadow-casting point lights into their cube-maps *before* any
        # scene geometry so every lit/textured/terrain draw can sample them.
        self._light_shadow_index = {}
        if current_mode == RENDER_MODE_LIT and self.shadows_enabled:
            shadow_lights = [l for l in lights if _light_casts_shadows(l)]
            if shadow_lights:
                shadow_brushes = config.get('all_brushes', brushes)
                shadow_things = config.get('all_things', things)
                self.render_shadow_maps(shadow_lights, shadow_brushes, shadow_things, config, camera_pos)

        terrain = config.get('terrain', None)
        if terrain and terrain.enabled:
            self.render_terrain(projection, view, camera_pos, terrain, lights)
        if config.get('play_mode', False) and Portal is not None and self._portal_gl_ready:
            # Use ALL things for portal discovery, not just frustum-visible ones.
            # But only render portal cameras when player is within 2048 units.
            all_things = config.get('all_things', things)
            portal_things = []
            for t in all_things:
                if not isinstance(t, Portal):
                    continue
                # Include if active OR still mid-fade (fading out but not yet hidden)
                if not t.is_active() and getattr(t, '_fade_alpha', 0.0) <= 0.01:
                    continue
                # Distance check: only render virtual camera if player is close enough
                portal_pos = glm.vec3(*t.pos)
                dist_sq = glm.distance2(portal_pos, camera_pos)
                if dist_sq <= (2048.0 * 2048.0):
                    portal_things.append(t)
            if portal_things:
                try:
                    def _portal_draw_scene(proj, vw, cam, br, th, sel, cfg):
                        # Re-sort from the FULL unculled brush set
                        all_br = cfg.get('all_brushes', br)
                        all_th = cfg.get('all_things', th) 
                        _opaque, _transparent, _sprites, _fog, _water, _glass, _glow = \
                            self._sort_objects(all_br, all_th, cfg) 

                        _t_opaque, _solid = self._split_opaque(_opaque)
                        _t_brush_mode = cfg.get('brush_display_mode', 'Textured')
                        _lights = [t for t in all_th if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']
                        if _t_brush_mode in ('Textured', 'Solid Lit'):
                            self.draw_textured_brushes_optimized(proj, vw, cam, _t_opaque, _lights, cfg)
                            self.draw_lit_brushes_optimized(proj, vw, cam, _solid, _lights, cfg)
                        else:
                            self.draw_lit_brushes_optimized(proj, vw, cam, _opaque, _lights, cfg)

                        self.draw_sprites(proj, vw, _sprites, self.sprite_textures, self.instance_textures)
                    self.draw_portals(
                        portal_things,
                        projection, view, camera_pos,
                        brushes, things, lights, config,
                        _portal_draw_scene,
                    )
                    self._proj_ptr = glm.value_ptr(projection)
                    self._view_ptr = glm.value_ptr(view)
                except Exception as _pe:
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
        if glow_brushes:
            self.draw_glow_brushes(projection, view, camera_pos, glow_brushes, lights, config)
        if models_to_render:
            self.draw_models(projection, view, camera_pos, models_to_render, lights, config)
        if transparent_brushes:
            transparent_brushes.sort(key=lambda b: -self._distance_sq(b.get('pos', [0,0,0]), camera_pos))
        if water_brushes:
            water_brushes.sort(key=lambda b: -self._distance_sq(b.get('pos', [0,0,0]), camera_pos))
        if glass_brushes:
            glass_brushes.sort(key=lambda b: -self._distance_sq(b.get('pos', [0,0,0]), camera_pos))
        if final_sprites:
            final_sprites.sort(key=lambda s: -self._distance_sq(s['pos'] if isinstance(s, dict) else s.pos, camera_pos))
        if not config.get('play_mode', False):
            self.draw_path_node_cubes(projection, view, things)
        self.draw_portal_wireframes(projection, view, things, config.get('play_mode', False))
        gl.glEnable(gl.GL_BLEND)
        gl.glDepthMask(gl.GL_FALSE)
        self.draw_sprites(projection, view, final_sprites, self.sprite_textures, self.instance_textures)
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
        if selected_object:
            if isinstance(selected_object, dict):
                self.draw_selected_brush_outline(projection, view, selected_object)
                pos = selected_object.get('pos')
                if pos is not None and not selected_object.get('lock', False):
                    self.render_gizmo(projection, view, pos)
            elif isinstance(selected_object, Thing):
                self.render_gizmo(projection, view, selected_object.pos)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_BLEND)
        gl.glUseProgram(0)