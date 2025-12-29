#version 330 core

out vec4 FragColor;

in vec3 FragPos;
in vec3 Normal;
in vec2 TexCoord;

struct Light {
    vec3 position;
    vec3 color;
    float intensity;
    float radius;
};

#define MAX_LIGHTS 8

uniform Light lights[MAX_LIGHTS];
uniform int active_lights;
uniform vec3 object_color;
uniform float alpha;

// Fog uniforms
uniform vec3 viewPos;
uniform float time;
uniform sampler3D noiseTexture;
uniform float density;
uniform vec3 fogColor;
uniform float noiseScale;

float sampleFogNoise(vec3 pos)
{
    vec3 samplePos = pos * noiseScale + vec3(time * 0.1, time * 0.05, time * 0.08);
    return texture(noiseTexture, samplePos).r;
}

void main()
{
    vec3 norm = normalize(Normal);
    vec3 ambient = 0.15 * object_color;
    vec3 result = ambient;
    
    // Lighting calculation
    for(int i = 0; i < active_lights && i < MAX_LIGHTS; i++)
    {
        vec3 lightDir = lights[i].position - FragPos;
        float distance = length(lightDir);
        lightDir = normalize(lightDir);
        
        float attenuation = 1.0;
        if(lights[i].radius > 0.0)
        {
            attenuation = clamp(1.0 - (distance / lights[i].radius), 0.0, 1.0);
            attenuation *= attenuation;
        }
        
        float diff = max(dot(norm, lightDir), 0.0);
        vec3 diffuse = diff * lights[i].color * lights[i].intensity * attenuation;
        
        result += diffuse * object_color;
    }
    
    if(active_lights == 0)
    {
        result = object_color * 0.5;
    }
    
    // Fog calculation
    float distanceToCamera = length(viewPos - FragPos);
    
    // Sample noise for volumetric variation
    float noise = sampleFogNoise(FragPos * 0.01);
    float fogDensity = density * (0.7 + 0.6 * noise);
    
    // Exponential fog
    float fogFactor = 1.0 - exp(-distanceToCamera * fogDensity * 0.001);
    fogFactor = clamp(fogFactor, 0.0, 1.0);
    
    // Mix with fog color
    result = mix(result, fogColor, fogFactor);
    
    FragColor = vec4(result, alpha);
}
