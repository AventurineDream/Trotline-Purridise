uniform vec3 eye, view_right, view_up, view_forward;
uniform float tanx, tany, anim, sun_i, moon_i, night, gold;
uniform vec3 sun, moon, horizon, zenith;
uniform vec2 viewport, boat_pos, boat_forward, slip_origin, slip_inland, slip_side;
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
// Point stars fixed to the dome. Two sizes, gently twinkling unless motion
// is reduced (snow_anim is held at zero then).
float star_field(vec3 d, float density) {
    vec3 cell = floor(d*430.0);
    float h = hash(cell.xy+cell.z*17.13);
    float big = step(1.0-0.0026*density,h);
    vec3 fine = floor(d*900.0);
    float small = step(1.0-0.0042*density,hash(fine.xz+fine.y*7.77))*0.55;
    return max(big,small)*(0.78+0.22*sin(snow_anim*2.3+h*61.0));
}
vec3 aurora_curtain(vec3 d) {
    float az = atan(d.z,d.x);
    float t = snow_anim;
    float base = 0.07+sin(az*3.0+t*0.05)*0.05+sin(az*7.0-t*0.03)*0.02;
    float v = (d.y-base)/(0.30+0.09*sin(az*2.0+1.3));
    float ribbon = smoothstep(0.0,0.07,v)*(1.0-smoothstep(0.30,1.0,v));
    float rays = 0.45+0.55*noise(vec2(az*42.0+t*0.09,v*1.5));
    float folds = 0.45+0.55*sin(az*11.0+t*0.07+sin(az*4.0)*2.0);
    vec3 colour = mix(vec3(0.18,0.95,0.62),vec3(0.80,0.34,0.88),smoothstep(0.25,1.0,v));
    return colour*ribbon*rays*folds;
}
vec3 nebula_sky(vec3 d, vec3 col) {
    float up = smoothstep(-0.02,0.25,d.y);
    vec2 p = d.xz/(abs(d.y)+0.55)*1.7;
    float gas_a = fbm(p*0.9+vec2(3.1,1.7)+anim*0.0004);
    float gas_b = fbm(p*1.7-vec2(5.3,2.2));
    vec3 gas = vec3(0.42,0.18,0.62)*smoothstep(0.45,0.85,gas_a)
             + vec3(0.10,0.42,0.50)*smoothstep(0.52,0.90,gas_b);
    // A galaxy band crosses the sky on one fixed great circle.
    float band = exp(-square(dot(d,vec3(0.4153,0.5440,-0.7290)))/0.03);
    gas += vec3(0.55,0.47,0.72)*band*(0.30+0.70*fbm(p*3.1));
    col += gas*up*mix(0.22,0.95,starlight)*(1.0-cloud_cover*0.25);
    col += vec3(0.85,0.88,1.0)*star_field(d,1.0+band*2.0)*starlight*up;
    col += aurora_curtain(d)*aurora_i*step(0.0,d.y)*0.85;
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
    float h = smoothstep(-0.04, 0.9, d.y);
    vec3 col = mix(horizon, zenith, h);
    float s = max(dot(d, sun), 0.0);
    col += vec3(1.0,0.68,0.33)*pow(s,24.0)*sun_i*0.23;
    col += vec3(1.0,0.85,0.53)*smoothstep(0.99945,0.99985,s)*sun_i*1.6*(1.0-rain*0.9);
    col += vec3(0.30,0.13,0.04)*gold*exp(-square(d.y-0.03)/0.025);
    float m = max(dot(d, moon),0.0);
    col += vec3(0.71,0.80,0.96)*smoothstep(0.99965,0.99987,m)*moon_i*1.4;
    if (nebula_lake()) col = nebula_sky(d,col);
    if (d.y>0.015) {
        vec2 p = d.xz/(d.y+0.22)*1.3+vec2(anim*0.002,0);
        float n = fbm(p);
        float cloud = smoothstep(0.48-cloud_cover*0.10,0.68,n)*cloud_cover;
        cloud *= smoothstep(0.015,0.16,d.y);
        vec3 white = mix(vec3(0.92,0.92,0.88),vec3(0.11,0.15,0.23),night);
        white = mix(white,vec3(0.40,0.45,0.48)*(1.0-night*0.65),rain*0.55);
        white += gold*vec3(0.18,0.07,0.0);
        // Nebula clouds are thin lilac stardust, never a gray deck.
        if (nebula_lake()) white = mix(white,vec3(0.62,0.52,0.80)*(1.0-night*0.62),0.65);
        col = mix(col,white,cloud*(nebula_lake() ? 0.42 : 0.68));
        float stars = step(0.9983,hash(floor(d.xz/(d.y+0.35)*620.0)));
        float visibility = 1.0-smoothstep(0.72,1.2,cloud_cover);
        if (!nebula_lake()) col += stars*night*max(0.0,1.0-cloud)*visibility*vec3(0.44,0.51,0.61);
    }
    // Small angular wing strokes stay legible without the old blurry circles.
    float day = 1.0-night;
    if (day>0.35 && rain<0.8 && d.y>0.04 && !nebula_lake()) {
        float birds = 0.0;
        float aa = max(0.00045,tanx/viewport.x*1.2);
        for (int i=0;i<4;i++) {
            float fi = float(i);
            float sx = hash(vec2(fi+1.0,1.7));
            float sy = hash(vec2(fi+3.0,5.2));
            float az = (sx*2.0-1.0)*2.2+sin(anim*0.15+fi)*0.35;
            float el = 0.16+sy*0.40+sin(anim*0.23+fi*1.3)*0.025;
            float ce = cos(el), se = sin(el);
            vec3 bdir = vec3(cos(az)*ce,se,sin(az)*ce);
            vec3 tangent = vec3(-sin(az),0,cos(az));
            vec3 vertical = vec3(-cos(az)*se,ce,-sin(az)*se);
            vec2 p = vec2(dot(d,tangent),dot(d,vertical));
            if (dot(d,bdir)<0.999 || abs(p.x)>0.018 || abs(p.y)>0.016) continue;
            float span = 0.010+0.002*sin(fi*2.3);
            float flap = sin(anim*4.5+fi*2.1)*0.005;
            float wing = segment_distance(vec2(abs(p.x),p.y),vec2(0,0),vec2(span*0.52,0.002+flap*0.65));
            wing = min(wing,segment_distance(vec2(abs(p.x),p.y),vec2(span*0.52,0.002+flap*0.65),vec2(span,flap)));
            birds += (1.0-smoothstep(0.0006,0.0006+aa,wing))*step(0.99,dot(d,bdir));
        }
        col = mix(col,vec3(0.08,0.09,0.09),clamp(birds,0.0,0.9)*day);
    }
    return col;
}
vec3 haze(vec3 c, vec3 p) {
    float dist = distance(p,eye);
    float fog = 1.0-exp(-dist*(mix(0.00085,0.0037,rain)+mist*0.004));
    // Low mist, strongest at first light and in rain.
    fog += exp(-max(p.y,0.0)*0.25)*smoothstep(45.0,500.0,dist)*(gold*0.13+rain*0.1);
    if (crater_lake()) {
        float layer = 1.0-smoothstep(3.0+mist*45.0,20.0+mist*75.0,p.y);
        fog += layer*mist*.38*smoothstep(20.0,450.0,dist);
    }
    if (comfort_fog_radius > 0.0 && distance(p.xz,boat_pos) <= comfort_fog_radius) fog *= 0.25;
    return mix(c,horizon,clamp(fog,0.0,0.92));
}
float lamp(vec3 p) {
    vec2 delta = p.xz-boat_pos;
    float dist = length(delta);
    float cone = smoothstep(0.91,0.995,dot(normalize(delta+0.0001),boat_forward));
    return cone*pow(max(0.0,1.0-dist/62.0),2.0)*spotlight*night;
}
