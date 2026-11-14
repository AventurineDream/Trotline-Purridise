// Coat patterns from object-space noise and masks, with no per-cat textures.
// fishing/catmesh.py coat_weights() is the reference; keep the two in step.
in vec3 pos, normal, coat, coat_n, color;
in float along, glow;
flat in float part;
uniform int pattern;
uniform vec3 coat_base, coat_secondary, coat_accent;
uniform float coat_scale, coat_glow;
out vec4 frag;

const float TORSO=0., HEAD=1., MUZZLE=2., EAR=5., ARM_UPPER=8., FOREARM=9., PAW=10., LEG=11., FOOT=12.,
            TAIL=13., RUFF=17., FOREARM_WAVE=18., PAW_WAVE=19.;
bool is(float a, float b) { return abs(a-b) < 0.5; }
float hash3(vec3 p) {
    // Match catmesh._hash3 with integer mixing, avoiding sin phase differences.
    uvec3 q = uvec3(ivec3(floor(p*10.0+0.5)));
    uint h = q.x*0x8DA6B343u ^ q.y*0xD8163841u ^ q.z*0xCB1AB31Fu;
    h ^= h >> 16;
    h *= 0x7FEB352Du;
    h ^= h >> 15;
    h *= 0x846CA68Bu;
    h ^= h >> 16;
    return float(h >> 8) * (1.0/16777216.0);
}
float noise3(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f*f*(3.0-2.0*f);
    float x00 = mix(hash3(i), hash3(i+vec3(1,0,0)), f.x);
    float x10 = mix(hash3(i+vec3(0,1,0)), hash3(i+vec3(1,1,0)), f.x);
    float x01 = mix(hash3(i+vec3(0,0,1)), hash3(i+vec3(1,0,1)), f.x);
    float x11 = mix(hash3(i+vec3(0,1,1)), hash3(i+vec3(1,1,1)), f.x);
    return mix(mix(x00,x10,f.y), mix(x01,x11,f.y), f.z);
}
bool fur(float k) {
    return is(k,TORSO)||is(k,HEAD)||is(k,MUZZLE)||is(k,EAR)||is(k,ARM_UPPER)||is(k,FOREARM)||is(k,PAW)
        ||is(k,LEG)||is(k,FOOT)||is(k,TAIL)||is(k,RUFF)||is(k,FOREARM_WAVE)||is(k,PAW_WAVE);
}

vec2 coat_weights(vec3 p, vec3 n, float k, float a) {
    float sec = 0.0, acc = 0.0;
    bool body = is(k,TORSO) || is(k,RUFF);
    bool belly = body && n.z > 0.25 && p.y < 0.36;
    float chest = smoothstep(0.15,0.55,n.z)*float(body)*float(p.y < 0.40);
    float muzzle = float(is(k,MUZZLE));
    float paws = float(is(k,PAW)||is(k,PAW_WAVE)||is(k,FOOT));
    bool limb = is(k,TAIL)||is(k,LEG)||is(k,ARM_UPPER)||is(k,FOREARM)||is(k,FOREARM_WAVE);
    float extremity = float(is(k,EAR)||is(k,TAIL)||is(k,PAW)||is(k,PAW_WAVE)||is(k,FOOT)||is(k,FOREARM)
                            ||is(k,FOREARM_WAVE)) + float(is(k,LEG))*smoothstep(0.5,0.9,a);
    float face = max(muzzle, float(is(k,HEAD))*smoothstep(0.55,0.85,n.z)*float(p.y < 0.51));
    float wobble = noise3(p*18.0);
    if (pattern == 1) {            // tabby
        float r = length(vec2(abs(p.x)-0.11, p.y-0.22)) + (wobble-0.5)*0.03;
        bool swirl = abs(sin(r*70.0)) < 0.45;
        bool back = abs(p.x) < 0.03 && n.z < -0.2;
        bool rings = abs(sin(a*22.0+wobble*2.0)) < 0.4;
        bool brow = is(k,HEAD) && n.z > 0.2 && p.y > 0.49 && abs(sin(p.x*160.0)) < 0.35;
        if (is(k,TORSO)) sec = float((swirl||back) && !belly);
        if (limb) sec = float(rings);
        if (brow) sec = 1.0;
    } else if (pattern == 2) {     // mackerel
        bool stripe = abs(sin(p.y*95.0+(wobble-0.5)*2.0+abs(p.x)*10.0)) < 0.32;
        bool spine = abs(p.x) < 0.025 && n.z < -0.1;
        bool rings = abs(sin(a*26.0+wobble*2.0)) < 0.38;
        if (is(k,TORSO)||is(k,HEAD)) sec = float((stripe||spine) && !belly && face < 0.5);
        if (limb) sec = float(rings);
    } else if (pattern == 7) {     // spotted
        vec3 cell = floor(p*26.0);
        vec3 local = p*26.0-cell-(0.25+0.5*vec3(hash3(cell),hash3(cell+7.1),hash3(cell+3.3)));
        sec = float(length(local) < 0.32 && hash3(cell+1.7) > 0.3 && !belly);
        if (is(k,TAIL)) sec = float(abs(sin(a*22.0)) < 0.35);
    } else if (pattern == 3 || pattern == 4) {   // calico, tortoiseshell
        bool calico = pattern == 3;
        float patches = noise3(p*(calico ? 9.0 : 22.0)) + (wobble-0.5)*0.3;
        sec = float(patches > (calico ? 0.55 : 0.5));
        if (calico) {
            acc = float(noise3(p*9.0+13.0) > 0.62 && sec < 0.5);
            bool low = belly||is(k,LEG)||is(k,FOOT)||is(k,PAW)||is(k,PAW_WAVE)||is(k,MUZZLE)||is(k,ARM_UPPER)
                       ||is(k,FOREARM)||is(k,FOREARM_WAVE);
            if (low) { sec = 0.0; acc = 0.0; }
        } else {
            acc = float(noise3(p*40.0+5.0) > 0.72)*(1.0-sec);
        }
    } else if (pattern == 5) {     // tuxedo
        acc = max(max(chest,muzzle),paws);
    } else if (pattern == 8) {     // bicolor
        acc = max(max(max(chest,muzzle),paws),
                  max(float(is(k,LEG))*smoothstep(0.3,0.6,a),
                      float(is(k,HEAD))*smoothstep(0.2,0.5,n.z)*float(p.y < 0.47)));
    } else if (pattern == 6) {     // point
        sec = clamp(extremity+face*0.9,0.0,1.0);
    }
    return vec2(sec, acc);
}

void main() {
    vec3 n = normalize(normal);
    // Thin ears and attire face either way.
    if (dot(n, eye-pos) < 0.0) n = -n;
    vec3 c = color;
    float emit = glow;
    if (fur(part)) {
        vec2 w = coat_weights(coat/coat_scale, normalize(coat_n), part, along);
        c = coat_base*(1.0-w.x-w.y) + coat_secondary*w.x + coat_accent*w.y;
        emit = max(emit, w.x*coat_glow);
    }
    float diffuse = max(dot(n,sun),0.0)*sun_i;
    float amb = mix(0.70,0.18,night)+moon_i*0.17+starlight*night*0.22;
    vec3 lit = c*(vec3(amb)+vec3(1.0,0.91,0.73)*diffuse*0.55);
    // A warm rim so cats read against the water.
    float rim = pow(1.0-abs(dot(n, normalize(eye-pos))), 3.0);
    lit += vec3(1.0,0.82,0.55)*rim*0.18*(1.0-night*0.6);
    lit += vec3(0.75,0.63,0.37)*lamp(pos)*0.6;
    lit = mix(lit, c*1.15, clamp(emit,0.0,1.0));
    frag = vec4(haze(lit,pos),1);
}
