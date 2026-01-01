#version 330 core

layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec2 aTexCoord;

out vec3 FragPos;
out vec3 Normal;      // Added: Required by frag shader for lighting
out vec2 TexCoord;
out float WaveHeight; // Added: Required by frag shader for color mix

uniform mat4 projection;
uniform mat4 view;
uniform mat4 model;
uniform float time;

void main()
{
    // 1. Calculate WaveHeight purely for color mixing (Fragment Shader)
    // We do NOT add this to the Y position, so the geometry stays flat.
    float wave1 = sin(aPos.x * 4.0 + time * 2.0) * 0.05;
    float wave2 = cos(aPos.z * 2.0 + time * 1.5) * 0.05;
    WaveHeight = wave1 + wave2;

    // 2. Pass world space position
    FragPos = vec3(model * vec4(aPos, 1.0));
    
    // 3. Pass Normal (Transforming normals to world space)
    // Using mat3(model) works if scaling is uniform. 
    // If you use non-uniform scaling, use mat3(transpose(inverse(model)))
    Normal = normalize(mat3(model) * aNormal); 

    TexCoord = aTexCoord;
    
    // 4. Standard projection (Flat Geometry)
    gl_Position = projection * view * vec4(FragPos, 1.0);
}