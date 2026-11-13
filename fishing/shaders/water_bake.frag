// Lake-load bake for fishing/waterfx.py; never runs per frame. One draw
// fills one layer of a seamless looping texture (or the noise texture):
//   mode 0: wave field (dh/du, dh/dv, height, slope^2) from `bake_waves`
//   mode 1: raindrop rings (slope, slope^2, impact sparkle)
//   mode 2: tileable noise (gust fbm, foam lace, bed fbm, caustic net)
// Everything is periodic on the unit tile (integer wave vectors, wrapped
// lattices) and in `bake_phase` (whole cycles per loop), so it tiles and loops.
uniform int bake_mode, bake_count;
uniform float bake_phase, bake_height;
uniform vec4 bake_waves[96];   // kx, ky (cycles per tile), height amplitude, start phase
uniform float bake_cycles[96]; // whole cycles per loop
in vec2 uv;
out vec4 frag;
const float TAU = 6.28318530718;

// PCG-style integer hash: well distributed, unlike the sine hash, and exact
// on every GPU, so the bake is the same everywhere.
uvec3 bake_pcg(uvec3 v) {
    v = v*1664525u+1013904223u;
    v.x += v.y*v.z; v.y += v.z*v.x; v.z += v.x*v.y;
    v ^= v>>16u;
    v.x += v.y*v.z; v.y += v.z*v.x; v.z += v.x*v.y;
    return v;
}
vec3 bake_rand(ivec2 cell, int period, int salt) {
    ivec2 c = ((cell%period)+period)%period;
    return vec3(bake_pcg(uvec3(uint(c.x),uint(c.y),uint(salt))))/4294967295.0;
}

// Periodic value noise with `period` lattice cells per tile.
float bake_value(vec2 p, int period, int salt) {
    vec2 q = p*float(period);
    ivec2 i = ivec2(floor(q));
    vec2 f = fract(q);
    f = f*f*f*(f*(f*6.0-15.0)+10.0);
    float a = bake_rand(i,period,salt).x, b = bake_rand(i+ivec2(1,0),period,salt).x;
    float c = bake_rand(i+ivec2(0,1),period,salt).x, d = bake_rand(i+ivec2(1,1),period,salt).x;
    return mix(mix(a,b,f.x),mix(c,d,f.x),f.y);
}
float bake_fbm(vec2 p, int period, int salt) {
    float sum = 0.0, amp = 0.5, norm = 0.0;
    for (int o=0;o<6;o++) {
        sum += bake_value(p,period,salt+o*31)*amp;
        norm += amp;
        amp *= 0.5;
        period *= 2;
    }
    return sum/norm;
}
// Periodic Voronoi: distance to the nearest and second-nearest feature point.
vec2 bake_voronoi(vec2 p, int period, int salt) {
    vec2 q = p*float(period);
    ivec2 i = ivec2(floor(q));
    float d1 = 9.0, d2 = 9.0;
    for (int y=-1;y<=1;y++) for (int x=-1;x<=1;x++) {
        ivec2 c = i+ivec2(x,y);
        vec2 feature = vec2(c)+bake_rand(c,period,salt).xy;
        float d = distance(q,feature);
        if (d<d1) { d2 = d1; d1 = d; } else if (d<d2) d2 = d;
    }
    return vec2(d1,d2);
}

vec4 bake_wave(vec2 p) {
    vec2 s = vec2(0);
    float h = 0.0;
    for (int i=0;i<96;i++) {
        if (i>=bake_count) break;
        vec4 w = bake_waves[i];
        float phase = TAU*(dot(w.xy,p)-bake_cycles[i]*bake_phase)+w.w;
        h += w.z*sin(phase);
        s += w.z*TAU*w.xy*cos(phase);
    }
    return vec4(s,h*bake_height,dot(s,s));
}

// Raindrop rings: half the cells of a 7x7 lattice hold one drop per loop.
// A ring is a short damped ripple packet that expands and fades.
vec4 bake_rain(vec2 p) {
    const int CELLS = 7;
    const float LIFE = 0.62, RADIUS = 0.8, WIDTH = 0.11;
    vec2 q = p*float(CELLS);
    ivec2 base = ivec2(floor(q));
    vec2 s = vec2(0);
    float splash = 0.0;
    for (int y=-1;y<=1;y++) for (int x=-1;x<=1;x++) {
        ivec2 c = base+ivec2(x,y);
        vec3 r = bake_rand(c,CELLS,7);
        vec3 r2 = bake_rand(c,CELLS,19);
        if (r2.x>0.6) continue;
        vec2 centre = vec2(c)+0.2+r.xy*0.6;
        float age = fract(bake_phase-r.z)/LIFE;
        if (age>=1.0) continue;
        vec2 d = q-centre;
        float dist = length(d);
        float size = 0.7+0.3*r2.y;
        float radius = (0.06+age)*RADIUS*size;
        float width = WIDTH*(1.0+age*1.4);
        float u = (dist-radius)/width;
        // h = env * cos(k u); slope is dh/du scaled to tile units.
        float env = exp(-u*u)*(1.0-age)*(1.0-age)*smoothstep(0.0,0.08,age);
        float k = 2.4;
        float dh = env*(-2.0*u*cos(k*u)-k*sin(k*u))/width;
        s += (dist>1e-4 ? d/dist : vec2(0))*dh*0.05;
        splash += exp(-dist*dist/0.004)*(1.0-smoothstep(0.0,0.14,age));
    }
    return vec4(s,dot(s,s),min(splash,1.0));
}

vec4 bake_noise(vec2 p) {
    float gust = bake_fbm(p,3,101);
    // Foam lace: thin, warped cell borders gathered into drifting patches,
    // with a finer froth of small bubbles between them.
    vec2 warp = vec2(bake_fbm(p,4,601),bake_fbm(p+0.5,4,607))-0.5;
    vec2 v = bake_voronoi(fract(p+warp*0.07),26,211);
    vec2 fine = bake_voronoi(fract(p-warp*0.05),61,229);
    float lace = (1.0-smoothstep(0.0,0.10+0.10*bake_fbm(p,12,331),v.y-v.x))*0.8
               + (1.0-smoothstep(0.0,0.16,fine.y-fine.x))*0.45;
    lace *= smoothstep(0.32,0.72,bake_fbm(p,5,307));
    float bed = bake_fbm(p+0.37,6,401);
    // Caustic net: sharp, warped ridges between Voronoi cells.
    vec2 c = bake_voronoi(fract(p+warp*0.12),14,503);
    float caustic = pow(1.0-smoothstep(0.0,0.16,c.y-c.x),2.0);
    return vec4(gust,min(lace,1.0),bed,caustic);
}

void main() {
    if (bake_mode==0) frag = bake_wave(uv);
    else if (bake_mode==1) frag = bake_rain(uv);
    else frag = bake_noise(uv);
}
