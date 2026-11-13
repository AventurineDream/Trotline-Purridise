// Bloom pyramid, downward step: halve `src`. The first step also keeps only
// light above the display white point, so unlit scenery never glows.
uniform sampler2D src;
uniform float prefilter;
in vec2 uv;
out vec4 frag;
const float BLOOM_THRESHOLD = 0.92, BLOOM_KNEE = 0.20;
vec3 bright(vec3 c) {
    float peak = max(c.r,max(c.g,c.b));
    float soft = clamp(peak-BLOOM_THRESHOLD+BLOOM_KNEE,0.0,2.0*BLOOM_KNEE);
    soft = soft*soft/(4.0*BLOOM_KNEE);
    return c*max(soft,peak-BLOOM_THRESHOLD)/max(peak,0.0001);
}
void main() {
    vec2 px = 1.0/vec2(textureSize(src,0));
    vec3 a = texture(src,uv+px*vec2(-1,-1)).rgb;
    vec3 b = texture(src,uv+px*vec2( 1,-1)).rgb;
    vec3 c = texture(src,uv+px*vec2(-1, 1)).rgb;
    vec3 d = texture(src,uv+px*vec2( 1, 1)).rgb;
    if (prefilter>0.5) {
        a = bright(a); b = bright(b); c = bright(c); d = bright(d);
        // Weighting by inverse brightness keeps one glittering pixel from
        // flickering the whole glow as it moves between samples.
        vec4 w = 1.0/(1.0+vec4(max(a.r,max(a.g,a.b)),max(b.r,max(b.g,b.b)),
                               max(c.r,max(c.g,c.b)),max(d.r,max(d.g,d.b))));
        frag = vec4((a*w.x+b*w.y+c*w.z+d*w.w)/(w.x+w.y+w.z+w.w),1);
        return;
    }
    frag = vec4((a+b+c+d)*0.25,1);
}
