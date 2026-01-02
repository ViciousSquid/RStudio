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
layout (location = 0) in vec3 a_pos;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

out vec3 localPos;

void main() {
    // Pass the local position of the vertex
    localPos = a_pos;
    gl_Position = projection * view * model * vec4(a_pos, 1.0);
}""",
    'fog.frag': """#version 330 core
out vec4 FragColor;

in vec3 localPos; // Interpolated local position of the fragment on the cube surface

uniform mat4 model;
uniform vec3 viewPos; // Camera's world position

uniform float density;
uniform vec3 fogColor;
uniform sampler3D noiseTexture;
uniform float noiseScale;
uniform float time;

// AABB is a unit cube from -0.5 to 0.5
vec2 intersectBox(vec3 rayOrigin, vec3 rayDir) {
    vec3 tMin = (-0.5 - rayOrigin) / rayDir;
    vec3 tMax = (0.5 - rayOrigin) / rayDir;
    vec3 t1 = min(tMin, tMax);
    vec3 t2 = max(tMin, tMax);
    float tNear = max(max(t1.x, t1.y), t1.z);
    float tFar = min(min(t2.x, t2.y), t2.z);
    return vec2(tNear, tFar);
}

void main() {
    // Calculate ray origin and direction in world space first
    vec3 fragWorldPos = vec3(model * vec4(localPos, 1.0));
    vec3 rayDirWorld = normalize(fragWorldPos - viewPos);

    // Now, transform the ray into the local space of the fog volume
    mat4 inverseModel = inverse(model);
    vec3 rayOriginLocal = (inverseModel * vec4(viewPos, 1.0)).xyz;
    vec3 rayDirLocal = normalize((inverseModel * vec4(rayDirWorld, 0.0)).xyz);

    // Calculate the entry and exit points of the ray through the cube
    vec2 t = intersectBox(rayOriginLocal, rayDirLocal);
    float tNear = t.x;
    float tFar = t.y;

    if (tNear >= tFar) {
        discard;
    }

    tNear = max(0.0, tNear);

    int num_steps = 32; // Reduced steps slightly for performance
    float stepSize = (tFar - tNear) / float(num_steps);
    vec4 accumulatedColor = vec4(0.0);

    // Ray Marching Loop
    for (int i = 0; i < num_steps; ++i) {
        float currentT = tNear + float(i) * stepSize;
        vec3 samplePos = rayOriginLocal + rayDirLocal * currentT;
        
        vec3 noiseCoord = samplePos * noiseScale + vec3(0.0, 0.0, time * 0.1);
        float noiseValue = texture(noiseTexture, noiseCoord).r;
        
        float stepDensity = density * noiseValue;
        float transmittance = exp(-stepDensity * stepSize);

        // Correctly blend color based on remaining transparency
        accumulatedColor.rgb += fogColor * (1.0 - transmittance) * (1.0 - accumulatedColor.a);
        accumulatedColor.a += (1.0 - transmittance);

        if (accumulatedColor.a > 0.99) {
            break;
        }
    }
    
    accumulatedColor.a = clamp(accumulatedColor.a, 0.0, 1.0);
    FragColor = accumulatedColor;
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

    'glass.vert': """#version 330 core
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

    'glass.frag': """#version 330 core
out vec4 FragColor;

in vec3 FragPos;
in vec3 Normal;
in vec2 TexCoords;

uniform vec3 viewPos;
uniform vec3 waterColor; // Acts as the base glass tint
uniform float distortionStrength;
uniform float causticStrength;

// --- NOISE & PATTERN FUNCTIONS ---
float random(in vec2 _st) {
    return fract(sin(dot(_st.xy, vec2(12.9898,78.233))) * 43758.5453123);
}

float noise(in vec2 _st) {
    vec2 i = floor(_st);
    vec2 f = fract(_st);
    float a = random(i);
    float b = random(i + vec2(1.0, 0.0));
    float c = random(i + vec2(0.0, 1.0));
    float d = random(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a)* u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

#define NUM_OCTAVES 5
float fbm(in vec2 _st) {
    float v = 0.0;
    float a = 0.5;
    vec2 shift = vec2(100.0);
    mat2 rot = mat2(cos(0.5), sin(0.5), -sin(0.5), cos(0.50));
    for (int i = 0; i < NUM_OCTAVES; ++i) {
        v += a * noise(_st);
        _st = rot * _st * 2.0 + shift;
        a *= 0.5;
    }
    return v;
}

float pattern(in vec2 p) {
    // Domain warping pattern for surface irregularities
    return fbm(p + fbm(p + fbm(p)));
}

void main() {
    vec3 viewDir = normalize(viewPos - FragPos);
    vec3 baseNormal = normalize(Normal);
    vec3 lightDir = normalize(vec3(0.5, 1.0, 0.3));

    // --- REFRACTION ---
    // Distort UVs based on view angle and normal
    vec3 refractDir = refract(-viewDir, baseNormal, 0.9);
    vec2 refractUV = TexCoords + refractDir.xy * distortionStrength * 0.02;

    // --- STATIC SURFACE BUMP MAPPING ---
    float surfaceHeight = pattern(refractUV * 2.0);
    float epsilon = 0.01;
    float hA = pattern((refractUV + vec2(epsilon, 0)) * 2.0);
    float hB = pattern((refractUV + vec2(0, epsilon)) * 2.0);

    vec3 perturbedNormal = normalize(vec3(
        (surfaceHeight - hA) * distortionStrength,
        1.0 / max(distortionStrength * 10.0, 0.1),
        (surfaceHeight - hB) * distortionStrength
    ));
    
    // Mix the geometric normal with the noise normal
    vec3 finalNormal = normalize(baseNormal + perturbedNormal * 0.1);

    // --- SHARP FRESNEL ---
    // Powers higher than 3.0 result in very sharp edges (glass look)
    float fresnel = pow(1.0 - max(dot(viewDir, finalNormal), 0.0), 5.0);

    // --- SPECULAR ---
    vec3 reflectDir = reflect(-lightDir, finalNormal);
    // 512.0 shininess for very tight, wet/glassy highlights
    float spec = pow(max(dot(viewDir, reflectDir), 0.0), 512.0);
    vec3 specular = vec3(1.0) * spec * causticStrength;

    // --- COMPOSITION ---
    vec3 backgroundColor = waterColor;
    vec3 reflectionColor = vec3(0.9, 0.95, 1.0); // Sky-ish reflection
    
    // Mix base tint with reflection based on Fresnel angle
    vec3 finalRGB = mix(backgroundColor, reflectionColor, fresnel);
    finalRGB += specular * 2.0;

    // Calculate Alpha: clear in center, opaque at edges
    float alpha = 0.05 + fresnel * 0.85;
    
    FragColor = vec4(finalRGB, clamp(alpha, 0.0, 1.0));
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
    'glass':         ('glass.vert', 'glass.frag'),
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