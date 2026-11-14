uniform sampler2D scene;
#if HDR
uniform sampler2D bloom;
const float BLOOM_STRENGTH = 0.11;
// Identity up to SHOULDER, then a smooth roll-off that reaches white only at
// infinity, so authored colours are untouched and highlights keep their hue.
const float SHOULDER = 0.80;
vec3 tone(vec3 c) {
    vec3 over = max(c-SHOULDER,0.0);
    return min(c,vec3(SHOULDER))+(1.0-SHOULDER)*(1.0-exp(-over/(1.0-SHOULDER)));
}
#endif
in vec2 uv;
out vec4 frag;
void main() {
    vec2 px = 1.0/vec2(textureSize(scene,0));
    vec3 c = texture(scene,uv).rgb;
    vec3 a = texture(scene,uv+vec2(px.x,0)).rgb;
    vec3 b = texture(scene,uv-vec2(px.x,0)).rgb;
    vec3 d = texture(scene,uv+vec2(0,px.y)).rgb;
    vec3 e = texture(scene,uv-vec2(0,px.y)).rgb;
    float contrast = length(max(max(a,b),max(d,e))-min(min(a,b),min(d,e)));
    c = mix(c,(a+b+d+e+c*2.0)/6.0,smoothstep(0.16,0.6,contrast)*0.25);
#if HDR
    c += texture(bloom,uv).rgb*BLOOM_STRENGTH;
    c = tone(c);
#else
    vec3 bloom = max(texture(scene,uv+px*vec2(3,2)).rgb-0.78,0.0)
               +max(texture(scene,uv+px*vec2(-3,2)).rgb-0.78,0.0)
               +max(texture(scene,uv+px*vec2(3,-2)).rgb-0.78,0.0)
               +max(texture(scene,uv-px*vec2(3,2)).rgb-0.78,0.0);
    c += bloom*0.05;
#endif
    c = pow(max(c,0.0),vec3(0.95));
    c *= vec3(1.025,1.005,0.97);
    float vignette = smoothstep(0.35,0.83,length((uv-0.5)*vec2(1.0,0.8)));
    c *= 1.0-vignette*0.12;
    // Rain lives in the foreground. Neither terrain nor camera moves.
    if (rain>0.0) {
        vec2 p = vec2(uv.x*130.0+uv.y*12.0,uv.y*24.0+anim*10.0);
        float streak = step(0.988,hash(vec2(floor(p.x),floor(p.y))))*
                       (1.0-smoothstep(0.02,0.07,fract(p.x)))*smoothstep(0.15,0.8,fract(p.y));
        c = mix(c,vec3(0.64,0.71,0.73),streak*0.25*rain);
    }
    if (snow>0.0) {
        vec2 p = vec2(uv.x*28.0+sin(uv.y*6.0+snow_anim*.18)*.18,uv.y*18.0+snow_anim*.20);
        vec2 cell = floor(p);
        vec2 centre = vec2(.18+.64*hash(cell),.18+.64*hash(cell+3.7));
        float flake = (1.0-smoothstep(.018,.055,length(fract(p)-centre)))*step(.78,hash(cell+8.1));
        c = mix(c,vec3(.85,.90,.94),flake*snow*.65);
    }
#if HDR
    // Half a code value of fixed noise hides banding in sky and haze gradients.
    c += (hash(gl_FragCoord.xy)+hash(gl_FragCoord.xy+17.3)-1.0)/255.0;
#endif
    frag = vec4(clamp(c,0.0,1.0),1);
}
