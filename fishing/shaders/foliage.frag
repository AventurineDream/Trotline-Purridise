uniform sampler2DArray atlas;
in vec2 uv;
in vec3 pos;
flat in float layer, shade;
out vec4 frag;
void main() {
    vec4 tex = texture(atlas,vec3(uv,layer));
    if (tex.a<0.42) discard;
    float light = mix(0.88,0.18,night)+sun_i*0.14+moon_i*0.18+starlight*night*0.22;
    float glow = shade < 0.0 ? 1.0 : 0.0;
    // Shade 2..3 marks a self-lit Nebula crystal; its emission is shade - 2.
    float self_lit = shade >= 1.5 ? clamp(shade-2.0,0.0,1.0) : 0.0;
    vec3 c = tex.rgb*(shade >= 1.5 ? 1.0 : abs(shade))*mix(light,1.3,glow);
    c += tex.rgb*self_lit*(0.35+0.85*night);
    c += vec3(0.07,0.035,0.005)*gold*uv.y;
    c += vec3(0.32,0.25,0.12)*lamp(pos);
    frag = vec4(haze(c,pos)+vec3(0.18,0.14,0.06)*glow,1);
}
