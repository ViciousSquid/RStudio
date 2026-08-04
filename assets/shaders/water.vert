#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out vec2 TexCoords;
out mediump vec3 Normal;
out mediump float WaveCrest;
out mediump float ShoreDist;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform highp float time;
uniform mat3 normalMatrix;

uniform float waveAmp;    // total wave amplitude in world units
uniform vec3 brushSize;   // world-space brush dimensions

// One Gerstner wave: displaces the vertex and accumulates normal derivatives.
void addWave(vec2 dir, float wavelength, float amp, float speed, vec2 p,
             inout float dy, inout vec2 dxz, inout vec3 n)
{
    float k = 6.2831853 / wavelength;
    float f = k * dot(dir, p) + speed * time;
    float s = sin(f);
    float c = cos(f);
    float steep = min(0.8 / (k * max(amp, 0.0001) * 4.0), 1.2);
    dy  += amp * s;
    dxz += steep * amp * c * dir;
    n.x -= dir.x * k * amp * c;
    n.z -= dir.y * k * amp * c;
    n.y -= steep * k * amp * s * 0.25;
}

void main()
{
    vec3 worldPos = vec3(model * vec4(aPos, 1.0));

    // World-space distance from this vertex to the nearest lateral brush edge.
    // Waves are pinned to zero at the edges so the surface always meets the
    // side faces / pool walls exactly (keeps the volume watertight).
    vec2 edgeLocal = vec2(0.5) - abs(aPos.xz);
    float edgeWorld = min(edgeLocal.x * brushSize.x, edgeLocal.y * brushSize.z);
    float fadeW = clamp(min(brushSize.x, brushSize.z) * 0.25, 4.0, 48.0);
    float edgeFade = smoothstep(0.0, fadeW, edgeWorld);

    float topVert = step(0.49, aPos.y);   // only the top surface deforms
    float amp = waveAmp * edgeFade * topVert;

    float dy = 0.0;
    vec2 dxz = vec2(0.0);
    vec3 n = vec3(0.0, 1.0, 0.0);
    if (amp > 0.001) {
        addWave(vec2( 0.788,  0.616), 190.0, amp * 0.42, 1.05, worldPos.xz, dy, dxz, n);
        addWave(vec2(-0.552,  0.834), 118.0, amp * 0.28, 1.45, worldPos.xz, dy, dxz, n);
        addWave(vec2( 0.943, -0.333),  74.0, amp * 0.19, 1.95, worldPos.xz, dy, dxz, n);
        addWave(vec2(-0.673, -0.740),  38.0, amp * 0.11, 2.70, worldPos.xz, dy, dxz, n);
        worldPos.y  += dy;
        worldPos.xz += dxz * 0.75 * edgeFade;
    }

    vec3 baseNormal = normalize(normalMatrix * aNormal);
    // Only the upward-facing surface takes the wave normal; side walls keep
    // their flat normals even at their top verts (which do get displaced)
    float topFaceVert = topVert * step(0.5, aNormal.y);
    Normal    = normalize(mix(baseNormal, normalize(n), topFaceVert));
    FragPos   = worldPos;
    TexCoords = aTexCoords;
    WaveCrest = clamp(dy / max(waveAmp * 0.85, 0.001) * 0.5 + 0.5, 0.0, 1.0);
    ShoreDist = edgeWorld;

    gl_Position = projection * view * vec4(worldPos, 1.0);
}