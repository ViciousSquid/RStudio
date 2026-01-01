#version 330 core
out vec4 FragColor;

in vec3 FragPos;
in vec3 Normal;
in vec2 TexCoord;
in vec3 LocalPos;

// Material properties
uniform vec3 material_color;
uniform float roughness;
uniform float metallic;
uniform float transparency;
uniform float emission;
uniform int material_type; 
// 0=default, 1=metal, 2=glass, 3=concrete, 4=brick, 5=wood, 6=marble, 7=rust, 8=glow, 9=water
uniform float time;
uniform int disable_pulse;  // NEW: When 1, disables pulse effect for glow

// Lighting
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

// --- Noise Functions ---
float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float hash3(vec3 p) {
    return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float noise3D(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float n = mix(
        mix(mix(hash3(i), hash3(i + vec3(1,0,0)), f.x),
            mix(hash3(i + vec3(0,1,0)), hash3(i + vec3(1,1,0)), f.x), f.y),
        mix(mix(hash3(i + vec3(0,0,1)), hash3(i + vec3(1,0,1)), f.x),
            mix(hash3(i + vec3(0,1,1)), hash3(i + vec3(1,1,1)), f.x), f.y),
        f.z);
    return n;
}

float fbm(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for(int i = 0; i < 5; i++) {
        value += amplitude * noise(p);
        p *= 2.0;
        amplitude *= 0.5;
    }
    return value;
}

float fbm3D(vec3 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for(int i = 0; i < 4; i++) {
        value += amplitude * noise3D(p);
        p *= 2.0;
        amplitude *= 0.5;
    }
    return value;
}

float voronoi(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float minDist = 1.0;
    for(int y = -1; y <= 1; y++) {
        for(int x = -1; x <= 1; x++) {
            vec2 neighbor = vec2(float(x), float(y));
            vec2 point = hash(i + neighbor) * vec2(0.8) + vec2(0.1);
            float d = length(neighbor + point - f);
            minDist = min(minDist, d);
        }
    }
    return minDist;
}

vec3 getProceduralColor(vec3 baseColor, vec3 worldPos, vec3 normal) {
    vec2 uv = worldPos.xz * 0.02;
    vec3 pos3d = worldPos * 0.02;
    
    if(material_type == 1) { // Metal
        float scratches = fbm(uv * 20.0 + vec2(worldPos.y * 5.0, 0.0));
        float shimmer = noise(uv * 50.0) * 0.1;
        return baseColor * (0.9 + scratches * 0.15 + shimmer);
    }
    else if(material_type == 2) { // Glass
        float distort = noise(uv * 10.0 + time * 0.1) * 0.05;
        return baseColor * (1.0 + distort);
    }
    else if(material_type == 3) { // Concrete
        float coarse = noise(uv * 8.0) * 0.3;
        float fine = noise(uv * 40.0) * 0.1;
        float cracks = smoothstep(0.4, 0.5, fbm(uv * 3.0)) * 0.2;
        return baseColor * (1.0 - coarse - fine - cracks);
    }
    else if(material_type == 4) { // Brick
        vec2 brickUV = worldPos.xz * 0.05;
        float row = floor(brickUV.y);
        brickUV.x += mod(row, 2.0) * 0.5;
        vec2 brick = fract(brickUV * vec2(2.0, 4.0));
        float mortar = step(0.9, brick.x) + step(0.85, brick.y);
        vec3 mortarColor = vec3(0.6, 0.6, 0.55);
        vec3 brickVariation = baseColor * (0.85 + noise(floor(brickUV * vec2(2.0, 4.0))) * 0.3);
        return mix(brickVariation, mortarColor, mortar);
    }
    else if(material_type == 5) { // Wood
        float grain = sin(worldPos.x * 0.5 + fbm(vec2(worldPos.x, worldPos.z) * 0.3) * 8.0) * 0.5 + 0.5;
        float rings = sin(length(worldPos.xz) * 2.0 + fbm(worldPos.xz * 0.5) * 5.0) * 0.5 + 0.5;
        float knots = smoothstep(0.7, 0.8, voronoi(worldPos.xz * 0.3)) * 0.3;
        vec3 darkWood = baseColor * 0.6;
        return mix(darkWood, baseColor, grain * 0.5 + rings * 0.3) - knots;
    }
    else if(material_type == 6) { // Marble
        float veins = abs(sin(worldPos.x * 0.1 + fbm3D(pos3d * 2.0) * 4.0));
        veins = pow(veins, 3.0);
        vec3 veinColor = baseColor * 0.4;
        return mix(baseColor, veinColor, veins * 0.6);
    }
    else if(material_type == 7) { // Rust
        float rust = fbm(uv * 5.0);
        float pitting = voronoi(uv * 15.0);
        vec3 rustColor = vec3(0.5, 0.25, 0.1);
        vec3 cleanMetal = baseColor;
        float rustAmount = smoothstep(0.3, 0.7, rust) * (1.0 - pitting * 0.5);
        return mix(cleanMetal, rustColor, rustAmount);
    }
    else if(material_type == 8) { // Glow
        // Pulse effect disabled when disable_pulse == 1
        if(disable_pulse == 1) {
            return baseColor;  // Constant glow, no animation
        } else {
            float pulse = sin(time * 2.0) * 0.2 + 0.8;
            float flicker = noise(vec2(time * 10.0, 0.0)) * 0.1;
            return baseColor * (pulse + flicker);
        }
    }
    else if(material_type == 9) { // Water
        float caustic1 = voronoi((uv + vec2(time * 0.1, time * 0.05)) * 8.0);
        float caustic2 = voronoi((uv - vec2(time * 0.08, time * 0.12)) * 10.0);
        float caustics = caustic1 * caustic2 * 2.0;
        return baseColor * (0.8 + caustics * 0.4);
    }
    
    // Default
    float variation = noise(uv * 10.0) * 0.1;
    return baseColor * (0.95 + variation);
}

vec3 perturbNormal(vec3 normal, vec3 worldPos) {
    float epsilon = 0.01;
    vec3 pos3d = worldPos * 0.02;
    float heightCenter = fbm3D(pos3d);
    float heightX = fbm3D(pos3d + vec3(epsilon, 0, 0));
    float heightZ = fbm3D(pos3d + vec3(0, 0, epsilon));
    vec3 tangent = normalize(vec3(1, (heightX - heightCenter) / epsilon * 0.3, 0));
    vec3 bitangent = normalize(vec3(0, (heightZ - heightCenter) / epsilon * 0.3, 1));
    vec3 perturbedNormal = normalize(cross(tangent, bitangent));
    return normalize(mix(normal, perturbedNormal, roughness * 0.3));
}

void main() {
    vec3 norm = normalize(Normal);
    if(roughness > 0.3 && material_type != 2) { 
        norm = perturbNormal(norm, FragPos);
    }
    
    vec3 proceduralColor = getProceduralColor(material_color, FragPos, norm);
    vec3 ambient = 0.15 * proceduralColor;
    vec3 total_diffuse = vec3(0.0);
    vec3 total_specular = vec3(0.0);
    vec3 viewDir = normalize(viewPos - FragPos);
    
    for(int i = 0; i < active_lights; i++) {
        vec3 light_dir = lights[i].position - FragPos;
        float distance = length(light_dir);
        if(distance < lights[i].radius) {
            light_dir = normalize(light_dir);
            float diff = max(dot(norm, light_dir), 0.0);
            float attenuation = 1.0 - (distance / lights[i].radius);
            total_diffuse += lights[i].color * diff * lights[i].intensity * attenuation;
            
            vec3 halfwayDir = normalize(light_dir + viewDir);
            float specPower = mix(128.0, 8.0, roughness);
            float spec = pow(max(dot(norm, halfwayDir), 0.0), specPower);
            vec3 specColor = mix(vec3(0.04), proceduralColor, metallic);
            total_specular += spec * specColor * lights[i].color * lights[i].intensity * attenuation * (1.0 - roughness * 0.7);
        }
    }
    
    vec3 emissive = proceduralColor * emission;
    vec3 result = ambient + (total_diffuse * proceduralColor) + total_specular + emissive;
    
    if(transparency > 0.0 || metallic > 0.5) {
        float fresnel = pow(1.0 - max(dot(viewDir, norm), 0.0), 3.0);
        fresnel = mix(0.04, 1.0, fresnel);
        result = mix(result, result * 1.5, fresnel * metallic);
    }
    
    float alpha = 1.0 - transparency;
    if(transparency > 0.0) {
        result *= 1.0 + transparency * 0.5;
    }
    
    FragColor = vec4(result, alpha);
}
