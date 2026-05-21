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


class Renderer_F(BaseRenderer):
    """
    Forward renderer.  Inherits all common functionality (texture loading,
    grid, sprites, terrain, water/glass/fog, gizmo, etc.) and only overrides
    render_scene and a few forward‑specific drawing methods.
    """
    def __init__(self, texture_loader, initial_grid_size, initial_world_size, config=None):
        super().__init__(texture_loader, initial_grid_size, initial_world_size, config)
        self._current_shader = None
        self._frame_lights_uploaded = False

    # --------------------------------------------------------------------------
    # Override base methods for forward-specific shader handling (already done
    # in base via _compile_arm_shaders / _compile_standard_shaders)
    # --------------------------------------------------------------------------
    def _upload_lights_once(self, shader_name, lights):
        super()._upload_lights_once(shader_name, lights)

    # --------------------------------------------------------------------------
    # Forward-specific drawing methods (some overrides for performance)
    # --------------------------------------------------------------------------
    def draw_lit_brushes_optimized(self, projection, view, camera_pos, brushes, lights, config, is_transparent_pass=False):
        """Optimised lit brush drawing for forward renderer."""
        if not brushes or 'lit' not in self.shaders:
            return

        visible = brushes  # trust pre‑culled data
        self.render_stats.visible_brushes += len(visible)
        if not visible:
            return

        shader, uniforms = self.shaders['lit'], self.uniforms['lit']
        gl.glUseProgram(shader)
        self._current_shader = shader
        self._upload_lights_once('lit', lights)

        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))

        gl.glBindVertexArray(self.vaos['cube'])

        display_mode = config.get('brush_display_mode', 'Textured')
        show_triggers_solid = config.get('show_triggers_as_solid', False)
        selected = config.get('selected_object')
        model_loc, color_loc, alpha_loc = uniforms['model'], uniforms['object_color'], uniforms['alpha']
        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None:
            normal_mat_loc = -1

        fill_mode = (gl.GL_FILL if show_triggers_solid else gl.GL_LINE) if is_transparent_pass else \
                    (gl.GL_FILL if display_mode != "Wireframe" else gl.GL_LINE)
        gl.glPolygonMode(gl.GL_FRONT_AND_BACK, fill_mode)

        for brush in visible:
            self.render_stats.visible_tris += 12
            model_matrix = self._brush_model_matrix(brush)
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            if normal_mat_loc > 0:
                normal_mat = self._compute_normal_matrix(model_matrix)
                gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(normal_mat))

            if brush.get('is_trigger'):
                color, alpha = [0.0, 1.0, 1.0], 0.3
            elif brush is selected:
                color, alpha = [1.0, 1.0, 0.0], 1.0
            elif brush.get('operation') == 'subtract':
                color, alpha = [1.0, 0.0, 0.0], 1.0
            else:
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
        if not brushes or 'textured' not in self.shaders:
            return

        visible = brushes
        self.render_stats.visible_brushes += len(visible)
        if not visible:
            return

        shader, uniforms = self.shaders['textured'], self.uniforms['textured']
        gl.glUseProgram(shader)
        self._current_shader = shader
        self._upload_lights_once('textured', lights)

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

        normal_mat_loc = uniforms.get('normalMatrix', -1)
        if normal_mat_loc is None:
            normal_mat_loc = -1

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
                model_matrix = self._brush_model_matrix(brush)
                gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
                if normal_mat_loc > 0:
                    normal_mat = self._compute_normal_matrix(model_matrix)
                    gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(normal_mat))

                if tex_scale_loc != -1:
                    size = brush.get('size', [64, 64, 64])
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

    def draw_glow_brushes(self, projection, view, camera_pos, brushes, lights, config):
        if not brushes or 'lit' not in self.shaders:
            return

        shader, uniforms = self.shaders['lit'], self.uniforms['lit']
        gl.glUseProgram(shader)
        self._current_shader = shader
        self._upload_lights_once('lit', lights)
        gl.glUniformMatrix4fv(uniforms['projection'], 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(uniforms['view'], 1, gl.GL_FALSE, glm.value_ptr(view))

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
            model_matrix = self._brush_model_matrix(brush)
            gl.glUniformMatrix4fv(model_loc, 1, gl.GL_FALSE, glm.value_ptr(model_matrix))
            if normal_mat_loc > 0:
                normal_mat = self._compute_normal_matrix(model_matrix)
                gl.glUniformMatrix3fv(normal_mat_loc, 1, gl.GL_FALSE, glm.value_ptr(normal_mat))

            tint = brush.get('tint') or brush.get('colour')
            base_color = normalize_color(tint, default=[1.0, 1.0, 1.0])
            intensity = float(brush.get('glow_intensity', 10.0))
            overbright = [min(c * intensity, 10.0) for c in base_color]

            gl.glUniform3fv(color_loc, 1, overbright)
            gl.glUniform1f(alpha_loc, 1.0)
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
            self.render_stats.draw_calls += 1

        gl.glBindVertexArray(0)

    # --------------------------------------------------------------------------
    # render_scene – forward rendering pipeline
    # --------------------------------------------------------------------------
    def render_scene(self, projection, view, camera_pos, brushes, things, selected_object, config, clear=True):
        current_mode = config.get('render_mode', RENDER_MODE_LIT)

        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
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

        terrain = config.get('terrain', None)
        if terrain and terrain.enabled:
            self.render_terrain(projection, view, camera_pos, terrain, lights)

        # Portal pre‑pass (only in play mode)
        if config.get('play_mode', False) and Portal is not None and self._portal_gl_ready:
            portal_things = [t for t in things if isinstance(t, Portal) and t.is_active()]
            if portal_things:
                try:
                    def _portal_draw_scene(proj, vw, cam, br, th, sel, cfg):
                        all_br = cfg.get('all_brushes', br)
                        _t_opaque, _solid = self._split_opaque(all_br)
                        _t_brush_mode = cfg.get('brush_display_mode', 'Textured')
                        _lights = [t for t in th if isinstance(t, Light) and t.properties.get('state', 'on') == 'on']
                        if _t_brush_mode in ('Textured', 'Solid Lit'):
                            self.draw_textured_brushes_optimized(proj, vw, cam, _t_opaque, _lights, cfg)
                            self.draw_lit_brushes_optimized(proj, vw, cam, _solid, _lights, cfg)
                        else:
                            self.draw_lit_brushes_optimized(proj, vw, cam, all_br, _lights, cfg)
                        _sprites = []
                        for t in th:
                            if PathNode is not None and isinstance(t, PathNode):
                                continue
                            if Portal is not None and isinstance(t, Portal):
                                continue
                            if isinstance(t, dict) and 'monster_type' in t:
                                _sprites.append(t)
                            elif Pickup is not None and isinstance(t, Pickup):
                                _sprites.append(t)
                            elif Monster is not None and isinstance(t, Monster):
                                _sprites.append(t)
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

        if current_mode == RENDER_MODE_LIT and self.shadows_enabled:
            shadow_lights = [l for l in lights if l.properties.get('casts_shadows')]
            if shadow_lights:
                all_brushes = config.get('all_brushes', brushes)
                self.render_projected_shadows_optimized(projection, view, camera_pos, all_brushes, shadow_lights)

        # sort transparents
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