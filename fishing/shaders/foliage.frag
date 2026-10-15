uniform sampler2DArray atlas;
in vec2 uv;
in vec3 pos;
flat in float layer, shade;
out vec4 frag;
void main() {
    vec4 tex = texture(atlas,vec3(uv,layer));
    if (tex.a<0.42) discard;
    float light = mix(0.88,0.18,night)+sun_i*0.14+moon_i*0.18;
    vec3 c = tex.rgb*shade*light;
    c += vec3(0.07,0.035,0.005)*gold*uv.y;
    c += vec3(0.32,0.25,0.12)*lamp(pos);
    frag = vec4(haze(c,pos),1);
}
