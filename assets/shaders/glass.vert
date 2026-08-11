#version 330 core
precision highp float;
layout (location = 0) in vec3 aPos;
layout (location = 1) in vec3 aNormal;
layout (location = 2) in vec2 aTexCoords;

out vec3 FragPos;
out mediump vec3 Normal;
out vec2 TexCoords;

uniform mat4 model;
uniform mat4 view;
uniform mat4 projection;
uniform mat3 normalMatrix;

void main() {
    FragPos     = vec3(model * vec4(aPos, 1.0));
    Normal      = normalize(normalMatrix * aNormal);
    TexCoords   = aTexCoords;
    gl_Position = projection * view * vec4(FragPos, 1.0);
}