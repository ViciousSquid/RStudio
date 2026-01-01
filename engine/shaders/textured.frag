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
uniform sampler2D texture_diffuse;
uniform vec3 object_color;
uniform float alpha;

void main()
{
    vec4 texColor = texture(texture_diffuse, TexCoord);
    vec3 baseColor = texColor.rgb * object_color;
    
    vec3 norm = normalize(Normal);
    vec3 ambient = 0.15 * baseColor;
    vec3 result = ambient;
    
    for(int i = 0; i < active_lights && i < MAX_LIGHTS; i++)
    {
        vec3 lightDir = lights[i].position - FragPos;
        float distance = length(lightDir);
        lightDir = normalize(lightDir);
        
        // Attenuation based on radius
        float attenuation = 1.0;
        if(lights[i].radius > 0.0)
        {
            attenuation = clamp(1.0 - (distance / lights[i].radius), 0.0, 1.0);
            attenuation *= attenuation;
        }
        
        // Diffuse
        float diff = max(dot(norm, lightDir), 0.0);
        vec3 diffuse = diff * lights[i].color * lights[i].intensity * attenuation;
        
        result += diffuse * baseColor;
    }
    
    // If no lights, use basic ambient
    if(active_lights == 0)
    {
        result = baseColor * 0.5;
    }
    
    FragColor = vec4(result, texColor.a * alpha);
}
