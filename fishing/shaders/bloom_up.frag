// Bloom pyramid, upward step: a 3x3 tent of the coarser level, added by the
// blend state into the next finer one.
uniform sampler2D src;
in vec2 uv;
out vec4 frag;
void main() {
    vec2 px = 1.0/vec2(textureSize(src,0));
    vec3 sum = texture(src,uv).rgb*4.0;
    sum += (texture(src,uv+px*vec2(1,0)).rgb+texture(src,uv-px*vec2(1,0)).rgb
           +texture(src,uv+px*vec2(0,1)).rgb+texture(src,uv-px*vec2(0,1)).rgb)*2.0;
    sum += texture(src,uv+px).rgb+texture(src,uv-px).rgb
          +texture(src,uv+px*vec2(1,-1)).rgb+texture(src,uv+px*vec2(-1,1)).rgb;
    frag = vec4(sum/16.0,1);
}
