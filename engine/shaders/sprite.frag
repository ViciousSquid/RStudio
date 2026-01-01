#version 330 core

out vec4 FragColor;

in vec2 TexCoord;

uniform sampler2D sprite_texture;

void main()
{
    vec4 texColor = texture(sprite_texture, TexCoord);
    
    // Alpha test - discard fully transparent pixels
    if(texColor.a < 0.1)
        discard;
    
    FragColor = texColor;
}
