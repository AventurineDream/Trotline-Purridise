"""Land slice effect layer: baked ground, canopy shadows and boat-space light.

`LandFx` is the land slice's `fishing.fx.Fx` layer (texture units 13-15). When
a lake loads it bakes, on the GPU and once:

- `land_groundmap` (unit 13): a two-layer RGBA8 array over the lake's terrain.
  Layer 0 is albedo plus the detail kind (0 vegetation, 1/3 soil or sand,
  2/3 gravel or scree, 1 rock); layer 1 is the shading normal's xz, cavity AO
  and gloss (0-0.8) or, above 0.82, crystal glow. Built from height, slope,
  shore distance and canopy cover with each lake's authored palette.
- `land_shadow` (unit 14): RGBA16F canopy/occluder map from trees, rocks and
  built things: density, density*crown top, density*crown base (metres above
  the ground) and the ground height. Mipmapped, so `land_occlusion` in
  common.glsl can blur shadows with distance and march the terrain for
  ridge and canyon-wall self-shadow.
- `land_detail` (unit 15): a small tiling micro-relief array, one layer per
  detail kind, blended in near the camera and on cliff faces.

Every frame `uniforms()` hands mesh.frag the player's boat frame and a hull
description (walls, bow plate, boxes) for analytic AO and contact shadows.

Constraints: one shader path for every tier, sized from `Detail`; nothing is
allocated per frame; frames depend on state only; the glint phase holds still
under Reduced Motion. CPU bake arrays are dropped as soon as they are
uploaded. The CPU renderer never sees this module.
"""

from __future__ import annotations

import math

import moderngl
import numpy as np

from .boat import HULL_BOW, HULL_INNER_BEAM, HULL_STERN
from .fx import LAND_UNITS, Fx, reduced_motion

GROUND_UNIT, SHADOW_UNIT, DETAIL_UNIT = LAND_UNITS
# The ground map's long edge never exceeds this: past ~0.45 m a texel the
# terrain field (1 m at best) and the near detail map carry the look, and an
# 8192 map would spend ~0.7 GB of the land share on invisible texels.
GROUND_CAP = 6144
# The occluder map is soft by design; finer than ~1 m buys nothing visible.
SHADOW_CAP = 2048
# Height/shore field sampled on the CPU from `World`: finer than the lake's
# own height grid would only interpolate it.
FIELD_TEXELS = {"low": 512, "standard": 768, "high": 1024, "ultra": 1024}
# Edge of each tiling detail layer (one layer covers 6 m of ground).
DETAIL_TEXELS = {"low": 128, "standard": 256, "high": 512, "ultra": 512}
DETAIL_KINDS = 4
MAX_BOXES = 8

TREE_KINDS = {
    # kind: (crown radius / height, crown base / height, density)
    "pine": (0.20, 0.30, 0.80), "oak": (0.30, 0.32, 0.90), "cypress": (0.17, 0.22, 0.85),
    "larch": (0.17, 0.25, 0.65), "spruce": (0.18, 0.18, 0.90), "hemlock": (0.20, 0.20, 0.90),
    "whitebark": (0.22, 0.30, 0.70), "deadpine": (0.10, 0.35, 0.30),
    "birch": (0.14, 0.28, 0.55), "cottonwood": (0.28, 0.30, 0.85), "willow": (0.30, 0.22, 0.60),
}
SOLID_KINDS = {
    # kind: (radius / height, top / height, density); base is the ground
    "rock": (0.70, 0.90, 2.5), "shore_stone": (0.80, 0.80, 2.0), "stump": (0.45, 1.0, 2.0),
    "driftwood": (0.90, 0.35, 1.2), "knee": (0.35, 1.0, 1.0), "spire": (0.22, 1.0, 0.55),
}


# --- GLSL ---------------------------------------------------------------------

_VERT = """#version 330
in vec2 in_xy;
void main() { gl_Position = vec4(in_xy,0.0,1.0); }
"""

# Copies the full-screen triangle into each layer so one draw fills an array.
_GEOM = """#version 330
layout(triangles) in;
layout(triangle_strip, max_vertices=%d) out;
flat out int layer;
void main() {
    for (int l=0; l<%d; l++) {
        for (int i=0; i<3; i++) { gl_Layer = l; layer = l; gl_Position = gl_in[i].gl_Position; EmitVertex(); }
        EndPrimitive();
    }
}
"""

_LIB = """
float h21(vec2 c) {
    uvec2 q = uvec2(ivec2(floor(c)))*uvec2(1597334673u,3812015801u);
    uint h = (q.x^q.y)*1597334673u;
    return float(h^(h>>16))*(1.0/4294967295.0);
}
// Value noise; `per` > 0 wraps the lattice so the result tiles.
float vn(vec2 p, float per) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f*f*(3.0-2.0*f);
    vec2 i1 = i+1.0;
    if (per>0.0) { i = mod(i,per); i1 = mod(i1,per); }
    return mix(mix(h21(i),h21(vec2(i1.x,i.y)),u.x),mix(h21(vec2(i.x,i1.y)),h21(i1),u.x),u.y);
}
float fbm(vec2 p, float per, int oct) {
    float s = 0.0, a = 0.5, w = 0.0;
    for (int k=0; k<6; k++) {
        if (k>=oct) break;
        s += vn(p,per)*a; w += a;
        p = p*2.0+vec2(17.3,9.1); per *= 2.0; a *= 0.5;
    }
    return s/w;
}
// Nearest and second-nearest feature distance and the nearest cell's hash.
vec3 cells(vec2 p, float per) {
    vec2 i = floor(p), f = fract(p);
    float d1 = 9.0, d2 = 9.0, id = 0.0;
    for (int y=-1; y<=1; y++) for (int x=-1; x<=1; x++) {
        vec2 c = i+vec2(x,y);
        vec2 cw = per>0.0 ? mod(c,per) : c;
        vec2 o = vec2(h21(cw),h21(cw+41.7))*0.8+0.1;
        float d = length(vec2(x,y)+o-f);
        if (d<d1) { d2 = d1; d1 = d; id = h21(cw+7.3); } else if (d<d2) d2 = d;
    }
    return vec3(d1,d2,id);
}
"""

# Resolve the CPU occluder sums into the premultiplied canopy map.
_RESOLVE = """#version 330
uniform sampler2D accum;   // sum w, sum w*top, sum w*base
uniform sampler2D field;   // ground height, shore sd, glow
uniform vec2 out_size;
out vec4 frag;
void main() {
    vec2 uv = gl_FragCoord.xy/out_size;
    vec3 a = texture(accum,uv).rgb;
    float d = 1.0-exp(-a.r);
    float k = d/max(a.r,1e-4);
    frag = vec4(d,a.g*k,a.b*k,texture(field,uv).r);
}
"""

_GROUND = """#version 330
uniform sampler2D field;     // r: ground height (m), g: shore sd (m), b: crystal glow pool
uniform sampler2D canopy;    // the resolved land_shadow map
uniform vec4 domain;
uniform vec2 field_size, out_size;
uniform float kind, snow_line, rim_top;
uniform vec4 island;
uniform vec2 lilies;
uniform vec4 drifts[12];
uniform int drift_count;
flat in int layer;
out vec4 frag;
""" + _LIB + """
vec2 uv_of(vec2 xz) { return (xz-domain.xy)/(domain.zw-domain.xy); }
vec4 cubic(float v) {
    vec4 n = vec4(1.0,2.0,3.0,4.0)-v;
    vec4 s = n*n*n;
    float x = s.x, y = s.y-4.0*s.x, z = s.z-4.0*s.y+6.0*s.x;
    return vec4(x,y,z,6.0-x-y-z)*(1.0/6.0);
}
// B-spline field sample: smooth slopes across the coarse field's cells.
vec4 field_at(vec2 xz) {
    vec2 st = uv_of(xz)*field_size-0.5;
    vec2 fxy = fract(st); st -= fxy;
    vec4 xc = cubic(fxy.x), yc = cubic(fxy.y);
    vec4 c = st.xxyy+vec2(-0.5,1.5).xyxy;
    vec4 s = vec4(xc.xz+xc.yw,yc.xz+yc.yw);
    vec4 o = (c+vec4(xc.yw,yc.yw)/s)/field_size.xxyy;
    vec4 s0 = texture(field,o.xz), s1 = texture(field,o.yz), s2 = texture(field,o.xw), s3 = texture(field,o.yw);
    float sx = s.x/(s.x+s.y), sy = s.z/(s.z+s.w);
    return mix(mix(s3,s2,sx),mix(s1,s0,sx),sy);
}
bool briar() { return kind<2.5; }
bool cedar() { return kind>0.5 && kind<1.5; }
bool alpine() { return kind>2.5 && kind<3.5; }
bool crater() { return kind>3.5 && kind<4.5; }
bool nebula() { return kind>4.5; }
float drift_at(vec2 p) {
    float best = 9.0;
    for (int i=0; i<12; i++) {
        if (i>=drift_count) break;
        best = min(best,length((p-drifts[i].xy)/drifts[i].zw));
    }
    return best;
}
const vec2 WIND = vec2(0.8,0.6);   // Nebula dune ripples run across this
// Small relief (m) added to the field for the shading normal. Wavelengths
// stay above ~3.5 m so the standard map resolves them.
float relief(vec2 p, float h, float sd, float slope) {
    float inland = smoothstep(0.5,4.0,sd);
    if (nebula()) {
        float along = dot(p,WIND);
        float warp = fbm(p*0.03,0.0,2)*9.0;
        float rip = sin((along+warp)*1.35);
        rip = rip*rip*rip;   // sharp crests, wide troughs
        return (rip*0.16+fbm(p*0.08,0.0,3)*0.9)*inland*(1.0-smoothstep(0.6,1.2,slope));
    }
    float lumps = fbm(p*0.11,0.0,3)-0.5;
    float r = lumps*0.7*inland;
    if (crater() || alpine()) {
        // Ledges: the wall steps in short flats between steep risers.
        float steep = smoothstep(0.45,1.1,slope);
        float step_h = 5.5+2.5*vn(p*0.01,0.0);
        float ph = h/step_h;
        float stair = (floor(ph)+smoothstep(0.55,1.0,fract(ph)))*step_h-h;
        r += stair*0.35*steep;
        r += (fbm(p*0.07,0.0,3)-0.5)*2.2*steep;
    }
    return r;
}
// Crater strata: weathered ash, basalt and rusted tuff, broken by the cliff face.
vec3 strata(float y, vec2 p) {
    float along = dot(p, vec2(0.6,0.8));
    float warp = (fbm(p*0.012,0.0,3)-0.5)*34.0
               +(fbm(p*0.05,0.0,2)-0.5)*7.0;
    float w = y+warp;
    float band = vn(vec2(w*0.11, along*0.028),0.0);
    float fine = vn(vec2(w*0.42, along*0.065),8.1);
    vec3 c = mix(vec3(.18,.19,.23),vec3(.37,.38,.41),smoothstep(0.25,0.75,band));
    c = mix(c,vec3(.40,.31,.28),smoothstep(0.62,0.80,vn(vec2(w*0.055,along*0.012),1.3))*0.72);
    c = mix(c,vec3(.25,.26,.32),smoothstep(0.7,0.9,fine)*0.48);
    return c*(0.88+0.24*fine);
}
// Flathead cliff bands: pale granite, grey gneiss and dark seams.
vec3 cliffs(float y, vec2 p) {
    float w = y+(fbm(p*0.015,0.0,3)-0.5)*10.0;
    float band = vn(vec2(w*0.12,2.1),0.0), fine = vn(vec2(w*0.7,5.3),0.0);
    vec3 c = mix(vec3(.30,.33,.36),vec3(.50,.52,.52),smoothstep(0.3,0.8,band));
    c = mix(c,vec3(.22,.23,.26),smoothstep(0.75,0.9,fine)*0.7);
    return c*(0.9+0.2*fine);
}
void main() {
    vec2 uv = gl_FragCoord.xy/out_size;
    vec2 p = mix(domain.xy,domain.zw,uv);
    vec2 tm = (domain.zw-domain.xy)/out_size;            // metres per output texel
    vec2 fm = (domain.zw-domain.xy)/field_size;          // metres per field texel
    vec4 f = field_at(p);
    float h = f.r, sd = f.g, pool = f.b;
    vec2 e = max(fm*0.5,tm);
    vec2 grad = vec2(field_at(p+vec2(e.x,0)).r-field_at(p-vec2(e.x,0)).r,
                     field_at(p+vec2(0,e.y)).r-field_at(p-vec2(0,e.y)).r)/(2.0*e);
    float slope = length(grad);
    // Concave ground (gullies, wall foots) collects shade and debris.
    float ring = 0.0;
    for (int k=0; k<6; k++) {
        float a = float(k)*1.0472;
        vec2 d = vec2(cos(a),sin(a));
        ring += texture(field,uv_of(p+d*7.0)).r+texture(field,uv_of(p+d*18.0)).r;
    }
    float cav = ring/12.0-h;
    float cover = textureLod(canopy,uv,1.0).r;
    // Uphill steepness 14 m away: the foot of a cliff gets scree fans.
    vec2 up = slope>1e-3 ? grad/slope : vec2(0.0);
    vec4 fu = texture(field,uv_of(p+up*14.0));
    vec2 gu = vec2(texture(field,uv_of(p+up*14.0+vec2(fm.x,0))).r-fu.r,
                   texture(field,uv_of(p+up*14.0+vec2(0,fm.y))).r-fu.r)/fm;
    float above = smoothstep(0.7,1.3,length(gu));

    float r0 = relief(p,h,sd,slope);
    vec2 dr = vec2(relief(p+vec2(tm.x,0),h,sd,slope)-relief(p-vec2(tm.x,0),h,sd,slope),
                   relief(p+vec2(0,tm.y),h,sd,slope)-relief(p-vec2(0,tm.y),h,sd,slope))/(2.0*tm);
    vec3 n = normalize(vec3(-(grad.x+dr.x),1.0,-(grad.y+dr.y)));

    float n1 = fbm(p*0.021,0.0,4), n2 = fbm(p*0.09,0.0,4), n3 = vn(p*0.45,0.0);
    float steep = smoothstep(0.55,1.15,slope);
    vec3 c;
    float dk = 0.0, gloss = 0.05, glow = 0.0;
    float ao = clamp(1.0-max(cav,0.0)*0.05,0.6,1.0);
    if (briar()) {
        vec3 grass = mix(vec3(.16,.24,.13),vec3(.31,.36,.18),n2);
        // Moss in damp hollows and under crowns, dry seed-heads on the knolls.
        grass = mix(grass,vec3(.13,.21,.10),(1.0-smoothstep(0.25,0.45,n1))*0.7+cover*0.25);
        grass = mix(grass,vec3(.40,.38,.22),smoothstep(0.62,0.8,n2)*(1.0-smoothstep(-1.5,0.0,cav))*0.55);
        vec3 earth = mix(vec3(.38,.31,.21),vec3(.57,.48,.33),n2);
        vec3 litter = mix(vec3(.30,.22,.13),vec3(.40,.29,.16),n3);
        float edge = sd+(n3-0.5)*3.0+(n1-0.5)*4.0;
        c = mix(earth,grass,smoothstep(1.5,7.0,edge));
        dk = mix(1.0/3.0,0.0,smoothstep(1.5,7.0,edge));
        c = mix(c,litter,smoothstep(0.15,0.6,cover)*0.8*smoothstep(3.0,8.0,sd));
        // Dark damp soil lip right at the waterline.
        float lip = 1.0-smoothstep(0.4,1.8+n3,sd);
        c = mix(c,vec3(.24,.18,.12),lip*0.8);
        gloss = mix(gloss,0.22,lip);
        // Gravel bars where the bank shelves out, sandstone riprap at Cedar.
        float bar = smoothstep(0.58,0.68,fbm(p*0.012+3.1,0.0,3))*(1.0-smoothstep(3.0,9.0,sd))*smoothstep(-0.5,0.3,sd);
        if (cedar()) bar = max(bar,(1.0-smoothstep(2.0,6.0,sd+n3*2.0))*0.85);
        vec3 gravel = cedar() ? mix(vec3(.52,.44,.33),vec3(.66,.56,.41),n3) : mix(vec3(.40,.38,.33),vec3(.55,.51,.43),n3);
        c = mix(c,gravel,bar);
        dk = mix(dk,2.0/3.0,bar);
        gloss = mix(gloss,0.12,bar);
        // Exposed bank and outcrop where the ground turns steep.
        vec3 rock = cedar() ? mix(vec3(.50,.42,.32),vec3(.62,.53,.40),n2) : mix(vec3(.36,.34,.30),vec3(.46,.43,.37),n2);
        c = mix(c,rock,steep*0.85);
        dk = mix(dk,1.0,steep);
        c = mix(c,vec3(0.26,0.29,0.25),smoothstep(18.0,62.0,h)*0.6);
    } else if (alpine()) {
        vec3 gravel = mix(vec3(.40,.43,.42),vec3(.57,.58,.53),n3);
        vec3 meadow = mix(vec3(.20,.29,.20),vec3(.30,.36,.22),n2);
        vec3 floor_c = mix(vec3(.21,.18,.12),vec3(.16,.23,.14),n1);   // needles and moss
        float edge = sd+(n3-0.5)*4.0;
        c = mix(gravel,meadow,smoothstep(2.0,16.0,edge));
        dk = mix(2.0/3.0,0.0,smoothstep(2.0,16.0,edge));
        c = mix(c,floor_c,smoothstep(0.1,0.5,cover)*smoothstep(4.0,12.0,sd)*0.85);
        // Thinning alpine turf then bare rock and scree with height.
        float alp = smoothstep(18.0,83.0,h+(n1-0.5)*30.0);
        c = mix(c,mix(vec3(.37,.42,.44),vec3(.45,.47,.46),n2),alp*0.85);
        dk = mix(dk,2.0/3.0,alp);
        float scree = above*(1.0-steep)*smoothstep(0.15,0.45,slope)*smoothstep(20.0,60.0,h);
        float streak = vn(vec2(dot(p,vec2(-up.y,up.x))*0.35,dot(p,up)*0.03),0.0);
        c = mix(c,mix(vec3(.46,.47,.46),vec3(.60,.60,.57),streak),scree*0.9);
        dk = mix(dk,2.0/3.0,scree);
        c = mix(c,cliffs(h,p),steep);
        dk = mix(dk,1.0,steep);
        gloss = mix(gloss,0.14,steep+scree*0.5);
        float snow = smoothstep(snow_line-12.0,snow_line+18.0,h+(n1-0.5)*36.0);
        snow *= 1.0-smoothstep(0.7,1.4,slope)*0.75;
        c = mix(c,vec3(.84,.89,.91)*(0.94+0.08*n3),snow);
        dk = mix(dk,1.0/3.0,snow);
        gloss = mix(gloss,0.45,snow);
    } else if (crater()) {
        float edge = sd+(n3-0.5)*3.0;
        vec3 talus = mix(vec3(.30,.31,.34),vec3(.46,.46,.48),n3);
        vec3 ash = mix(vec3(.30,.31,.33),vec3(.44,.44,.46),n2);
        vec3 alp = mix(vec3(.21,.26,.22),vec3(.29,.32,.27),n2);   // hemlock moss on the ledges
        c = mix(talus,ash,smoothstep(3.0,10.0,edge));
        dk = 2.0/3.0;
        c = mix(c,alp,smoothstep(0.1,0.45,cover+(1.0-smoothstep(0.25,0.6,slope))*smoothstep(25.0,40.0,h)*0.4)*0.8);
        float wall = smoothstep(0.45,1.0,slope);
        c = mix(c,strata(h,p),wall);
        dk = mix(dk,1.0,wall);
        // Rubble fans at the foot of the wall.
        float fan = above*(1.0-wall)*(1.0-smoothstep(30.0,70.0,h));
        c = mix(c,mix(vec3(.34,.33,.35),vec3(.52,.50,.49),n3),fan*0.85);
        dk = mix(dk,2.0/3.0,fan);
        gloss = mix(0.08,0.16,wall);
        c = mix(c,mix(vec3(.30,.33,.30),vec3(.40,.42,.38),n2),smoothstep(rim_top*0.85,rim_top,h)*(1.0-wall));
        float isl = length((p-island.xy)/island.zw);
        if (isl<1.15) {
            // The cinder isle: black scoria, rust flecks, darker towards the vent.
            vec3 cinder = mix(vec3(.045,.055,.08),vec3(.13,.15,.20),n2);
            cinder = mix(cinder,vec3(.20,.10,.08),smoothstep(0.7,0.85,n3)*0.6);
            cinder *= mix(1.0,0.7,1.0-smoothstep(0.0,0.6,isl));
            c = mix(c,cinder,1.0-smoothstep(1.0,1.15,isl));
            dk = mix(dk,2.0/3.0,1.0-smoothstep(1.0,1.15,isl));
            gloss = mix(gloss,0.12,1.0-smoothstep(1.0,1.15,isl));
        }
        if (distance(p,lilies)<110.0 && sd<30.0) c = vec3(.14,.26,.18)*(0.8+n2*.3);
        float lip = 1.0-smoothstep(0.3,1.5,sd);
        c = mix(c,c*0.7,lip);
    } else if (nebula()) {
        vec3 dust = mix(vec3(.26,.22,.36),vec3(.44,.38,.56),n2);
        float edge = sd+(n3-0.5)*3.0;
        c = mix(vec3(.55,.52,.66),dust,smoothstep(1.0,10.0,edge));
        c = mix(c,vec3(.62,.56,.80),smoothstep(30.0,90.0,h));
        dk = 1.0/3.0;
        // Ripple crests catch light; troughs and lee faces fall to violet.
        float along = dot(p,WIND);
        float rip = sin((along+fbm(p*0.03,0.0,2)*9.0)*1.35);
        float inland = smoothstep(0.5,4.0,sd);
        c *= 1.0+rip*0.08*inland;
        float lee = clamp(dot(normalize(grad+1e-5),WIND)*smoothstep(0.05,0.3,slope),0.0,1.0);
        c = mix(c,c*vec3(0.78,0.66,1.0),lee*0.6);
        float drift = drift_at(p);
        if (drift<1.05) c = mix(vec3(.10,.30,.30),vec3(.22,.48,.44),n2), dk = 0.0;
        gloss = 0.28;
        // Crystal beds: soft light pools round the spires plus scattered grit beds.
        float bed = smoothstep(0.78,0.86,fbm(p*0.05+7.7,0.0,3))*inland*(1.0-smoothstep(0.5,1.0,slope));
        glow = max(pool,bed*0.7);
        if (glow>0.02) {
            vec3 hue = mix(vec3(.40,.70,.88),vec3(.66,.48,.92),vn(p*0.04,0.0));
            c = mix(c,hue,smoothstep(0.0,0.6,glow));
            dk = mix(dk,2.0/3.0,glow);
        }
    } else {
        c = mix(vec3(.38,.31,.21),vec3(.31,.36,.18),smoothstep(1.0,9.0,sd));
    }
    // Hollows and relief troughs read darker; crests a touch lighter.
    ao *= clamp(1.0+r0*0.25,0.75,1.1);
    ao = clamp(ao,0.0,1.0);
    if (layer==0) frag = vec4(clamp(c,0.0,1.0),dk);
    else {
        vec2 nxz = clamp(n.xz,-1.0,1.0)*0.5+0.5;
        frag = vec4(nxz,ao,glow>0.02 ? 0.82+0.18*clamp(glow,0.0,1.0) : min(gloss,0.8));
    }
}
"""

# Tiling detail: rg = normal xz tilt, b = shade (mean 0.5), a = grain.
_DETAIL = """#version 330
uniform float size;
flat in int layer;
out vec4 frag;
""" + _LIB + """
float hgt(vec2 p, int k) {
    if (k==0) {   // grass and moss: clumps and blade streaks
        return fbm(p*8.0,8.0,4)*0.6+vn(vec2(p.x*64.0,p.y*16.0),16.0)*0.4;
    }
    if (k==1) {   // soil, sand and dust: fine grain and a few pebbles
        vec3 c = cells(p*24.0,24.0);
        return fbm(p*16.0,16.0,4)*0.6+(1.0-smoothstep(0.0,0.35,c.x))*step(0.8,c.z)*0.5;
    }
    if (k==2) {   // gravel and scree: rounded stones
        vec3 c = cells(p*12.0,12.0);
        return sqrt(max(0.0,1.0-c.x*c.x*1.6))*(0.7+0.3*c.z)*smoothstep(0.0,0.12,c.y-c.x)
               +fbm(p*32.0,32.0,2)*0.15;
    }
    // rock: cracks and fine horizontal bedding (v is height on cliff faces)
    vec3 c = cells(p*vec2(5.0,3.0),5.0);
    float crack = smoothstep(0.0,0.08,c.y-c.x);
    return fbm(p*8.0,8.0,5)*0.7+crack*0.3+sin(p.y*6.2832*12.0+fbm(p*4.0,4.0,2)*5.0)*0.05;
}
void main() {
    vec2 p = gl_FragCoord.xy/size;
    float e = 1.0/size;
    float h0 = hgt(p,layer);
    float hx = hgt(p+vec2(e,0.0),layer)-hgt(p-vec2(e,0.0),layer);
    float hy = hgt(p+vec2(0.0,e),layer)-hgt(p-vec2(0.0,e),layer);
    float k = layer==2 ? 2.2 : layer==3 ? 1.6 : 1.0;
    vec2 tilt = clamp(-vec2(hx,hy)*size*0.012*k,-1.0,1.0);
    float shade = clamp(0.5+(h0-0.5)*(layer==2 ? 0.9 : 0.6),0.0,1.0);
    frag = vec4(tilt*0.5+0.5,shade,h21(floor(p*size)));
}
"""


# --- CPU helpers -------------------------------------------------------------

def _domain(world) -> tuple[float, float, float, float]:
    """World rectangle (x0, z0, x1, z1) in metres the bakes cover: the terrain mesh's extent."""
    if world.placeholder:
        return (-600.0, -500.0, 600.0, 500.0)
    if world.id == "cedar" or world.generated:
        x0, z0, x1, z1 = world.bounds
        return (x0 - 300.0, z0 - 300.0, x1 + 300.0, z1 + 300.0)
    return (-1400.0, -1400.0, 1400.0, 1400.0)


def _grid(domain, long_edge: int) -> tuple[int, int]:
    """Texel width and height for `domain` with `long_edge` texels on its longer side."""
    x0, z0, x1, z1 = domain
    w, h = x1 - x0, z1 - z0
    if w >= h:
        return long_edge, max(4, int(round(long_edge * h / w / 4)) * 4)
    return max(4, int(round(long_edge * w / h / 4)) * 4), long_edge


def _centres(domain, nx: int, nz: int):
    """World x and z of every texel centre, as two (nz, nx) float32 arrays."""
    x0, z0, x1, z1 = domain
    xs = x0 + (np.arange(nx, dtype=np.float32) + 0.5) * np.float32((x1 - x0) / nx)
    zs = z0 + (np.arange(nz, dtype=np.float32) + 0.5) * np.float32((z1 - z0) / nz)
    return np.meshgrid(xs, zs)


def _splat(acc, domain, xs, zs, radii, weights, values):
    """Add soft discs into `acc` (channels, nz, nx).

    Args:
        xs, zs, radii: Disc centres and radii in metres.
        weights: Peak weight of each disc.
        values: (n, channels-1) per-disc values accumulated as weight*value.
    """
    if len(xs) == 0:
        return
    chans, nz, nx = acc.shape
    x0, z0, x1, z1 = domain
    tx = (np.asarray(xs) - x0) / (x1 - x0) * nx
    tz = (np.asarray(zs) - z0) / (z1 - z0) * nz
    rt = np.maximum(np.asarray(radii) / ((x1 - x0) / nx), 0.75)
    reach = np.ceil(rt).astype(np.int32)
    flat = acc.reshape(chans, -1)
    for r in np.unique(reach):
        sel = reach == r
        oz, ox = np.mgrid[-r:r + 1, -r:r + 1]
        cx = np.floor(tx[sel])[:, None] + ox.reshape(-1)[None, :]
        cz = np.floor(tz[sel])[:, None] + oz.reshape(-1)[None, :]
        d2 = ((cx + 0.5 - tx[sel][:, None]) ** 2 + (cz + 0.5 - tz[sel][:, None]) ** 2) / rt[sel][:, None] ** 2
        w = np.clip(1.0 - d2, 0.0, 1.0) ** 0.7 * np.asarray(weights)[sel][:, None]
        ok = (w > 0) & (cx >= 0) & (cx < nx) & (cz >= 0) & (cz < nz)
        idx = (cz * nx + cx)[ok].astype(np.int64)
        wv = w[ok]
        flat[0] += np.bincount(idx, wv, flat.shape[1]).astype(np.float32)
        vals = np.asarray(values)[sel]
        for c in range(1, chans):
            per = np.broadcast_to(vals[:, c - 1][:, None], w.shape)[ok]
            flat[c] += np.bincount(idx, wv * per, flat.shape[1]).astype(np.float32)


def _occluders(world):
    """Disc occluders from the lake's props and built faces.

    Returns:
        (x, z, radius, weight, top, base) arrays; top and base are metres
        above the local ground, `weight` is optical density per disc.
    """
    rows = []
    for prop in world.props:
        if prop.kind in TREE_KINDS:
            rf, bf, dens = TREE_KINDS[prop.kind]
            height = prop.h * 1.35   # the billboard is drawn 1.35x the prop height
            rows.append((prop.x, prop.z, height * rf, dens, height * 0.95, height * bf))
        elif prop.kind in SOLID_KINDS:
            rf, tf, dens = SOLID_KINDS[prop.kind]
            rows.append((prop.x, prop.z, max(prop.h * rf, 0.3), dens, prop.h * tf, 0.0))
    # Built things: sample each camp/dock face so decks, roofs and posts
    # shade what is beneath and beside them.
    built = []
    if world.faces:
        pts = np.stack([np.asarray(f.pts, np.float32)[:4] for f in world.faces])        # (n, 4, 3)
        flat = np.abs(np.array([float(f.normal[1]) for f in world.faces])) > 0.7
        lo, hi = pts.min(1), pts.max(1)
        nus = np.maximum(1, np.ceil(np.maximum(hi[:, 0] - lo[:, 0], hi[:, 2] - lo[:, 2]) / 0.8)).astype(int)
        for nu in np.unique(nus):
            sel = nus == nu
            g = np.linspace(0, 1, nu + 1, dtype=np.float32)
            s, t = (v.reshape(1, -1, 1) for v in np.meshgrid(g, g))
            p = pts[sel]
            q = ((p[:, 0:1] * (1 - s) + p[:, 1:2] * s) * (1 - t)
                 + (p[:, 3:4] * (1 - s) + p[:, 2:3] * s) * t).reshape(-1, 3)
            k = s.size
            top = np.repeat(hi[sel, 1], k)
            base = np.repeat(lo[sel, 1] - np.where(flat[sel], 0.25, 0.0), k)
            built.append(np.column_stack([q[:, 0], q[:, 2], np.full(len(q), 0.6), np.full(len(q), 1.5), top, base]))
    if built:
        arr = np.concatenate(built).astype(np.float32)
        # Faces are in world height; the map stores height above the ground.
        ground = np.asarray(world.sample_height(arr[:, 0], arr[:, 1]), np.float32).reshape(-1)
        arr[:, 4] -= ground
        arr[:, 5] -= ground
        built = arr[arr[:, 4] > 0.05]
    else:
        built = np.zeros((0, 6), np.float32)
    arr = np.concatenate([np.asarray(rows, np.float32).reshape(-1, 6), built])
    return arr[:, 0], arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5]


def _glow_pools(world, domain, nx, nz):
    """Soft 0-1 glow around each Nebula crystal spire, at the field grid."""
    pools = np.zeros((nz, nx), np.float32)
    spires = [p for p in world.props if p.kind == "spire"]
    if not spires:
        return pools
    acc = np.zeros((2, nz, nx), np.float32)
    _splat(acc, domain, [p.x for p in spires], [p.z for p in spires],
           [max(4.0, p.h * 0.6) for p in spires], [1.0] * len(spires), np.zeros((len(spires), 1)))
    return np.clip(acc[0] * 1.2, 0.0, 1.0)


# --- boat description ------------------------------------------------------------

def _boxes_from_faces(faces):
    """Axis-aligned boxes found in a boat's face list (eye frame), largest first.

    Generated and handcrafted meshes emit a box as consecutive faces of one
    colour whose normals run +y[, -y], -z, +z, -x, +x.
    """
    found = []
    i = 0
    axes = [tuple(np.round(np.asarray(f.normal, np.float32), 3)) for f in faces]
    while i < len(faces):
        if axes[i] == (0.0, 1.0, 0.0):
            for pattern in (((0, 1, 0), (0, -1, 0), (0, 0, -1), (0, 0, 1), (-1, 0, 0), (1, 0, 0)),
                            ((0, 1, 0), (0, 0, -1), (0, 0, 1), (-1, 0, 0), (1, 0, 0))):
                group = faces[i:i + len(pattern)]
                if len(group) == len(pattern) and all(axes[i + k] == tuple(float(v) for v in pattern[k])
                                                      for k in range(len(pattern))) \
                        and all(np.allclose(g.color, group[0].color) for g in group):
                    pts = np.concatenate([np.asarray(g.pts, np.float32) for g in group])
                    lo, hi = pts.min(0), pts.max(0)
                    half = (hi - lo) * 0.5
                    if half.max() < 0.8 and half.min() > 0.012 and float(np.prod(half)) > 2e-4:
                        found.append(((lo + hi) * 0.5, half))
                    i += len(pattern) - 1
                    break
        i += 1
    found.sort(key=lambda b: -float(np.prod(b[1])))
    return found


def _hull(state):
    """Hull walls of the player's boat for boat-space AO.

    Returns:
        (land_hull, land_hull_shape, land_hull_flags, ramp): floor y, gunwale
        y, stern z, bow z; mid inner half-width, stern and bow width
        fractions, floor/top width; bow sheer rise, has walls, flat bow plate,
        taper start; stern ramp end. All metres in the eye frame or 0-1
        fractions of the hull length.
    """
    model = state.boat
    bid = state.boat_id
    if bid == "jon":
        return ((-0.96, -0.50, HULL_STERN, HULL_BOW), (HULL_INNER_BEAM, 1.0, 1.0, 1.0),
                (0.0, 1.0, 1.0, 1.0), 0.0)
    length = model.bow - model.stern
    if bid == "rowboat":
        return ((-0.88, -0.44, -1.34, 1.62), (0.64, 0.68, 0.07, 0.68),
                (0.0, 1.0, 0.0, (0.48 + 1.34) / 2.96), (-0.58 + 1.34) / 2.96)
    if bid == "sail":
        return ((-1.00, -0.48, model.stern, model.bow), (model.half_beam, 1.0, 0.02, 1.0),
                (0.0, 1.0, 0.0, (1.25 - model.stern) / length), 0.0)
    if bid == "pontoon":
        return ((-0.92, -0.27, model.stern, model.bow), (model.half_beam - 0.07, 1.0, 1.0, 1.0),
                (0.0, 1.0, 0.0, 1.0), 0.0)
    from .boatfamilies import SPECS, _Hull
    spec = SPECS[bid]
    hull = _Hull(model, spec)
    floor = hull.deck_y()
    if model.family == "pontoon" or bid == "steam_barge":
        return ((floor, floor + 0.66, model.stern, model.bow), (model.half_beam - 0.03, 1.0, 1.0, 1.0),
                (0.0, 1.0, 0.0, 1.0), 0.0)
    top = hull.gunwale(0.5) - 0.03
    walls = 1.0 if top - floor > 0.12 else 0.0
    return ((floor, top, model.stern, model.bow),
            (model.half_beam * 0.93, spec.stern_width, spec.bow_width, 0.86 / 0.93),
            (spec.bow_rise, walls, 1.0 if spec.bow_width > 0.05 else 0.0, 0.4), 0.4)


def _jon_boxes(state):
    """The jon's bench, livewell, bow deck and transom: open shells in its mesh, and the transom
    shades the cockpit when the sun is astern. Then the outboard's cowl and midsection, yawed by
    steer through boatmesh.outboard_boxes like its mesh. The tiller has no box: its arm, knuckle
    and rod are 2 to 6 cm across, too slight to be worth one of the MAX_BOXES slots. Six boxes,
    so the Bot's perch, which _boat appends after at most MAX_BOXES - 1 boxes, still fits."""
    from .boatmesh import outboard_boxes
    cy1 = -0.96 + 0.36 * (1.0 + state.well_tier * 0.12)
    beam = HULL_INNER_BEAM
    boxes = [
        ((0.0, -0.768, 1.77), (beam - 0.035, 0.032, 0.07)),
        ((-0.31, (-0.96 + cy1) * 0.5, 2.06), (0.17, (cy1 + 0.96) * 0.5, 0.14)),
        ((0.0, -0.54, 2.63), (beam, 0.04, 0.23)),
        ((0.0, -0.73, HULL_STERN - 0.01), (beam, 0.23, 0.01)),
    ]
    return [(np.asarray(c, np.float32), np.asarray(h, np.float32)) for c, h in boxes] + outboard_boxes(state.steer)


# --- the layer ---------------------------------------------------------------------

class LandFx(Fx):
    """Baked ground, canopy shadows and boat-space lighting for one lake.

    Args:
        renderer: The owning `LakeRenderer`.
        detail: The `Detail` tier; sizes the ground map (`terrain_texels`,
            capped at GROUND_CAP), the canopy map (`shadow_texels`, capped at
            SHADOW_CAP) and the detail array.

    Side effects:
        Bakes three textures on the GPU at construction (owned by the
        renderer, released with the lake); `bake_seconds` records how long.
    """

    def __init__(self, renderer, detail):
        super().__init__(renderer, detail)
        import time
        t0 = time.perf_counter()
        ctx = renderer.ctx
        world = renderer.world
        self.domain = _domain(world)
        self._boat_key = None
        self._boat_values = {}
        temps = []
        # Seconds per bake step, for the load-time report.
        self.bake_steps = {}

        def step(name, start):
            ctx.finish()
            now = time.perf_counter()
            self.bake_steps[name] = round(now - start, 3)
            return now

        try:
            t = t0
            field, fsize = self._field(ctx, world, temps)
            t = step("field", t)
            self.shadow = self._bake_shadow(ctx, world, field, temps)
            t = step("shadow", t)
            self.ground = self._bake_ground(ctx, world, field, fsize, temps)
            t = step("ground", t)
            self.detail_tex = self._bake_detail(ctx, temps)
            step("detail", t)
        finally:
            # Never leave a bake framebuffer bound once it is released.
            renderer.scene_fb.use()
            for obj in reversed(temps):
                obj.release()
        ctx.finish()
        self.bake_seconds = time.perf_counter() - t0

    # Bakes ---------------------------------------------------------------------

    def _quad(self, ctx, program, temps):
        buf = ctx.buffer(np.array([[-1, -1], [3, -1], [-1, 3]], np.float32).tobytes())
        temps.append(buf)
        vao = ctx.vertex_array(program, [(buf, "2f", "in_xy")])
        temps.append(vao)
        return vao

    def _field(self, ctx, world, temps):
        """Ground height, shore distance and crystal glow on a coarse grid, as an RGB32F texture."""
        nx, nz = _grid(self.domain, FIELD_TEXELS.get(self.detail.name, 768))
        x, z = _centres(self.domain, nx, nz)
        data = np.empty((nz, nx, 3), np.float32)
        data[..., 0] = world.sample_height(x, z)
        data[..., 1] = world.shore_sd(x, z)
        data[..., 2] = _glow_pools(world, self.domain, nx, nz)
        tex = ctx.texture((nx, nz), 3, data.tobytes(), dtype="f4")
        tex.filter = (moderngl.LINEAR, moderngl.LINEAR)
        tex.repeat_x = tex.repeat_y = False
        temps.append(tex)
        return tex, (nx, nz)

    def _bake_shadow(self, ctx, world, field, temps):
        """The canopy/occluder map: CPU disc splats resolved on the GPU, then mipmapped."""
        sw, sh = _grid(self.domain, min(self.detail.shadow_texels, SHADOW_CAP))
        x, z, radius, weight, top, base = _occluders(world)
        acc = np.zeros((3, sh, sw), np.float32)
        _splat(acc, self.domain, x, z, radius, weight, np.stack([top, base], 1) if len(x) else np.zeros((0, 2)))
        accum = ctx.texture((sw, sh), 3, np.ascontiguousarray(acc.transpose(1, 2, 0)).tobytes(), dtype="f4")
        del acc
        accum.filter = (moderngl.NEAREST, moderngl.NEAREST)
        temps.append(accum)
        shadow = self.renderer.own(ctx.texture((sw, sh), 4, dtype="f2"))
        fb = ctx.framebuffer([shadow])
        temps.append(fb)
        prog = ctx.program(vertex_shader=_VERT, fragment_shader=_RESOLVE)
        temps.append(prog)
        accum.use(0)
        field.use(1)
        prog["accum"] = 0
        prog["field"] = 1
        prog["out_size"] = (float(sw), float(sh))
        fb.use()
        ctx.viewport = (0, 0, sw, sh)
        ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND)
        self._quad(ctx, prog, temps).render()
        shadow.build_mipmaps()
        shadow.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        shadow.repeat_x = shadow.repeat_y = False
        self.shadow_size = (sw, sh)
        return shadow

    def _bake_ground(self, ctx, world, field, fsize, temps):
        """Albedo/kind and normal/AO/gloss layers, rendered in one layered pass."""
        gw, gh = _grid(self.domain, min(self.detail.terrain_texels, GROUND_CAP))
        ground = self.renderer.own(ctx.texture_array((gw, gh, 2), 4))
        fb = ctx.framebuffer([ground])
        temps.append(fb)
        prog = ctx.program(vertex_shader=_VERT, geometry_shader=_GEOM % (6, 2), fragment_shader=_GROUND)
        temps.append(prog)
        env = world.environment or {}
        kind = (5.0 if world.nebula else 4.0 if world.caldera else 3.0 if world.generated
                else (2.0 if world.placeholder else float(world.id == "cedar")))
        island = (env.get("islands") or [(0, 0, 1, 1, 0)])[0]
        lilies = next((tuple(row[1:3]) for row in world.zones if row[0] == "lilies"), (-175.0, -115.0))
        drifts = np.zeros((12, 4), np.float32)
        rows = list(env.get("drifts", ()))[:12]
        for i, row in enumerate(rows):
            drifts[i] = row[:4]
        values = {"field": 1, "canopy": 2, "domain": self.domain, "field_size": tuple(map(float, fsize)),
                  "out_size": (float(gw), float(gh)), "kind": kind,
                  "snow_line": float(env.get("snow_line", 95)),
                  "rim_top": float((env.get("rim") or (125, 62))[0]),
                  "island": tuple(float(v) for v in island[:4]), "lilies": tuple(map(float, lilies)),
                  "drift_count": len(rows)}
        for key, value in values.items():
            if key in prog:
                prog[key].value = value
        if "drifts" in prog:
            prog["drifts"].write(drifts.tobytes())
        field.use(1)
        self.shadow.use(2)
        fb.use()
        ctx.viewport = (0, 0, gw, gh)
        self._quad(ctx, prog, temps).render()
        ground.build_mipmaps()
        ground.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        ground.repeat_x = ground.repeat_y = False
        ground.anisotropy = 1.0 if self.renderer.software_gl else 4.0
        self.ground_size = (gw, gh)
        return ground

    def _bake_detail(self, ctx, temps):
        """The tiling micro-relief array, one layer per detail kind."""
        size = DETAIL_TEXELS.get(self.detail.name, 256)
        tex = self.renderer.own(ctx.texture_array((size, size, DETAIL_KINDS), 4))
        fb = ctx.framebuffer([tex])
        temps.append(fb)
        prog = ctx.program(vertex_shader=_VERT, geometry_shader=_GEOM % (3 * DETAIL_KINDS, DETAIL_KINDS),
                           fragment_shader=_DETAIL)
        temps.append(prog)
        prog["size"] = float(size)
        fb.use()
        ctx.viewport = (0, 0, size, size)
        self._quad(ctx, prog, temps).render()
        tex.build_mipmaps()
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.repeat_x = tex.repeat_y = True
        tex.anisotropy = 1.0 if self.renderer.software_gl else 4.0
        self.detail_size = size
        return tex

    # Per frame -----------------------------------------------------------------

    def bind(self) -> None:
        """Bind the ground, canopy and detail maps to units 13, 14 and 15."""
        self.ground.use(GROUND_UNIT)
        self.shadow.use(SHADOW_UNIT)
        self.detail_tex.use(DETAIL_UNIT)

    def _boat(self, state):
        """Hull and occluder-box uniforms for the player's boat, rebuilt when the boat changes.

        The jon's outboard yaws with steer, so its key holds steer in 1/32 steps: the boxes
        follow the motor without rebuilding on every tiny tiller twitch."""
        key = (state.boat_id, state.well_tier, bool(state.light), bool(state.rowboat_trolling_motor),
               bool(state.sail_raised), state.bot_phase == "home",
               round(state.steer * 32) if state.boat_id == "jon" else 0)
        if key == self._boat_key:
            return self._boat_values
        hull, shape, flags, ramp = _hull(state)
        if state.boat_id == "jon":
            boxes = _jon_boxes(state)
        else:
            boxes = _boxes_from_faces(self.renderer._boat_faces(state))
        if state.bot_phase == "home":
            # Bot's body casts a small contact shadow where it perches.
            from .bot import _PERCH
            if state.boat.handcrafted:
                px, py, pz = _PERCH[state.boat_id]
            else:
                from .boatfamilies import perch
                px, py, pz = perch(state.boat)
            boxes = boxes[:MAX_BOXES - 1] + [(np.array([px, py + 0.15, pz], np.float32),
                                              np.array([0.10, 0.15, 0.09], np.float32))]
        boxes = boxes[:MAX_BOXES]
        packed = np.zeros((2 * MAX_BOXES, 4), np.float32)
        for i, (c, h) in enumerate(boxes):
            packed[2 * i, :3] = c
            packed[2 * i + 1, :3] = h
        self._boat_values = dict(land_hull=tuple(map(float, hull)), land_hull_shape=tuple(map(float, shape)),
                                 land_hull_flags=tuple(map(float, flags)), land_hull_ramp=float(ramp),
                                 land_boxes=packed.tobytes(), land_box_count=len(boxes))
        self._boat_key = key
        return self._boat_values

    def uniforms(self, state, light, cam) -> dict:
        """Sampler units, the baked domain, the boat frame and hull, and the glint phase."""
        boat_cam = cam.boat_frame()
        values = dict(land_groundmap=GROUND_UNIT, land_shadow=SHADOW_UNIT, land_detail=DETAIL_UNIT,
                      land_domain=tuple(map(float, self.domain)),
                      land_boat_o=tuple(map(float, boat_cam.eye)),
                      land_boat_x=tuple(map(float, boat_cam.right)),
                      land_boat_z=tuple(map(float, boat_cam.forward)),
                      land_anim=0.0 if reduced_motion(state) else float(state.anim) % 1000.0)
        values.update(self._boat(state))
        return values

    def memory_bytes(self) -> int:
        """GPU bytes of the three baked maps, mipmaps included (x4/3)."""
        gw, gh = self.ground_size
        sw, sh = self.shadow_size
        d = self.detail_size
        return int((gw * gh * 4 * 2 + sw * sh * 8 + d * d * 4 * DETAIL_KINDS) * 4 / 3)
