#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
uniform vec3 object_color;
uniform float alpha;
struct Light { vec3 position; vec3 color; float intensity; float radius; int shadowIndex; };
uniform Light lights[16];
uniform int active_lights;
#define MAX_SHADOW_LIGHTS 4
uniform samplerCube shadowMaps[MAX_SHADOW_LIGHTS];

highp float _sampleShadowCube(int idx, highp vec3 dir) {
    if (idx == 0) return texture(shadowMaps[0], dir).r;
    else if (idx == 1) return texture(shadowMaps[1], dir).r;
    else if (idx == 2) return texture(shadowMaps[2], dir).r;
    return texture(shadowMaps[3], dir).r;
}

// idx          : which cube-map (0..3), or <0 for a non-shadow-casting light
// fragToLight  : lightPos - fragmentWorldPos (world space)
// farPlane     : the light radius used when the cube-map was rendered
// ndotl        : diffuse term, used to scale the slope bias
// Returns 0 (fully lit) .. 1 (fully shadowed).  highp throughout because the
// world coordinates can be in the thousands and mediump would band badly.
float calcPointShadow(int idx, highp vec3 fragToLight, highp float farPlane, float ndotl) {
    if (idx < 0) return 0.0;
    highp float currentDepth = length(fragToLight);
    if (currentDepth >= farPlane) return 0.0;   // beyond the light's reach
    // The cube-map was rendered from the light looking outward, so the lookup
    // direction runs light -> fragment, i.e. the negation of fragToLight.
    highp vec3 lookDir = -fragToLight;
    highp float diskRadius = farPlane * 0.004 * (1.0 + currentDepth / farPlane);
    // Bias covers surface slope plus the depth spread from the PCF disk, so
    // flat lit surfaces don't self-shadow ("shadow acne").
    highp float bias = diskRadius + clamp(farPlane * 0.03 * (1.0 - ndotl),
                                          farPlane * 0.004, farPlane * 0.04);
    vec3 sampleDirs[20] = vec3[](
        vec3( 1, 1, 1), vec3( 1,-1, 1), vec3(-1,-1, 1), vec3(-1, 1, 1),
        vec3( 1, 1,-1), vec3( 1,-1,-1), vec3(-1,-1,-1), vec3(-1, 1,-1),
        vec3( 1, 1, 0), vec3( 1,-1, 0), vec3(-1,-1, 0), vec3(-1, 1, 0),
        vec3( 1, 0, 1), vec3(-1, 0, 1), vec3( 1, 0,-1), vec3(-1, 0,-1),
        vec3( 0, 1, 1), vec3( 0,-1, 1), vec3( 0,-1,-1), vec3( 0, 1,-1)
    );
    float shadow = 0.0;
    for (int s = 0; s < 20; ++s) {
        highp float closest = _sampleShadowCube(idx, lookDir + sampleDirs[s] * diskRadius) * farPlane;
        if (currentDepth - bias > closest) shadow += 1.0;
    }
    return shadow / 20.0;
}

void main() {
    vec3 norm = normalize(Normal);
    vec3 result = vec3(0.12) * object_color;
    for(int i = 0; i < active_lights && i < 16; i++) {
        vec3 toLight = lights[i].position - FragPos;
        float distSq = dot(toLight, toLight);
        float radiusSq = lights[i].radius * lights[i].radius;
        if(distSq < radiusSq) {
            float dist = sqrt(distSq);
            vec3 lightDir = toLight / dist;
            float diff = max(dot(norm, lightDir), 0.0);
            float att = 1.0 - (dist / lights[i].radius);
            att = att * att;
            float shadow = calcPointShadow(lights[i].shadowIndex, toLight, lights[i].radius, diff);
            result += (1.0 - shadow) * (diff * lights[i].color * lights[i].intensity * att) * object_color;
        }
    }
    FragColor = vec4(result, alpha);
}