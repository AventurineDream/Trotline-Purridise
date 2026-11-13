// Contact shading disc under one tree (fishing/florafx.py): a quad laid on
// the terrain's tangent plane at the trunk base. Static geometry, no depth
// writes, so it can never move the depth buffer.
in vec2 in_corner;
in vec3 in_base, in_normal;
in float in_radius;
out vec2 local;
out vec3 pos;
void main() {
    vec3 n = normalize(in_normal);
    vec3 t = normalize(cross(n, vec3(0.0, 0.0, 1.0)));
    vec3 b = cross(t, n);
    local = in_corner;
    // Lifted a little off the ground so the 3-6 m terrain cells do not cut it.
    pos = in_base + (t*in_corner.x + b*in_corner.y)*in_radius + n*0.18;
    vec3 p = pos;
    p.y *= mirror;
    gl_Position = project(p);
}
