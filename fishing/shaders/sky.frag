in vec2 uv;
out vec4 frag;
void main() {
    vec3 d = normalize(view_right*(uv.x*2.0-1.0)*tanx
             +view_up*(uv.y*2.0-1.0)*tany+view_forward);
    d.y *= mirror;
    frag = vec4(sky(d),1);
}
