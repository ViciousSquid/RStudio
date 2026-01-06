#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out vec2 TexCoords;
out vec3 Normal; // Pass normal to frag for recalculation if needed

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform float time;

// New uniforms for displacement
uniform int useWaveDisplacement;
uniform float waveStrength; // Controls the height/amplitude

void main()
{
    vec3 pos = aPos;
    
    // Sum of Sines Displacement
    if (useWaveDisplacement == 1) {
        float speed = time * 1.5;
        
        // Wave 1 (Large, slow)
        float y = sin(pos.x * 0.5 + speed) * cos(pos.z * 0.5 + speed) * waveStrength;
        
        // Wave 2 (Smaller, diagonal)
        y += sin(pos.x * 1.1 + pos.z * 0.4 + speed * 1.2) * (waveStrength * 0.5);
        
        // Wave 3 (Detail irregularity)
        y += cos(pos.x * 2.1 - speed) * (waveStrength * 0.2);
        
        pos.y += y;
    }
    
    FragPos = vec3(model * vec4(pos, 1.0));
    
    // Scale UVs (4.0) gives good density for the normal map provided
    TexCoords = aTexCoords * 4.0; 
    
    // Recalculate normal based on model rotation
    Normal = mat3(transpose(inverse(model))) * aNormal;
    
    gl_Position = projection * view * vec4(FragPos, 1.0);
}