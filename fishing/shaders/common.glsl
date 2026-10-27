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

// Signed distances must not use pow(x, 2): GLSL leaves negative bases undefined.
float square(float x) { return x*x; }

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
vec3 sky(vec3 d) {
    float h = smoothstep(-0.04, 0.9, d.y);
    vec3 col = mix(horizon, zenith, h);
    float s = max(dot(d, sun), 0.0);
    col += vec3(1.0,0.68,0.33)*pow(s,24.0)*sun_i*0.23;
    col += vec3(1.0,0.85,0.53)*smoothstep(0.99945,0.99985,s)*sun_i*1.6*(1.0-rain*0.9);
    col += vec3(0.30,0.13,0.04)*gold*exp(-square(d.y-0.03)/0.025);
    float m = max(dot(d, moon),0.0);
    col += vec3(0.71,0.80,0.96)*smoothstep(0.99965,0.99987,m)*moon_i*1.4;
    if (d.y>0.015) {
        vec2 p = d.xz/(d.y+0.22)*1.3+vec2(anim*0.002,0);
        float n = fbm(p);
        float cloud = smoothstep(0.48-cloud_cover*0.10,0.68,n)*cloud_cover;
        cloud *= smoothstep(0.015,0.16,d.y);
        vec3 white = mix(vec3(0.92,0.92,0.88),vec3(0.11,0.15,0.23),night);
        white = mix(white,vec3(0.40,0.45,0.48)*(1.0-night*0.65),rain*0.55);
        white += gold*vec3(0.18,0.07,0.0);
        col = mix(col,white,cloud*0.68);
        float stars = step(0.9983,hash(floor(d.xz/(d.y+0.35)*620.0)));
        float visibility = 1.0-smoothstep(0.72,1.2,cloud_cover);
        col += stars*night*max(0.0,1.0-cloud)*visibility*vec3(0.44,0.51,0.61);
    }
    // Small angular wing strokes stay legible without the old blurry circles.
    float day = 1.0-night;
    if (day>0.35 && rain<0.8 && d.y>0.04) {
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
    if (lake_kind>3.5) {
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
