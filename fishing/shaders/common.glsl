uniform vec3 eye, view_right, view_up, view_forward;
uniform float tanx, tany, anim, sun_i, moon_i, night, gold;
uniform vec3 sun, moon, horizon, zenith;
uniform vec2 viewport, boat_pos, boat_forward, slip_origin, slip_inland, slip_side;
uniform vec2 boat_ends;  // (stern, bow) along the heading from the eye, metres
uniform vec3 slip_size;
uniform float cloud_cover, rain, mist, speed, spotlight;
uniform float comfort_fog_radius;
uniform float mirror;
uniform float lake_kind, snow, snow_anim, snow_line, still_reflection;
uniform vec3 alpine_shallow, alpine_deep;
uniform vec3 lake_water;
uniform sampler2D lake_shore, lake_depth;
uniform vec4 lake_bounds, cinder_island;
uniform vec2 lake_grid, lily_centre;
// Nebula: band star strength, aurora curtains and the Meteor Shower show.
uniform float starlight, aurora_i, meteors;
uniform vec4 drift_shapes[12];
uniform int drift_count;

// Effect-layer uniforms (fishing/fx.py). Each slice declares its own inside
// its block; values arrive from that layer's `uniforms()`.
// --- sky uniforms ---
// Baked by fishing/skyfx.py: cumulus tile (density, light-march gradient,
// mean), second tile (altocumulus, cirrus, erosion, cumulus), the night dome
// with the moon face in its bottom rows, and the star cells.
uniform sampler2D sky_cloud, sky_cloud2, sky_dome, sky_stars;
uniform vec4 sky_drift, sky_drift2;   // tile offsets: cumulus, alto | cirrus, boil
uniform vec4 sky_layout;              // dome edge, moon rows, star cells, unused
uniform vec3 sky_sun_col;             // sunlight colour on clouds and haze
uniform float sky_anim;               // anim, held at 0 under Reduced Motion
uniform float sky_overcast, sky_haze, sky_under, sky_night_vis;
// --- end sky uniforms ---

// --- land uniforms ---
// Baked once per lake by fishing/landfx.py (texture units 13-15).
uniform sampler2DArray land_groundmap;  // layer 0: albedo + detail kind; layer 1: normal xz, ao, gloss/glow
uniform sampler2D land_shadow;       // canopy density, density*top, density*base (m above ground), ground y
uniform sampler2DArray land_detail;  // tiling micro relief per detail kind: normal xz, shade, grain
uniform vec4 land_domain;            // baked area x0, z0, x1, z1 in metres
uniform vec3 land_boat_o, land_boat_x, land_boat_z;  // boat frame: eye, starboard, bow (level)
uniform vec4 land_hull;              // floor y, gunwale y, stern z, bow z (boat frame, m)
uniform vec4 land_hull_shape;        // mid half-width, stern width, bow width, floor/top width
uniform vec4 land_hull_flags;        // bow sheer rise, has walls, flat bow plate, taper start (0-1)
uniform float land_hull_ramp;        // hull fraction where the stern ramp reaches full width
uniform vec4 land_boxes[16];         // boat occluders: centre xyz + 0, half size xyz + 0
uniform int land_box_count;
uniform float land_anim;             // glint twinkle phase, held still under Reduced Motion
// --- end land uniforms ---

// --- flora uniforms ---
// Foliage light atlas (unit 16): normal x/y, translucency (glow on self-lit
// sprites), AO. Coverage table (unit 17): alpha scale per mip level x layer.
uniform sampler2DArray flora_light;
uniform sampler2D flora_cover;
// Shading-only animation clock (0 under Reduced Motion), wind 0.2-1.6,
// alpha-to-coverage on (1) in the multisampled main pass, mip level count.
uniform float flora_time, flora_wind, flora_a2c, flora_levels;
// --- end flora uniforms ---

// --- water uniforms ---
// Baked by fishing/waterfx.py: the looping wave volume (dh/du, dh/dv, height,
// slope^2), raindrop rings (slope, slope^2, sparkle) and tileable noise
// (gust, foam lace, bed, caustics).
uniform sampler2DArray wave_tex, rain_tex;
uniform sampler2D water_noise;
uniform vec4 wave_layers;  // frame pairs: near tile (xy), far tile (zw)
uniform vec2 wave_mix;     // blend toward the second frame of each pair
uniform vec4 wave_drift;   // drift in tile units, near (xy) and far (zw)
uniform vec4 wave_axes;    // world xz of each tile's wind axis, near (xy) and far (zw)
uniform vec4 wave_scale;   // tiles per metre: near, far, rain, gust
uniform float wave_slope;  // RMS surface slope from today's wind, rain and stillness
uniform vec4 water_gust;   // gust drift (xy) and patch strength (z)
uniform vec4 rain_layers;  // rain frame pairs for the two drop sets
uniform vec2 rain_mix;
uniform vec2 water_glint;  // sun and moon glitter radiance scale
uniform float water_star;  // reflected starlight on clear, calm nights
uniform float water_t;     // seconds for foam and churn; 0 under Reduced Motion
// --- end water uniforms ---

// --- particle uniforms ---
// Particle clock in seconds (held still under Reduced Motion) and the steady
// lake breeze in m/s that motes, flakes and leaves drift on.
uniform float p_time;
uniform vec2 p_drift;
// --- end particle uniforms ---

// Signed distances must not use pow(x, 2): GLSL leaves negative bases undefined.
float square(float x) { return x*x; }
bool crater_lake() { return lake_kind>3.5 && lake_kind<4.5; }
bool nebula_lake() { return lake_kind>4.5; }
bool on_drift(vec2 p) {
    for (int i=0;i<12;i++) {
        if (i>=drift_count) break;
        if (length((p-drift_shapes[i].xy)/drift_shapes[i].zw)<1.05) return true;
    }
    return false;
}

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}
float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f*f*(3.0-2.0*f);
    return mix(mix(hash(i), hash(i+vec2(1,0)), f.x),
               mix(hash(i+vec2(0,1)), hash(i+1.0), f.x), f.y);
}
float fbm(vec2 p) {
    return noise(p)*0.57 + noise(p*2.03+17.2)*0.28 + noise(p*4.1+9.7)*0.15;
}
vec2 lake_uv(vec2 p) {
    vec2 f = (p-lake_bounds.xy)/(lake_bounds.zw-lake_bounds.xy);
    return (f*(lake_grid-1.0)+0.5)/lake_grid;
}
float shore(vec2 p) {
    if (lake_kind>2.5) return texture(lake_shore,lake_uv(p)).r;
    if (lake_kind>1.5) return max(abs(p.x)-320.0,abs(p.y)-240.0);
    if (lake_kind>0.5) return texture(lake_shore,lake_uv(p)).r;
    float a = atan(p.y, p.x);
    float inlet = exp(-square(a-2.5393053)/(2.0*0.16*0.16));
    float warp = 1.0+0.05*sin(3.0*a)+0.035*sin(5.0*a+0.7)
                 +0.02*sin(8.0*a+1.9)+0.145*inlet;
    return length(p)-length(vec2(cos(a)*430.0, sin(a)*285.0))*warp;
}
bool in_slip(vec2 p) {
    vec2 d = p-slip_origin;
    float a = dot(d, slip_inland), s = dot(d, slip_side);
    return abs(s)<=slip_size.x && a>=-slip_size.z && a<=slip_size.y;
}
vec4 project(vec3 p) {
    vec3 d = p-eye;
    vec3 v = vec3(dot(d, view_right), dot(d, view_up), dot(d, view_forward));
    const float near = 0.18, far = 2400.0;
    return vec4(v.x/tanx, v.y/tany,
                (far+near)/(far-near)*v.z-2.0*far*near/(far-near), v.z);
}
float segment_distance(vec2 p, vec2 a, vec2 b) {
    vec2 ab = b-a;
    return length(p-a-ab*clamp(dot(p-a,ab)/dot(ab,ab),0.0,1.0));
}
// --- sky fx ---
// Octahedral map of the upper hemisphere onto [0,1]^2 (skyfx.octa_encode).
vec2 sky_octa(vec3 d) {
    vec3 a = vec3(d.x,max(d.y,0.0),d.z);
    vec2 p = a.xz/(abs(a.x)+a.y+abs(a.z)+1e-6);
    return vec2(p.x+p.y,p.x-p.y)*0.5+0.5;
}
vec3 sky_octa_dir(vec2 t) {
    vec2 q = t*2.0-1.0;
    vec2 p = vec2(q.x+q.y,q.x-q.y)*0.5;
    return normalize(vec3(p.x,1.0-abs(p.x)-abs(p.y),p.y));
}
// Night dome (Milky Way, or the Lagoon's gas and band): rgb light, a = knots.
// Texels are stored scaled (skybake.frag NEBULA_SCALE, MILKY_SCALE).
vec4 sky_dome_at(vec3 d) {
    vec2 t = sky_octa(d);
    vec4 v = texture(sky_dome,vec2(t.x,(sky_layout.y+t.y*sky_layout.x)/(sky_layout.x+sky_layout.y)));
    return vec4(v.rgb*(nebula_lake() ? 2.0 : 0.25),v.a);
}
// Catalogue stars as crisp points: each of the 2x2 cells nearest the pixel
// holds at most one star (skyfx.star_catalogue). Stars fainter than about
// `floor_level` fade out, as moonlight and twilight drown them.
vec3 sky_stars_at(vec3 d, float floor_level) {
    float cells = sky_layout.z;
    vec2 g = sky_octa(d)*cells-0.5;
    vec2 base = floor(g);
    float px = 2.0*tanx/viewport.x;
    float scint = 1.0-0.6*smoothstep(0.1,0.6,d.y);
    vec3 sum = vec3(0);
    for (int j=0;j<2;j++) for (int i=0;i<2;i++) {
        vec2 cell = clamp(base+vec2(i,j),0.0,cells-1.0);
        vec4 s = texelFetch(sky_stars,ivec2(cell),0);
        if (s.b<0.002) continue;
        float r = length(d-sky_octa_dir((cell+s.rg)/cells))/px;
        float bright = exp2(s.b*10.0-7.0);
        // Gentle twinkle, stronger low in the sky; still under Reduced Motion.
        float phase = fract(s.r*13.7+s.g*7.3+s.a*3.1)*56.5;
        bright *= 1.0+0.25*scint*sin(sky_anim*(1.3+s.a*2.1)+phase);
        bright *= smoothstep(floor_level,floor_level*2.5+0.002,bright);
        float sigma = 0.55+0.3*clamp(bright,0.0,1.5);
        vec3 tint = s.a<0.5 ? mix(vec3(1.0,0.72,0.48),vec3(1.0,0.96,0.90),s.a*2.0)
                            : mix(vec3(1.0,0.96,0.90),vec3(0.72,0.82,1.0),s.a*2.0-1.0);
        sum += tint*bright*exp(-r*r/(2.0*sigma*sigma));
    }
    return sum;
}
// Clear-sky colour with no texture fetches: the authored horizon-to-zenith
// gradient plus directional in-scatter. haze() fogs toward this same colour,
// so a far shore dissolves into the sky behind it without a seam.
vec3 sky_clear(vec3 d) {
    float h = smoothstep(-0.04,0.9,d.y);
    vec3 col = mix(horizon,zenith,h);
    float y = max(d.y,0.0);
    float s = max(dot(d,sun),0.0);
    // A low sun warms and brightens the horizon on its side and cools the
    // far side, under the rose anti-twilight band. Cloud flattens it.
    float toward = dot(normalize(d.xz+vec2(1e-5)),normalize(sun.xz+vec2(1e-5)))*0.5+0.5;
    float low = (1.0-smoothstep(0.10,0.55,sun.y))*smoothstep(-0.30,-0.02,sun.y)*(1.0-sky_overcast*0.8);
    col *= mix(vec3(1.0),mix(vec3(0.80,0.85,0.98),vec3(1.12,1.02,0.90),toward),(1.0-h)*low);
    col += vec3(0.10,0.04,0.07)*low*(1.0-toward)*exp(-square(y-0.12)/0.006);
    // The authored broad glow, then a Mie aureole that widens in haze.
    col += vec3(1.0,0.68,0.33)*pow(s,24.0)*sun_i*0.23;
    col += sky_sun_col*(pow(s,mix(900.0,160.0,sky_haze))*mix(0.55,0.75,sky_haze)
                        +pow(s,mix(90.0,14.0,sky_haze))*0.16)*sun_i;
    col += vec3(0.30,0.13,0.04)*gold*exp(-square(d.y-0.03)/0.025);
    // Night: faint airglow low down keeps treelines readable against the sky;
    // the moon lifts the whole dome blue and haloes softly.
    col += vec3(0.016,0.022,0.034)*night*exp(-y*7.0);
    float m = max(dot(d,moon),0.0);
    col += vec3(0.020,0.032,0.060)*moon_i*(1.0-h*0.5);
    col += vec3(0.55,0.62,0.78)*(pow(m,400.0)*0.35+pow(m,40.0)*0.06)*moon_i*(1.0+sky_haze*1.5);
    return col;
}
// HDR sun disc with limb darkening; whatever cloud covers it is composited
// over it afterwards. Hidden by overcast.
vec3 sky_sun_disc(vec3 d) {
    float c = dot(d,sun);
    if (c<0.9997) return vec3(0);
    const float R = 0.0135;
    float ang = sqrt(max(2.0-2.0*c,0.0));
    float px = 2.0*tanx/viewport.x;
    float edge = 1.0-smoothstep(R-px*0.7,R+px*0.7,ang);
    float mu = sqrt(max(1.0-square(ang/R),0.0));
    float strength = (1.0-sky_overcast)*smoothstep(-0.015,0.02,sun.y)*mix(5.0,16.0,smoothstep(0.0,0.35,sun.y));
    return sky_sun_col*(0.6+0.4*mu)*edge*strength*(1.0-rain*0.9);
}
// The moon with its baked face (maria, craters) and limb darkening. Returns
// its colour; `cover` is the disc's coverage of this pixel.
vec3 sky_moon_disc(vec3 d, out float cover) {
    cover = 0.0;
    float c = dot(d,moon);
    if (c<0.9996 || moon_i<=0.0) return vec3(0);
    const float R = 0.0165;
    vec3 right = normalize(cross(moon,vec3(0,1,0)));
    vec3 up = cross(right,moon);
    vec2 q = vec2(dot(d,right),dot(d,up))/R;
    float r = length(q);
    float px = 2.0*tanx/viewport.x/R;
    cover = 1.0-smoothstep(1.0-px*0.7,1.0+px*0.7,r);
    vec2 t = clamp(q*0.5+0.5,0.0,1.0)*sky_layout.y;
    float face = texture(sky_dome,vec2(t.x/sky_layout.x,t.y/(sky_layout.x+sky_layout.y))).r;
    float limb = 0.72+0.28*sqrt(max(1.0-r*r,0.0));
    // Bright enough to bloom at the highlands, never so bright the maria clip.
    return vec3(0.90,0.93,1.0)*face*limb*min(moon_i*2.6,1.22);
}
// A direction's point on a flat cloud layer, in tile units. `lift` keeps the
// horizon finite (mipmaps absorb the squeeze there); `scale` sets how many
// tiles the layer spans.
vec2 sky_plane(vec3 d, float lift, float scale) {
    return d.xz/(max(d.y,0.0)+lift)*scale;
}
// Cloud layers over `bg`, highest first: cirrus, altocumulus, then lit
// cumulus blending into the overcast deck. `alpha` returns their cover.
vec3 sky_clouds(vec3 d, vec3 bg, out float alpha) {
    alpha = 0.0;
    float y = d.y;
    if (y<=0.0) return bg;
    float fade = smoothstep(0.0,0.10,y);
    vec3 col = bg;
    // Light the sky itself sheds on cloud: a greyed blend of its colours.
    vec3 base = horizon*0.55+zenith*0.45;
    vec3 amb = mix(vec3(dot(base,vec3(0.30,0.55,0.15))),base,0.45);
    vec3 sunc = sky_sun_col*sun_i;
    vec3 moonc = vec3(0.62,0.70,0.86)*moon_i;
    vec2 dh = normalize(d.xz+vec2(1e-5));
    vec2 us = normalize(sun.xz+vec2(1e-5)), um = normalize(moon.xz+vec2(1e-5));
    float toward = dot(dh,us)*0.5+0.5;
    // Twilight from below the horizon: gold and rose on every underside,
    // strongest on the sun's side of the sky.
    vec3 under = sky_sun_col*sky_under*(0.30+0.70*toward);
    float cs = max(dot(d,sun),0.0), cm = max(dot(d,moon),0.0);
    float clear_part = 1.0-sky_overcast;
    // Cirrus: high combed fibres on clear and fair days, last to lose the
    // sunset. The Lagoon keeps its one thin stardust layer.
    float cirrus_amt = nebula_lake() ? 0.0 : clear_part*(1.0-0.75*smoothstep(0.5,1.0,cloud_cover));
    if (cirrus_amt>0.01) {
        vec2 q = sky_plane(d,0.03,0.12)+sky_drift2.xy;
        float a = smoothstep(0.58,0.92,texture(sky_cloud2,q).g)*cirrus_amt*0.70*fade;
        vec3 lit = amb*1.05+sunc*(0.22+pow(cs,6.0)*0.8)+under*2.0+moonc*(0.3+pow(cm,20.0));
        col = mix(col,lit,a);
        alpha = a;
    }
    // Altocumulus: a mid-height field of small soft lumps; a mackerel sky
    // that catches the whole sunset.
    float alto = nebula_lake() ? 0.0 : clamp((cloud_cover-0.50)*0.75,0.0,0.40)*(1.0-sky_overcast*0.7);
    if (alto>0.01) {
        vec2 q = sky_plane(d,0.05,0.28)+sky_drift.zw;
        float e = smoothstep(1.0-alto,1.30-alto,texture(sky_cloud2,q).r);
        float a = smoothstep(0.0,0.9,e)*0.62*fade;
        vec3 lit = amb*(0.98-0.18*e)+sunc*(0.24+pow(cs,6.0)*0.7*(1.0-e))+under*1.6+moonc*0.45;
        col = mix(col,lit,a);
        alpha += (1.0-alpha)*a;
    }
    // Cumulus cover for weather.py's cloud_cover (clear 0.40 -> 7 %, fair
    // 0.72 -> 34 %, overcast 1.10 -> 66 % under the deck). The baked
    // densities are near-uniform, so the threshold is one minus the cover.
    // Fair-weather cumulus are convective and thin out after dark.
    float cover = clamp(0.07+(cloud_cover-0.40)*0.85,0.02,0.97);
    cover *= 1.0-0.8*night*clear_part;
    float thr = 1.0-cover;
    // The layer's base and a second sample 25 % farther out stand in for its
    // tops: a cloud low in the sky rises as a wall above its own base.
    vec2 p = sky_plane(d,0.06,0.11);
    vec4 c0 = texture(sky_cloud,p+sky_drift.xy);
    vec4 c1 = texture(sky_cloud,p*1.25+sky_drift.xy);
    float ero = (texture(sky_cloud2,p*3.0+sky_drift2.zw).b-0.5)*0.10;
    // Optical depth above the threshold, in absolute units: sparse clouds on
    // a clear day are small and thin, a fair-weather field grows thick cores.
    float t0 = max(c0.r+ero-thr,0.0);
    float t1 = max(c1.r+ero-thr,0.0)*(1.0-smoothstep(0.25,0.85,y));
    float t = max(t0,t1);
    // 0 where we see only the flat underside, 1 for the top of a side wall.
    float wall = t1/(t0+t1+1e-4);
    float thick = 1.0-exp(-t0*7.0);
    // Optical depth toward each light: straight up for a high light, the
    // baked horizontal march (mean + gradient . direction) for a low one.
    vec2 grad = (c0.gb-0.5)*0.25;
    float low_s = clamp((1.0-sun.y)*1.3-0.3,0.0,1.0);
    float ts = mix(c0.r,c0.a+dot(us,grad),low_s);
    float tm = mix(c0.r,c0.a+dot(um,grad),clamp((1.0-moon.y)*1.3-0.3,0.0,1.0));
    float lit_s = exp(-max(ts-thr,0.0)*6.0);
    float lit_m = exp(-max(tm-thr,0.0)*6.0);
    // Under a low sun the walls facing us are lit when it is behind us and
    // in shadow when we look into it; a high sun lights tops, not bellies,
    // which stay a light blue-grey lumped by the billows above them.
    float facing = mix(1.0,mix(1.12,0.50,toward),low_s*wall);
    float belly = thick*(1.0-wall)*(1.0-low_s*0.4)*(0.7+0.6*smoothstep(0.3,0.9,c1.r));
    float sunlit = mix(0.40,1.0,lit_s)*facing*(1.0-0.40*belly);
    // Thin edges scatter forward: silver linings near the sun and moon.
    float rim = 1.0-smoothstep(0.0,0.10,t);
    float silver = (pow(cs,6.0)*0.9+pow(cs,48.0)*2.5)*rim*rim;
    vec3 lit = amb*(0.76-0.12*belly)
             + sunc*(sunlit*0.46+silver)
             + under*(1.25-0.8*wall)*(1.0-thick*0.3)
             + moonc*(lit_m*0.7+pow(cm,30.0)*rim*1.6);
    // Below a few percent cover only specks would remain: let them go.
    float a = smoothstep(0.0,nebula_lake() ? 0.12 : 0.035,t)*mix(0.97,1.0,thick)*smoothstep(0.02,0.06,cover);
    if (sky_overcast>0.0) {
        // The overcast deck: broad soft rolls in slate, flatter in rain.
        vec4 big = texture(sky_cloud,p*0.31+vec2(0.37,0.61)+sky_drift.xy*0.5);
        float rolls = mix(big.a,c0.r,0.45);
        float shade = 1.04-0.40*smoothstep(0.25,0.85,rolls)*(1.0-rain*0.5);
        // A deck glows with the light it diffuses: brighter than the sky's
        // own greyed colour by day, a heavy darker slate in rain.
        vec3 slate = amb*shade*mix(1.42,1.05,rain)
                   + sunc*0.22*pow(cs,4.0)*(1.0-rolls)
                   + moonc*0.12;
        lit = mix(lit,slate,sky_overcast*0.8);
        a = max(a,sky_overcast*0.97);
    }
    // Toward the horizon cloud thins into the haze, the sky's own colour.
    a *= mix(fade,smoothstep(0.0,0.30,y)*0.85+0.15*fade,sky_overcast);
    if (nebula_lake()) {
        // Nebula clouds are thin lilac stardust, never a gray deck.
        lit = mix(lit,vec3(0.62,0.52,0.80)*(1.0-night*0.62),0.65);
        a *= 0.62*(1.0-0.45*night);
    }
    col = mix(col,lit,a);
    alpha += (1.0-alpha)*a;
    return col;
}
// --- end sky fx ---
vec3 aurora_curtain(vec3 d) {
    float az = atan(d.z,d.x);
    float t = sky_anim;
    float base = 0.07+sin(az*3.0+t*0.05)*0.05+sin(az*7.0-t*0.03)*0.02;
    float v = (d.y-base)/(0.30+0.09*sin(az*2.0+1.3));
    float ribbon = smoothstep(0.0,0.07,v)*(1.0-smoothstep(0.30,1.0,v));
    // Soft vertical rays from one row of the baked erosion noise (six wraps
    // round the sky), sharpest at the foot and melting into a veil above.
    float rays = texture(sky_cloud2,vec2(az*0.95493+t*0.0012,0.31)).b;
    rays = mix(0.45+0.80*smoothstep(0.25,0.85,rays),0.85,smoothstep(0.25,0.9,v));
    float folds = 0.45+0.55*sin(az*11.0+t*0.07+sin(az*4.0)*2.0);
    vec3 colour = mix(vec3(0.18,0.95,0.62),vec3(0.80,0.34,0.88),smoothstep(0.25,1.0,v));
    // A bright lower hem, the way real curtains glow hottest at their foot.
    float hem = 1.0+1.2*exp(-v*9.0)*smoothstep(0.0,0.05,v);
    return colour*ribbon*rays*folds*hem*1.35;
}
vec3 nebula_sky(vec3 d, vec3 col) {
    float up = smoothstep(-0.02,0.25,d.y);
    // The gas and galaxy band are baked (skybake.frag) with finer filaments.
    vec4 gas = sky_dome_at(d);
    float glow = up*mix(0.22,0.95,starlight)*(1.0-cloud_cover*0.25);
    col += gas.rgb*glow;
    // Its brightest knots burn above display white and bloom.
    col += vec3(0.80,0.62,1.0)*gas.a*gas.a*glow*1.8;
    col += sky_stars_at(d,0.0)*starlight*up*1.5;
    if (aurora_i>0.0) col += aurora_curtain(d)*aurora_i*step(0.0,d.y)*0.85;
    if (meteors>0.0 && d.y>0.02) {
        // Eight streaks fly outward from one high radiant, restarting in turn.
        vec3 radiant = normalize(vec3(0.30,0.45,0.37));
        for (int i=0;i<8;i++) {
            float fi = float(i);
            float cycle = snow_anim*0.23+fi*0.29;
            float life = fract(cycle);
            vec2 seed = vec2(fi,floor(cycle));
            float az = hash(seed)*6.2832;
            vec3 side = normalize(cross(radiant,vec3(cos(az),0.0,sin(az))));
            vec3 start = normalize(radiant+cross(side,radiant)*(0.18+0.35*hash(seed+3.1)));
            vec3 away = normalize(start-radiant*dot(start,radiant));
            vec3 tangent = normalize(away-start*dot(away,start));
            // Angle along the streak's great circle, and distance off it.
            float along = atan(dot(d,tangent),dot(d,start));
            float off = abs(dot(d,normalize(cross(start,tangent))));
            float head = life*0.95, tail = max(0.0,head-0.16);
            float on = (1.0-smoothstep(0.0016,0.0042,off))*step(tail,along)*step(along,head);
            col += vec3(1.0,0.93,0.82)*on*(along-tail)/max(head-tail,0.001)*(1.0-life)*1.6*meteors;
        }
    }
    return col;
}
vec3 sky(vec3 d) {
    vec3 col = sky_clear(d);
    if (nebula_lake()) col = nebula_sky(d,col);
    else if (sky_night_vis>0.0 && d.y>0.0) {
        // Moonlight washes out the band and faint stars, most near the moon.
        float wash = clamp(moon_i*1.5*(0.45+0.55*exp((dot(d,moon)-1.0)*3.0)),0.0,0.85);
        float vis = sky_night_vis*smoothstep(0.0,0.22,d.y)*(1.0-sky_overcast)*(1.0-mist*0.7);
        vec4 band = sky_dome_at(d);
        col += (band.rgb+vec3(0.05,0.045,0.04)*band.a)*vis*(1.0-wash);
        col += sky_stars_at(d,0.004+wash*0.07)*vis;
    }
    col += sky_sun_disc(d);
    float cover;
    vec3 disc = sky_moon_disc(d,cover);
    col = mix(col,disc,cover);
    float alpha;
    col = sky_clouds(d,col,alpha);
    // Small angular wing strokes stay legible without the old blurry circles.
    float day = 1.0-night;
    if (day>0.35 && rain<0.8 && d.y>0.04 && !nebula_lake()) {
        float birds = 0.0;
        float aa = max(0.00045,tanx/viewport.x*1.2);
        for (int i=0;i<4;i++) {
            float fi = float(i);
            float sx = hash(vec2(fi+1.0,1.7));
            float sy = hash(vec2(fi+3.0,5.2));
            float az = (sx*2.0-1.0)*2.2+sin(sky_anim*0.15+fi)*0.35;
            float el = 0.16+sy*0.40+sin(sky_anim*0.23+fi*1.3)*0.025;
            float ce = cos(el), se = sin(el);
            vec3 bdir = vec3(cos(az)*ce,se,sin(az)*ce);
            vec3 tangent = vec3(-sin(az),0,cos(az));
            vec3 vertical = vec3(-cos(az)*se,ce,-sin(az)*se);
            vec2 p = vec2(dot(d,tangent),dot(d,vertical));
            if (dot(d,bdir)<0.999 || abs(p.x)>0.018 || abs(p.y)>0.016) continue;
            float span = 0.010+0.002*sin(fi*2.3);
            float flap = sin(sky_anim*4.5+fi*2.1)*0.005;
            float wing = segment_distance(vec2(abs(p.x),p.y),vec2(0,0),vec2(span*0.52,0.002+flap*0.65));
            wing = min(wing,segment_distance(vec2(abs(p.x),p.y),vec2(span*0.52,0.002+flap*0.65),vec2(span,flap)));
            birds += (1.0-smoothstep(0.0006,0.0006+aa,wing))*step(0.99,dot(d,bdir));
        }
        col = mix(col,vec3(0.08,0.09,0.09),clamp(birds,0.0,0.9)*day);
    }
    return col;
}
// Aerial perspective toward the clear-sky colour in the fragment's direction
// (sky_clear), so distance fog is warmer toward a low sun and cooler away.
vec3 haze(vec3 c, vec3 p) {
    vec3 ray = p-eye;
    float dist = length(ray);
    vec3 dir = ray/max(dist,0.001);
    // Clear air thins with height (90 m scale), so a far hill's foot hazes
    // more than its crest: the mean density along the ray, in closed form.
    float dy = abs(ray.y)<0.5 ? 0.5 : ray.y;
    float mean = exp(-max(eye.y,0.0)/90.0)*(1.0-exp(-dy/90.0))*90.0/dy;
    float k = mix(0.00085*(0.45+0.55*mean),0.0037,rain)+mist*0.004;
    float fog = 1.0-exp(-dist*k*mix(1.0,0.8,night));
    // Low mist hugging the water, strongest at first light and in rain.
    float low = gold*(0.10+0.10*smoothstep(-0.3,0.3,sun.x))+rain*0.12;
    fog += exp(-max(p.y,0.0)*0.22)*smoothstep(40.0,450.0,dist)*low;
    if (crater_lake()) {
        float layer = 1.0-smoothstep(3.0+mist*45.0,20.0+mist*75.0,p.y);
        fog += layer*mist*.38*smoothstep(20.0,450.0,dist);
    }
    if (comfort_fog_radius > 0.0 && distance(p.xz,boat_pos) <= comfort_fog_radius) fog *= 0.25;
    vec3 tint = sky_clear(vec3(dir.x,min(dir.y,0.03),dir.z));
    return mix(c,tint,clamp(fog,0.0,0.92+0.06*smoothstep(900.0,1800.0,dist)));
}
float lamp(vec3 p) {
    // The bow light: a soft-edged cone, bright near the boat and fading by inverse square
    // so the landing 25 m off is lit, not washed out (V1-42).
    vec2 delta = p.xz-boat_pos;
    float dist = length(delta);
    float cone = smoothstep(0.80,0.985,dot(normalize(delta+0.0001),boat_forward));
    float fall = (1.0-smoothstep(30.0,62.0,dist))/(1.0+dist*dist/256.0);
    return cone*fall*spotlight*night;
}
float lamp_facing(vec3 p, vec3 n) {
    // Faces turned toward the bow light take more of it.
    vec3 to_lamp = normalize(vec3(boat_pos.x,1.2,boat_pos.y)-p);
    return 0.35+0.65*max(dot(n,to_lamp),0.0);
}

// --- land fx ---
// Integer lattice hash: stable at world coordinates in the thousands, where
// the sin() hash above loses its fraction bits.
float land_hash(vec2 cell) {
    uvec2 q = uvec2(ivec2(floor(cell)))*uvec2(1597334673u,3812015801u);
    uint h = (q.x^q.y)*1597334673u;
    return float(h^(h>>16))*(1.0/4294967295.0);
}
float land_vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f*f*(3.0-2.0*f);
    return mix(mix(land_hash(i),land_hash(i+vec2(1,0)),u.x),
               mix(land_hash(i+vec2(0,1)),land_hash(i+vec2(1,1)),u.x),u.y);
}
float land_lum(vec3 c) { return dot(c,vec3(0.299,0.587,0.114)); }
// `c` scaled to luminance 1, then pulled `k` of the way from white: a light
// tint that never changes how bright a surface reads.
vec3 land_tint(vec3 c, float k) { return mix(vec3(1.0),c/max(land_lum(c),1e-3),k); }
vec2 land_uv(vec2 xz) { return (xz-land_domain.xy)/(land_domain.zw-land_domain.xy); }
// Share of direct sun the clouds let through: overcast and rain have none.
float land_sun_weather() { return 1.0-smoothstep(0.78,1.08,cloud_cover); }
// White at noon, amber when the sun is low and through the gold hour.
vec3 land_sun_colour() {
    vec3 c = mix(vec3(1.0,0.96,0.90),vec3(1.0,0.76,0.50),1.0-smoothstep(0.06,0.45,sun.y));
    return mix(c,vec3(1.0,0.62,0.32),gold*0.8);
}
const vec3 LAND_MOON = vec3(0.60,0.70,1.0);
// The light that casts shadows now: the sun while it is up, else the moon.
// `strength` is its direct intensity after the weather.
vec3 land_key(out float strength, out vec3 colour) {
    if (sun.y>-0.03) { strength = sun_i*land_sun_weather(); colour = land_sun_colour(); return sun; }
    strength = moon_i*0.8; colour = LAND_MOON; return moon;
}
// Occlusion at world point `p` from the baked canopy/terrain map.
// x: key-light visibility (tree crowns, docks and ridges between `p` and the
// sun or moon, soft with distance); y: sky visibility under a canopy;
// z: ground height (m) under `p`; w: canopy density over `p`.
// `taps` 0 is the reflection pass's cheap form (crowns only, near).
vec4 land_occlusion(vec3 p, float taps) {
    vec4 here = textureLod(land_shadow,land_uv(p.xz),0.5);
    float r0 = max(here.r,0.004);
    float top = here.a+here.g/r0;
    // Ground under trees and posts under a dock lose sky; a deck top does not.
    float amb = 1.0-0.45*here.r*(1.0-smoothstep(top-0.6,top-0.1,p.y));
    float strength; vec3 kc;
    vec3 L = land_key(strength,kc);
    float vis = 1.0;
    if (strength>0.002 && L.y>0.02) {
        float run = max(length(L.xz),1e-3);
        vec2 dir = L.xz/run;
        float tanv = L.y/run;
        // The water plane's bank crack lies under the bank's surface.
        float y0 = max(p.y,here.a);
        float texel = (land_domain.z-land_domain.x)/float(textureSize(land_shadow,0).x);
        float occ = 0.0, rock = 0.0;
        int crowns = taps>0.5 ? 5 : 3;
        for (int k=0; k<crowns; k++) {
            float rise = k==0 ? 1.5 : k==1 ? 4.0 : k==2 ? 7.5 : k==3 ? 12.0 : 19.0;
            float s = rise/tanv;
            if (s>260.0) break;
            vec4 t = textureLod(land_shadow,land_uv(p.xz+dir*s),log2(max(1.0,(0.3+s*0.05)/texel)));
            float rr = max(t.r,0.004);
            float ry = y0+rise;
            float ct = t.a+t.g/rr, cb = t.a+t.b/rr;
            occ = max(occ,t.r*smoothstep(cb-1.5,cb+0.5,ry)*(1.0-smoothstep(ct-0.5,ct+1.5,ry)));
            rock = max(rock,smoothstep(-0.3,1.2,t.a-ry));
        }
        if (taps>0.5) {
            // Ridges and canyon walls: long taps that only test the ground.
            for (int k=0; k<3; k++) {
                float s = k==0 ? 35.0 : k==1 ? 95.0 : 230.0;
                float g = textureLod(land_shadow,land_uv(p.xz+dir*s),log2(max(1.0,(1.0+s*0.06)/texel))).a;
                rock = max(rock,smoothstep(-1.0,3.0,g-(y0+s*tanv)));
            }
        }
        vis = (1.0-0.88*occ)*(1.0-rock);
    }
    return vec4(vis,amb,here.a,here.r);
}
// Sky seen along direction `r`, cheap: no clouds, a soft sun lobe, and the
// lake's own colour below the horizon.
vec3 land_env(vec3 r) {
    vec3 c = mix(horizon*1.05,zenith,smoothstep(-0.05,0.55,r.y));
    c = mix(mix(lake_water*0.7,horizon*0.6,0.5),c,smoothstep(-0.25,0.02,r.y));
    c += land_sun_colour()*pow(max(dot(r,sun),0.0),24.0)*sun_i*land_sun_weather()*0.5;
    return c;
}
// Full lighting model behind shade_surface. `v` points to the viewer,
// `vis` is key-light visibility (0 in shadow), `metal` 0-1 tints reflections
// by the albedo, and a non-zero `brush` is a unit tangent that stretches the
// highlight across it (brushed aluminium).
vec3 land_light(vec3 albedo, vec3 n, vec3 v, vec3 p, float ao, float vis,
                float gloss, float metal, float cockpit, vec3 brush) {
    float wsun = land_sun_weather();
    float level = mix(0.67,0.14,night)+moon_i*0.10+starlight*night*0.22;
    // The player's own boat keeps a brighter floor so the deck reads at night.
    if (cockpit>0.5) level = mix(0.74,0.29,night)+moon_i*0.07+starlight*night*0.12;
    level += (1.0-wsun)*0.11*(1.0-night);
    // Hemisphere ambient: sky from above, lake and ground bounce from below.
    vec3 skyc = land_tint(mix(horizon,zenith,0.6),0.42)*1.04;
    vec3 lowc = land_tint(mix(lake_water,horizon,0.45),0.30)*0.70;
    vec3 amb = level*mix(lowc,skyc,clamp(n.y*0.5+0.5,0.0,1.0));
    float wrap_s = max(0.0,(dot(n,sun)+0.15)/1.15);
    vec3 sunc = land_sun_colour()*sun_i*wsun*0.52;
    float strength; vec3 keyc;
    vec3 L = land_key(strength,keyc);
    float sun_key = sun.y>-0.03 ? 1.0 : 0.0;
    float wrap_m = max(0.0,(dot(n,moon)+0.3)/1.3);
    vec3 moonc = LAND_MOON*moon_i*0.42*mix(vis,1.0,sun_key);
    vec3 c = albedo*(amb*ao+sunc*wrap_s*mix(1.0,vis,sun_key)+moonc*wrap_m*mix(1.0,ao,0.5));
    // A cool rim on upright edges keeps silhouettes legible by moon and stars.
    float rim = pow(1.0-clamp(dot(n,v),0.0,1.0),3.0)*(1.0-abs(n.y)*0.8);
    c += (0.25+albedo)*vec3(0.55,0.66,0.95)*rim*(moon_i*0.55+starlight*night*0.30)*(0.4+0.6*ao);
    if (gloss>0.0) {
        vec3 h = normalize(L+v);
        float nh = max(dot(n,h),0.0);
        if (dot(brush,brush)>0.5) { float th = dot(brush,h); nh = mix(nh,sqrt(max(1.0-th*th,0.0)),0.7); }
        float power = mix(10.0,170.0,gloss*gloss);
        float spec = pow(nh,power)*(power+6.0)/40.0*gloss*strength*vis*smoothstep(0.0,0.12,dot(n,L));
        c += keyc*mix(vec3(1.0),albedo/max(land_lum(albedo),0.05),metal*0.6)*spec;
        // Sky sheen at grazing angles, everywhere on metal.
        vec3 env = land_env(reflect(-v,n))*mix(vec3(1.0),albedo*1.3,metal);
        float fres = pow(1.0-clamp(dot(n,v),0.0,1.0),5.0);
        float k = gloss*mix(0.04+0.8*fres,0.5,metal)*mix(0.35,1.0,ao);
        c = mix(c,env,clamp(k,0.0,0.8));
    }
    c += vec3(0.75,0.63,0.37)*lamp(p)*smoothstep(2.5,6.0,length(p.xz-boat_pos));
    return c;
}
// One baked ground sample: albedo, shading normal, cavity AO, gloss and
// crystal glow (0-1). `detail` 0-1 blends in the tiling micro map near the eye.
struct LandGround { vec3 albedo; vec3 n; float ao; float gloss; float glow; };
LandGround land_ground(vec3 p, float sd, float detail) {
    vec2 uv = land_uv(p.xz);
    vec4 a = texture(land_groundmap,vec3(uv,0.0));
    vec4 b = texture(land_groundmap,vec3(uv,1.0));
    LandGround g;
    vec2 nxz = b.rg*2.0-1.0;
    g.n = vec3(nxz.x,sqrt(max(1.0-dot(nxz,nxz),0.0)),nxz.y);
    g.ao = b.b;
    // Gloss is stored up to 0.8; above 0.82 the texel is a glowing crystal.
    g.gloss = min(b.a,0.8);
    g.glow = clamp((b.a-0.82)/0.18,0.0,1.0);
    g.albedo = a.rgb;
    if (detail>0.0) {
        float k = clamp(a.a,0.0,1.0)*3.0;
        float l0 = floor(min(k,2.999));
        vec2 duv = p.xz*(1.0/6.0);
        vec4 d = mix(texture(land_detail,vec3(duv,l0)),texture(land_detail,vec3(duv,l0+1.0)),k-l0);
        g.n = normalize(g.n+vec3(d.r*2.0-1.0,0.0,d.g*2.0-1.0)*detail);
        g.albedo *= mix(1.0,0.6+0.8*d.b,detail*0.85);
    }
    // Wet within about a metre of the waterline, and everywhere in rain.
    float wet = clamp((1.0-smoothstep(0.0,1.1,sd))*(1.0-smoothstep(0.6,1.6,p.y))+rain*0.35,0.0,1.0);
    g.albedo *= 1.0-0.38*wet;
    g.gloss = max(g.gloss,wet*0.5);
    if (nebula_lake()) g.albedo += vec3(.05,.04,.10)*night;
    return g;
}
// Unlit ground colour at world point `p`, `sd` metres inland of the shore.
// The terrain and the water plane's bank crack both read the same bake, so
// they match; valid at p.y == 0.
vec3 ground_albedo(vec3 p, float sd) {
    return land_ground(p,sd,0.0).albedo;
}
// Lit colour of an opaque surface with normal `n` at world point `p`.
// `ao` darkens ambient (1 = open), `gloss` is 0 for matte up to 1 for
// polished, and `cockpit` is 1 for the player's own boat, which keeps a
// brighter ambient floor so the deck stays readable at night. Shadows from
// the baked canopy and terrain are applied here.
vec3 shade_surface(vec3 albedo, vec3 n, vec3 p, float ao, float gloss, float cockpit) {
    vec4 occ = land_occlusion(p,mirror>0.0 ? 1.0 : 0.0);
    vec3 v = normalize(vec3(eye.x,eye.y*mirror,eye.z)-p);
    return land_light(albedo,n,v,p,ao*occ.y,occ.x,gloss,0.0,cockpit,vec3(0.0));
}
// --- end land fx ---

// --- flora fx ---
// How much of a surface at `p` aerial perspective replaces with the horizon
// (0 near, toward 0.92 far): lets multiplicative shading fade like colour.
float flora_haze_amount(vec3 p) {
    return clamp(dot(haze(vec3(0.0),p),horizon)/max(dot(horizon,horizon),1e-4),0.0,1.0);
}
// --- end flora fx ---

// --- water fx ---
// Fresnel reflectance of water (n = 1.33) for the cosine between the view
// and the facet normal; Schlick's fit with F0 = 0.02.
float water_fresnel(float cosine) {
    float m = 1.0-clamp(cosine,0.0,1.0);
    float m2 = m*m;
    return 0.02+0.98*m2*m2*m;
}
// Radiance of a light's glitter on the water for unit light strength.
// Facet slopes are Gaussian around the resolved slope `mean` with per-axis
// variance `variance` (from the mipmapped slope^2), so near water sparkles
// facet by facet and far water merges into one smooth path.
float water_glitter(vec3 v, vec3 l, vec2 mean, float variance) {
    if (l.y<-0.02) return 0.0;
    vec3 h = normalize(v+l);
    vec2 facet = -h.xz/max(h.y,0.08);
    vec2 d = facet-mean;
    float density = exp(-dot(d,d)/(2.0*variance))/(6.2832*variance);
    float h2 = h.y*h.y;
    return water_fresnel(dot(v,h))*density/(4.0*max(v.y,0.035)*h2*h2)*smoothstep(-0.02,0.04,l.y);
}
// --- end water fx ---

// --- particle fx ---
// --- end particle fx ---
