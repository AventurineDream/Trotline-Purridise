// Multiplicative darkening where a trunk meets the ground (blend DST_COLOR,
// ZERO). It fades with the same aerial perspective `haze()` applies, so far
// banks are not ringed with dark spots.
in vec2 local;
in vec3 pos;
out vec4 frag;
void main() {
    float r = length(local);
    if (r > 1.0) discard;
    float k = 1.0-smoothstep(0.1, 1.0, r);
    k *= k;
    float fog = flora_haze_amount(pos);
    float strength = mix(0.45, 0.25, night)*(1.0-fog)*(1.0-0.35*cloud_cover);
    frag = vec4(vec3(1.0-strength*k), 1.0);
}
