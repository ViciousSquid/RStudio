#version 330 core

out vec4 FragColor;

in vec3 FragPos;
in vec3 Normal;      // Must match 'out' in vertex shader
in vec2 TexCoord;
in float WaveHeight; // Must match 'out' in vertex shader

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
uniform float time;

// Water configuration
const vec3 deepColor = vec3(0.0, 0.1, 0.3);      // Dark Blue
const vec3 shallowColor = vec3(0.0, 0.6, 0.8);   // Cyan/Teal
const float shininess = 64.0;
const float specularStrength = 1.5;

void main()
{
    vec3 norm = normalize(Normal);
    vec3 viewDir = normalize(viewPos - FragPos);

    // 1. Ambient based on wave height (tips are lighter)
    float heightFactor = (WaveHeight + 0.2) * 2.5;
    vec3 baseColor = mix(deepColor, shallowColor, clamp(heightFactor, 0.0, 1.0));
    vec3 ambient = 0.2 * baseColor;
    
    vec3 lighting = ambient;

    // 2. Loop through lights
    for(int i = 0; i < active_lights && i < MAX_LIGHTS; i++)
    {
        vec3 lightDir = normalize(lights[i].position - FragPos);
        float distance = length(lights[i].position - FragPos);
        
        // Attenuation
        float attenuation = 1.0;
        if(lights[i].radius > 0.0) {
            attenuation = clamp(1.0 - (distance / lights[i].radius), 0.0, 1.0);
            attenuation *= attenuation;
        }
        
        // Diffuse
        float diff = max(dot(norm, lightDir), 0.0);
        vec3 diffuse = diff * lights[i].color * lights[i].intensity * attenuation;

        // Specular (Blinn-Phong)
        vec3 halfwayDir = normalize(lightDir + viewDir);
        float spec = pow(max(dot(norm, halfwayDir), 0.0), shininess);
        vec3 specular = specularStrength * spec * lights[i].color * lights[i].intensity * attenuation;

        lighting += (diffuse * baseColor) + specular;
    }
    
    // 3. Fresnel Effect
    float fresnel = dot(viewDir, norm);
    fresnel = clamp(1.0 - fresnel, 0.0, 1.0);
    fresnel = pow(fresnel, 3.0);

    vec3 finalColor = lighting + (fresnel * vec3(0.1, 0.3, 0.5));

    // Add sky tint on fresnel (More opaque at glancing angles)
    float alpha = 0.65 + (fresnel * 0.3);
    
    FragColor = vec4(finalColor, alpha);
}