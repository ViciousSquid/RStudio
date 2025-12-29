#version 330 core

layout(location = 0) in vec2 aPos;

out vec2 TexCoord;

uniform mat4 projection;
uniform mat4 view;
uniform vec3 sprite_pos_world;
uniform vec2 sprite_size;

void main()
{
    // Extract camera right and up vectors from view matrix
    vec3 camera_right = vec3(view[0][0], view[1][0], view[2][0]);
    vec3 camera_up = vec3(view[0][1], view[1][1], view[2][1]);
    
    // Billboard the quad to face the camera
    vec3 world_pos = sprite_pos_world
                   + camera_right * aPos.x * sprite_size.x
                   + camera_up * aPos.y * sprite_size.y;
    
    gl_Position = projection * view * vec4(world_pos, 1.0);
    
    // Map vertex position to texture coordinates
    TexCoord = aPos + vec2(0.5, 0.5);
}
