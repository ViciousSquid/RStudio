#version 330 core
out vec4 FragColor;

in vec3 FragPos;
in vec2 TexCoords;
in vec3 Normal;

struct Light {
    vec3 position;
    vec3 color;
    float intensity;
    float radius;
};

#define MAX_LIGHTS 8
uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform vec3 viewPos;
uniform sampler2D normalMap; 
uniform float time;

uniform float waterOpacity;
uniform float waterReflectivity;
uniform vec3 waterTint;

void main()
{
    // 1. Animated Normal Mapping (Counter-scrolling layers)
    vec2 speed = vec2(0.04, 0.02);
    
    vec2 coord1 = TexCoords + time * speed;
    vec3 n1 = texture(normalMap, coord1).rgb;
    
    vec2 coord2 = (TexCoords * 0.7) - (time * vec2(speed.y, speed.x));
    vec3 n2 = texture(normalMap, coord2).rgb;
    
    vec3 norm = normalize((n1 + n2) - 1.0);

    // 2. Base Color & Environment
    vec3 viewDir = normalize(viewPos - FragPos);
    
    float R0 = 0.02; 
    float fresnel = R0 + (1.0 - R0) * pow(1.0 - max(dot(viewDir, vec3(0.0, 1.0, 0.0)), 0.0), 5.0);
    fresnel = clamp(fresnel * waterReflectivity * 2.5, 0.0, 1.0);

    // 3. Lighting (Blinn-Phong)
    vec3 lightAccumulation = vec3(0.0);
    vec3 specularAccum = vec3(0.0);
    float shininess = 128.0; 

    for(int i = 0; i < active_lights; i++) {
        float distance = length(lights[i].position - FragPos);
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
}