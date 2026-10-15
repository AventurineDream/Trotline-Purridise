in vec3 in_pos, in_normal, in_color;
in float in_material;
out vec3 pos, normal, color;
flat out float material;
void main() {
    pos = in_pos;
    normal = in_normal;
    color = in_color;
    material = in_material;
    vec3 p = pos;
    p.y *= mirror;
    gl_Position = project(p);
}
