import os

SHADER_DIR = os.path.join(os.path.dirname(__file__), 'shaders')

# ==============================================================================
# DEFAULT SHADER SOURCES
# ==============================================================================
DEFAULT_SHADERS = {
    'simple.vert': """#version 330 core
layout (location = 0) in vec3 aPos;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
}""",
    'simple.frag': """#version 330 core
out vec4 FragColor;
uniform vec3 color;
void main() {
    FragColor = vec4(color, 1.0);
}""",

    'lit.vert': """#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
out vec3 FragPos;
out vec3 Normal;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = mat3(transpose(inverse(model))) * aNormal;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",
    'lit.frag': """#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
uniform vec3 object_color;
uniform float alpha;
struct Light { vec3 position; vec3 color; float intensity; float radius; };
uniform Light lights[8];
uniform int active_lights;
void main() {
    vec3 norm = normalize(Normal);
    vec3 result = vec3(0.1) * object_color; // Ambient
    for(int i = 0; i < active_lights; i++) {
        float distance = length(lights[i].position - FragPos);
        if(distance < lights[i].radius) {
            vec3 lightDir = normalize(lights[i].position - FragPos);
            float diff = max(dot(norm, lightDir), 0.0);
            float att = 1.0 - smoothstep(0.0, lights[i].radius, distance);
            result += (diff * lights[i].color * lights[i].intensity * att) * object_color;
        }
    }
    FragColor = vec4(result, alpha);
}""",

    'textured.vert': """#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;
out vec3 FragPos;
out vec3 Normal;
out vec2 TexCoords;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = mat3(transpose(inverse(model))) * aNormal;
    TexCoords = aTexCoords;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",
    'textured.frag': """#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
in vec2 TexCoords;
uniform sampler2D texture_diffuse;
struct Light { vec3 position; vec3 color; float intensity; float radius; };
uniform Light lights[8];
uniform int active_lights;
void main() {
    vec4 texColor = texture(texture_diffuse, TexCoords);
    if(texColor.a < 0.1) discard;
    vec3 norm = normalize(Normal);
    vec3 result = vec3(0.1) * texColor.rgb;
    for(int i = 0; i < active_lights; i++) {
        float distance = length(lights[i].position - FragPos);
        if(distance < lights[i].radius) {
            vec3 lightDir = normalize(lights[i].position - FragPos);
            float diff = max(dot(norm, lightDir), 0.0);
            float att = 1.0 - smoothstep(0.0, lights[i].radius, distance);
            result += (diff * lights[i].color * lights[i].intensity * att) * texColor.rgb;
        }
    }
    FragColor = vec4(result, texColor.a);
}""",

    'sprite.vert': """#version 330 core
layout (location = 0) in vec2 aPos;
out vec2 TexCoords;
uniform mat4 projection;
uniform mat4 view;
uniform vec3 sprite_pos_world;
uniform vec2 sprite_size;
void main() {
    TexCoords = aPos + 0.5;
    vec3 cameraRight = vec3(view[0][0], view[1][0], view[2][0]);
    vec3 cameraUp = vec3(view[0][1], view[1][1], view[2][1]);
    vec3 worldPos = sprite_pos_world 
                  + cameraRight * aPos.x * sprite_size.x 
                  + cameraUp * aPos.y * sprite_size.y;
    gl_Position = projection * view * vec4(worldPos, 1.0);
}""",
    'sprite.frag': """#version 330 core
out vec4 FragColor;
in vec2 TexCoords;
uniform sampler2D sprite_texture;
void main() {
    vec4 texColor = texture(sprite_texture, TexCoords);
    if(texColor.a < 0.1) discard;
    FragColor = texColor;
}""",

    'fog.vert': """#version 330 core
layout (location = 0) in vec3 aPos;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
out vec3 FragPos;
void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",
    'fog.frag': """#version 330 core
out vec4 FragColor;
in vec3 FragPos;
uniform vec3 fogColor;
uniform float density;
uniform float alpha;
void main() {
    FragColor = vec4(fogColor, alpha * 0.5);
}""",

    'water.vert': """#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out vec2 TexCoords;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform float time;

void main()
{
    // Vertex displacement removed (Flat surface)
    vec3 pos = aPos;
    
    FragPos = vec3(model * vec4(pos, 1.0));
    // Scale UVs so texture repeats
    TexCoords = aTexCoords * 4.0; 
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",

    'water.frag': """#version 330 core
out vec4 FragColor;

in vec3 FragPos;
in vec2 TexCoords;

struct Light {
    vec3 position;
    vec3 color;
    float intensity;
    float radius;
};

#define MAX_LIGHTS 8
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform vec3 viewPos;
uniform sampler2D normalMap; 
uniform float time;

uniform float waterOpacity;
uniform float waterReflectivity;
uniform vec3 waterTint;

void main()
{
    // 1. Animated Normal Mapping
    vec2 speed = vec2(0.05, 0.03);
    
    // Layer 1
    vec2 coord1 = TexCoords + time * speed;
    vec3 n1 = texture(normalMap, coord1).rgb;
    
    // Layer 2
    vec2 coord2 = (TexCoords * 1.61) + (time * vec2(-speed.x, speed.y) * 0.7);
    vec3 n2 = texture(normalMap, coord2).rgb;
    
    vec3 norm = normalize((n1 + n2) - 1.0);

    // 2. Base Color
    vec3 baseColor = waterTint;

    // 3. Lighting
    vec3 viewDir = normalize(viewPos - FragPos);
    
    vec3 diffuseAccum = vec3(0.0);
    vec3 specularAccum = vec3(0.0);

    // Calculate dynamic shininess:
    // At 0.0 (Lowest): 100.0 (Sharp, normal wet look)
    // At 1.0 (Highest): 2.0 (Massive, broad highlight)
    float shininess = mix(100.0, 2.0, waterReflectivity);

    for(int i = 0; i < active_lights; i++) {
        vec3 lightDir = normalize(lights[i].position - FragPos);
        float diff = max(dot(norm, lightDir), 0.0);
        
        vec3 halfwayDir = normalize(lightDir + viewDir);
        
        float spec = pow(max(dot(norm, halfwayDir), 0.0), shininess);
        
        vec3 lightColor = lights[i].color * lights[i].intensity;
        
        diffuseAccum += (diff * lightColor);
        specularAccum += (spec * lightColor);
    }
    
    vec3 litSurface = baseColor * diffuseAccum;

    // 4. Fresnel & Environment
    vec3 envColor = vec3(0.7, 0.85, 1.0); 
    
    float fresnel = pow(1.0 - max(dot(viewDir, vec3(0.0, 1.0, 0.0)), 0.0), 3.0);
    
    // Mix diffuse base with environment color
    vec3 finalColor = mix(litSurface, envColor, fresnel * waterReflectivity);

    // 5. Add Specular Highlights
    // Intensity Boost:
    // At 0.0 (Lowest): 0.5 (Normal intensity)
    // At 1.0 (Highest): 8.0 (Blindingly bright/Exaggerated)
    float specularIntensity = mix(0.5, 8.0, waterReflectivity);
    
    finalColor += specularAccum * specularIntensity;

    float alpha = clamp(waterOpacity + (fresnel * 0.5), 0.0, 1.0);

    FragColor = vec4(finalColor, alpha);
}""",
    
    'shadow_volume.vert': """#version 330 core
layout (location = 0) in vec3 aPos;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
}""",
    'shadow_volume.frag': """#version 330 core
out vec4 FragColor;
void main() {
    FragColor = vec4(0.0, 0.0, 0.0, 0.5);
}"""
}

# Central Registry: (Shader Name) -> (Vertex Filename, Fragment Filename)
SHADER_MAP = {
    'simple':        ('simple.vert', 'simple.frag'),
    'lit':           ('lit.vert', 'lit.frag'),
    'textured':      ('textured.vert', 'textured.frag'),
    'sprite':        ('sprite.vert', 'sprite.frag'),
    'shadow_volume': ('shadow_volume.vert', 'shadow_volume.frag'),
    'fog':           ('fog.vert', 'fog.frag'),
    'water':         ('water.vert', 'water.frag'),
    # Procedural is available but not yet integrated into the main render loop
    'procedural':    ('procedural_vert.glsl', 'procedural_frag.glsl'),
}

def load_shader_source(filename):
    """Loads a shader source string from the shader directory."""
    filepath = os.path.join(SHADER_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"FATAL: Shader file not found: {filepath}")
        return ""
    except Exception as e:
        print(f"FATAL: Error reading shader file {filepath}: {e}")
        return ""