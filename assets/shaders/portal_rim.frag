#version 330 core
out vec4 FragColor;
uniform vec4 rim_color;
void main() {
    FragColor = rim_color;
}