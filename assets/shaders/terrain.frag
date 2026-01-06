#version 330 core
out vec4 FragColor;

in vec3 FragPos;
in vec3 Normal;
in vec3 VertexColor;
in vec2 TexCoords;
in vec3 SmoothNormal; // Interpolated smooth normal

uniform sampler2D texGrass;    // 0
uniform sampler2D texRock;     // 1
uniform sampler2D texSand;     // 2
uniform sampler2D texSnow;     // 3
uniform vec4 biomeWeights;       // grass.r, rock.g, sand.b, snow.a
uniform float terrainHeightScale;
uniform int use_textures;

struct Light {
    vec3 position;
    vec3 color;
    float intensity;
    float radius;
};

uniform Light lights[8];
uniform int active_lights;

// Cheap 2D noise for variation
float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

// Procedural splat weights using SmoothNormal for soft blends
vec4 get_splat_weights(vec3 worldPos, vec3 smoothNorm) {
    float height = clamp(worldPos.y * terrainHeightScale, 0.0, 1.0);
    // Use SmoothNormal for slope calculation -> Smooth transitions!
    float slope = 1.0 - max(smoothNorm.y, 0.0);  
    float n = noise(worldPos.xz * 0.02 + height * 5.0) * 0.5 + 0.5;

    float grass_w = (1.0 - slope * 1.5) * (1.0 - height * 0.6) * biomeWeights.r;
    float rock_w = slope * 0.8 + n * 0.4 * biomeWeights.g;
    float sand_w = (1.0 - height * 0.4) * (1.0 - slope * 0.5) * biomeWeights.b;
    float snow_w = smoothstep(0.6, 1.0, height) * biomeWeights.a;

    vec4 weights = vec4(grass_w, rock_w, sand_w, snow_w);
    return weights / (dot(weights, vec4(1.0)) + 0.001);
}

void main() {
    // Normal used for Lighting (Flat/Faceted)
    vec3 norm = normalize(Normal);
    vec3 texColor;
    
    if (use_textures == 1) {
        // SmoothNormal used for Texturing (Smooth gradients)
        vec3 smoothNorm = normalize(SmoothNormal);
        
        // Splat blend
        vec4 splat = get_splat_weights(FragPos, smoothNorm);
        
        // Sample with reduced tiling to fix "grid" look (4.0 -> 1.0)
        vec4 grass_col = texture(texGrass, TexCoords * 1.0);
        vec4 rock_col = texture(texRock, TexCoords * 0.5 + vec2(splat.g * 0.5, 0.0));
        vec4 sand_col = texture(texSand, TexCoords * 1.5 + vec2(splat.b * 0.3, splat.b * 0.2));
        vec4 snow_col = texture(texSnow, TexCoords * 0.8);
        
        vec3 splatColor = (
            grass_col.rgb * splat.r +
            rock_col.rgb * splat.g +
            sand_col.rgb * splat.b +
            snow_col.rgb * splat.a
        );
        texColor = splatColor * VertexColor * 1.1;
    } else {
        texColor = VertexColor;
    }
    
    // Lighting uses Faceted 'norm' to keep low-poly look
    vec3 skyColor = vec3(0.6, 0.75, 0.9);
    vec3 groundColor = vec3(0.3, 0.25, 0.2);
    float skyFactor = (norm.y + 1.0) * 0.5;
    vec3 ambient = mix(groundColor, skyColor, skyFactor) * 0.3 * texColor;
    
    vec3 result = ambient;
    
    vec3 sunDir = normalize(vec3(0.4, 0.7, 0.3));
    vec3 sunColor = vec3(1.0, 0.95, 0.85);
    float sunDiff = max(dot(norm, sunDir), 0.0);
    float wrappedDiff = (sunDiff + 0.3) / 1.3;
    result += wrappedDiff * sunColor * 0.7 * texColor;
    
    vec3 fillDir = normalize(vec3(-0.3, 0.2, -0.4));
    float fillDiff = max(dot(norm, fillDir), 0.0) * 0.2;
    result += fillDiff * skyColor * texColor;
    
    for (int i = 0; i < active_lights; i++) {
        float distance = length(lights[i].position - FragPos);
        if (distance < lights[i].radius) {
            vec3 lightDir = normalize(lights[i].position - FragPos);
            float diff = max(dot(norm, lightDir), 0.0);
            float attenuation = 1.0 - smoothstep(0.0, lights[i].radius, distance);
            attenuation = attenuation * attenuation;
            result += diff * lights[i].color * lights[i].intensity * attenuation * texColor;
        }
    }
    
    float gray = dot(result, vec3(0.299, 0.587, 0.114));
    result = mix(vec3(gray), result, 1.15);
    
    FragColor = vec4(result, 1.0);
}