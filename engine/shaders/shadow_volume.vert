#version 330 core

layout(location = 0) in vec3 aPos;

uniform mat4 projection;
uniform mat4 view;
uniform mat4 model;
uniform vec3 light_pos;

void main()
{
    vec4 worldPos = model * vec4(aPos, 1.0);
    
    // Extrude away from light for shadow volume
    vec3 lightDir = normalize(worldPos.xyz - light_pos);
    
    // Check if this vertex should be extruded (w component trick)
    // In a real implementation, you'd pass this as vertex attribute
    // For now, just pass through
    gl_Position = projection * view * worldPos;
}
