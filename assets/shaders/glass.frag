#version 330 core
out vec4 FragColor;

in vec3 FragPos;
in vec3 Normal;
in vec2 TexCoords;

uniform vec3 viewPos;
uniform vec3 waterColor; // Acts as the base glass tint
uniform float distortionStrength;
uniform float causticStrength;
uniform float glassOpacity;      // Base opacity (0=transparent, 1=opaque)
uniform float refractionIndex;   // Index of refraction (1.0-2.5)
uniform float roughness;          // Surface roughness (0=clear, 1=frosted)

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

    // --- USE WORLD-SPACE COORDINATES FOR VISIBLE SURFACE TEXTURE ---
    // Using FragPos makes the texture stay fixed on the surface (visible!)
    vec2 surfaceUV = FragPos.xz * 0.5 + FragPos.xy * 0.3; // Combine XZ and XY planes
    
    // --- REFRACTION ---
    float iorRatio = 1.0 / max(refractionIndex, 1.0);
    vec3 refractDir = refract(-viewDir, baseNormal, iorRatio);
    // Use world-space position for distortion calculation
    vec2 refractUV = surfaceUV + refractDir.xy * distortionStrength * 0.2;

    // --- SURFACE BUMP MAPPING ---
    float bumpScale = 1.5 + roughness * 8.0;
    float surfaceHeight = pattern(refractUV * bumpScale);
    float epsilon = 0.015;
    float hA = pattern((refractUV + vec2(epsilon, 0)) * bumpScale);
    float hB = pattern((refractUV + vec2(0, epsilon)) * bumpScale);

    float distortMultiplier = (distortionStrength * 4.0) + roughness * 2.0;
    vec3 perturbedNormal = normalize(vec3(
        (surfaceHeight - hA) * distortMultiplier,
        1.0 / max(distortMultiplier * 3.0, 0.1),
        (surfaceHeight - hB) * distortMultiplier
    ));
    
    // Strong normal mixing for visible surface detail
    float normalMix = 0.5 + roughness * 0.4 + distortionStrength * 0.3;
    vec3 finalNormal = normalize(baseNormal + perturbedNormal * normalMix);

    // --- VISIBLE SURFACE TEXTURE PATTERN ---
    // Add subtle surface variation that's always visible
    float surfacePattern = pattern(surfaceUV * 2.0);
    float detailPattern = pattern(surfaceUV * 8.0) * 0.3;
    float combinedPattern = surfacePattern * 0.7 + detailPattern;
    
    // --- FRESNEL EFFECT (Much stronger) ---
    float fresnelPower = mix(1.5, 10.0, causticStrength); // Wider range
    float fresnel = pow(1.0 - max(dot(viewDir, finalNormal), 0.0), fresnelPower);
    
    // Add pattern-based fresnel variation for surface detail
    float fresnelWithPattern = fresnel * (0.8 + combinedPattern * 0.4);

    // --- SPECULAR HIGHLIGHTS (Much more prominent) ---
    vec3 reflectDir = reflect(-lightDir, finalNormal);
    float shininess = mix(256.0, 16.0, roughness);
    float spec = pow(max(dot(viewDir, reflectDir), 0.0), shininess);
    
    // Add multiple specular lobes for more glass-like appearance
    vec3 reflectDir2 = reflect(-viewDir, finalNormal);
    float envSpec = pow(max(dot(reflectDir2, vec3(0, 1, 0)), 0.0), 32.0);
    
    vec3 specular = vec3(1.0) * (spec * causticStrength * 4.0 + envSpec * 0.5);

    // --- COMPOSITION WITH VISIBLE SURFACE DETAILS ---
    vec3 backgroundColor = waterColor;
    
    // Add surface color variation based on pattern
    vec3 surfaceColor = backgroundColor * (0.85 + combinedPattern * 0.3);
    
    // Bright reflection color for sky/environment
    vec3 reflectionColor = vec3(0.95, 0.98, 1.0) + vec3(combinedPattern * 0.1);
    
    // Mix with strong fresnel influence and pattern
    vec3 baseMix = mix(surfaceColor, reflectionColor, fresnelWithPattern * min(causticStrength * 2.5, 1.0));
    
    // Add subtle color shifts at different view angles
    vec3 angleColor = vec3(0.9, 0.95, 1.0) * fresnel * 0.2;
    
    vec3 finalRGB = baseMix + angleColor;
    
    // Add prominent specular highlights
    finalRGB += specular * (2.5 - roughness * 1.2);
    
    // Add slight surface scattering for depth
    float scattering = combinedPattern * 0.15 * (1.0 - glassOpacity);
    finalRGB += vec3(scattering) * waterColor;

    // --- ALPHA CALCULATION ---
    // Make opacity more visible at all ranges
    float fresnelContribution = fresnelWithPattern * (0.2 + roughness * 0.1) * (1.0 - glassOpacity);
    float roughnessOpacity = roughness * 0.25;
    float patternOpacity = combinedPattern * 0.08; // Surface pattern adds slight opacity
    float alpha = clamp(glassOpacity + fresnelContribution + roughnessOpacity + patternOpacity, 0.05, 1.0);
    
    FragColor = vec4(finalRGB, alpha);
}