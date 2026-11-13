// Sky bake: renders the lake's cloud tiles and night dome once at lake load
// (fishing/skyfx.py). Compiled with common.glsl prepended so the Lagoon's gas
// reuses the exact hash/noise/fbm its old per-pixel sky used.
//
// bake_mode 0: cloud tile B, seamless: R altocumulus, G cirrus, B fine
//              erosion noise, A cumulus density (read back by mode 1).
// bake_mode 1: cloud tile A, seamless: R cumulus density, G/B its light-march
//              gradient (x, z; 0.5 = none), A the mean density toward every
//              horizontal direction. sky() rebuilds the march toward any light
//              from these: T(u) = A + dot(u, GB-0.5).
// bake_mode 2: night dome (octahedral upper hemisphere) above, moon face in
//              the bottom `moon_rows` rows.
uniform int bake_mode;
uniform uint bake_seed;
uniform sampler2D bake_field;      // mode 1: the tile written by mode 0
uniform vec2 bake_size;            // target texels
uniform float bake_moon_rows;      // mode 2: rows reserved for the moon face
uniform float bake_nebula;         // mode 2: 1 bakes the Lagoon's gas and band
in vec2 uv;
out vec4 frag;
// Measured centre and spread of each raw field (the same for every seed).
const float CUMULUS_MEAN = 0.133, CUMULUS_SIGMA = 0.158;
const float ALTO_MEAN = 0.346, ALTO_SIGMA = 0.179;
const float CIRRUS_MEAN = 0.0, CIRRUS_SIGMA = 0.215;
const float ERO_MEAN = 0.0, ERO_SIGMA = 0.152;
// The light-march gradient is stored at this gain (sky() divides it back).
const float GRADIENT_GAIN = 4.0;
// Dome texels hold light divided by these (sky() multiplies them back):
// the Lagoon's gas can exceed 1, the Milky Way needs fine low steps.
const float NEBULA_SCALE = 2.0, MILKY_SCALE = 0.25;

uvec2 pcg2d(uvec2 v) {
    v = v*1664525u+1013904223u;
    v.x += v.y*1664525u; v.y += v.x*1664525u;
    v ^= v>>16u;
    v.x += v.y*1664525u; v.y += v.x*1664525u;
    v ^= v>>16u;
    return v;
}
// Lattice values wrap at `period` cells, so every octave tiles the unit square.
vec2 lattice(vec2 cell, vec2 period, uint salt) {
    uvec2 c = uvec2(ivec2(mod(cell,period)))+uvec2(bake_seed*7919u+salt,salt*131u);
    return vec2(pcg2d(c))*(1.0/4294967295.0);
}
float gnoise(vec2 p, vec2 period, uint salt) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f*f*f*(f*(f*6.0-15.0)+10.0);
    float a = dot(lattice(i,period,salt)*2.0-1.0,f);
    float b = dot(lattice(i+vec2(1,0),period,salt)*2.0-1.0,f-vec2(1,0));
    float c = dot(lattice(i+vec2(0,1),period,salt)*2.0-1.0,f-vec2(0,1));
    float d = dot(lattice(i+vec2(1,1),period,salt)*2.0-1.0,f-vec2(1,1));
    return mix(mix(a,b,u.x),mix(c,d,u.x),u.y)*1.4;
}
// Seamless fbm in [-1,1]-ish over `octaves`, starting at `period` cells per tile.
float tfbm(vec2 t, float period, int octaves, uint salt) {
    float sum = 0.0, amp = 0.5, norm = 0.0;
    for (int i=0;i<8;i++) {
        if (i>=octaves) break;
        sum += gnoise(t*period,vec2(period),salt+uint(i)*17u)*amp;
        norm += amp;
        period *= 2.0; amp *= 0.5;
    }
    return sum/norm;
}
// Distance to the nearest of one jittered point per cell, wrapping at `period`.
float worley(vec2 t, float period, uint salt) {
    vec2 p = t*period, i = floor(p), f = fract(p);
    float best = 2.0;
    for (int y=-1;y<=1;y++) for (int x=-1;x<=1;x++) {
        vec2 o = vec2(x,y);
        vec2 jitter = lattice(i+o,vec2(period),salt)*0.8+0.1;
        best = min(best,length(o+jitter-f));
    }
    return best;
}

// Raw noise sums cluster near their mean; this logistic stand-in for the
// normal CDF spreads them to roughly uniform [0,1], so sky() can turn a
// coverage fraction straight into a threshold (threshold = 1 - cover).
float uniformize(float x, float mean, float sigma) {
    return 1.0/(1.0+exp(-1.702*(x-mean)/sigma));
}

vec4 tile_b(vec2 t) {
    // Cumulus: cloud-sized masses (about six per tile edge) crowding in broad
    // fields, their rims broken into rounded billows.
    vec2 warp = vec2(tfbm(t,5.0,3,11u),tfbm(t+0.37,5.0,3,23u));
    vec2 tw = t+warp*0.04;
    float mass = tfbm(tw,6.0,4,31u);
    float region = tfbm(t,2.0,2,37u);
    float billow = 1.0-worley(tw,24.0,41u);
    float billow2 = 1.0-worley(tw+warp*0.01,56.0,43u);
    float cumulus = mass+region*0.35+billow*0.16+billow2*0.07;
    // Altocumulus: small soft lumps (48 per tile edge) in wandering patches.
    vec2 aw = vec2(tfbm(t,8.0,2,51u),tfbm(t+0.61,8.0,2,53u));
    float cells = smoothstep(0.05,0.85,1.0-worley(t+aw*0.02,48.0,57u));
    float lumps = tfbm(t,96.0,2,58u);
    float patchy = tfbm(t,4.0,4,59u);
    float alto = cells*0.5+lumps*0.15+patchy*0.9;
    // Cirrus: hair-fine fibres combed along a bending flow, in patches. The
    // warp is periodic, so the combed coordinates still tile.
    vec2 cw = vec2(tfbm(t,3.0,3,61u),tfbm(t+0.5,3.0,3,63u));
    vec2 ct = vec2(t.x+cw.y*0.05,t.y+cw.x*0.16);
    float hair = gnoise(vec2(ct.x*4.0,ct.y*48.0),vec2(4.0,48.0),73u)*0.5
               + gnoise(vec2(ct.x*8.0,ct.y*96.0),vec2(8.0,96.0),79u)*0.3
               + gnoise(vec2(ct.x*16.0,ct.y*192.0),vec2(16.0,192.0),83u)*0.2;
    float patches = tfbm(t+cw*0.05,4.0,4,89u);
    float cirrus = patches*1.3+hair*0.5;
    float erosion = tfbm(t,24.0,4,97u);
    return vec4(uniformize(alto,ALTO_MEAN,ALTO_SIGMA),uniformize(cirrus,CIRRUS_MEAN,CIRRUS_SIGMA),
                uniformize(erosion,ERO_MEAN,ERO_SIGMA),uniformize(cumulus,CUMULUS_MEAN,CUMULUS_SIGMA));
}

vec4 tile_a(vec2 t) {
    float here = texture(bake_field,t).a;
    // March eight horizontal directions through the cumulus; the mean along
    // each is its optical depth toward a light sitting in that direction.
    const int STEPS = 10;
    const float REACH = 0.07;    // tile units: about half a cloud mass
    float m[8];
    for (int k=0;k<8;k++) {
        float a = float(k)*0.78539816;
        vec2 dir = vec2(cos(a),sin(a))*REACH/float(STEPS);
        float s = 0.0;
        for (int i=1;i<=STEPS;i++) s += texture(bake_field,t+dir*float(i)).a;
        m[k] = s/float(STEPS);
    }
    float mean = 0.0;
    for (int k=0;k<8;k++) mean += m[k];
    mean *= 0.125;
    // Least-squares fit of m(angle) = mean + gx*cos + gz*sin over the eight;
    // stored at GRADIENT_GAIN so eight bits keep its subtle slopes.
    float gx = 0.0, gz = 0.0;
    for (int k=0;k<8;k++) {
        float a = float(k)*0.78539816;
        gx += m[k]*cos(a); gz += m[k]*sin(a);
    }
    gx *= 0.25*GRADIENT_GAIN; gz *= 0.25*GRADIENT_GAIN;
    return vec4(here,clamp(0.5+gx,0.0,1.0),clamp(0.5+gz,0.0,1.0),mean);
}

vec3 octa_dir(vec2 t) {
    vec2 q = t*2.0-1.0;
    vec2 p = vec2(q.x+q.y,q.x-q.y)*0.5;
    return normalize(vec3(p.x,1.0-abs(p.x)-abs(p.y),p.y));
}

// The Lagoon's gas and galaxy band: the old per-pixel formula, plus finer
// octaves for filaments. Alpha marks the brightest knots, which sky() lets
// glow above display white.
vec4 nebula_gas(vec3 d) {
    vec2 p = d.xz/(abs(d.y)+0.55)*1.7;
    float fine_a = (noise(p*7.3+4.1)-0.5)*0.16+(noise(p*15.1+1.3)-0.5)*0.08;
    float fine_b = (noise(p*6.7-2.9)-0.5)*0.14+(noise(p*13.9+8.4)-0.5)*0.07;
    float gas_a = fbm(p*0.9+vec2(3.1,1.7))+fine_a;
    float gas_b = fbm(p*1.7-vec2(5.3,2.2))+fine_b;
    vec3 gas = vec3(0.42,0.18,0.62)*smoothstep(0.45,0.85,gas_a)
             + vec3(0.10,0.42,0.50)*smoothstep(0.52,0.90,gas_b);
    float band = exp(-square(dot(d,vec3(0.4153,0.5440,-0.7290)))/0.03);
    float grain = fbm(p*3.1)+(noise(p*11.0)-0.5)*0.2;
    gas += vec3(0.55,0.47,0.72)*band*(0.30+0.70*grain);
    float core = smoothstep(0.80,0.98,gas_a)*0.7+smoothstep(0.84,1.0,gas_b)*0.5
               + smoothstep(0.80,1.0,grain)*band*0.6;
    return vec4(gas/NEBULA_SCALE,clamp(core,0.0,1.0));
}

// Value noise on the sphere's 3D position: no seams anywhere on the dome.
float vnoise3(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f*f*(3.0-2.0*f);
    uvec3 c = uvec3(ivec3(i)+ivec3(4096))+uvec3(bake_seed);
    float v[8];
    for (int k=0;k<8;k++) {
        uvec3 o = c+uvec3(k&1,(k>>1)&1,(k>>2)&1);
        uvec2 h = pcg2d(uvec2(o.x*73856093u^o.z*83492791u,o.y*19349663u+o.z));
        v[k] = float(h.x)*(1.0/4294967295.0);
    }
    return mix(mix(mix(v[0],v[1],f.x),mix(v[2],v[3],f.x),f.y),
               mix(mix(v[4],v[5],f.x),mix(v[6],v[7],f.x),f.y),f.z);
}
float fbm3(vec3 p, int octaves) {
    float sum = 0.0, amp = 0.5, norm = 0.0;
    for (int i=0;i<7;i++) {
        if (i>=octaves) break;
        sum += vnoise3(p)*amp; norm += amp;
        p = p*2.03+vec3(1.7,9.2,4.4); amp *= 0.5;
    }
    return sum/norm;
}

// A Milky Way on a fixed great circle: a warm bulge low in one quarter of
// the sky, lumpy star clouds, a forked rift of dark dust along its spine
// and a fine grain of unresolved stars. Stored at 1/MILKY_SCALE.
vec4 milky_way(vec3 d) {
    vec3 n = normalize(vec3(0.58,0.38,0.72));
    vec3 a = normalize(cross(n,vec3(0,1,0)));
    vec3 b = cross(n,a);
    float lat = dot(d,n);
    float lon = atan(dot(d,b),dot(d,a));
    // Noise space stretched along the band so features stream with it.
    vec3 s = a*dot(d,a)+b*dot(d,b)+n*lat*2.6;
    float bulge = exp(-square(lon+0.6)/0.30);
    float width = 0.10+0.07*bulge+0.025*(fbm3(s*2.0,3)-0.5);
    float body = exp(-square(lat-0.01*sin(lon*3.0))/(width*width));
    float halo = exp(-square(lat)/(0.06+0.05*bulge));
    float clouds = smoothstep(0.30,0.80,fbm3(s*5.0+3.1,5));
    float grain = fbm3(s*38.0,3);
    // The rift: thin dark ridges of noise hugging the spine, forking wide.
    float ridge = 1.0-abs(fbm3(s*7.0+11.0,5)*2.0-1.0);
    float rift = smoothstep(0.72,0.93,ridge)*exp(-square(lat+0.008)/(0.0035+0.004*bulge));
    float dust = smoothstep(0.55,0.8,fbm3(s*3.0+5.0,4))*body*0.5;
    float glow = body*(0.35+0.95*clouds)*(0.6+0.8*grain)+halo*0.25;
    glow *= (1.0-rift*0.6)*(1.0-dust*0.35)*(0.6+0.9*bulge);
    vec3 tint = mix(vec3(0.70,0.77,0.98),vec3(1.0,0.88,0.72),bulge*0.8);
    float knots = smoothstep(0.55,0.95,clouds*grain*1.4)*body*(1.0-rift);
    return vec4(clamp(tint*glow*0.13/MILKY_SCALE,0.0,1.0),clamp(knots,0.0,1.0));
}

// Moon face on [-1,1]^2: bright highlands, dark maria, a few rayed craters.
// Alpha is the disc coverage so the edge stays antialiased when sampled.
vec4 moon_face(vec2 q) {
    float r = length(q);
    vec2 t = q*0.5+0.5;
    float maria = smoothstep(0.50,0.68,tfbm(t+vec2(0.11,0.03),2.0,4,101u)*0.5+0.5
                             +0.20*exp(-dot(q-vec2(-0.25,0.20),q-vec2(-0.25,0.20))*5.0)
                             +0.15*exp(-dot(q-vec2(0.30,0.30),q-vec2(0.30,0.30))*7.0)
                             -0.20*smoothstep(0.1,0.9,-q.y));
    float rough = tfbm(t,10.0,4,103u)*0.5+0.5;
    float craters = 0.0;
    for (int i=0;i<3;i++) {
        float w = worley(t+float(i)*0.21,6.0+float(i)*5.0,107u+uint(i));
        craters += (smoothstep(0.10,0.16,w)-smoothstep(0.16,0.24,w))*0.5-(1.0-smoothstep(0.0,0.10,w))*0.12;
    }
    float tycho = exp(-length(q-vec2(-0.10,-0.62))*9.0);
    float rays = tycho*0.3+exp(-length(q-vec2(-0.10,-0.62))*2.5)
               *smoothstep(0.75,1.0,gnoise(vec2(atan(q.y+0.62,q.x+0.10)*1.909859+6.0,0.5),vec2(12.0),109u)*0.5+0.5)*0.25;
    float albedo = mix(0.86,0.50,maria)*(0.90+0.16*rough)+craters*0.10+rays;
    return vec4(vec3(clamp(albedo,0.0,1.0)),1.0-smoothstep(0.985,1.0,r));
}

void main() {
    if (bake_mode==0) { frag = tile_b(uv); return; }
    if (bake_mode==1) { frag = tile_a(uv); return; }
    // Dome texture: the hemisphere fills the top square, the moon the bottom rows.
    vec2 px = uv*bake_size;
    if (px.y<bake_moon_rows) {
        if (px.x>=bake_moon_rows) { frag = vec4(0); return; }
        frag = moon_face(px/bake_moon_rows*2.0-1.0);
        return;
    }
    vec2 t = vec2(px.x/bake_size.x,(px.y-bake_moon_rows)/(bake_size.y-bake_moon_rows));
    vec3 d = octa_dir(t);
    frag = bake_nebula>0.5 ? nebula_gas(d) : milky_way(d);
}
