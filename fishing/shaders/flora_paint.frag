// Atlas bake: rasterise one sprite primitive (blob, limb, drape, blade,
// facet; fishing/sprites.py Painter documents each). Every primitive is a
// rounded volume: gl_FragDepth carries its height so the depth test keeps the
// highest surface per texel, independent of call order. Pass 0 writes colour,
// normal and height of that winner; pass 1 (depth test off, MAX blend) writes
// coverage, the union of every primitive's antialiased footprint.
uniform vec2 base, scale;
uniform vec2 grain_seed;   // per-sprite grain offset so sprites differ
uniform int cov_pass;
flat in vec4 v_kind, v_col, v_p0, v_p1, v_p2, v_mat, v_tip;
layout(location = 0) out vec4 o_col;   // rgb, leafy   (pass 1: coverage)
layout(location = 1) out vec4 o_nrm;   // normal xyz (unnormalised), glow
layout(location = 2) out vec4 o_z;     // height

float h21(vec2 c) {
    uvec2 q = uvec2(ivec2(c)+ivec2(65536));
    uint h = q.x*1597334677u ^ q.y*3812015801u;
    h ^= h >> 16; h *= 0x7feb352du; h ^= h >> 15; h *= 0x846ca68bu; h ^= h >> 16;
    return float(h)*(2.0/4294967295.0)-1.0;
}
float vnoise(vec2 p) {
    vec2 i = floor(p), f = p-i;
    vec2 u = f*f*(3.0-2.0*f);
    return mix(mix(h21(i), h21(i+vec2(1,0)), u.x), mix(h21(i+vec2(0,1)), h21(i+vec2(1,1)), u.x), u.y);
}
// Octaves per grain kind as (cell x, cell y, weight) in design units:
// leaf, needle, fine, bark, stone (sprites.GRAINS order).
const vec3 OCT[15] = vec3[15](
    vec3(2.6,2.4,0.50), vec3(1.25,1.2,0.30), vec3(5.5,5.0,0.20),
    vec3(2.2,1.0,0.50), vec3(1.0,0.6,0.30), vec3(5.0,2.6,0.20),
    vec3(1.4,1.3,0.55), vec3(0.7,0.7,0.30), vec3(3.2,3.0,0.15),
    vec3(0.9,4.5,0.55), vec3(0.5,2.0,0.25), vec3(3.0,9.0,0.20),
    vec3(6.0,5.0,0.50), vec3(2.5,2.2,0.30), vec3(1.0,1.0,0.20));
float grain(int kind, vec2 q) {
    float s = 0.0;
    for (int k = 0; k < 3; k++) {
        vec3 o = OCT[kind*3+k];
        // Never finer than a texel: sub-texel grain would only alias.
        vec2 cell = max(o.xy, 1.0/scale);
        s += o.z*vnoise(q/cell+grain_seed+vec2(float(k)*17.3+float(kind)*31.7, float(k)*5.1));
    }
    return clamp(s*1.2, -1.0, 1.0);
}
// Grain and its gradient per design unit (central difference, one texel).
vec3 grain3(int kind, vec2 q) {
    vec2 e = 0.5/scale;
    return vec3(grain(kind, q),
                (grain(kind, q+vec2(e.x,0))-grain(kind, q-vec2(e.x,0)))/(2.0*e.x),
                (grain(kind, q+vec2(0,e.y))-grain(kind, q-vec2(0,e.y)))/(2.0*e.y));
}

void main() {
    vec2 q = vec2(gl_FragCoord.x, base.y*scale.y-gl_FragCoord.y)/scale;  // design, y down
    int kind = int(v_kind.x+0.5), gk = int(v_kind.y+0.5);
    float z = v_kind.z, leafy = v_kind.w;
    vec3 rgb = v_col.rgb;
    float cov = 0.0, zz = z;
    vec3 n = vec3(0.0, 0.0, 1.0);
    vec3 col = rgb;
    if (kind == 0) {            // blob
        vec2 c = v_p0.xy, r2 = v_p0.zw;
        float rough = v_mat.x, dome = v_mat.y, speck = v_mat.z, bump = v_mat.w;
        vec3 g = grain3(gk, q);
        vec2 d = (q-c)/r2;
        float r = length(d);
        float edge = 1.0+rough*g.x;
        cov = clamp((edge-r)*min(r2.x*scale.x, r2.y*scale.y)+0.5, 0.0, 1.0);
        float qq = clamp(r/edge, 0.0, 1.0);
        float h = sqrt(1.0-qq*qq);
        float rad = min(r2.x, r2.y);
        zz = z+h*rad*dome+g.x*rad*0.2;
        float inv = 1.0/max(edge, 0.3);
        n = vec3(d.x*inv-g.y*bump*rad*0.15, -d.y*inv+g.z*bump*rad*0.15, h*dome+0.15);
        col = rgb*(1.0+speck*g.x);
    } else if (kind == 1) {     // limb
        vec2 a = v_p0.xy, e = v_p0.zw-v_p0.xy;
        float t = clamp(dot(q-a, e)/max(dot(e, e), 1e-6), 0.0, 1.0);
        vec2 p = q-a-t*e;
        float d = length(p);
        float r = mix(v_p1.x, v_p1.y, t);
        cov = clamp((r-d)*min(scale.x, scale.y)+0.5, 0.0, 1.0);
        float qq = clamp(d/max(r, 1e-3), 0.0, 1.0);
        float h = sqrt(1.0-qq*qq);
        zz = z+h*r;
        float inv = 1.0/max(r, 1e-3);
        n = vec3(p.x*inv, -p.y*inv, h+0.05);
        col = rgb*(1.0+v_mat.z*grain(gk, q));
    } else if (kind == 2) {     // drape
        float x0 = v_p0.x, x1 = v_p0.y, ytop = v_p0.z, len = v_p0.w;
        float density = v_p1.x, period = v_p1.y, sway = v_p1.z;
        float g = grain(gk, q);
        float colnoise = sin(q.x*1.7+0.3)*0.5+sin(q.x*0.63+1.9)*0.5;
        float u = (q.y-ytop)/len;
        float span = 0.45+0.55*(0.5+0.5*colnoise);
        float across = 0.5+0.5*sin((q.x+sway*u*u*6.0+g*0.9)*(6.2831853/period));
        float width = density*(1.0-0.6*clamp(u/span, 0.0, 1.0));
        // Antialiased across the strand; tips and ends cut over one texel.
        float aa = max(fwidth(across), 1e-4);
        cov = clamp((across-(1.0-width))/aa+0.5, 0.0, 1.0)
            * clamp((span-u)*len*scale.y+0.5, 0.0, 1.0) * step(0.0, u)
            * step(x0, q.x)*step(q.x, x1);
        zz = z+(1.0-u)*0.5;
        n = vec3((across-0.5)*0.8, -0.15, 1.0);
        col = rgb*(1.0+0.18*g-0.25*u);
    } else if (kind == 3) {     // blade
        vec2 b = v_p0.xy, tip = v_p0.zw;
        float width = v_p1.x, bend = v_p1.y;
        float t = (q.y-b.y)/(tip.y-b.y);
        float valid = step(0.0, t)*step(t, 1.0);
        float tc = clamp(t, 0.0, 1.0);
        float xc = b.x+(tip.x-b.x)*t+bend*t*t;
        float half_w = width*(1.0-0.85*tc)+0.05;
        float across = (q.x-xc)/half_w;
        cov = clamp((1.0-abs(across))*half_w*scale.x+0.5, 0.0, 1.0)*valid;
        float h = sqrt(clamp(1.0-across*across, 0.0, 1.0));
        zz = z+h*half_w+t*0.5;
        float g = grain(gk, q);
        col = mix(rgb, v_tip.rgb, tc)*(1.0+0.08*g);
        n = vec3(clamp(across, -1.0, 1.0), 0.15-0.3*t, h+0.1);
    } else {                    // facet
        vec2 A = v_p0.xy, B = v_p0.zw, C = v_p1.xy;
        float area = (B.x-A.x)*(C.y-A.y)-(B.y-A.y)*(C.x-A.x);
        if (abs(area) < 1e-6) discard;
        float w0 = ((B.x-q.x)*(C.y-q.y)-(B.y-q.y)*(C.x-q.x))/area;
        float w1 = ((C.x-q.x)*(A.y-q.y)-(C.y-q.y)*(A.x-q.x))/area;
        float m = min(min(w0, w1), 1.0-w0-w1);
        cov = clamp(m*sqrt(abs(area))*min(scale.x, scale.y)*0.9+0.5, 0.0, 1.0);
        zz = z+m;
        n = vec3(v_p1.zw, v_p2.x);
    }
    if (cov <= 0.0) discard;
    if (cov_pass == 1) {
        o_col = vec4(cov);
        o_nrm = vec4(0.0);
        o_z = vec4(0.0);
        gl_FragDepth = 0.5;
        return;
    }
    o_col = vec4(col, leafy);
    o_nrm = vec4(n, v_col.a);
    o_z = vec4(zz, 0.0, 0.0, 1.0);
    // Higher surfaces are nearer: depth falls as height rises.
    gl_FragDepth = clamp(0.5-zz/4096.0, 0.0, 1.0);
}
