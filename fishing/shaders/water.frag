uniform sampler2D reflection;
uniform vec4 line_segments[8];
uniform float line_heat[8];
uniform int line_count;
uniform vec4 ripples[4];
uniform int ripple_count;
in vec3 pos;
out vec4 frag;
void main() {
    float sd = shore(pos.xz);
    bool slip = in_slip(pos.xz);
    // Opaque terrain hides this existing bounded plane. At the coarse bank's
    // raised clipped edge, shade the projected crack as land rather than
    // reflecting bright sky. No shore, depth, navigation or geometry changes.
    if (sd>=0.0 && !slip) {
        float patch = fbm(pos.xz*0.18);
        vec3 grass = mix(vec3(0.16,0.24,0.13),vec3(0.31,0.36,0.18),patch);
        vec3 earth = mix(vec3(0.38,0.31,0.21),vec3(0.57,0.48,0.33),patch);
        vec3 bank = mix(earth,grass,smoothstep(1.0,9.0,sd));
        if (lake_kind>2.5) bank = mix(vec3(.49,.50,.46),vec3(.22,.31,.23),smoothstep(2.0,16.0,sd));
        float canopy = smoothstep(3.0,12.0,sd)*(1.0-smoothstep(55.0,95.0,sd));
        bank *= 1.0-canopy*(0.12+0.18*noise(pos.xz*0.10));
        float ambient = mix(0.67,0.14,night)+moon_i*0.17;
        bank *= vec3(ambient)+vec3(1.0,0.91,0.73)*max(sun.y,0.0)*sun_i*0.52;
        bank += vec3(0.75,0.63,0.37)*lamp(pos)*smoothstep(2.5,6.0,length(pos.xz-boat_pos));
        frag = vec4(haze(bank,pos),1);
        return;
    }
    float dist = distance(pos,eye);
    float fine = 1.0-smoothstep(18.0,125.0,dist);
    float a = dot(pos.xz,vec2(0.24,0.17))+anim*0.55;
    float b = dot(pos.xz,vec2(-0.17,0.31))-anim*0.39;
    // Crossing wind ripples are shading only; the shore and depth remain fixed.
    float phase = pos.x*1.7+pos.z*2.1+anim*1.6;
    float crossphase = pos.x*3.4-pos.z*1.3-anim*1.1;
    float wave = sin(phase)*(1.0-smoothstep(0.8,2.8,fwidth(phase)));
    float crosswave = sin(crossphase)*(1.0-smoothstep(0.8,2.8,fwidth(crossphase)));
    float ripple = 1.0+rain*0.5;
    vec3 n = normalize(vec3((cos(a)*0.045+(wave*0.012+crosswave*0.006)*fine)*ripple,1,
                            (cos(b)*0.040+(wave*0.009-crosswave*0.010)*fine)*ripple));
    vec3 v = normalize(eye-pos);
    float fres = 0.12+0.78*pow(1.0-clamp(dot(v,n),0.0,1.0),4.0);
    vec2 screen = gl_FragCoord.xy/viewport;
    vec2 distortion = n.xz*0.070*vec2(1.0,0.65);
    vec3 reflected = texture(reflection,clamp(screen+distortion,0.002,0.998)).rgb;
    float depth = 0.5+5.0*(1.0-exp(min(sd,0.0)/28.0));
    depth += 10.0*exp(-dot(pos.xz-vec2(75,-28),pos.xz-vec2(75,-28))/(2.0*72.0*72.0));
    if (lake_kind>2.5) depth = texture(lake_depth,lake_uv(pos.xz)).r;
    else if (lake_kind>1.5) depth = 4.0;
    else if (lake_kind>0.5) depth = texture(lake_depth,lake_uv(pos.xz)).r;
    vec3 body = mix(vec3(0.22,0.32,0.23),vec3(0.035,0.14,0.16),smoothstep(0.5,8.0,depth));
    if (lake_kind>2.5) body = mix(alpine_shallow,alpine_deep,smoothstep(.5,20.0,depth));
    else if (lake_kind>1.5) body = lake_water;
    else if (lake_kind>0.5) {
        float upper = smoothstep(-0.25,0.6,lake_uv(pos.xz).y);
        body = mix(vec3(0.055,0.20,0.23),vec3(0.26,0.27,0.17),upper*0.65);
        body = mix(body,vec3(0.31,0.31,0.22),1.0-smoothstep(0.5,3.0,depth));
    }
    body *= mix(0.85,0.30,night)+moon_i*0.1;
    vec3 c = mix(body,reflected,fres);
    // Restrained rippled highlights give open water detail away from reflections.
    float facets = (wave*0.5+crosswave*0.5)*fine;
    c *= 1.0+facets*0.022*(1.0-night*0.7);
    vec3 r = reflect(-v,n);
    float spec = pow(max(dot(r,sun),0.0),240.0)*sun_i;
    spec *= 0.5+0.5*sin(a*3.2+b*2.5);
    c += vec3(1.0,0.79,0.47)*spec*0.58;
    c += vec3(0.46,0.59,0.76)*pow(max(dot(r,moon),0.0),180.0)*moon_i*0.48;
    float edge = exp(-square(sd+0.2)*3.0)*(0.5+0.5*sin(a*2.0));
    if (!slip) c = mix(c,vec3(0.57,0.59,0.47),edge*0.16);
    // Pads, their veins and occasional flowers in the lily cove.
    vec2 cell = floor(pos.xz/2.3), f = fract(pos.xz/2.3)-0.5;
    float seed = hash(cell);
    bool cove = distance(pos.xz,lily_centre)<105.0;
    float radius = 0.17+seed*0.07;
    float leaf = 1.0-smoothstep(radius-0.025,radius,length(f));
    leaf *= step(0.64,seed)*float(cove && dist>9.0 && !slip);
    leaf *= 1.0-float(f.x>0.0 && abs(f.y)<f.x*0.2);
    if (lake_kind>2.5) leaf = (1.0-smoothstep(.035,.075,abs(f.x)))*
        (1.0-smoothstep(.22,.38,abs(f.y)))*step(.64,seed)*float(cove && dist>9.0 && !slip);
    vec3 pad = mix(vec3(0.07,0.20,0.09),vec3(0.24,0.35,0.13),seed);
    pad += vec3(0.06,0.07,0.015)*exp(-abs(f.y)*100.0);
    c = mix(c,pad*mix(1.0,0.25,night),leaf);
    float flower = (1.0-smoothstep(0.0,0.028,length(f)))*step(0.94,seed)*leaf;
    if (lake_kind<2.5) c = mix(c,vec3(0.91,0.77,0.48),flower);
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
    // Water ahead has negative behind: keep the Gaussian variance positive.
    // An overflowing exponential multiplied by a zero fade used to poison it.
    float rail = exp(-square(side-spread)/max(0.045,0.045+behind*0.010));
    float wake = rail*smoothstep(0.55,1.3,behind)*(1.0-smoothstep(5.0,16.0,behind))*spd;
    float streak = exp(-square(side)/0.07)*smoothstep(0.25,0.9,behind)*(1.0-smoothstep(2.2,9.0,behind))*spd;
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
            float ring = exp(-square((distance(pos.xz,center)-rad)/0.085));
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
        float ring = exp(-square(d-rad)/0.25)*(1.0-clamp(age/2.4,0.0,1.0));
        c += ring*0.35;
    }
    c += vec3(0.65,0.55,0.33)*lamp(pos)*0.35;
    c = haze(c,pos);
    frag = vec4(c,1);
}
