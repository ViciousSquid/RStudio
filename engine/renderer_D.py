"""
engine/renderer_D.py  –  Deferred (G-buffer) renderer

Inherits shared logic from BaseRenderer, but overrides render_scene to use
a G‑buffer + lighting pass.  Falls back to the forward renderer when the
deferred pipeline is incomplete or wireframe/vertex modes are active.
"""

import ctypes
import OpenGL.GL as gl
import glm
import numpy as np

from .renderer_core import BaseRenderer, normalize_color
from .renderer_F import Renderer_F
from engine.constants import (
    RENDER_MODE_LIT, RENDER_MODE_UNLIT,
    RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX,
)
from editor.things import Light, Thing
from OpenGL.GL.shaders import compileProgram, compileShader

# G‑buffer shaders – kept inline because they are specific to deferred
_GBUF_VERT = """#version 330 core
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out vec3 Normal;
out vec2 TexCoords;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;
uniform vec2 tex_scale;

void main() {
    vec4 worldPos   = model * vec4(aPos, 1.0);
    FragPos         = worldPos.xyz;
    Normal          = normalMatrix * aNormal;
    TexCoords       = aTexCoords * tex_scale;
    gl_Position     = projection * view * worldPos;
}
"""

_GBUF_FRAG_TEXTURED = """#version 330 core
layout(location = 0) out vec3 gPosition;
layout(location = 1) out vec3 gNormal;
layout(location = 2) out vec4 gAlbedo;

in vec3 FragPos;
in vec3 Normal;
in vec2 TexCoords;

uniform sampler2D texture_diffuse;

void main() {
    vec4 texColor = texture(texture_diffuse, TexCoords);
    if (texColor.a < 0.1) discard;
    gPosition = FragPos;
    gNormal   = normalize(Normal);
    gAlbedo   = texColor;
}
"""

_GBUF_FRAG_SOLID = """#version 330 core
layout(location = 0) out vec3 gPosition;
layout(location = 1) out vec3 gNormal;
layout(location = 2) out vec4 gAlbedo;

in vec3 FragPos;
in vec3 Normal;

uniform vec3  object_color;
uniform float alpha;

void main() {
    gPosition = FragPos;
    gNormal   = normalize(Normal);
    gAlbedo   = vec4(object_color, alpha);
}
"""

_QUAD_VERT = """#version 330 core
layout(location = 0) in vec2 aPos;
layout(location = 1) in vec2 aTexCoords;

out vec2 TexCoords;

void main() {
    TexCoords   = aTexCoords;
    gl_Position = vec4(aPos, 0.0, 1.0);
}
"""

_LIGHT_FRAG = """#version 330 core
out vec4 FragColor;
in  vec2 TexCoords;

uniform sampler2D gPosition;
uniform sampler2D gNormal;
uniform sampler2D gAlbedo;

struct Light {
    vec3  position;
    vec3  color;
    float intensity;
    float radius;
};
uniform Light lights[16];
uniform int   active_lights;

void main() {
    vec3 FragPos = texture(gPosition, TexCoords).rgb;
    vec3 Normal  = normalize(texture(gNormal,  TexCoords).rgb);
    vec4 albedo  = texture(gAlbedo,   TexCoords);

    if (albedo.a < 0.01) discard;

    vec3 result = vec3(0.12) * albedo.rgb;

    for (int i = 0; i < active_lights && i < 16; i++) {
        vec3  toLight  = lights[i].position - FragPos;
        float distSq   = dot(toLight, toLight);
        float radiusSq = lights[i].radius * lights[i].radius;
        if (distSq < radiusSq) {
            float dist     = sqrt(distSq);
            vec3  lightDir = toLight / dist;
            float diff     = max(dot(Normal, lightDir), 0.0);
            float att      = 1.0 - (dist / lights[i].radius);
            att *= att;
            result += (diff * lights[i].color * lights[i].intensity * att) * albedo.rgb;
        }
    }
    FragColor = vec4(result, albedo.a);
}
"""


class Renderer_D(BaseRenderer):
    def __init__(self, texture_loader, initial_grid_size, initial_world_size, config=None):
        super().__init__(texture_loader, initial_grid_size, initial_world_size, config)

        # G-buffer GL objects
        self._gbuf_fbo    = None
        self._gbuf_pos    = None
        self._gbuf_norm   = None
        self._gbuf_albedo = None
        self._gbuf_depth  = None
        self._gbuf_size   = (0, 0)
        self._gbuf_ready  = False

        self._quad_vao = None
        self._quad_vbo = None

        self._gbuf_prog_textured = None
        self._gbuf_prog_solid    = None
        self._light_prog         = None

        self._deferred_init_failed = False
        self._init_deferred_shaders()
        self._init_quad()

        # Fallback forward renderer for wireframe/vertex modes and when deferred fails
        self._forward_fallback = Renderer_F(texture_loader, initial_grid_size, initial_world_size, config)

    def _init_deferred_shaders(self):
        try:
            self._gbuf_prog_textured = compileProgram(
                compileShader(_GBUF_VERT,          gl.GL_VERTEX_SHADER),
                compileShader(_GBUF_FRAG_TEXTURED, gl.GL_FRAGMENT_SHADER),
            )
            self._gbuf_prog_solid = compileProgram(
                compileShader(_GBUF_VERT,        gl.GL_VERTEX_SHADER),
                compileShader(_GBUF_FRAG_SOLID,  gl.GL_FRAGMENT_SHADER),
            )
            self._light_prog = compileProgram(
                compileShader(_QUAD_VERT,  gl.GL_VERTEX_SHADER),
                compileShader(_LIGHT_FRAG, gl.GL_FRAGMENT_SHADER),
            )
            print("[Renderer_D] Deferred shaders compiled successfully.")
        except Exception as exc:
            print(f"[Renderer_D] Shader compile failed — falling back to forward: {exc}")
            self._deferred_init_failed = True

    def _init_quad(self):
        try:
            quad_verts = np.array([
                -1.0,  1.0,   0.0, 1.0,
                -1.0, -1.0,   0.0, 0.0,
                 1.0, -1.0,   1.0, 0.0,
                -1.0,  1.0,   0.0, 1.0,
                 1.0, -1.0,   1.0, 0.0,
                 1.0,  1.0,   1.0, 1.0,
            ], dtype=np.float32)
            self._quad_vao = gl.glGenVertexArrays(1)
            self._quad_vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(self._quad_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self._quad_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, quad_verts.nbytes, quad_verts, gl.GL_STATIC_DRAW)
            stride = 4*4
            gl.glEnableVertexAttribArray(0)
            gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(0))
            gl.glEnableVertexAttribArray(1)
            gl.glVertexAttribPointer(1, 2, gl.GL_FLOAT, gl.GL_FALSE, stride, ctypes.c_void_p(8))
            gl.glBindVertexArray(0)
        except Exception as exc:
            print(f"[Renderer_D] Fullscreen quad init failed: {exc}")
            self._deferred_init_failed = True

    # G‑buffer management
    def _init_gbuffer(self, width: int, height: int):
        original_fbo = gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING)
        self._destroy_gbuffer()

        fbo = gl.glGenFramebuffers(1)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)

        def _attach_texture(internal_fmt, fmt, dtype, attachment):
            tid = gl.glGenTextures(1)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tid)
            gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, internal_fmt,
                            width, height, 0, fmt, dtype, None)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)
            gl.glFramebufferTexture2D(gl.GL_FRAMEBUFFER, attachment,
                                      gl.GL_TEXTURE_2D, tid, 0)
            return tid

        self._gbuf_pos    = _attach_texture(gl.GL_RGBA16F, gl.GL_RGBA, gl.GL_FLOAT,         gl.GL_COLOR_ATTACHMENT0)
        self._gbuf_norm   = _attach_texture(gl.GL_RGBA16F, gl.GL_RGBA, gl.GL_FLOAT,         gl.GL_COLOR_ATTACHMENT1)
        self._gbuf_albedo = _attach_texture(gl.GL_RGBA,    gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, gl.GL_COLOR_ATTACHMENT2)

        self._gbuf_depth = gl.glGenRenderbuffers(1)
        gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, self._gbuf_depth)
        gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH24_STENCIL8, width, height)
        gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_STENCIL_ATTACHMENT,
                                     gl.GL_RENDERBUFFER, self._gbuf_depth)

        gl.glDrawBuffers(3, [gl.GL_COLOR_ATTACHMENT0, gl.GL_COLOR_ATTACHMENT1, gl.GL_COLOR_ATTACHMENT2])

        status = gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, original_fbo)

        if status != gl.GL_FRAMEBUFFER_COMPLETE:
            print(f"[Renderer_D] G-buffer FBO incomplete (status=0x{status:X})")
            self._gbuf_ready = False
            return

        self._gbuf_fbo  = fbo
        self._gbuf_size = (width, height)
        self._gbuf_ready = True
        print(f"[Renderer_D] G-buffer created at {width}×{height}")

    def _resize_gbuffer_if_needed(self, width, height):
        if (width, height) != self._gbuf_size:
            self._init_gbuffer(width, height)

    def _destroy_gbuffer(self):
        for attr in ('_gbuf_pos', '_gbuf_norm', '_gbuf_albedo'):
            tid = getattr(self, attr, None)
            if tid:
                gl.glDeleteTextures(1, [tid])
                setattr(self, attr, None)
        if self._gbuf_depth:
            gl.glDeleteRenderbuffers(1, [self._gbuf_depth])
            self._gbuf_depth = None
        if self._gbuf_fbo:
            gl.glDeleteFramebuffers(1, [self._gbuf_fbo])
            self._gbuf_fbo = None
        self._gbuf_ready = False
        self._gbuf_size = (0, 0)

    def _gbuf_render_textured(self, projection, view, brushes, config):
        if not brushes or not self._gbuf_prog_textured:
            return
        import os
        prog = self._gbuf_prog_textured
        gl.glUseProgram(prog)
        u_proj    = gl.glGetUniformLocation(prog, "projection")
        u_view    = gl.glGetUniformLocation(prog, "view")
        u_model   = gl.glGetUniformLocation(prog, "model")
        u_nm      = gl.glGetUniformLocation(prog, "normalMatrix")
        u_scale   = gl.glGetUniformLocation(prog, "tex_scale")
        u_diffuse = gl.glGetUniformLocation(prog, "texture_diffuse")
        gl.glUniformMatrix4fv(u_proj, 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(u_view, 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glUniform1i(u_diffuse, 0)
        gl.glBindVertexArray(self.vaos['cube'])

        for brush in brushes:
            model = self._brush_model_matrix(brush)
            nm    = self._compute_normal_matrix(model)
            gl.glUniformMatrix4fv(u_model, 1, gl.GL_FALSE, glm.value_ptr(model))
            gl.glUniformMatrix3fv(u_nm,    1, gl.GL_FALSE, glm.value_ptr(nm))

            size = brush.get('size', [64, 64, 64])
            for i, key in enumerate(['south','north','west','east','down','top']):
                tex_name = brush.get('textures', {}).get(key, 'default.png')
                if tex_name == 'caulk.jpg':
                    continue
                tex_id = self.texture_manager.get(os.path.join('textures', tex_name)) or \
                         self.load_texture_callback(tex_name, 'textures')
                gl.glBindTexture(gl.GL_TEXTURE_2D, tex_id or 0)
                if brush.get('texture_tiling', False):
                    tex_unit_size = 128.0
                    if i == 0 or i == 1:
                        scale_x, scale_y = size[0] / tex_unit_size, size[1] / tex_unit_size
                    elif i == 2 or i == 3:
                        scale_x, scale_y = size[2] / tex_unit_size, size[1] / tex_unit_size
                    else:
                        scale_x, scale_y = size[0] / tex_unit_size, size[2] / tex_unit_size
                    gl.glUniform2f(u_scale, scale_x, scale_y)
                else:
                    gl.glUniform2f(u_scale, 1.0, 1.0)
                gl.glDrawArrays(gl.GL_TRIANGLES, i*6, 6)
        gl.glBindVertexArray(0)

    def _gbuf_render_solid(self, projection, view, brushes, config):
        if not brushes or not self._gbuf_prog_solid:
            return
        prog = self._gbuf_prog_solid
        gl.glUseProgram(prog)
        u_proj  = gl.glGetUniformLocation(prog, "projection")
        u_view  = gl.glGetUniformLocation(prog, "view")
        u_model = gl.glGetUniformLocation(prog, "model")
        u_nm    = gl.glGetUniformLocation(prog, "normalMatrix")
        u_scale = gl.glGetUniformLocation(prog, "tex_scale")
        u_color = gl.glGetUniformLocation(prog, "object_color")
        u_alpha = gl.glGetUniformLocation(prog, "alpha")
        gl.glUniformMatrix4fv(u_proj, 1, gl.GL_FALSE, glm.value_ptr(projection))
        gl.glUniformMatrix4fv(u_view, 1, gl.GL_FALSE, glm.value_ptr(view))
        gl.glBindVertexArray(self.vaos['cube'])

        for brush in brushes:
            model = self._brush_model_matrix(brush)
            nm    = self._compute_normal_matrix(model)
            gl.glUniformMatrix4fv(u_model, 1, gl.GL_FALSE, glm.value_ptr(model))
            gl.glUniformMatrix3fv(u_nm,    1, gl.GL_FALSE, glm.value_ptr(nm))
            scale = brush.get('tex_scale', [1.0,1.0])
            gl.glUniform2f(u_scale, float(scale[0]), float(scale[1]))
            brush_tint = brush.get('tint')
            brush_colour = brush.get('colour')
            col = normalize_color(brush_tint) if brush_tint else normalize_color(brush_colour)
            gl.glUniform3f(u_color, *col[:3])
            gl.glUniform1f(u_alpha, float(brush.get('alpha', 1.0)))
            gl.glDrawArrays(gl.GL_TRIANGLES, 0, 36)
        gl.glBindVertexArray(0)

    def _lighting_pass(self, lights):
        if not self._light_prog or not self._quad_vao:
            return
        prog = self._light_prog
        gl.glUseProgram(prog)
        for unit, (uname, tid) in enumerate((
            ('gPosition', self._gbuf_pos),
            ('gNormal',   self._gbuf_norm),
            ('gAlbedo',   self._gbuf_albedo),
        )):
            gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
            gl.glBindTexture(gl.GL_TEXTURE_2D, tid)
            gl.glUniform1i(gl.glGetUniformLocation(prog, uname), unit)

        active = min(len(lights), self.MAX_LIGHTS)
        gl.glUniform1i(gl.glGetUniformLocation(prog, "active_lights"), active)
        if active == 0:
            gl.glUniform3f(gl.glGetUniformLocation(prog, "lights[0].position"), 0,0,0)
            gl.glUniform3f(gl.glGetUniformLocation(prog, "lights[0].color"), 0,0,0)
            gl.glUniform1f(gl.glGetUniformLocation(prog, "lights[0].intensity"), 0)
            gl.glUniform1f(gl.glGetUniformLocation(prog, "lights[0].radius"), 0)

        for i, light in enumerate(lights[:self.MAX_LIGHTS]):
            base = f"lights[{i}]"
            pos = getattr(light, 'pos', [0,0,0])
            gl.glUniform3f(gl.glGetUniformLocation(prog, f"{base}.position"), float(pos[0]), float(pos[1]), float(pos[2]))
            color = light.properties.get('colour', [1.0,1.0,1.0])
            if color and max(color) > 1.0:
                color = [c/255.0 for c in color]
            gl.glUniform3f(gl.glGetUniformLocation(prog, f"{base}.color"), *[float(c) for c in color[:3]])
            gl.glUniform1f(gl.glGetUniformLocation(prog, f"{base}.intensity"), float(light.properties.get('intensity', 1.0)))
            gl.glUniform1f(gl.glGetUniformLocation(prog, f"{base}.radius"), float(light.properties.get('radius', 512.0)))

        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glBindVertexArray(self._quad_vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
        gl.glBindVertexArray(0)
        gl.glEnable(gl.GL_DEPTH_TEST)

    # --------------------------------------------------------------------------
    # render_scene override
    # --------------------------------------------------------------------------
    def render_scene(self, projection, view, camera_pos, brushes, things,
                     selected_object, config):
        current_mode = config.get('render_mode', RENDER_MODE_LIT)

        # Fallback for wireframe/vertex modes or deferred failure
        if self._deferred_init_failed or current_mode in (RENDER_MODE_WIREFRAME, RENDER_MODE_VERTEX):
            self._forward_fallback.render_scene(
                projection, view, camera_pos, brushes, things,
                selected_object, config)
            return

        original_fbo = gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING)
        viewport = gl.glGetIntegerv(gl.GL_VIEWPORT)
        w, h = int(viewport[2]), int(viewport[3])
        if w <= 0 or h <= 0:
            self._forward_fallback.render_scene(
                projection, view, camera_pos, brushes, things,
                selected_object, config)
            return

        self._resize_gbuffer_if_needed(w, h)
        if not self._gbuf_ready:
            self._forward_fallback.render_scene(
                projection, view, camera_pos, brushes, things,
                selected_object, config)
            return

        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthFunc(gl.GL_LESS)
        self._proj_ptr = glm.value_ptr(projection)
        self._view_ptr = glm.value_ptr(view)

        self.render_stats.reset()
        self.render_stats.total_brushes = len(brushes)
        self._frame_lights_uploaded = False
        self._current_shader = None

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

        # Geometry pass
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, self._gbuf_fbo)
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)

        brush_display_mode = config.get('brush_display_mode', 'Textured')
        if brush_display_mode in ('Textured', 'Solid Lit'):
            self._gbuf_render_textured(projection, view, textured_opaque, config)
            self._gbuf_render_solid(projection, view, solid_opaque, config)
        else:
            self._gbuf_render_solid(projection, view, opaque_brushes, config)

        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, original_fbo)

        # Lighting pass
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT | gl.GL_STENCIL_BUFFER_BIT)
        self._lighting_pass(lights)

        # Copy depth from G‑buffer
        gl.glBindFramebuffer(gl.GL_READ_FRAMEBUFFER, self._gbuf_fbo)
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, original_fbo)
        gl.glBlitFramebuffer(0, 0, w, h, 0, 0, w, h, gl.GL_DEPTH_BUFFER_BIT, gl.GL_NEAREST)
        gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, original_fbo)

        # Forward pass for remaining objects
        gl.glEnable(gl.GL_DEPTH_TEST)

        self.draw_grid(projection, view, self.grid_indices_count,
                      config.get('play_mode', False), config.get('grid_visible', True))

        terrain = config.get('terrain', None)
        if terrain and terrain.enabled:
            self.render_terrain(projection, view, camera_pos, terrain, lights)

        if glow_brushes:
            self._forward_fallback.draw_glow_brushes(projection, view, camera_pos, glow_brushes, lights, config)

        if models_to_render:
            self.draw_models(projection, view, camera_pos, models_to_render, lights, config)

        if not config.get('play_mode', False):
            self.draw_path_node_cubes(projection, view, things)

        self.draw_portal_wireframes(projection, view, things, config.get('play_mode', False))

        # Sort transparents
        if transparent_brushes:
            transparent_brushes.sort(key=lambda b: -self._distance_sq(b.get('pos', [0,0,0]), camera_pos))
        if water_brushes:
            water_brushes.sort(key=lambda b: -self._distance_sq(b.get('pos', [0,0,0]), camera_pos))
        if glass_brushes:
            glass_brushes.sort(key=lambda b: -self._distance_sq(b.get('pos', [0,0,0]), camera_pos))
        if final_sprites:
            final_sprites.sort(key=lambda s: -self._distance_sq(s['pos'] if isinstance(s, dict) else s.pos, camera_pos))

        gl.glEnable(gl.GL_BLEND)
        gl.glDepthMask(gl.GL_FALSE)

        self.draw_sprites(projection, view, final_sprites, self.sprite_textures, self.instance_textures)
        self._forward_fallback.draw_lit_brushes_optimized(projection, view, camera_pos, transparent_brushes, lights, config, is_transparent_pass=True)
        self.draw_water_brushes(projection, view, camera_pos, water_brushes, lights, config)
        self.draw_glass_brushes(projection, view, camera_pos, glass_brushes, lights, config)
        self.draw_fog_volumes(projection, view, camera_pos, fog_volumes, lights, config)

        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_DEPTH_TEST)

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

    def cleanup(self):
        self._destroy_gbuffer()
        if self._quad_vao:
            gl.glDeleteVertexArrays(1, [self._quad_vao])
        if self._quad_vbo:
            gl.glDeleteBuffers(1, [self._quad_vbo])
        for prog in (self._gbuf_prog_textured, self._gbuf_prog_solid, self._light_prog):
            if prog:
                try:
                    gl.glDeleteProgram(prog)
                except Exception:
                    pass
        self._forward_fallback.cleanup()
        super().cleanup()