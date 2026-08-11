#version 330 core
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
}