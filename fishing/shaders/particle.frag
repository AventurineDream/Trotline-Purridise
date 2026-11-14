// Particle shapes (fishing/particlefx.py): glow dots, streaks, leaves, mist
// sheets and soft specks. Output is premultiplied: the lit body is blended
// over the scene and the emission is added on top of it.
uniform sampler2D p_wisp;
uniform int p_prim;
in vec2 v_uv;
in vec4 v_col;
in vec3 v_emit;
in vec3 v_tex;
in vec2 v_world;
flat in int v_shape;
out vec4 frag;
void main() {
    vec2 uv = p_prim == 0 ? gl_PointCoord*2.0-1.0 : v_uv;
    float r2 = dot(uv, uv);
    float body, glow;
    if (v_shape == 0) {
        // Emitter: a bright core inside a soft halo.
        if (r2 > 1.0) discard;
        glow = exp(-r2*9.0)+exp(-r2*3.0)*0.22;
        body = 0.0;
    } else if (v_shape == 1) {
        // Streak: soft across a quad, tapered at both ends.
        body = exp(-uv.x*uv.x*3.0)*(1.0-smoothstep(0.3, 1.0, abs(uv.y)));
        glow = body;
    } else if (v_shape == 2) {
        // Leaf: a pointed oval.
        float w = (1.0-uv.y*uv.y)*0.95;
        if (abs(uv.x) > w) discard;
        body = 1.0-smoothstep(w*0.7, w, abs(uv.x));
        glow = 0.0;
    } else if (v_shape == 3) {
        // Mist sheet: streaky noise in a long soft ellipse, thinning to
        // nothing at the water so the sheet never shows a cut edge.
        float ell = max(0.0, 1.0-(uv.x*uv.x*0.92+uv.y*uv.y));
        float n = texture(p_wisp, v_tex.xy+uv*vec2(0.55, 0.12)).r;
        float m = texture(p_wisp, v_tex.xy*1.7+uv*vec2(1.3, 0.25)+0.37).r;
        float density = smoothstep(0.18, 0.72, n*0.7+m*0.45);
        // Soft against land without a depth read: thin the sheet where it
        // nears a bank, or where land lies between it and the eye (a slope
        // in front would otherwise cut it with a hard edge).
        float open = 1.0-smoothstep(-9.0, -1.0, shore(v_world));
        for (int k = 0; k < 3; k++) {
            vec2 q = mix(eye.xz, v_world, 0.55+0.17*float(k));
            open = min(open, 1.0-smoothstep(-6.0, 2.0, shore(q)));
        }
        body = ell*density*smoothstep(0.0, 0.8, v_tex.z)*open;
        glow = 0.0;
    } else {
        // Matte speck: a soft round dot.
        if (r2 > 1.0) discard;
        body = 1.0-smoothstep(0.1, 1.0, r2);
        glow = body;
    }
    float a = v_col.a*body;
    frag = vec4(v_col.rgb*a+v_emit*glow, a);
}
