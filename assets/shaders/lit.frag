#version 330 core
out vec4 FragColor;
in vec3 FragPos;
in vec3 Normal;
uniform vec3 object_color;
uniform float alpha;
struct Light { vec3 position; vec3 color; float intensity; float radius; };
uniform Light lights[8];
uniform int active_lights;
void main() {
    vec3 norm = normalize(Normal);
    vec3 result = vec3(0.1) * object_color; // Ambient
    for(int i = 0; i < active_lights; i++) {
        float distance = length(lights[i].position - FragPos);
        if(distance < lights[i].radius) {
            vec3 lightDir = normalize(lights[i].position - FragPos);
            float diff = max(dot(norm, lightDir), 0.0);
            float att = 1.0 - smoothstep(0.0, lights[i].radius, distance);
            result += (diff * lights[i].color * lights[i].intensity * att) * object_color;
        }
    }
    FragColor = vec4(result, alpha);
}