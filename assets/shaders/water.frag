#version 330 core
precision mediump float;
out vec4 FragColor;

in highp vec3 FragPos;
in highp vec2 TexCoords;
in vec3 Normal;
in float WaveCrest;
in float ShoreDist;

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

const vec3 SUN_DIR   = vec3(0.4767, 0.6555, 0.5859);  // pre-normalized
const vec3 SUN_COLOR = vec3(1.00, 0.95, 0.82);

highp float hash21(highp vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
highp float vnoise(highp vec2 p) {
    highp vec2 i = floor(p);
    highp vec2 f = fract(p);
    highp vec2 u = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}

// Procedural sky used for reflections: horizon haze -> blue zenith + sun.
vec3 skyColor(vec3 dir) {
    float h = clamp(dir.y, 0.0, 1.0);
    vec3 sky = mix(vec3(0.66, 0.76, 0.83), vec3(0.19, 0.38, 0.66), pow(h, 0.55));
    float sunAmount = max(dot(dir, SUN_DIR), 0.0);
    sky += SUN_COLOR * (pow(sunAmount, 350.0) * 3.0 + pow(sunAmount, 24.0) * 0.18);
    return sky;
}

void main()
{
    highp vec3 toView = viewPos - FragPos;
    highp float viewDist = length(toView);
    vec3 viewDir = toView / max(viewDist, 0.0001);

    vec3 geoN = normalize(Normal);
    bool backside = dot(geoN, viewDir) < 0.0;   // camera inside the volume
    if (backside) geoN = -geoN;

    // Horizontal surface vs. vertical side wall (side normals have y ~= 0)
    float topFace = step(0.35, abs(geoN.y));

    // ---- Detail ripples: three scrolling normal-map layers projected in
    //      world space, so ripple scale is constant regardless of brush size.
    //      Side walls project onto their own plane or the pattern collapses
    //      into 1D streaks. ----
    highp vec2 wuv;
    if (topFace > 0.5) {
        wuv = FragPos.xz;
    } else if (abs(geoN.x) > abs(geoN.z)) {
        wuv = vec2(FragPos.z, FragPos.y - time * 6.0);   // slow downward drift
    } else {
        wuv = vec2(FragPos.x, FragPos.y - time * 6.0);
    }
    vec2 r1 = texture(normalMap, wuv * 0.0110 + time * vec2( 0.021,  0.014)).xy - 0.5;
    vec2 r2 = texture(normalMap, wuv * 0.0047 + time * vec2(-0.011,  0.008)).xy - 0.5;
    vec2 r3 = texture(normalMap, wuv * 0.0310 + time * vec2( 0.016, -0.029)).xy - 0.5;
    vec2 ripple = r1 + r2 * 0.65 + r3 * 0.35;

    // Fade fine detail with distance to stop specular aliasing shimmer
    float detailFade = 1.0 / (1.0 + viewDist * 0.0009);
    float rippleStrength = (0.34 + WaveCrest * 0.18) * detailFade;

    // Perturb tangentially to the face so ripples work on walls too
    vec3 N;
    if (topFace > 0.5) {
        N = normalize(vec3(geoN.x + ripple.x * rippleStrength,
                           geoN.y,
                           geoN.z + ripple.y * rippleStrength));
    } else {
        vec3 up = vec3(0.0, 1.0, 0.0);
        vec3 tangent = normalize(cross(up, geoN));
        N = normalize(geoN + (tangent * ripple.x + up * ripple.y) * rippleStrength * 0.6);
    }

    // ---- Fresnel (Schlick, R0 of water = 0.02) with the real normal ----
    float NdV = max(dot(N, viewDir), 0.0);
    float fresnel = 0.02 + 0.98 * pow(1.0 - NdV, 5.0);
    fresnel = clamp(fresnel * clamp(waterReflectivity * 2.0, 0.0, 1.6), 0.0, 1.0);

    // ---- Sky reflection ----
    vec3 R = reflect(-viewDir, N);
    R.y = abs(R.y);   // reflections that would sample "below horizon" mirror upward
    vec3 reflection = skyColor(R);

    // ---- Water body: deep tint straight down, brighter scatter at angles,
    //      subsurface glow through wave crests ----
    vec3 deepCol    = waterTint * 0.55;
    vec3 shallowCol = waterTint * 1.25 + vec3(0.02, 0.10, 0.09);
    vec3 bodyCol = mix(deepCol, shallowCol, pow(1.0 - NdV, 1.5) * 0.7 + 0.15);

    float sss = pow(WaveCrest, 2.0)
              * pow(max(dot(viewDir, -normalize(vec3(SUN_DIR.x, 0.0, SUN_DIR.z))), 0.0), 2.0);
    bodyCol += (waterTint * 0.8 + vec3(0.05, 0.22, 0.18)) * sss;

    // Constant sun term so water reads correctly even with no point lights
    bodyCol *= (0.45 + 0.55 * max(dot(N, SUN_DIR), 0.0));

    // ---- Dynamic point lights: wide diffuse + tight Blinn specular ----
    vec3 diffuseAcc = vec3(0.0);
    vec3 specAcc = vec3(0.0);
    for (int i = 0; i < active_lights; i++) {
        highp vec3 toL = lights[i].position - FragPos;
        highp float dist = length(toL);
        if (dist < lights[i].radius) {
            vec3 Ldir = toL / dist;
            float att = 1.0 - smoothstep(0.0, lights[i].radius, dist);
            vec3 lc = lights[i].color * lights[i].intensity * att;
            diffuseAcc += max(dot(N, Ldir), 0.0) * lc;
            vec3 Hl = normalize(Ldir + viewDir);
            float ndh = max(dot(N, Hl), 0.0);
            specAcc += (pow(ndh, 240.0) * 1.6 + pow(ndh, 28.0) * 0.15) * lc;
        }
    }
    bodyCol += bodyCol * diffuseAcc * 0.9;

    // ---- Sun glint with sparkle (twinkling micro-facets) ----
    vec3 Hs = normalize(SUN_DIR + viewDir);
    float sunSpec = pow(max(dot(N, Hs), 0.0), 320.0);
    float sparkle = vnoise(wuv * 0.9 + vec2(time * 1.7, -time * 1.3))
                  * vnoise(wuv * 1.7 - vec2(time * 0.9, -time * 1.1));
    sunSpec *= (1.0 + sparkle * 6.0) * detailFade;
    vec3 specular = SUN_COLOR * sunSpec * 2.2 + specAcc;

    // ---- Foam: breaking wave crests + lapping at the shore/walls
    //      (horizontal surface only — walls get none) ----
    float foamNoise = vnoise(wuv * 0.16 + vec2(time * 0.05, -time * 0.04)) * 0.6
                    + vnoise(wuv * 0.45 - vec2(time * 0.07, time * 0.06)) * 0.4;
    float crestFoam = smoothstep(0.68, 0.92, WaveCrest) * smoothstep(0.35, 0.75, foamNoise);
    float shoreWave = 0.5 + 0.5 * sin(ShoreDist * 0.30 - time * 1.8);
    float shoreFoam = (1.0 - smoothstep(2.0, 26.0, ShoreDist))
                    * (0.30 + 0.70 * shoreWave)
                    * smoothstep(0.25, 0.60, foamNoise + 0.15);
    float foam = clamp(crestFoam + shoreFoam, 0.0, 1.0) * topFace;

    // ---- Combine ----
    vec3 color = mix(bodyCol, reflection, fresnel);
    color += specular * (0.35 + 0.65 * waterReflectivity);
    color = mix(color, vec3(0.90, 0.95, 0.96), foam * 0.85);

    // ---- Alpha: more transparent looking straight down, opaque at glancing
    //      angles; foam and glints always read solid ----
    float alpha = clamp(waterOpacity, 0.05, 1.0) * (0.60 + 0.40 * (1.0 - NdV));
    alpha = clamp(alpha + fresnel * 0.35 + foam * 0.45 + sunSpec * 0.4, 0.05, 1.0);

    if (backside) {
        // Seen from underwater: milkier, brighter surface (approx. Snell window)
        color = mix(color, waterTint * 1.4 + vec3(0.10, 0.18, 0.20), 0.35);
        alpha = min(alpha + 0.15, 1.0);
    }

    FragColor = vec4(color, alpha);
}