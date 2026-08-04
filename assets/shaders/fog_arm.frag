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

vec2 intersectBox(vec3 rayOrigin, vec3 rayDir) {
    vec3 tMin = (-0.5 - rayOrigin) / rayDir;
    vec3 tMax = ( 0.5 - rayOrigin) / rayDir;
    vec3 t1 = min(tMin, tMax);
    vec3 t2 = max(tMin, tMax);
    float tNear = max(max(t1.x, t1.y), t1.z);
    float tFar  = min(min(t2.x, t2.y), t2.z);
    return vec2(tNear, tFar);
}

void main() {
    vec3 fragWorldPos   = vec3(model * vec4(localPos, 1.0));
    vec3 rayDirWorld    = normalize(fragWorldPos - viewPos);
    vec3 rayOriginLocal = (inverseModel * vec4(viewPos,       1.0)).xyz;
    vec3 rayDirLocal    = normalize((inverseModel * vec4(rayDirWorld, 0.0)).xyz);
    vec2 t = intersectBox(rayOriginLocal, rayDirLocal);
    float tNear = t.x;
    float tFar  = t.y;
    if (tNear >= tFar) discard;
    tNear = max(0.0, tNear);

    int   num_steps = 16;
    float stepSize  = (tFar - tNear) / float(num_steps);
    vec4  accumulatedColor = vec4(0.0);

    for (int i = 0; i < num_steps; ++i) {
        float currentT   = tNear + float(i) * stepSize;
        vec3  samplePos  = rayOriginLocal + rayDirLocal * currentT;
        vec3  noiseCoord = samplePos * noiseScale + vec3(0.0, 0.0, time * 0.1);
        float noiseValue = texture(noiseTexture, noiseCoord).r;
        float stepDensity   = density * noiseValue;
        float transmittance = exp(-stepDensity * stepSize);
        accumulatedColor.rgb += fogColor * (1.0 - transmittance) * (1.0 - accumulatedColor.a);
        accumulatedColor.a   += (1.0 - transmittance);
        if (accumulatedColor.a > 0.95) break;
    }
    accumulatedColor.a = clamp(accumulatedColor.a, 0.0, 1.0);
    FragColor = accumulatedColor;
}