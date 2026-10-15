uniform sampler2D reflection;
uniform vec4 line_segments[5];
uniform float line_heat[5];
uniform int line_count;
uniform vec4 ripples[4];
uniform int ripple_count;
in vec3 pos;
out vec4 frag;
void main() {
    float sd = shore(pos.xz);
    bool slip = in_slip(pos.xz);
    if (sd>=0.0 && !slip) discard;
    float dist = distance(pos,eye);
    float fine = 1.0-smoothstep(20.0,160.0,dist);
    float a = dot(pos.xz,vec2(0.24,0.17))+anim*0.55;
    float b = dot(pos.xz,vec2(-0.17,0.31))-anim*0.39;
    float micro = sin(pos.x*2.4+pos.z*1.8+anim*1.6)*fine;
    float ripple = 1.0+rain*0.5;
    vec3 n = normalize(vec3((cos(a)*0.028+micro*0.008)*ripple,1,
                            (cos(b)*0.025+micro*0.006)*ripple));
    vec3 v = normalize(eye-pos);
    float fres = 0.12+0.78*pow(1.0-max(dot(v,n),0.0),4.0);
    vec2 screen = gl_FragCoord.xy/viewport;
    vec2 distortion = n.xz*0.045*vec2(1.0,0.65);
    vec3 reflected = texture(reflection,clamp(screen+distortion,0.002,0.998)).rgb;
    float depth = 0.5+5.0*(1.0-exp(min(sd,0.0)/28.0));
    depth += 10.0*exp(-dot(pos.xz-vec2(75,-28),pos.xz-vec2(75,-28))/(2.0*72.0*72.0));
    if (lake_kind>0.5) depth = texture(lake_depth,lake_uv(pos.xz)).r;
    vec3 body = mix(vec3(0.22,0.32,0.23),vec3(0.035,0.14,0.16),smoothstep(0.5,8.0,depth));
    if (lake_kind>0.5) {
        float upper = smoothstep(-0.25,0.6,lake_uv(pos.xz).y);
        body = mix(vec3(0.055,0.20,0.23),vec3(0.26,0.27,0.17),upper*0.65);
        body = mix(body,vec3(0.31,0.31,0.22),1.0-smoothstep(0.5,3.0,depth));
    }
    body *= mix(0.85,0.30,night)+moon_i*0.1;
    vec3 c = mix(body,reflected,fres);
    vec3 r = reflect(-v,n);
    float spec = pow(max(dot(r,sun),0.0),240.0)*sun_i;
    spec *= 0.5+0.5*sin(a*3.2+b*2.5);
    c += vec3(1.0,0.79,0.47)*spec*0.58;
    c += vec3(0.46,0.59,0.76)*pow(max(dot(r,moon),0.0),180.0)*moon_i*0.48;
    float edge = exp(-pow(sd+0.2,2.0)*3.0)*(0.5+0.5*sin(a*2.0));
    if (!slip) c = mix(c,vec3(0.57,0.59,0.47),edge*0.16);
    // Pads, their veins and occasional flowers in the lily cove.
    vec2 cell = floor(pos.xz/2.3), f = fract(pos.xz/2.3)-0.5;
    float seed = hash(cell);
    bool cove = distance(pos.xz,lily_centre)<105.0;
    float radius = 0.17+seed*0.07;
    float leaf = 1.0-smoothstep(radius-0.025,radius,length(f));
    leaf *= step(0.64,seed)*float(cove && dist>9.0 && !slip);
    leaf *= 1.0-float(f.x>0.0 && abs(f.y)<f.x*0.2);
    vec3 pad = mix(vec3(0.07,0.20,0.09),vec3(0.24,0.35,0.13),seed);
    pad += vec3(0.06,0.07,0.015)*exp(-abs(f.y)*100.0);
    c = mix(c,pad*mix(1.0,0.25,night),leaf);
    float flower = (1.0-smoothstep(0.0,0.028,length(f)))*step(0.94,seed)*leaf;
    c = mix(c,vec3(0.91,0.77,0.48),flower);
    for (int i=0;i<line_count;i++) {
        vec2 ab = line_segments[i].zw-line_segments[i].xy;
        float t = clamp(dot(pos.xz-line_segments[i].xy,ab)/max(dot(ab,ab),0.001),0.0,1.0);
        float d = distance(pos.xz,line_segments[i].xy+ab*t);
        float width = max(0.045,fwidth(d)*0.8);
        float rope = 1.0-smoothstep(width*0.5,width,d);
        c = mix(c,vec3(0.19,0.16,0.10),rope*0.65);
        float heat = line_heat[i];
        float travel = 0.5+0.5*sin(t*16.0-anim*2.4);
        c += vec3(0.86,0.70,0.32)*rope*heat*travel*0.85;
        c += vec3(0.72,0.58,0.24)*exp(-d*d/0.22)*heat*(0.25+0.75*travel)*0.18;
    }
    // Wake and rise rings are color on the same plane. Depth stays put, and
    // the rings follow anim so a held weather pair does not swim.
    vec2 rel = pos.xz-boat_pos;
    float along = dot(rel,boat_forward);
    float side = length(rel-boat_forward*along);
    float behind = -along;
    float spd = clamp(abs(speed)/2.0,0.0,1.0);
    float spread = 0.38+behind*0.10;
    float rail = exp(-pow(side-spread,2.0)/(0.045+behind*0.010));
    float wake = rail*smoothstep(0.55,1.3,behind)*(1.0-smoothstep(5.0,16.0,behind))*spd;
    float streak = exp(-pow(side,2.0)/0.07)*smoothstep(0.25,0.9,behind)*(1.0-smoothstep(2.2,9.0,behind))*spd;
    c = mix(c,vec3(0.74,0.80,0.76),clamp(wake*0.62+streak*0.38,0.0,0.7));
    if (!slip) {
        float rises = 0.0;
        for (int i=0;i<5;i++) {
            float fi = float(i);
            float sx = hash(vec2(fi+1.0,2.3));
            float sz = hash(vec2(fi+4.0,8.1));
            float life = fract(anim*0.07+sx);
            vec2 center = boat_pos+vec2(sx*2.0-1.0,sz*2.0-1.0)*vec2(28.0,22.0);
            center += vec2(sin(anim*0.15+fi),cos(anim*0.11+fi*1.7))*6.0;
            if (distance(center,boat_pos)<9.0) continue;
            float rad = life*2.4;
            float ring = exp(-pow((distance(pos.xz,center)-rad)/0.085,2.0));
            rises += ring*(1.0-smoothstep(0.62,1.0,life));
        }
        c = mix(c,vec3(0.78,0.84,0.80),clamp(rises,0.0,0.7)*0.5);
    }
    // Bite and idle rises. Age is computed on the CPU. An empty list draws nothing.
    for (int i=0;i<4;i++) {
        if (i>=ripple_count) break;
        float age = ripples[i].z;
        float rad = 0.4+age*2.4;
        float d = distance(pos.xz,ripples[i].xy);
        float ring = exp(-pow(d-rad,2.0)/0.25)*(1.0-clamp(age/2.4,0.0,1.0));
        c += ring*0.35;
    }
    c += vec3(0.65,0.55,0.33)*lamp(pos)*0.35;
    c = haze(c,pos);
    frag = vec4(c,1);
}
