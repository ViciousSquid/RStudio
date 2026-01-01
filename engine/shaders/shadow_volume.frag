#version 330 core

out vec4 FragColor;

void main()
{
    // Shadow volumes typically don't write color
    // They only affect the stencil buffer
    FragColor = vec4(0.0, 0.0, 0.0, 0.0);
}
