import os

SHADER_DIR = os.path.join(os.path.dirname(__file__), 'shaders')

# ==============================================================================
# DEFAULT SHADER SOURCES
# These are the fallback strings used if the .vert/.frag files are missing from
# disk (e.g. in a packaged build that doesn't include loose shader files).
# Keep these in sync with the files under assets/shaders/.
# ==============================================================================
DEFAULT_SHADERS = {
    'simple.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
}""",
    'simple.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;
uniform vec3 color;
uniform float alpha;
void main() {
    FragColor = vec4(color, alpha);
}""",

    'lit.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
out vec3 FragPos;         // implicitly highp
out mediump vec3 Normal;  // explicit mediump to match frag default
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;
void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = normalize(normalMatrix * aNormal);
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",
    'lit.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;
in highp vec3 FragPos;
in vec3 Normal;
uniform vec3 object_color;
uniform float alpha;
struct Light { highp vec3 position; vec3 color; float intensity; highp float radius; };
uniform Light lights[8];
uniform int active_lights;
void main() {
    vec3 norm = normalize(Normal);
    vec3 result = vec3(0.1) * object_color;
    for(int i = 0; i < active_lights; i++) {
        // FIX: use distSq to skip sqrt for out-of-range lights (matches ARM shader behaviour)
        highp vec3  toLight  = lights[i].position - FragPos;
        highp float distSq   = dot(toLight, toLight);
        highp float radiusSq = lights[i].radius * lights[i].radius;
        if(distSq < radiusSq) {
            highp float dist = sqrt(distSq);
            vec3  lightDir = toLight / dist;
            float diff = max(dot(norm, lightDir), 0.0);
            float att  = 1.0 - (dist / lights[i].radius);
            att = att * att;
            result += (diff * lights[i].color * lights[i].intensity * att) * object_color;
        }
    }
    FragColor = vec4(result, alpha);
}""",

    'textured.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out mediump vec3 Normal;
out vec2 TexCoords;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform vec2 tex_scale;
uniform mat3 normalMatrix;

void main() {
    FragPos = vec3(model * vec4(aPos, 1.0));
    Normal = normalize(normalMatrix * aNormal);
    TexCoords = aTexCoords * tex_scale;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",
    'textured.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 FragPos;
in vec3 Normal;
in highp vec2 TexCoords;

uniform sampler2D texture_diffuse;
struct Light { highp vec3 position; vec3 color; float intensity; highp float radius; };
uniform Light lights[8];
uniform int active_lights;

void main() {
    vec4 texColor = texture(texture_diffuse, TexCoords);
    if(texColor.a < 0.1) discard;

    vec3 norm = normalize(Normal);
    vec3 result = vec3(0.1) * texColor.rgb;

    for(int i = 0; i < active_lights; i++) {
        // FIX: use distSq to skip sqrt for out-of-range lights (matches ARM shader behaviour)
        highp vec3  toLight  = lights[i].position - FragPos;
        highp float distSq   = dot(toLight, toLight);
        highp float radiusSq = lights[i].radius * lights[i].radius;
        if(distSq < radiusSq) {
            highp float dist = sqrt(distSq);
            vec3  lightDir = toLight / dist;
            float diff = max(dot(norm, lightDir), 0.0);
            float att  = 1.0 - (dist / lights[i].radius);
            att = att * att;
            result += (diff * lights[i].color * lights[i].intensity * att) * texColor.rgb;
        }
    }
    FragColor = vec4(result, texColor.a);
}""",

    'sprite.vert': """#version 330 core
precision highp float;
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
precision mediump float;
out vec4 FragColor;
in highp vec2 TexCoords;
uniform sampler2D sprite_texture;
void main() {
    vec4 texColor = texture(sprite_texture, TexCoords);
    if(texColor.a < 0.1) discard;
    FragColor = texColor;
}""",

    'fog.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 a_pos;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;

out vec3 localPos;

void main() {
    localPos = a_pos;
    gl_Position = projection * view * model * vec4(a_pos, 1.0);
}""",

    'fog.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 localPos;

uniform highp mat4 model;
uniform highp mat4 inverseModel;
uniform highp vec3 viewPos;

uniform float density;
uniform vec3 fogColor;
uniform sampler3D noiseTexture;
uniform float noiseScale;
uniform highp float time;

highp vec2 intersectBox(highp vec3 rayOrigin, highp vec3 rayDir) {
    highp vec3 tMin = (-0.5 - rayOrigin) / rayDir;
    highp vec3 tMax = ( 0.5 - rayOrigin) / rayDir;
    highp vec3 t1 = min(tMin, tMax);
    highp vec3 t2 = max(tMin, tMax);
    return vec2(max(max(t1.x, t1.y), t1.z),
                min(min(t2.x, t2.y), t2.z));
}

void main() {
    highp vec3 fragWorldPos = vec3(model * vec4(localPos, 1.0));
    highp vec3 rayDirWorld  = normalize(fragWorldPos - viewPos);

    highp vec3 rayOriginLocal = (inverseModel * vec4(viewPos,       1.0)).xyz;
    highp vec3 rayDirLocal    = normalize((inverseModel * vec4(rayDirWorld, 0.0)).xyz);

    highp vec2 t = intersectBox(rayOriginLocal, rayDirLocal);
    if (t.x >= t.y) discard;

    highp float tNear    = max(0.0, t.x);
    highp float stepSize = (t.y - tNear) / 16.0;

    vec4  acc        = vec4(0.0);
    highp float timeOffset = time * 0.1;

    for (int i = 0; i < 16; ++i) {
        highp vec3 sp = rayOriginLocal + rayDirLocal * (tNear + float(i) * stepSize);
        float n       = texture(noiseTexture, sp * noiseScale + vec3(0.0, 0.0, timeOffset)).r;
        float tr      = exp(-density * n * stepSize);
        acc.rgb      += fogColor * (1.0 - tr) * (1.0 - acc.a);
        acc.a        += (1.0 - tr);
        if (acc.a > 0.99) break;
    }

    FragColor = vec4(acc.rgb, clamp(acc.a, 0.0, 1.0));
}""",

    'water.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out vec2 TexCoords;
out mediump vec3 Normal;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform highp float time;
uniform mat3 normalMatrix;

uniform int useWaveDisplacement;
uniform float waveStrength;

void main()
{
    vec3 pos = aPos;
    if (useWaveDisplacement == 1) {
        float speed = time * 1.5;
        float y = sin(pos.x * 0.5 + speed) * cos(pos.z * 0.5 + speed) * waveStrength;
        y += sin(pos.x * 1.1 + pos.z * 0.4 + speed * 1.2) * (waveStrength * 0.5);
        y += cos(pos.x * 2.1 - speed) * (waveStrength * 0.2);
        pos.y += y;
    }
    
    FragPos   = vec3(model * vec4(pos, 1.0));
    TexCoords = aTexCoords * 4.0;
    Normal    = normalize(normalMatrix * aNormal);
    
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",

    'water.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 FragPos;
in highp vec2 TexCoords;
in vec3 Normal;

struct Light {
    highp vec3 position;
    vec3 color;
    float intensity;
    highp float radius;
};

#define MAX_LIGHTS 8
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform highp vec3 viewPos;
uniform sampler2D normalMap; 
uniform highp float time;

uniform float waterOpacity;
uniform float waterReflectivity;
uniform vec3 waterTint;

void main()
{
    vec2 speed = vec2(0.04, 0.02);
    highp vec2 coord1 = TexCoords + time * speed;
    vec3 n1 = texture(normalMap, coord1).rgb;
    
    highp vec2 coord2 = (TexCoords * 0.7) - (time * vec2(speed.y, speed.x));
    vec3 n2 = texture(normalMap, coord2).rgb;
    
    vec3 norm = normalize((n1 + n2) - 1.0);
    vec3 viewDir = normalize(viewPos - FragPos);
    
    float R0 = 0.02; 
    float fresnel = R0 + (1.0 - R0) * pow(1.0 - max(dot(viewDir, vec3(0.0, 1.0, 0.0)), 0.0), 5.0);
    fresnel = clamp(fresnel * waterReflectivity * 2.5, 0.0, 1.0);

    vec3 lightAccumulation = vec3(0.0);
    vec3 specularAccum = vec3(0.0);
    float shininess = 128.0; 

    for(int i = 0; i < active_lights; i++) {
        highp float distance = length(lights[i].position - FragPos);
        if(distance < lights[i].radius) {
            vec3 lightDir = normalize(lights[i].position - FragPos);
            float att = 1.0 - smoothstep(0.0, lights[i].radius, distance);
            vec3 lightColor = lights[i].color * lights[i].intensity * att;
            float diff = max(dot(norm, lightDir), 0.0);
            lightAccumulation += diff * lightColor;
            vec3 halfwayDir = normalize(lightDir + viewDir);
            float spec = pow(max(dot(norm, halfwayDir), 0.0), shininess);
            specularAccum += spec * lightColor;
        }
    }
    
    vec3 ambient = vec3(0.15) * waterTint;
    vec3 diffuseColor = waterTint * (ambient + lightAccumulation);
    vec3 skyColor = vec3(0.65, 0.80, 0.95);
    vec3 finalColor = mix(diffuseColor, skyColor, fresnel);
    finalColor += specularAccum * (waterReflectivity * 2.0);

    float alpha = clamp(waterOpacity + (fresnel * 0.6), 0.0, 1.0);
    FragColor = vec4(finalColor, alpha);
}""",

    'glass.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out mediump vec3 Normal;
out vec2 TexCoords;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;

void main() {
    FragPos     = vec3(model * vec4(aPos, 1.0));
    Normal      = normalize(normalMatrix * aNormal);
    TexCoords   = aTexCoords;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}""",

    'glass.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 FragPos;
in vec3 Normal;
in highp vec2 TexCoords;

uniform highp vec3 viewPos;
uniform vec3 waterColor;
uniform float distortionStrength;
uniform float causticStrength;
uniform float glassOpacity;
uniform float refractionIndex;
uniform float roughness;

highp float random(in highp vec2 st) {
    return fract(sin(dot(st, vec2(12.9898, 78.233))) * 43758.5453123);
}

highp float noise(in highp vec2 st) {
    highp vec2 i = floor(st);
    highp vec2 f = fract(st);
    float a = random(i);
    float b = random(i + vec2(1.0, 0.0));
    float c = random(i + vec2(0.0, 1.0));
    float d = random(i + vec2(1.0, 1.0));
    highp vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

#define NUM_OCTAVES 3
highp float fbm(in highp vec2 st) {
    float v = 0.0;
    float a = 0.5;
    highp vec2 shift = vec2(100.0);
    mat2 rot = mat2(cos(0.5), sin(0.5), -sin(0.5), cos(0.5));
    for (int i = 0; i < NUM_OCTAVES; ++i) {
        v  += a * noise(st);
        st  = rot * st * 2.0 + shift;
        a  *= 0.5;
    }
    return v;
}

highp float pattern(in highp vec2 p) {
    return fbm(p + vec2(fbm(p)));
}

void main() {
    vec3 viewDir    = normalize(viewPos - FragPos);
    vec3 baseNormal = normalize(Normal);
    vec3 lightDir   = normalize(vec3(0.5, 1.0, 0.3));

    highp vec2 surfaceUV = FragPos.xz * 0.5 + FragPos.xy * 0.3;
    
    float iorRatio  = 1.0 / max(refractionIndex, 1.0);
    vec3 refractDir = refract(-viewDir, baseNormal, iorRatio);
    highp vec2 refractUV  = surfaceUV + refractDir.xy * distortionStrength * 0.2;

    float bumpScale     = 1.5 + roughness * 8.0;
    float surfaceHeight = pattern(refractUV * bumpScale);
    float epsilon       = 0.015;
    float hA = pattern((refractUV + vec2(epsilon, 0.0)) * bumpScale);
    float hB = pattern((refractUV + vec2(0.0, epsilon)) * bumpScale);

    float distortMul = (distortionStrength * 4.0) + roughness * 2.0;
    vec3 perturbedNormal = normalize(vec3(
        (surfaceHeight - hA) * distortMul,
        1.0 / max(distortMul * 3.0, 0.1),
        (surfaceHeight - hB) * distortMul
    ));
    
    float normalMix  = 0.5 + roughness * 0.4 + distortionStrength * 0.3;
    vec3 finalNormal = normalize(baseNormal + perturbedNormal * normalMix);

    float combinedPattern = pattern(surfaceUV * 2.0) * 0.7 + pattern(surfaceUV * 8.0) * 0.3;
    
    float fresnelPower       = mix(1.5, 10.0, causticStrength);
    float fresnel            = pow(1.0 - max(dot(viewDir, finalNormal), 0.0), fresnelPower);
    float fresnelWithPattern = fresnel * (0.8 + combinedPattern * 0.4);

    vec3  reflectDir  = reflect(-lightDir, finalNormal);
    float shininess   = mix(256.0, 16.0, roughness);
    float spec        = pow(max(dot(viewDir, reflectDir), 0.0), shininess);
    vec3  reflectDir2 = reflect(-viewDir, finalNormal);
    float envSpec     = pow(max(dot(reflectDir2, vec3(0.0, 1.0, 0.0)), 0.0), 32.0);
    vec3  specular    = vec3(1.0) * (spec * causticStrength * 4.0 + envSpec * 0.5);

    vec3 surfaceColor    = waterColor * (0.85 + combinedPattern * 0.3);
    vec3 reflectionColor = vec3(0.95, 0.98, 1.0) + vec3(combinedPattern * 0.1);
    vec3 baseMix         = mix(surfaceColor, reflectionColor, fresnelWithPattern * min(causticStrength * 2.5, 1.0));
    vec3 angleColor      = vec3(0.9, 0.95, 1.0) * fresnel * 0.2;
    vec3 finalRGB        = baseMix + angleColor;
    finalRGB += specular * (2.5 - roughness * 1.2);
    finalRGB += vec3(combinedPattern * 0.15 * (1.0 - glassOpacity)) * waterColor;

    float alpha = clamp(
        glassOpacity
        + fresnelWithPattern * (0.2 + roughness * 0.1) * (1.0 - glassOpacity)
        + roughness * 0.25
        + combinedPattern * 0.08,
        0.05, 1.0
    );
    
    FragColor = vec4(finalRGB, alpha);
}""",
    
    'shadow_volume.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
void main() {
    gl_Position = projection * view * model * vec4(aPos, 1.0);
}""",
    'shadow_volume.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;
void main() {
    FragColor = vec4(0.0, 0.0, 0.0, 0.5);
}""",

    'terrain.vert': """#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec3 aColor;
layout (location = 3) in vec2 aTexCoord;
layout (location = 4) in vec3 aSmoothNormal;

out vec3 FragPos;
out mediump vec3 Normal;
out mediump vec3 VertexColor;
out vec2 TexCoords;
out mediump vec3 SmoothNormal;

uniform mat4 projection;
uniform mat4 view;

void main() {
    FragPos      = aPos;
    Normal       = aNormal;
    VertexColor  = aColor;
    TexCoords    = aTexCoord;
    SmoothNormal = aSmoothNormal;
    gl_Position  = projection * view * vec4(aPos, 1.0);
}""",

    'terrain.frag': """#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 FragPos;
in vec3 Normal;
in vec3 VertexColor;
in highp vec2 TexCoords;
in vec3 SmoothNormal;

uniform sampler2D texGrass;
uniform sampler2D texRock;
uniform sampler2D texSand;
uniform sampler2D texSnow;
uniform vec4 biomeWeights;
uniform float terrainHeightScale;
uniform int use_textures;

struct Light {
    highp vec3 position;
    vec3 color;
    float intensity;
    highp float radius;
};

uniform Light lights[8];
uniform int active_lights;

highp float hash(highp vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
highp float noise(highp vec2 p) {
    highp vec2 i = floor(p);
    highp vec2 f = fract(p);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    highp vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

vec4 get_splat_weights(highp vec3 worldPos, vec3 smoothNorm) {
    float height = clamp(worldPos.y * terrainHeightScale, 0.0, 1.0);
    float slope  = 1.0 - max(smoothNorm.y, 0.0);  
    float n      = noise(worldPos.xz * 0.02 + height * 5.0) * 0.5 + 0.5;

    float grass_w = (1.0 - slope * 1.5) * (1.0 - height * 0.6) * biomeWeights.r;
    float rock_w  = slope * 0.8 + n * 0.4 * biomeWeights.g;
    float sand_w  = (1.0 - height * 0.4) * (1.0 - slope * 0.5) * biomeWeights.b;
    float snow_w  = smoothstep(0.6, 1.0, height) * biomeWeights.a;

    vec4 weights = vec4(grass_w, rock_w, sand_w, snow_w);
    return weights / (dot(weights, vec4(1.0)) + 0.001);
}

void main() {
    vec3 norm = normalize(Normal);
    vec3 texColor;
    
    if (use_textures == 1) {
        vec3 smoothNorm = normalize(SmoothNormal);
        vec4 splat = get_splat_weights(FragPos, smoothNorm);
        
        vec4 grass_col = texture(texGrass, TexCoords * 1.0);
        vec4 rock_col  = texture(texRock,  TexCoords * 0.5 + vec2(splat.g * 0.5, 0.0));
        vec4 sand_col  = texture(texSand,  TexCoords * 1.5 + vec2(splat.b * 0.3, splat.b * 0.2));
        vec4 snow_col  = texture(texSnow,  TexCoords * 0.8);
        
        vec3 splatColor = (
            grass_col.rgb * splat.r +
            rock_col.rgb  * splat.g +
            sand_col.rgb  * splat.b +
            snow_col.rgb  * splat.a
        );
        texColor = splatColor * VertexColor * 1.1;
    } else {
        texColor = VertexColor;
    }
    
    vec3 skyColor    = vec3(0.6, 0.75, 0.9);
    vec3 groundColor = vec3(0.3, 0.25, 0.2);
    float skyFactor  = (norm.y + 1.0) * 0.5;
    vec3 ambient     = mix(groundColor, skyColor, skyFactor) * 0.3 * texColor;
    
    vec3 result  = ambient;
    vec3 sunDir  = normalize(vec3(0.4, 0.7, 0.3));
    vec3 sunColor = vec3(1.0, 0.95, 0.85);
    float sunDiff    = max(dot(norm, sunDir), 0.0);
    float wrappedDiff = (sunDiff + 0.3) / 1.3;
    result += wrappedDiff * sunColor * 0.7 * texColor;
    
    vec3 fillDir  = normalize(vec3(-0.3, 0.2, -0.4));
    float fillDiff = max(dot(norm, fillDir), 0.0) * 0.2;
    result += fillDiff * skyColor * texColor;
    
    for (int i = 0; i < active_lights; i++) {
        highp float distance = length(lights[i].position - FragPos);
        if (distance < lights[i].radius) {
            vec3  lightDir    = normalize(lights[i].position - FragPos);
            float diff        = max(dot(norm, lightDir), 0.0);
            float attenuation = 1.0 - smoothstep(0.0, lights[i].radius, distance);
            attenuation       = attenuation * attenuation;
            result += diff * lights[i].color * lights[i].intensity * attenuation * texColor;
        }
    }
    
    float gray = dot(result, vec3(0.299, 0.587, 0.114));
    result = mix(vec3(gray), result, 1.15);
    
    FragColor = vec4(result, 1.0);
}"""
}

# Central Registry: (Shader Name) -> (Vertex Filename, Fragment Filename)
SHADER_MAP = {
    'simple':        ('simple.vert',         'simple.frag'),
    'lit':           ('lit.vert',            'lit.frag'),
    'textured':      ('textured.vert',       'textured.frag'),
    'sprite':        ('sprite.vert',         'sprite.frag'),
    'shadow_volume': ('shadow_volume.vert',  'shadow_volume.frag'),
    'fog':           ('fog.vert',            'fog.frag'),
    'water':         ('water.vert',          'water.frag'),
    'glass':         ('glass.vert',          'glass.frag'),
    'terrain':       ('terrain.vert',        'terrain.frag'),
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