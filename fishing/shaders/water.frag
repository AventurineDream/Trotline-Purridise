uniform sampler2D reflection, reflection_depth;
uniform vec4 line_segments[8];
uniform float line_heat[8];
uniform int line_count;
uniform vec4 ripples[4];
uniform int ripple_count;
// Nebula current lanes (x, z, radius), the mid-water violet and the shoals.
uniform vec3 lane_circles[48];
uniform int lane_count;
uniform vec3 nebula_mid, shoal;
in vec3 pos;
out vec4 frag;
// The same field as bottools.flow_at: lanes and dashes follow the drift.
vec2 flow_dir(vec2 p) {
    float h = 1.7*sin(p.x/190.0+0.6)+1.1*cos(p.y/150.0-0.4);
    return vec2(cos(h),sin(h));
}
float lane_strength(vec2 p) {
    float best = 0.0;
    for (int i=0;i<48;i++) {
        if (i>=lane_count) break;
        float r = lane_circles[i].z;
        float d = distance(p,lane_circles[i].xy);
        best = max(best,1.0-clamp((d-r*0.55)/(r*0.45),0.0,1.0));
    }
    return best;
}
// nebula.dashes: one dash per 6 m cell, pointing and moving along the flow.
float current_dashes(vec2 p, float t) {
    vec2 base = floor(p/6.0);
    float best = 0.0;
    for (int j=-1;j<=1;j++) for (int i=-1;i<=1;i++) {
        vec2 c = base+vec2(i,j);
        float seed = hash(c+7.3);
        vec2 centre = (c+0.5+(vec2(hash(c+1.7),hash(c+4.1))-0.5)*0.7)*6.0;
        vec2 dir = flow_dir(centre);
        float phase = fract(t*0.11+seed);
        vec2 rel = p-(centre+dir*(phase-0.5)*6.0);
        float along = dot(rel,dir), side = dot(rel,vec2(-dir.y,dir.x));
        float dash = (1.0-clamp(abs(along)/2.0,0.0,1.0))*(1.0-clamp((abs(side)-0.10)/0.22,0.0,1.0));
        best = max(best,dash*sin(phase*3.14159)*step(0.35,seed));
    }
    return best;
}
// One wave tile at world p: world-axis slope (xy), height (z) and the
// filtered slope^2 (w). Gradients are passed in so every fetch can sit in
// uniform control flow and still filter anisotropically at grazing angles.
vec4 wave_tile(vec2 p, vec2 dpx, vec2 dpy, vec2 axis, float scale, vec2 drift,
               float first, float second, float blend) {
    vec2 across = vec2(-axis.y,axis.x);
    vec2 uv = vec2(dot(p,axis),dot(p,across))*scale-drift;
    vec2 gx = vec2(dot(dpx,axis),dot(dpx,across))*scale;
    vec2 gy = vec2(dot(dpy,axis),dot(dpy,across))*scale;
    vec4 a = mix(textureGrad(wave_tex,vec3(uv,first),gx,gy),
                 textureGrad(wave_tex,vec3(uv,second),gx,gy),blend);
    return vec4(axis*a.x+across*a.y,a.z,a.w);
}
vec4 rain_set(vec2 uv, vec2 gx, vec2 gy, float first, float second, float blend) {
    return mix(textureGrad(rain_tex,vec3(uv,first),gx,gy),
               textureGrad(rain_tex,vec3(uv,second),gx,gy),blend);
}
void main() {
    // Every derivative and filtered fetch happens before the bank branch.
    vec2 dpx = dFdx(pos.xz), dpy = dFdy(pos.xz);
    float sd = shore(pos.xz);
    float sd_px = max(fwidth(sd),1e-4);
    bool slip = in_slip(pos.xz);
    vec4 nearw = wave_tile(pos.xz,dpx,dpy,wave_axes.xy,wave_scale.x,wave_drift.xy,
                           wave_layers.x,wave_layers.y,wave_mix.x);
    vec4 farw = wave_tile(pos.xz,dpx,dpy,wave_axes.zw,wave_scale.y,wave_drift.zw,
                          wave_layers.z,wave_layers.w,wave_mix.y);
    vec2 gaxis = wave_axes.xy, gacross = vec2(-gaxis.y,gaxis.x);
    vec2 guv = vec2(dot(pos.xz,gaxis),dot(pos.xz,gacross))*wave_scale.w-water_gust.xy;
    float gust = textureGrad(water_noise,guv,dpx*wave_scale.w,dpy*wave_scale.w).r;
    vec4 lace_bed = textureGrad(water_noise,pos.xz*0.33,dpx*0.33,dpy*0.33);
    // Opaque terrain hides this existing bounded plane. At the coarse bank's
    // raised clipped edge, shade the projected crack as land rather than
    // reflecting bright sky. No shore, depth, navigation or geometry changes.
    if (sd>=0.0 && !slip) {
        vec3 bank = shade_surface(ground_albedo(pos,sd),vec3(0,1,0),pos,1.0,0.0,0.0);
        frag = vec4(haze(bank,pos),1);
        return;
    }
    float dist = distance(pos,eye);
    vec3 v = normalize(eye-pos);
    // Wind patches (cat's paws) drift across the lake: glassy stretches
    // that keep a clean mirror between rougher, darker gusts.
    float patches = mix(1.0-water_gust.z,1.0+water_gust.z*1.4,smoothstep(0.3,0.72,gust));
    float amp = wave_slope*patches;
    // Weights keep the combined RMS slope at 1 before `amp`.
    vec2 slope = (nearw.xy*0.6+farw.xy*0.8)*amp;
    float energy = (nearw.w*0.36+farw.w*0.64)*amp*amp;
    float swell = nearw.z*0.45+farw.z*0.9;
    // Past ~30 m the eye cannot follow single waves: hand their slope over
    // to roughness, so distant water softens instead of scratching.
    float resolve = 1.0-0.8*smoothstep(30.0,170.0,dist);
    energy += dot(slope,slope)*(1.0-resolve*resolve);
    slope *= resolve;
    float sparkle = 0.0;
    if (rain>0.01) {
        // Two offset drop sets; the second fills in as drizzle turns to rain.
        vec2 ruv = pos.xz*wave_scale.z;
        vec2 rgx = dpx*wave_scale.z, rgy = dpy*wave_scale.z;
        vec4 ra = rain_set(ruv,rgx,rgy,rain_layers.x,rain_layers.y,rain_mix.x);
        vec2 quv = vec2(-ruv.y,ruv.x)*1.37+vec2(0.43,0.71);
        vec4 rb = rain_set(quv,vec2(-rgx.y,rgx.x)*1.37,vec2(-rgy.y,rgy.x)*1.37,
                           rain_layers.z,rain_layers.w,rain_mix.y);
        float heavy = smoothstep(0.3,0.9,rain);
        float drops = rain*0.3;
        slope += (ra.xy+vec2(rb.y,-rb.x)*heavy)*drops;
        energy += (ra.z+rb.z*heavy)*drops*drops;
        sparkle = (ra.w+rb.w*heavy)*rain*(1.0-smoothstep(6.0,30.0,dist));
    }
    // Bite rings and idle rises also bend the surface, so they catch the
    // light; their colour is added at the same place as before.
    float bite = 0.0;
    for (int i=0;i<4;i++) {
        if (i>=ripple_count) break;
        float age = ripples[i].z;
        float rad = 0.4+age*2.4;
        vec2 to = pos.xz-ripples[i].xy;
        float d = length(to);
        float fade = 1.0-clamp(age/2.4,0.0,1.0);
        float ring = exp(-square(d-rad)/0.25)*fade;
        bite += ring;
        slope += to/max(d,1e-3)*(-(d-rad)*8.0)*ring*0.05;
    }
    float rises = 0.0;
    if (!slip) {
        for (int i=0;i<5;i++) {
            float fi = float(i);
            float sx = hash(vec2(fi+1.0,2.3));
            float sz = hash(vec2(fi+4.0,8.1));
            float life = fract(anim*0.07+sx);
            vec2 center = boat_pos+vec2(sx*2.0-1.0,sz*2.0-1.0)*vec2(28.0,22.0);
            center += vec2(sin(anim*0.15+fi),cos(anim*0.11+fi*1.7))*6.0;
            if (distance(center,boat_pos)<9.0) continue;
            float rad = life*2.4;
            vec2 to = pos.xz-center;
            float d = length(to);
            float ring = exp(-square((d-rad)/0.085))*(1.0-smoothstep(0.62,1.0,life));
            rises += ring;
            slope += to/max(d,1e-3)*(-(d-rad)/0.085)*ring*0.03;
        }
    }
    // The boat's wake: the authored V rails and centre streak, a bow wave
    // spreading from the leading end at the Kelvin angle, and churn astern.
    vec2 rel = pos.xz-boat_pos;
    float along = dot(rel,boat_forward);
    vec2 beside = rel-boat_forward*along;
    float side = length(beside);
    // The terms below are authored for forward travel. Reversing, the stern
    // leads: mirror along about the hull's middle (boat.wake_along) so the wake
    // trails the bow and the bow wave forms at the stern. Every term fades
    // with |speed|, so the flip at zero speed cannot be seen.
    if (speed < 0.0) along = boat_ends.x+boat_ends.y-along;
    float behind = -along;
    float spd = clamp(abs(speed)/2.0,0.0,1.0);
    float spread = 0.38+behind*0.10;
    // Water ahead has negative behind: keep the Gaussian variance positive.
    // An overflowing exponential multiplied by a zero fade used to poison it.
    float rail = exp(-square(side-spread)/max(0.045,0.045+behind*0.010));
    float wake = rail*smoothstep(0.55,1.3,behind)*(1.0-smoothstep(5.0,16.0,behind))*spd;
    float streak = exp(-square(side)/0.07)*smoothstep(0.25,0.9,behind)*(1.0-smoothstep(2.2,9.0,behind))*spd;
    float bow_side = 0.72+max(0.0,boat_ends.y-along)*0.36;
    float bow = exp(-square(side-bow_side)/(0.018+max(0.0,boat_ends.y-along)*0.012))
              *smoothstep(-3.5,-0.5,along)*(1.0-smoothstep(boat_ends.y-0.16,boat_ends.y+0.14,along))*spd;
    float churn = smoothstep(0.75,1.2,behind)*(1.0-smoothstep(2.5,5.5,behind))
                *(1.0-smoothstep(0.35+behind*0.08,0.75+behind*0.12,side))*spd;
    vec2 outward = beside/max(side,1e-3);
    slope += outward*(-(side-spread)*12.0)*wake*0.035+outward*(-(side-bow_side)*14.0)*bow*0.03;
    slope += (lace_bed.yz-0.5)*churn*0.12;
    energy += churn*0.004;
    // Slope variance the filtered textures could not resolve: far water
    // stays rough instead of turning to glass or shimmering.
    float variance = max(energy-dot(slope,slope),0.0)*0.5+0.00005;
    vec3 n = normalize(vec3(-slope.x,1.0,-slope.y));
    // Schlick with an art-directed F0 of 0.10 (water is 0.02): the authored
    // body colours are brighter than real deep water, so a physical F0 would
    // drown the shore's reflection in teal a few metres off the boat.
    float cosv = clamp(dot(v,n),0.0,1.0);
    float fres = 0.10+0.88*square(square(1.0-cosv));
    fres = mix(fres,.96,still_reflection);
    if (nebula_lake()) fres = max(fres,0.46);
    // Look up the reflection where the mirrored scene drew the reflected
    // ray. Tilt toward or away from the eye swings it vertically, so ripples
    // smear far trees into soft columns and break them up near the boat.
    // Far off the swing is damped and traded for blur, so the far shore's
    // reflection keeps its shapes instead of shattering into sky.
    float bend = mix(1.0,0.4,smoothstep(15.0,120.0,dist));
    vec3 r = reflect(-v,normalize(vec3(-slope.x*bend,1.0,-slope.y*bend)));
    // Never past the mirrored horizon: there the reflection holds no scene,
    // which used to draw a bright seam under the far bank.
    r.y = max(r.y,v.y*0.55+0.0015);
    vec3 m = vec3(r.x,-r.y,r.z);
    float mz = max(dot(m,view_forward),0.05);
    vec2 ruv = 0.5+0.5*vec2(dot(m,view_right)/(mz*tanx),dot(m,view_up)/(mz*tany));
    ruv = clamp(ruv,0.002,0.998);
    vec2 rsize = vec2(textureSize(reflection,0));
    float blur = min(sqrt(variance)*(0.5+0.5*bend)/tany,0.06);
    float lod = log2(max(blur*rsize.y*0.5,1.0));
    vec2 tap = vec2(0.0,blur*0.6);
    vec3 reflected = textureLod(reflection,ruv,lod).rgb*0.4
                   + textureLod(reflection,clamp(ruv+tap,0.002,0.998),lod).rgb*0.3
                   + textureLod(reflection,clamp(ruv-tap,0.002,0.998),lod).rgb*0.3;
    // Open sky in the reflection (no scenery drew there): stars, sky glow.
    float open_sky = step(.999999,textureLod(reflection_depth,ruv,0.0).r);
    float celestial_mix = nebula_lake() ? 0.9 : crater_lake() ? max(still_reflection,water_star) : water_star;
    if (celestial_mix>0.0 && open_sky>0.5) {
        // The reflection depth preserves the rim/island silhouette. Only open
        // sky gets a full-resolution celestial sample, keeping small stars;
        // a gentler normal keeps reflected stars crisp points.
        vec3 calm = normalize(vec3(-slope.x*0.35,1.0,-slope.y*0.35));
        vec3 celestial = sky(reflect(-v,calm));
        reflected = mix(reflected,celestial,celestial_mix);
    }
    float depth = 0.5+5.0*(1.0-exp(min(sd,0.0)/28.0));
    depth += 10.0*exp(-dot(pos.xz-vec2(75,-28),pos.xz-vec2(75,-28))/(2.0*72.0*72.0));
    if (lake_kind>2.5) depth = texture(lake_depth,lake_uv(pos.xz)).r;
    else if (lake_kind>1.5) depth = 4.0;
    else if (lake_kind>0.5) depth = texture(lake_depth,lake_uv(pos.xz)).r;
    vec3 body = mix(vec3(0.22,0.32,0.23),vec3(0.035,0.14,0.16),smoothstep(0.5,8.0,depth));
    if (lake_kind>2.5) body = mix(alpine_shallow,alpine_deep,smoothstep(.5,20.0,depth));
    else if (lake_kind>1.5) body = lake_water;
    else if (lake_kind>0.5) {
        float upper = smoothstep(-0.25,0.6,lake_uv(pos.xz).y);
        body = mix(vec3(0.055,0.20,0.23),vec3(0.26,0.27,0.17),upper*0.65);
        body = mix(body,vec3(0.31,0.31,0.22),1.0-smoothstep(0.5,3.0,depth));
    }
    if (crater_lake() && distance(pos.xz,lily_centre)<110.0)
        body = mix(body,vec3(.09,.19,.15),(1.0-smoothstep(3.0,12.0,depth))*.65);
    if (nebula_lake()) {
        // Teal shallows, violet mid-water and a starry void bed below 30 m.
        body = mix(mix(alpine_shallow,nebula_mid,smoothstep(0.5,7.0,depth)),alpine_deep,
                   smoothstep(7.0,40.0,depth));
        vec2 cell = floor(pos.xz*0.9);
        float h = hash(cell+31.7);
        vec2 f = fract(pos.xz*0.9)-0.5-(vec2(hash(cell+2.1),hash(cell+5.3))-0.5)*0.6;
        float star = (1.0-smoothstep(0.0,0.09,length(f)))*step(0.93,h)*smoothstep(6.0,30.0,depth);
        star *= 1.0-smoothstep(25.0,90.0,dist);
        body += vec3(0.75,0.80,1.0)*star*(0.6+0.4*sin(snow_anim*2.0+h*50.0));
        body *= mix(0.95,0.62,night)+starlight*0.12;
    } else {
        body *= mix(0.85,0.30,night)+moon_i*0.1;
    }
    // Clear shallows: the bank's own sand, gravel or dust continues under
    // the water and fades out by ~1.5 m. Optical depth reaches zero at the
    // waterline, so the water thins into the bank instead of a hard edge.
    float optical = min(depth,max(-sd,0.0)*0.6);
    float cos_t = sqrt(1.0-(1.0-v.y*v.y)/1.77);
    float clarity = exp(-optical*(0.9+0.5/cos_t));
    if (clarity>0.004) {
        vec3 bed = ground_albedo(pos,0.35)*(0.8+0.4*lace_bed.z);
        float caustic = texture(water_noise,pos.xz*0.37+slope*2.5).a;
        bed *= 1.0+caustic*sun_i*(1.0-smoothstep(0.6,1.1,cloud_cover))*0.55*(1.0-clarity*0.5);
        vec3 seen = shade_surface(bed,vec3(0,1,0),pos,1.0,0.0,0.0);
        // Water tints and darkens what it covers.
        seen *= mix(vec3(0.62,0.70,0.66),vec3(1.0),clarity);
        body = mix(body,seen,clarity);
    }
    vec3 c = mix(body,reflected,fres);
    // Night: open water keeps a Fresnel-weighted floor of sky glow, so
    // moonlit water reads as water rather than a black slab, while the
    // banks' reflections stay dark silhouettes. Dusk keeps its mirror.
    vec3 glow = mix(horizon,zenith,0.35)*(0.3+0.7*fres)*(0.6+moon_i*0.9)*mix(0.3,1.0,open_sky);
    c = max(c,glow*night*night);
    // Sun and moon glitter: facets that mirror the light toward the eye
    // sparkle along the path (they ride the baked waves, so they move
    // smoothly), over a soft sheen from the capillary roughness that runs
    // the path out to the horizon. The capillaries are steeper than the
    // swell that bends the reflection, hence the wider glitter slopes.
    // HDR targets let the brightest glints bloom.
    vec2 facets = slope*2.4;
    float glints = variance*4.0+square(amp*2.0)+0.0001;
    float sheen = square(amp*4.0)+0.0025;
    vec3 sun_colour = mix(vec3(1.0,0.93,0.80),vec3(1.0,0.64,0.32),gold);
    c += sun_colour*(water_glitter(v,sun,facets,glints)
                    +water_glitter(v,sun,vec2(0.0),sheen*(1.0+gold))*1.6)*water_glint.x;
    // The moon rides high here, so its path is drawn as if from a low moon
    // on the same bearing: a sparkling column under it, plus a soft sheen.
    vec3 low_moon = normalize(vec3(moon.x,min(moon.y,0.12),moon.z));
    float moon_light = water_glitter(v,low_moon,facets,glints)
                     + water_glitter(v,low_moon,vec2(0.0),sheen*1.5)*2.5;
    c += vec3(0.70,0.80,1.0)*moon_light*water_glint.y*step(0.0,moon.y);
    // Rain: tiny bright impact points where drops land.
    c += mix(horizon,vec3(1.0),0.5)*sparkle*0.35*(1.0-night*0.7);
    if (!slip) {
        // A wet, darker waterline and a breathing line of lapping foam.
        float reach = 0.16+0.20*(0.5+0.5*sin(water_t*0.85+dot(pos.xz,vec2(0.13,0.09))))
                    +max(swell,0.0)*0.05;
        float band = -sd/reach;
        float lace = lace_bed.y;
        // The foam gathers in drifts along the bank rather than one even line.
        float drifts = smoothstep(0.3,0.75,lace_bed.x);
        float foam = (exp(-square((band-0.8)/0.25))*(0.25+0.9*lace)+(1.0-smoothstep(0.0,0.8,band))*lace*0.4)
                   *(1.0-smoothstep(1.0,1.25,band))*(0.35+0.65*drifts);
        // Thinner than a pixel far off: keep its energy, not its shimmer.
        foam *= clamp(reach/(sd_px*1.5),0.0,1.0)*clamp(amp/0.012,0.6,1.3);
        if (crater_lake()) foam *= 0.45;
        if (nebula_lake()) foam *= 0.35;
        // The coarse bank mesh meets the plane a little inside sd = 0, so
        // the wet band is wide enough to always reach the visible edge.
        float edge = 1.0-smoothstep(0.0,max(0.45,sd_px*2.5),-sd);
        if (edge+foam>0.003) {
            vec3 froth = shade_surface(vec3(0.82,0.85,0.84),vec3(0,1,0),pos,1.0,0.0,0.0);
            vec3 wet = shade_surface(ground_albedo(pos,0.1)*0.62,vec3(0,1,0),pos,1.0,0.0,0.0);
            c = mix(c,wet,edge*0.8);
            c = mix(c,froth,clamp(foam*0.85,0.0,0.85));
        }
    }
    // Pads, their veins and occasional flowers in the lily cove.
    vec2 cell = floor(pos.xz/2.3), f = fract(pos.xz/2.3)-0.5;
    float seed = hash(cell);
    bool cove = distance(pos.xz,lily_centre)<105.0;
    float radius = 0.17+seed*0.07;
    float leaf = 1.0-smoothstep(radius-0.025,radius,length(f));
    leaf *= step(0.64,seed)*float(cove && dist>9.0 && !slip);
    leaf *= 1.0-float(f.x>0.0 && abs(f.y)<f.x*0.2);
    if (lake_kind>2.5 && !nebula_lake()) leaf = (1.0-smoothstep(.035,.075,abs(f.x)))*
        (1.0-smoothstep(.22,.38,abs(f.y)))*step(.64,seed)*float(cove && dist>9.0 && !slip);
    vec3 pad = mix(vec3(0.07,0.20,0.09),vec3(0.24,0.35,0.13),seed);
    pad += vec3(0.06,0.07,0.015)*exp(-abs(f.y)*100.0);
    if (nebula_lake()) {
        // Zero-G lily pads glow at their rims and keep their light at night.
        pad = mix(vec3(0.10,0.30,0.32),vec3(0.26,0.48,0.52),seed);
        pad += vec3(0.30,0.70,0.75)*smoothstep(radius-0.05,radius-0.01,length(f));
        c = mix(c,pad*mix(1.0,0.78,night),leaf);
    } else if (lake_kind<3.5) c = mix(c,pad*mix(1.0,0.25,night),leaf);
    if (crater_lake()) leaf = 0.0;
    float flower = (1.0-smoothstep(0.0,0.028,length(f)))*step(0.94,seed)*leaf;
    if (lake_kind<2.5) c = mix(c,vec3(0.91,0.77,0.48),flower);
    if (nebula_lake()) {
        c = mix(c,vec3(1.0,0.74,0.95),flower);
        // Banks and drifts are rimmed by soft bioluminescence.
        c += vec3(0.30,0.85,0.90)*exp(-square(sd+0.6)*1.2)*0.22*(0.5+0.5*night)*float(!slip);
        // Astral current: a lit lane with dashes that ride the flow field.
        float lane = lane_strength(pos.xz);
        if (lane>0.0) {
            float near = 1.0-smoothstep(40.0,130.0,dist);
            float dash = current_dashes(pos.xz,snow_anim)*near;
            // The lane quiets the mirror and glows teal; its dashes run downstream.
            c = mix(c,vec3(0.10,0.40,0.52)*(0.75+0.25*(1.0-night)),lane*0.38);
            c += vec3(0.12,0.48,0.60)*lane*(0.10+0.16*night);
            c += vec3(0.70,0.97,1.0)*dash*lane*1.05;
        }
        // Stardust shoals glint gold in their shallowest water.
        vec2 sc = floor(pos.xz*1.6);
        float glint = step(0.985,hash(sc+13.1))*(1.0-smoothstep(0.0,shoal.z,distance(pos.xz,shoal.xy)))
                    *(1.0-smoothstep(1.0,6.0,depth))*(1.0-smoothstep(20.0,60.0,dist));
        c += vec3(1.0,0.86,0.55)*glint*(0.55+0.45*sin(snow_anim*3.0+hash(sc)*40.0));
        // Aurora nights tint the whole surface with a teal-green glow.
        c += vec3(0.10,0.42,0.30)*aurora_i*(0.25+0.75*fres)*0.35;
    }
    for (int i=0;i<line_count;i++) {
        vec2 ab = line_segments[i].zw-line_segments[i].xy;
        float t = clamp(dot(pos.xz-line_segments[i].xy,ab)/max(dot(ab,ab),0.001),0.0,1.0);
        float d = distance(pos.xz,line_segments[i].xy+ab*t);
        float width = max(0.045,fwidth(d)*0.8);
        float rope = 1.0-smoothstep(width*0.5,width,d);
        c = mix(c,vec3(0.19,0.16,0.10),rope*0.65);
        float heat = line_heat[i];
        float travel = 0.5+0.5*sin(t*16.0-anim*2.4);
        c += vec3(0.86,0.70,0.32)*rope*heat*travel*0.85;
        c += vec3(0.72,0.58,0.24)*exp(-d*d/0.22)*heat*(0.25+0.75*travel)*0.18;
    }
    // Wake and rise rings are color on the same plane. Depth stays put, and
    // the rings follow anim so a held weather pair does not swim.
    if (wake+streak+bow+churn>0.002) {
        vec3 froth = shade_surface(vec3(0.80,0.85,0.82),vec3(0,1,0),pos,1.0,0.0,0.0);
        // World-anchored, so the foam stays where it formed: soft streaks
        // drawn out along the boat's heading, threaded with bubbly lace that
        // is sampled a mip softer so it reads as froth rather than a net.
        vec2 across = vec2(-boat_forward.y,boat_forward.x);
        vec2 suv = vec2(dot(pos.xz,boat_forward)*0.07,dot(pos.xz,across)*0.6);
        float streaks = textureGrad(water_noise,suv,vec2(dot(dpx,boat_forward)*0.07,dot(dpx,across)*0.6),
                                    vec2(dot(dpy,boat_forward)*0.07,dot(dpy,across)*0.6)).b;
        float s = smoothstep(0.36,0.64,streaks);
        vec4 bubbles = textureGrad(water_noise,pos.xz*1.1,dpx*2.2,dpy*2.2);
        float lacy = 0.4+0.5*s+0.35*bubbles.y*smoothstep(0.4,0.65,bubbles.z)*(0.4+0.6*s);
        c = mix(c,mix(vec3(0.74,0.80,0.76),froth,0.5),clamp((wake*0.62+streak*0.38)*lacy,0.0,0.7));
        c = mix(c,froth,clamp(bow*0.5*lacy+churn*(0.1+0.3*bubbles.y)*(0.5+0.5*s),0.0,0.6));
    }
    if (!slip) c = mix(c,vec3(0.78,0.84,0.80),clamp(rises,0.0,0.7)*0.5);
    // Bite and idle rises. Age is computed on the CPU. An empty list draws nothing.
    c += bite*0.35;
    // The lamp: its authored cone, plus a wider pool with a soft falloff,
    // scattered up from inside the water.
    vec2 to_lamp = pos.xz-boat_pos;
    float lamp_cone = smoothstep(0.55,0.97,dot(normalize(to_lamp+0.0001),boat_forward));
    float pool = lamp_cone*exp(-length(to_lamp)/24.0)*spotlight*night;
    c += vec3(0.65,0.55,0.33)*(lamp(pos)*0.35+pool*0.16*(1.0-fres*0.6));
    c = haze(c,pos);
    frag = vec4(c,1);
}
