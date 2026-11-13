// Stateless particles (fishing/particlefx.py). An instance is a point sprite,
// a two-vertex line or a four-vertex quad (p_prim 0/1/2); its place is a pure
// function of the instance seeds (in_a, in_b), p_time and weather uniforms.
// Weather systems live in a camera-centred box but stay fixed in the world
// (they wrap at the box edge and fade well inside it); anchored systems carry
// their world anchor in in_a.xyz. Each system has a cheap `_place` step and a
// `_shade` step that only runs for particles inside the view. Sizes keep at
// least MINPX pixels and trade the rest for alpha, so distant specks thin out
// instead of shimmering.
in vec4 in_a, in_b;
uniform int p_kind, p_prim;
uniform float p_count, p_density, p_strength, p_box;

out vec2 v_uv;          // quad/line coordinate, -1..1 (points use gl_PointCoord)
out vec4 v_col;         // straight colour and alpha of the lit body
out vec3 v_emit;        // light added on top (premultiplied, may exceed 1)
out vec3 v_tex;         // wisp texture coordinate and fragment world height
out vec2 v_world;       // fragment world xz, for the mist's per-pixel shore fade
flat out int v_shape;   // 0 glow, 1 streak, 2 leaf, 3 mist sheet, 4 soft dot

const float TAU = 6.2831853;
const float PI = 3.1415927;

// Shared particle state, filled by a system's _place then _shade.
vec3 C;       // world centre (before mirroring)
vec2 S;       // half size in metres (x across, y along the axis)
vec3 AXIS;    // world long axis for streaks and leaves
vec3 SIDE;    // world cross axis for leaves; zero for camera-facing
float MINPX;  // smallest half size in pixels
float CPOW;   // how much of its alpha a speck smaller than MINPX keeps (1 = all of the loss)
float FADE;   // 0..1 visibility from life cycle, distance and place
int SHAPE;
vec4 COL;
vec3 EMIT;
float G;      // per-system scratch carried from _place to _shade

vec3 wrap_box(vec3 world, float r) {
    // A world-fixed lattice of positions folded into a box around the eye.
    vec2 rel = mod(world.xz-eye.xz+r, 2.0*r)-r;
    return vec3(eye.x+rel.x, world.y, eye.z+rel.y);
}
float box_fade(vec3 c, float r) {
    return 1.0-smoothstep(0.55*r, 0.95*r, length(c.xz-eye.xz));
}
float near_fade(vec3 c, float a, float b) {
    return smoothstep(a, b, distance(c, eye));
}
float far_fade(vec3 c, float a, float b) {
    return 1.0-smoothstep(a, b, distance(c, eye));
}
// Sky light a matte speck receives, plus direct sun and moon.
vec3 ambient_light() {
    return mix(horizon, zenith, 0.35)*0.95 + vec3(1.0,0.90,0.74)*sun_i*0.32
         + vec3(0.55,0.62,0.80)*moon_i*0.12;
}
// Forward scattering: bright when the particle sits between the eye and sun.
float toward_sun(vec3 c, float power) {
    return pow(max(dot(normalize(c-eye), sun), 0.0), power);
}
vec3 nebula_tint(float k) {
    return k < 0.45 ? vec3(0.30,0.95,0.92) : (k < 0.85 ? vec3(0.74,0.46,1.0) : vec3(0.86,0.90,1.0));
}

// --- 0 sun motes and pollen: sunlit specks near the boat and bank ---------
void motes_place(vec4 a, vec4 b) {
    float r = p_box;
    vec3 w = vec3((a.x*2.0-1.0)*r, 0.3+a.y*a.y*4.5, (a.z*2.0-1.0)*r);
    w.xz += p_drift*p_time*(0.6+0.8*b.x);
    w += vec3(sin(p_time*(0.11+0.1*b.y)+a.w*TAU)*0.9,
              sin(p_time*(0.17+0.1*b.z)+b.w*TAU)*0.3,
              cos(p_time*(0.09+0.1*b.x)+a.y*TAU)*0.9);
    C = wrap_box(w, r);
    S = vec2(0.010+0.018*b.z*b.z);
    MINPX = 1.1;
    CPOW = 0.75;
    SHAPE = 4;
    FADE = box_fade(C, r)*near_fade(C, 2.0, 5.5);
}
void motes_shade(vec4 a, vec4 b) {
    float fwd = toward_sun(C, 5.0);
    vec3 sunc = mix(vec3(1.0,0.94,0.82), vec3(1.0,0.70,0.38), gold);
    // Front-lit specks barely show at midday; low warm light and backlight
    // are what make the air glitter.
    float lit = (mix(0.3, 1.1, gold)+6.0*fwd)*(0.35+0.65*max(sun_i, gold));
    float shimmer = 0.6+0.4*sin(p_time*0.7+a.w*TAU);
    COL = vec4(0.0);
    EMIT = sunc*lit*shimmer;
}

// --- 13 bank pollen: the firefly seeds by day, idling in the sun ---------
void pollen_place(vec4 a, vec4 b) {
    // Seed fluff and pollen hang in the warm air over the grass and shallows,
    // circling slowly about their anchor rather than travelling.
    C = a.xyz + vec3(sin(p_time*(0.07+0.05*b.y)+a.w*TAU)*2.4,
                     0.4+1.4*b.x+sin(p_time*(0.11+0.06*b.z)+b.w*TAU)*0.5,
                     cos(p_time*(0.06+0.05*b.x)+b.y*TAU)*2.4);
    S = vec2(0.011+0.016*b.z*b.z);
    MINPX = 1.0;
    CPOW = 0.7;
    SHAPE = 4;
    FADE = near_fade(C, 2.0, 5.0)*far_fade(C, 110.0, 190.0);
}

// --- 1 fireflies: slow wanderers along the wooded bank ---------------------
void firefly_place(vec4 a, vec4 b) {
    C = a.xyz + vec3(sin(p_time*(0.21+0.12*b.x)+a.w*TAU)*1.7,
                     sin(p_time*(0.29+0.10*b.y)+b.z*TAU)*0.45,
                     cos(p_time*(0.17+0.12*b.z)+b.w*TAU)*1.7);
    // A soft glow that swells and fades over a second or two, every 3-8 s.
    float period = 3.0+5.0*b.x;
    float phase = fract(p_time/period+b.y);
    G = exp(-square((phase-0.5)/(0.16+0.06*b.z)));
    S = vec2(0.07);
    MINPX = 3.2;
    SHAPE = 0;
    FADE = near_fade(C, 2.5, 6.0)*far_fade(C, 280.0, 450.0)*(0.12+0.88*G);
}
void firefly_shade(vec4 a, vec4 b) {
    vec3 tint = mix(vec3(0.72,1.0,0.30), vec3(1.0,0.80,0.30), b.w);
    COL = vec4(0.0);
    EMIT = tint*(0.25+G*4.0)*(0.6+0.4*p_strength);
}

// --- 2 mist wisps: long soft sheets low over open water ---------------------
void wisp_place(vec4 a, vec4 b) {
    float r = p_box;
    // Each wisp lives one slow cycle, then reappears somewhere else.
    float period = 70.0+60.0*b.x;
    float cyc = p_time/period+a.w;
    float life = fract(cyc);
    float k = floor(cyc);
    vec2 jitter = vec2(hash(vec2(k, a.x*91.0)), hash(vec2(a.z*57.0, k)));
    vec3 w = vec3((fract(a.x+jitter.x)*2.0-1.0)*r, 0.0, (fract(a.z+jitter.y)*2.0-1.0)*r);
    w.xz += p_drift*p_time*0.5;
    C = wrap_box(w, r);
    // Long and low: a band of breath lying on the water, never a puff.
    S = vec2(7.0+16.0*b.y, 1.0+2.2*b.z*b.z);
    C.y = S.y*0.45;
    MINPX = 0.0;
    SHAPE = 3;
    // Centres sit over water; the fragment shader thins each sheet towards
    // the bank so none cuts into the land. Near ones fade out so the mist
    // never walls off the view from the boat.
    float wet = smoothstep(4.0, -6.0, shore(C.xz));
    FADE = wet*box_fade(C, r)*smoothstep(9.0, 30.0, distance(C, eye))*far_fade(C, 80.0, 135.0)*sin(life*PI);
    v_tex.xy = vec2(b.w*7.0, a.y*5.0) + p_time*vec2(0.0035, 0.0006);
}
vec3 mist_colour(float lift) {
    vec3 white = vec3(0.93,0.95,0.97)*(1.0-night*0.86);
    vec3 base = mix(horizon, white, lift);
    base += vec3(1.0,0.64,0.34)*gold*toward_sun(C, 3.0)*0.7;
    base += vec3(1.0,0.82,0.55)*gold*0.12;
    return base + vec3(0.70,0.78,0.95)*moon_i*0.10;
}
void wisp_shade(vec4 a, vec4 b) {
    COL = vec4(mist_colour(0.6), 0.6*(0.55+0.45*p_strength));
    EMIT = vec3(0.0);
}

// --- 11 spring steam: Crater's warm springs breathe thin rising sheets ----
void steam_place(vec4 a, vec4 b) {
    float period = 26.0+18.0*a.w;
    G = fract(p_time/period+b.x);
    C = a.xyz + vec3(p_drift.x*G*period*0.6, 0.5+G*5.0, p_drift.y*G*period*0.6);
    C.xz += vec2(sin(G*3.0+b.y*TAU), cos(G*2.3+b.z*TAU))*1.2;
    S = vec2(4.0+5.0*b.y, 0.8+0.9*b.z)*(0.7+0.8*G);
    MINPX = 0.0;
    SHAPE = 3;
    FADE = smoothstep(0.0, 0.25, G)*(1.0-smoothstep(0.5, 1.0, G))
         *smoothstep(10.0, 30.0, distance(C, eye))*far_fade(C, 500.0, 800.0);
    v_tex.xy = vec2(b.w*7.0, a.w*5.0) + vec2(0.0, -G*0.35);
}
void steam_shade(vec4 a, vec4 b) {
    COL = vec4(mist_colour(0.6), 0.45);
    EMIT = vec3(0.0);
}

// --- 3 rain: straight, calm streaks at every depth around the boat ---------
void rain_place(vec4 a, vec4 b) {
    float r = p_box;
    const float H = 18.0;
    float speed = 6.0+1.5*b.x;
    vec3 w = vec3((a.x*2.0-1.0)*r, H-mod(a.y*H+speed*p_time, H), (a.z*2.0-1.0)*r);
    C = wrap_box(w, r);
    S = vec2(0.006, 0.32+0.22*b.y);
    AXIS = vec3(0.0, 1.0, 0.0);
    MINPX = 0.5;
    SHAPE = 1;
    FADE = box_fade(C, r)*near_fade(C, 1.6, 4.5);
}
void rain_shade(vec4 a, vec4 b) {
    vec3 base = mix(horizon, vec3(0.86,0.89,0.92), 0.45)*mix(1.0, 0.45, night)
              + vec3(0.75,0.63,0.37)*lamp(C)*3.0;
    COL = vec4(base, 0.42+0.25*b.z);
    EMIT = vec3(0.0);
}

// --- 4 snow: soft flakes drifting down on the breeze ------------------------
void snow_place(vec4 a, vec4 b) {
    float r = p_box;
    const float H = 16.0;
    float fall = 0.55+0.45*b.x;
    vec3 w = vec3((a.x*2.0-1.0)*r, H-mod(a.y*H+fall*p_time, H), (a.z*2.0-1.0)*r);
    w.xz += p_drift*p_time*0.8;
    w.xz += vec2(sin(p_time*(0.5+0.4*b.y)+a.w*TAU), cos(p_time*(0.4+0.3*b.z)+b.w*TAU))*0.35;
    C = wrap_box(w, r);
    S = vec2(0.012+0.014*b.z);
    MINPX = 0.9;
    SHAPE = 4;
    FADE = box_fade(C, r)*near_fade(C, 0.9, 2.6);
}
void snow_shade(vec4 a, vec4 b) {
    COL = vec4(vec3(0.93,0.95,0.98)*ambient_light()*1.2 + vec3(0.75,0.63,0.37)*lamp(C)*2.0, 0.9);
    EMIT = vec3(0.0);
}

// --- 5 leaves / 12 larch needles: an occasional fall from the crowns -------
vec3 LEAF_N;
void fall_place(vec4 a, vec4 b, bool needle) {
    // Each one falls from its crown to the water or ground, rests a moment,
    // fades, and waits for its next turn.
    float rate = needle ? 0.75 : 0.85;
    // Settle on the water if the breeze carried it off the bank.
    float guess = (a.y-b.x)/rate;
    float rest = (shore(a.xz+p_drift*guess*1.4) < 0.0 ? 0.0 : b.x)+0.02;
    float flight = max(a.y-rest, 0.0)/rate;
    // The wait between falls keeps them occasional; it never cuts a fall short.
    float period = flight+6.0+(needle ? 4.0+14.0*b.y : 18.0+50.0*b.y);
    float tau = fract(p_time/period+a.w)*period;
    float air = min(tau, flight);
    vec2 sway = vec2(sin(air*1.3+b.z*TAU), cos(air*1.1+b.w*TAU))*(needle ? 0.25 : 0.7);
    C = vec3(a.x, max(a.y-tau*rate, rest), a.z);
    C.xz += p_drift*air*1.4 + sway;
    float landed = smoothstep(flight, flight+0.4, tau);
    float spin = air*(needle ? 2.4 : 1.7)*(0.6+0.8*b.z)+b.w*TAU;
    float yaw = b.z*TAU+air*0.3;
    vec3 e1 = vec3(cos(yaw), 0.0, sin(yaw));
    vec3 e2 = vec3(-e1.z, 0.0, e1.x);
    // Tumbling about e1, then lying flat once it rests.
    vec3 tumble = cos(spin)*vec3(0.0,1.0,0.0)+sin(spin)*e2;
    AXIS = normalize(mix(tumble, e2, landed)+e2*0.001);
    SIDE = e1;
    LEAF_N = normalize(cross(AXIS, SIDE));
    S = needle ? vec2(0.005, 0.05) : vec2(0.035, 0.05);
    MINPX = needle ? 1.0 : 0.8;
    // Thin needles keep more of their alpha when sub-pixel: a drifting gold
    // stroke should still read against a dark forest.
    CPOW = needle ? 0.5 : 0.8;
    SHAPE = needle ? 1 : 2;
    FADE = smoothstep(0.0, 1.0, tau)*(1.0-smoothstep(flight+2.0, flight+5.0, tau))
         *near_fade(C, 1.5, 4.0)*far_fade(C, 110.0, 170.0);
}
void fall_shade(vec4 a, vec4 b, bool needle) {
    vec3 tint;
    if (needle) tint = mix(vec3(0.92,0.66,0.20), vec3(0.98,0.80,0.36), b.w);
    else if (lake_kind>0.5 && lake_kind<1.5) tint = mix(vec3(0.66,0.44,0.16), vec3(0.76,0.58,0.22), b.w);
    else tint = mix(mix(vec3(0.38,0.44,0.14), vec3(0.72,0.48,0.12), b.w), vec3(0.64,0.27,0.10), step(0.8, b.z));
    float facing = abs(dot(LEAF_N, sun))*sun_i*0.6;
    COL = vec4(tint*(ambient_light()*0.75+vec3(1.0,0.9,0.7)*facing) + vec3(0.75,0.63,0.37)*lamp(C), 1.0);
    // A tumbling needle catches the sun now and then.
    vec3 h = normalize(sun-normalize(C-eye));
    EMIT = needle ? vec3(1.0,0.80,0.42)*pow(abs(dot(LEAF_N, h)), 8.0)*(sun_i+gold)*4.0 : vec3(0.0);
}

// --- 6 cinder ash at Crater, with a rare ember ------------------------------
void ash_place(vec4 a, vec4 b) {
    float r = p_box;
    const float H = 22.0;
    bool ember = b.x < 0.08;
    float fall = ember ? -0.10 : 0.12+0.10*b.y;
    vec3 w = vec3((a.x*2.0-1.0)*r, H-mod(a.y*H+fall*p_time, H), (a.z*2.0-1.0)*r);
    w.xz += p_drift*p_time + vec2(sin(p_time*0.21+a.w*TAU), cos(p_time*0.17+b.w*TAU))*0.8;
    C = wrap_box(w, r);
    S = vec2(0.008+0.010*b.z);
    MINPX = ember ? 1.4 : 0.9;
    SHAPE = ember ? 0 : 4;
    FADE = box_fade(C, r)*near_fade(C, 1.5, 4.0)*smoothstep(0.0, 1.5, C.y);
}
void ash_shade(vec4 a, vec4 b) {
    if (b.x < 0.08) {
        float breathe = 0.6+0.4*sin(p_time*0.8+b.w*TAU);
        COL = vec4(0.0);
        EMIT = vec3(1.0,0.42,0.12)*breathe*mix(0.6, 3.6, night);
    } else {
        // Warm grey cinder, darker than snow so it never reads as a flurry.
        COL = vec4(vec3(0.42,0.39,0.37)*ambient_light(), 0.5);
        EMIT = vec3(1.0,0.85,0.70)*toward_sun(C, 6.0)*sun_i*1.4;
    }
}

// --- 7 Nebula star dust rising slowly off the lagoon ------------------------
void dust_place(vec4 a, vec4 b) {
    float r = p_box;
    // Rises off the water and dissolves within a few metres, so the dust
    // gathers low over the lagoon instead of mixing with the stars.
    const float H = 7.0;
    float y = mod(a.y*H+(0.10+0.10*b.x)*p_time, H);
    vec3 w = vec3((a.x*2.0-1.0)*r, y, (a.z*2.0-1.0)*r);
    w.xz += vec2(sin(p_time*0.13+a.w*TAU), cos(p_time*0.11+b.w*TAU))*1.2+p_drift*p_time;
    C = wrap_box(w, r);
    S = vec2(0.018+0.022*b.z);
    MINPX = 1.9;
    SHAPE = 0;
    float wet = smoothstep(2.0, -4.0, shore(C.xz));
    FADE = wet*box_fade(C, r)*near_fade(C, 2.0, 5.0)*smoothstep(0.0, 0.6, y)*(1.0-smoothstep(2.0, H, y));
}
void dust_shade(vec4 a, vec4 b) {
    float twinkle = 0.55+0.45*sin(p_time*(0.5+0.4*b.y)+b.z*TAU);
    COL = vec4(0.0);
    EMIT = nebula_tint(b.y)*twinkle*(1.8+2.2*b.w)*mix(0.5, 1.0, night);
}

// --- 8 light motes riding the Nebula's current lanes ------------------------
void lane_place(vec4 a, vec4 b) {
    // The same flow field as nebula.flow_direction, frozen at the anchor.
    float heading = 1.7*sin(a.x/190.0+0.6)+1.1*cos(a.z/150.0-0.4);
    vec2 dir = vec2(cos(heading), sin(heading));
    const float L = 28.0;
    G = fract(p_time*(0.55+0.4*b.x)/L+a.w);
    C = vec3(a.x, 0.18+0.55*b.y+0.12*sin(p_time*0.7+b.z*TAU), a.z);
    C.xz += dir*(G-0.5)*L;
    S = vec2(0.018+0.010*b.z);
    MINPX = 1.8;
    SHAPE = 0;
    FADE = sin(G*PI)*near_fade(C, 2.0, 5.0)*far_fade(C, 160.0, 260.0);
}
void lane_shade(vec4 a, vec4 b) {
    COL = vec4(0.0);
    EMIT = mix(vec3(0.35,1.0,0.88), vec3(0.62,0.80,1.0), b.w)*(1.6+1.4*b.z)*mix(0.55, 1.0, night);
}

// --- 9 sparkles orbiting the crystal spires ---------------------------------
void sparkle_place(vec4 a, vec4 b) {
    float h = b.x;
    float ang = a.w*TAU+p_time*(0.05+0.06*b.y)*(b.z < 0.5 ? 1.0 : -1.0);
    float rad = 0.5+h*(0.10+0.25*b.y);
    C = a.xyz + vec3(cos(ang)*rad, h*(0.10+0.95*b.z)+sin(p_time*0.3+b.w*TAU)*0.2, sin(ang)*rad);
    // A gentle swell rather than a blink: up and down over a couple of seconds.
    G = square(0.5+0.5*sin(p_time*(0.35+0.3*b.w)+b.y*TAU));
    S = vec2(0.03);
    MINPX = 1.6;
    SHAPE = 0;
    FADE = near_fade(C, 2.0, 5.0)*far_fade(C, 180.0, 300.0)*(0.35+0.65*G);
}
void sparkle_shade(vec4 a, vec4 b) {
    COL = vec4(0.0);
    EMIT = nebula_tint(fract(b.w*3.7))*(0.8+3.0*G)*mix(0.55, 1.0, night);
}

// --- 10 insects skimming over the reeds at dusk -----------------------------
void insect_place(vec4 a, vec4 b) {
    C = a.xyz + vec3(sin(p_time*(0.9+0.6*a.w)+b.x*TAU)*0.9+sin(p_time*2.3+b.y*TAU)*0.15,
                     0.08+0.55*b.z*b.z+sin(p_time*(1.4+b.w)+a.w*TAU)*0.06,
                     cos(p_time*(0.8+0.7*b.y)+b.w*TAU)*0.9+cos(p_time*2.1+b.x*TAU)*0.15);
    S = vec2(0.005);
    MINPX = 0.6;
    SHAPE = 4;
    FADE = near_fade(C, 1.0, 3.0)*far_fade(C, 40.0, 70.0);
}
void insect_shade(vec4 a, vec4 b) {
    COL = vec4(vec3(0.05,0.05,0.04), 0.85);
    EMIT = vec3(1.0,0.78,0.48)*toward_sun(C, 8.0)*(sun_i+gold)*2.2;
}

void place(vec4 a, vec4 b) {
    if (p_kind == 0) motes_place(a, b);
    else if (p_kind == 1) firefly_place(a, b);
    else if (p_kind == 2) wisp_place(a, b);
    else if (p_kind == 3) rain_place(a, b);
    else if (p_kind == 4) snow_place(a, b);
    else if (p_kind == 5) fall_place(a, b, false);
    else if (p_kind == 6) ash_place(a, b);
    else if (p_kind == 7) dust_place(a, b);
    else if (p_kind == 8) lane_place(a, b);
    else if (p_kind == 9) sparkle_place(a, b);
    else if (p_kind == 10) insect_place(a, b);
    else if (p_kind == 11) steam_place(a, b);
    else if (p_kind == 12) fall_place(a, b, true);
    else pollen_place(a, b);
}
void shade(vec4 a, vec4 b) {
    if (p_kind == 0) motes_shade(a, b);
    else if (p_kind == 1) firefly_shade(a, b);
    else if (p_kind == 2) wisp_shade(a, b);
    else if (p_kind == 3) rain_shade(a, b);
    else if (p_kind == 4) snow_shade(a, b);
    else if (p_kind == 5) fall_shade(a, b, false);
    else if (p_kind == 6) ash_shade(a, b);
    else if (p_kind == 7) dust_shade(a, b);
    else if (p_kind == 8) lane_shade(a, b);
    else if (p_kind == 9) sparkle_shade(a, b);
    else if (p_kind == 10) insect_shade(a, b);
    else if (p_kind == 11) steam_shade(a, b);
    else if (p_kind == 12) fall_shade(a, b, true);
    else motes_shade(a, b);
}

void cull() {
    v_world = vec2(0.0);
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    gl_PointSize = 1.0;
    v_col = vec4(0.0);
    v_emit = vec3(0.0);
    v_shape = 0;
}

void main() {
    int corner = gl_VertexID;
    vec2 q = p_prim == 2 ? vec2(float(corner & 1)*2.0-1.0, float(corner >> 1)*2.0-1.0)
           : vec2(0.0, p_prim == 1 ? float(corner)*2.0-1.0 : 0.0);
    v_uv = q;
    v_tex = vec3(0.0);
    AXIS = vec3(0.0);
    SIDE = vec3(0.0);
    G = 0.0;
    CPOW = 1.0;
    vec4 a = in_a, b = in_b;
    place(a, b);
    // Weak systems thin out smoothly by instance rank.
    float rank = (float(gl_InstanceID)+0.5)/p_count;
    FADE *= clamp((p_density*1.08-rank)/0.08, 0.0, 1.0);
    vec3 centre = C;
    centre.y *= mirror;
    vec3 d = centre-eye;
    float depth = dot(d, view_forward);
    float reach = max(S.x, S.y)+0.5;
    // Skip the shading for anything faded, behind the eye or outside the view.
    if (FADE <= 0.002 || depth < 0.3
        || abs(dot(d, view_right)) > depth*tanx+reach
        || abs(dot(d, view_up)) > depth*tany+reach) {
        cull();
        return;
    }
    shade(a, b);
    // Keep at least MINPX pixels; what the speck lacks in size it loses in alpha.
    float px = 2.0*depth*tanx/viewport.x;
    float cover = 1.0;
    float want = MINPX*px;
    if (S.x < want) { cover *= S.x/want; S.x = want; }
    if (p_prim != 1 && S.y < want) { cover *= S.y/want; S.y = want; }
    // A light is seen by its brightness, not its size: distant glows keep
    // more of their strength than matte specks do.
    cover = pow(cover, SHAPE == 0 ? 0.45 : CPOW);
    // haze() is linear in the colour, so this recovers the scene's transmittance.
    float trans = haze(vec3(1.0), C).g-haze(vec3(0.0), C).g;
    v_col = vec4(SHAPE == 3 ? mix(COL.rgb, haze(COL.rgb, C), 0.5) : haze(COL.rgb, C), COL.a*FADE*cover);
    v_emit = EMIT*FADE*cover*trans;
    v_shape = SHAPE;
    vec3 p = centre;
    if (p_prim == 0) {
        gl_PointSize = max(1.0, 2.0*S.x/px);
    } else if (p_prim == 1) {
        vec3 ax = AXIS; ax.y *= mirror;
        p += ax*q.y*S.y;
    } else {
        vec3 ux = view_right, uy = view_up;
        if (SIDE != vec3(0.0)) {
            ux = SIDE; uy = AXIS;
            ux.y *= mirror; uy.y *= mirror;
        }
        p += ux*q.x*S.x+uy*q.y*S.y;
    }
    v_tex.z = C.y+q.y*S.y;
    v_world = p.xz;
    gl_Position = project(p);
}
