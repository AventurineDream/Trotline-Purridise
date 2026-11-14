// Every billboard: trees, shore plants, lagoon flora, buoys, corks, cat
// impostors. Colour comes from the atlas (unit 0); the light atlas carries a
// rounded normal, translucency and AO so clumps take the sun, glow when it is
// behind them and keep dark cores. Ambient and sun come from shade_surface()
// so foliage sits at the same exposure as the ground. Animation (dapple,
// leaf shimmer) is shading only; depth and coverage never move.
uniform sampler2DArray atlas;
in vec2 uv;
in vec3 pos;
flat in float layer, shade, seed;
out vec4 frag;

// Billboard alpha with coverage kept per mip (fishing/florafx.py) and edges
// antialiased: in the MSAA main pass alpha becomes a one-pixel ramp that
// alpha-to-coverage turns into sample coverage; elsewhere (half-res
// reflection, software GL) it is a plain test at the same 0.5 cutoff.
float flora_alpha(float a, vec2 uv, float layer, vec2 size) {
    vec2 dx = dFdx(uv*size), dy = dFdy(uv*size);
    float lod = clamp(0.5*log2(max(max(dot(dx,dx),dot(dy,dy)),1e-8)),0.0,flora_levels-1.0);
    float rows = float(textureSize(flora_cover,0).y);
    a *= texture(flora_cover,vec2((lod+0.5)/flora_levels,(layer+0.5)/rows)).r;
    float ramp = clamp((a-0.5)/max(fwidth(a),1e-3)+0.5,0.0,1.0);
    return (flora_a2c>0.5 && mirror>0.0) ? ramp : step(0.5,a);
}
void main() {
    vec4 tex = texture(atlas,vec3(uv,layer));
    vec2 size = vec2(textureSize(atlas,0).xy);
    float alpha = flora_alpha(tex.a,uv,layer,size);
    vec2 duv = fwidth(uv*size);
    float lod = log2(max(max(duv.x,duv.y),1e-4));
    if (alpha<=0.0) discard;
    // Both atlases are premultiplied by coverage (see florafx._encode).
    float inv = 1.0/max(tex.a,1.0/255.0);
    vec4 L = texture(flora_light,vec3(uv,layer))*inv;
    bool self_lit = shade>=1.5;
    float glow_buoy = shade<0.0 ? 1.0 : 0.0;
    vec3 base = min(tex.rgb*inv,vec3(1.0));
    vec3 albedo = base;
    // Each instance is tinted a touch warmer or cooler so repeated variants differ.
    albedo *= 1.0+(seed-0.5)*vec3(0.10,0.05,-0.06);
    if (!self_lit) albedo *= abs(shade);

    vec2 nxy = L.rg*2.0-1.0;
    float nz = sqrt(max(0.0,1.0-dot(nxy,nxy)));
    vec3 right = normalize(vec3(view_right.x,0.0,view_right.z));
    vec3 toward = normalize(vec3(eye.x-pos.x,0.0,eye.z-pos.z)+vec3(1e-4,0,0));
    vec3 n = normalize(right*nxy.x+vec3(0.0,nxy.y,0.0)+toward*nz);
    float thin = L.b, ao = L.a;
    float wood = self_lit ? 0.0 : 1.0-smoothstep(0.04,0.18,thin);
    float leaf = self_lit ? 0.0 : 1.0-wood;

    // Weather on the surface: wet bark and stone darken in rain, leaves less;
    // snow settles on upward-facing needles, heavier toward the snow line.
    albedo *= 1.0-rain*(0.38*wood+0.10*leaf);
    float dust = snow*(0.35+0.65*smoothstep(snow_line-90.0,snow_line-5.0,pos.y));
    float settle = smoothstep(0.08,0.6,n.y)*(0.55+0.9*noise(uv*size*0.09+seed*31.0));
    albedo = mix(albedo,vec3(0.84,0.88,0.93),clamp(dust*settle*(leaf+wood*0.4),0.0,0.92));

    // Dappled light drifting through the canopy (shading only).
    float sunlit = max(dot(n,sun),0.0)*sun_i;
    float t = flora_time*(0.25+0.35*flora_wind);
    float dapple = noise(uv*vec2(6.0,9.0)+seed*17.0+vec2(t*0.11,-t*0.07))-0.5;
    float far = 1.0-smoothstep(0.5,2.6,lod);
    float sky_open = 1.0-cloud_cover*0.75;
    vec3 c = shade_surface(albedo,n,pos,ao,0.0,0.0);
    c *= 1.0+dapple*0.5*leaf*sunlit*sky_open*(0.4+0.6*far);
    // A faint shimmer as single leaves turn in the wind; faded out before it
    // could alias at a distance.
    vec2 cell = floor(uv*size/(2.2*size.x/160.0));
    float turn = sin(t*2.6+hash(cell+layer*7.1)*6.2832);
    c *= 1.0+turn*0.07*thin*leaf*far*min(flora_wind,1.3)*(0.35+0.65*sunlit);

    // Shadowed sides take a little of the sky's hue (luminance kept).
    vec3 skyc = mix(horizon,zenith,clamp(n.y*0.5+0.5,0.0,1.0));
    vec3 hue = clamp(skyc/max(dot(skyc,vec3(0.3333)),1e-3),vec3(0.6),vec3(1.5));
    c *= mix(vec3(1.0),hue,0.22*(1.0-sunlit)*(1.0-night));

    // Light through leaves when the sun is behind them; strongest at the thin
    // rims, warmest at gold hour.
    vec3 view = normalize(pos-eye);
    float back = pow(max(dot(view,sun),0.0),4.0);
    vec3 transmit = albedo*vec3(1.30,1.25,0.50)+vec3(0.05,0.04,0.0);
    c += transmit*back*thin*leaf*sun_i*sky_open*(0.75+1.1*gold)*mix(0.6,1.0,ao);
    float rim = pow(1.0-nz,1.6);
    c += vec3(1.0,0.60,0.28)*albedo*gold*rim*leaf*max(dot(n,sun),0.0)*sun_i*0.9;
    // Cool moonlit edges keep silhouettes legible at night.
    c += vec3(0.38,0.48,0.70)*rim*(0.35+0.65*max(dot(n,moon),0.0))*moon_i*night*(0.25+0.3*thin);

    if (self_lit) {
        // Shade 2..3 marks a self-lit Nebula sprite; its emission is shade - 2.
        float emit = clamp(shade-2.0,0.0,1.0);
        float core = L.b;
        c += base*emit*(0.35+0.85*night)*(0.55+0.7*core);
        // Only emitters exceed 1.0; the bloom picks the bright cores up.
        c += base*core*core*emit*night*(HDR==1 ? 0.9 : 0.25);
    }
    c = mix(c,albedo*1.3,glow_buoy);
    frag = vec4(haze(c,pos)+vec3(0.18,0.14,0.06)*glow_buoy,alpha);
}
