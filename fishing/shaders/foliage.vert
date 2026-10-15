in vec2 in_corner;
in vec3 in_pos;
in vec2 in_size;
in float in_layer, in_shade;
out vec2 uv;
out vec3 pos;
flat out float layer, shade;
void main() {
    uv = vec2(in_corner.x+0.5,in_corner.y);
    // Cylindrical billboards: bases and trunks stay fixed as the boat moves.
    vec3 right = normalize(vec3(view_right.x,0,view_right.z));
    pos = in_pos+right*in_corner.x*in_size.x+vec3(0,in_corner.y*in_size.y,0);
    layer = in_layer;
    shade = in_shade;
    vec3 p = pos;
    p.y *= mirror;
    gl_Position = project(p);
}
