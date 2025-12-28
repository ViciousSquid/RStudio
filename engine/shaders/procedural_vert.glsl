#version 330 core
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
// Texture coordinates are often at location 2, but procedural shaders might calculate them based on world position. 
// If your mesh provides UVs, you can add: layout (location = 2) in vec2 aTexCoord;

out vec3 FragPos;
out vec3 Normal;
out vec3 ViewPos;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform vec3 viewPos;

void main()
{
    // Transform vertex position to world space
    FragPos = vec3(model * vec4(aPos, 1.0));
    
    // Transform normal vector (using normal matrix to handle non-uniform scaling)
    Normal = mat3(transpose(inverse(model))) * aNormal;
    
    // Pass view position to fragment shader
    ViewPos = viewPos;
    
    // Calculate final vertex position on screen
    gl_Position = projection * view * vec4(FragPos, 1.0);
}