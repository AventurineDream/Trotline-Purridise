// Atlas bake: resolve one painted layer into the two atlas layers.
// Colour is premultiplied by coverage (rgb*a, a); light is (normal xy,
// translucency or glow, AO), each mapped to 0-1 and premultiplied too, so the
// GPU's box mips average only covered texels. foliage.frag divides by alpha.
uniform sampler2D t_col, t_nrm, t_cov, t_soft;
uniform vec2 base, scale;
uniform float contact, thin_floor, edge_glow, gold;
layout(location = 0) out vec4 o_colour;
layout(location = 1) out vec4 o_light;
void main() {
    ivec2 ij = ivec2(gl_FragCoord.xy);
    float a = clamp(texelFetch(t_cov, ij, 0).r, 0.0, 1.0);
    if (a <= 0.0) { o_colour = vec4(0.0); o_light = vec4(0.0); return; }
    vec4 c = texelFetch(t_col, ij, 0);
    vec4 n = texelFetch(t_nrm, ij, 0);
    vec2 q = vec2(gl_FragCoord.x, base.y*scale.y-gl_FragCoord.y)/scale;
    // Soft fields are stored top row first, so v grows downward in design.
    vec3 soft = texture(t_soft, q/base).rgb;
    float ao = soft.r*(1.0-contact*exp(-(gl_FragCoord.y/scale.y)/7.0));
    float thin = c.a*(thin_floor+(1.0-thin_floor)*soft.g);
    if (n.a > 0.0) thin = clamp(n.a+edge_glow*soft.b, 0.0, 1.0);
    vec3 rgb = clamp(c.rgb, 0.0, 1.0);
    if (gold > 0.5 && thin > 0.05) {
        // The autumn larch: needles turn gold, bark and silhouette stay.
        float lum = dot(rgb, vec3(0.3, 0.55, 0.15));
        rgb = clamp(lum*vec3(2.15, 1.62, 0.52), 0.0, 1.0);
    }
    vec2 nxy = n.xy/sqrt(dot(n.xy, n.xy)+pow(max(n.z, 0.05), 2.0));
    o_colour = vec4(rgb*a, a);
    o_light = vec4((nxy*0.5+0.5)*a, thin*a, clamp(ao, 0.12, 1.0)*a);
}
