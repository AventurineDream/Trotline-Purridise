in vec3 pos, normal, color;
flat in float material;
out vec4 frag;
void main() {
    vec3 n = normalize(normal);
    vec3 c = color;
    float kind = mod(material,4.0);
    if (kind<0.5) {
        float sd = shore(pos.xz);
        if (sd<0.0 || in_slip(pos.xz)) discard;
        float patch = fbm(pos.xz*0.18);
        vec3 grass = mix(vec3(0.16,0.24,0.13),vec3(0.31,0.36,0.18),patch);
        vec3 earth = mix(vec3(0.38,0.31,0.21),vec3(0.57,0.48,0.33),patch);
        c = mix(earth,grass,smoothstep(1.0,9.0,sd));
        c = mix(c,vec3(0.26,0.29,0.25),smoothstep(18.0,62.0,pos.y)*0.6);
        // Dappled shadows along the forest edge, fixed in world space.
        float canopy = smoothstep(3.0,12.0,sd)*(1.0-smoothstep(55.0,95.0,sd));
        c *= 1.0-canopy*(0.12+0.18*noise(pos.xz*0.10));
    } else if (kind<1.5) {
        float grain = noise(vec2((pos.x+pos.z)*22.0,pos.y*1.6));
        c *= 0.86+grain*0.24;
    } else if (kind<2.5) {
        float metal = noise(pos.xz*110.0);
        c *= 0.96+metal*0.07;
    }
    float diffuse = max(dot(n,sun),0.0)*sun_i;
    float amb = mix(0.67,0.14,night)+moon_i*0.17;
    if (material>=4.0) amb = mix(0.74,0.29,night)+moon_i*0.12;
    vec3 lighting = vec3(amb)+vec3(1.0,0.91,0.73)*diffuse*0.52;
    c *= lighting;
    c += vec3(0.75,0.63,0.37)*lamp(pos)*smoothstep(2.5,6.0,length(pos.xz-boat_pos));
    if (kind>2.5) c += color*night*0.9;
    frag = vec4(haze(c,pos),1);
}
