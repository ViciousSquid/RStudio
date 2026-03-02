#version 330 core
out vec4 FragColor;

in vec3 localPos;

uniform mat4 model;
uniform mat4 inverseModel;
uniform vec3 viewPos;

uniform float density;
uniform vec3 fogColor;
uniform sampler3D noiseTexture;
uniform float noiseScale;
uniform float time;

// AABB is a unit cube from -0.5 to 0.5
vec2 intersectBox(vec3 rayOrigin, vec3 rayDir) {
    vec3 tMin = (-0.5 - rayOrigin) / rayDir;
    vec3 tMax = ( 0.5 - rayOrigin) / rayDir;
    vec3 t1 = min(tMin, tMax);
    vec3 t2 = max(tMin, tMax);
    return vec2(max(max(t1.x, t1.y), t1.z),
                min(min(t2.x, t2.y), t2.z));
}

void main() {
    vec3 fragWorldPos = vec3(model * vec4(localPos, 1.0));
    vec3 rayDirWorld  = normalize(fragWorldPos - viewPos);

    // Use precomputed inverseModel instead of per-fragment inverse()
    vec3 rayOriginLocal = (inverseModel * vec4(viewPos,       1.0)).xyz;
    vec3 rayDirLocal    = normalize((inverseModel * vec4(rayDirWorld, 0.0)).xyz);

    vec2 t = intersectBox(rayOriginLocal, rayDirLocal);
    if (t.x >= t.y) discard;

    float tNear    = max(0.0, t.x);
    float stepSize = (t.y - tNear) / 16.0;

    vec4  acc        = vec4(0.0);
    float timeOffset = time * 0.1;

    for (int i = 0; i < 16; ++i) {
        vec3  sp   = rayOriginLocal + rayDirLocal * (tNear + float(i) * stepSize);
        float n    = texture(noiseTexture, sp * noiseScale + vec3(0.0, 0.0, timeOffset)).r;
        float tr   = exp(-density * n * stepSize);
        acc.rgb   += fogColor * (1.0 - tr) * (1.0 - acc.a);
        acc.a     += (1.0 - tr);
        if (acc.a > 0.99) break;
    }

    FragColor = vec4(acc.rgb, clamp(acc.a, 0.0, 1.0));
}