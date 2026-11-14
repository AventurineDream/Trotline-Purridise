// Atlas bake (fishing/florafx.py PaintBaker): one instanced quad per recorded
// sprite primitive (fishing/sprites.py Painter), covering its design-space
// box plus a texel of antialiasing margin. Design units are y-down; the
// layer's bottom row is GL row 0, as texture arrays expect.
uniform vec2 base;    // design size (units)
uniform vec2 scale;   // layer texels per design unit
in vec2 in_corner;
in vec4 in_box, in_kind, in_col, in_p0, in_p1, in_p2, in_mat, in_tip;
flat out vec4 v_kind, v_col, v_p0, v_p1, v_p2, v_mat, v_tip;
void main() {
    vec2 pad = 1.5/scale;
    vec2 d = mix(in_box.xy-pad, in_box.zw+pad, in_corner);
    v_kind = in_kind; v_col = in_col; v_p0 = in_p0; v_p1 = in_p1; v_p2 = in_p2;
    v_mat = in_mat; v_tip = in_tip;
    gl_Position = vec4(d.x/base.x*2.0-1.0, 1.0-d.y/base.y*2.0, 0.0, 1.0);
}
