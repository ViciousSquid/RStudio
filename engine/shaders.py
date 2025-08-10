VERTEX_SHADER_SIMPLE = """
#version 330
layout(location = 0) in vec3 a_position;
uniform mat4 projection;
uniform mat4 view;
uniform mat4 model;
uniform vec3 color;
out vec4 v_color;
void main() {
    gl_Position = projection * view * model * vec4(a_position, 1.0);
    v_color = vec4(color, 1.0);
}
"""
FRAGMENT_SHADER_SIMPLE = """
#version 330
in vec4 v_color;
out vec4 out_color;
void main() {
    out_color = v_color;
}
"""
VERTEX_SHADER_LIT = """
#version 330 core
layout (location = 0) in vec3 a_pos;
layout (location = 1) in vec3 a_normal;
out vec3 FragPos;
out vec3 Normal;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    FragPos = vec3(model * vec4(a_pos, 1.0));
    Normal = mat3(transpose(inverse(model))) * a_normal;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}
"""
FRAGMENT_SHADER_LIT = """
#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
struct Light {
    vec3 position;
    vec3 color;
    float intensity;
    float radius;
};
#define MAX_LIGHTS 16
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform vec3 object_color;
uniform float alpha;
void main() {
    vec3 ambient = 0.15 * object_color;
    vec3 norm = normalize(Normal);
    vec3 total_diffuse = vec3(0.0);
    for (int i = 0; i < active_lights; i++) {
        vec3 light_dir = lights[i].position - FragPos;
        float distance = length(light_dir);
        if(distance < lights[i].radius){
            light_dir = normalize(light_dir);
            float diff = max(dot(norm, light_dir), 0.0);
            float attenuation = 1.0 - (distance / lights[i].radius);
            total_diffuse += lights[i].color * diff * lights[i].intensity * attenuation;
        }
    }
    vec3 result = ambient + (total_diffuse * object_color);
    FragColor = vec4(result, alpha);
}
"""
VERTEX_SHADER_TEXTURED = """
#version 330 core
layout (location = 0) in vec3 a_pos;
layout (location = 1) in vec3 a_normal;
layout (location = 2) in vec2 a_tex_coord;
out vec3 FragPos;
out vec3 Normal;
out vec2 TexCoord;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    FragPos = vec3(model * vec4(a_pos, 1.0));
    Normal = mat3(transpose(inverse(model))) * a_normal;
    TexCoord = a_tex_coord;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}
"""
FRAGMENT_SHADER_TEXTURED = """
#version 330 core
out vec4 FragColor;
in vec3 FragPos; in vec3 Normal; in vec2 TexCoord;
struct Light {
    vec3 position;
    vec3 color;
    float intensity;
    float radius;
};
#define MAX_LIGHTS 16
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform sampler2D texture_diffuse;
void main() {
    vec3 tex_color = texture(texture_diffuse, TexCoord).rgb;
    vec3 ambient = 0.15 * tex_color;
    vec3 norm = normalize(Normal);
    vec3 total_diffuse_light = vec3(0.0);
    for (int i = 0; i < active_lights; i++) {
        vec3 light_dir = lights[i].position - FragPos;
        float distance = length(light_dir);
        if(distance < lights[i].radius){
            light_dir = normalize(light_dir);
            float diff = max(dot(norm, light_dir), 0.0);
            float attenuation = 1.0 - (distance / lights[i].radius);
            total_diffuse_light += lights[i].color * diff * lights[i].intensity * attenuation;
        }
    }
    vec3 final_color = ambient + (total_diffuse_light * tex_color);
    FragColor = vec4(final_color, 1.0);
}
"""
VERTEX_SHADER_SPRITE = """
#version 330 core
layout (location = 0) in vec2 a_pos;
uniform mat4 projection;
uniform mat4 view;
uniform vec3 sprite_pos_world;
uniform vec2 sprite_size;
out vec2 TexCoord;
void main() {
    vec4 pos_world = vec4(sprite_pos_world, 1.0);
    vec4 pos_view = view * pos_world;
    pos_view.xy += a_pos * sprite_size;
    gl_Position = projection * pos_view;
    TexCoord = a_pos + vec2(0.5, 0.5);
    TexCoord.y = 1.0 - TexCoord.y;
}
"""
FRAGMENT_SHADER_SPRITE = """
#version 330 core
out vec4 FragColor;
in vec2 TexCoord;
uniform sampler2D sprite_texture;
void main() {
    vec4 tex_color = texture(sprite_texture, TexCoord);
    if(tex_color.a < 0.1) discard;
    FragColor = tex_color;
}
"""
SHADOW_VOLUME_VERTEX_SHADER = """
#version 330 core
layout (location = 0) in vec3 a_pos;
layout (location = 1) in vec3 a_normal;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform vec3 light_pos;
uniform float extrude_amount = 1000.0; // How far to extrude the shadow

void main()
{
    vec3 world_pos = vec3(model * vec4(a_pos, 1.0));
    vec3 light_dir = normalize(world_pos - light_pos);

    // Only extrude vertices that are part of back-facing triangles from the light's POV
    if (dot(a_normal, light_dir) < 0.0) {
        // This is a back-facing vertex, extrude it
        gl_Position = projection * view * vec4(world_pos + light_dir * extrude_amount, 1.0);
    } else {
        // This is a front-facing vertex, keep it in place
        gl_Position = projection * view * model * vec4(a_pos, 1.0);
    }
}
"""

SHADOW_VOLUME_FRAGMENT_SHADER = """
#version 330 core
void main()
{
    // No color output is needed, we only care about the stencil buffer
}
"""

VERTEX_SHADER_FOG = """
#version 330 core
layout (location = 0) in vec3 a_pos;
layout (location = 1) in vec3 a_normal;

out vec3 FragPos;
out vec3 Normal;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

void main() {
    FragPos = vec3(model * vec4(a_pos, 1.0));
    Normal = mat3(transpose(inverse(model))) * a_normal;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}
"""

FRAGMENT_SHADER_FOG = """
#version 330 core
out vec4 FragColor;

in vec3 FragPos;
in vec3 Normal;

struct Light {
    vec3 position;
    vec3 color;
    float intensity;
    float radius;
};

#define MAX_LIGHTS 16
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform vec3 viewPos;
uniform float density;
uniform bool emitLight;

void main() {
    vec3 norm = normalize(Normal);
    vec3 total_light = vec3(0.0);

    for (int i = 0; i < active_lights; i++) {
        vec3 light_dir = lights[i].position - FragPos;
        float distance = length(light_dir);
        if(distance < lights[i].radius){
            light_dir = normalize(light_dir);
            float diff = max(dot(norm, light_dir), 0.0);
            float attenuation = 1.0 - (distance / lights[i].radius);
            total_light += lights[i].color * diff * lights[i].intensity * attenuation;
        }
    }

    if (emitLight) {
        total_light += vec3(1.0, 1.0, 1.0);
    }
    
    float dist = length(viewPos - FragPos);
    float fogFactor = exp(-density * dist);
    
    vec3 fogColor = vec3(0.5, 0.6, 0.7); // A cool grey fog color
    
    FragColor = vec4(mix(fogColor, total_light, fogFactor), 1.0 - fogFactor);
}
"""