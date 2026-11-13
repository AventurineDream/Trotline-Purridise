// Opaque mesh shading: baked terrain, docks and camp, the player's boat and
// the Bot. Materials come from the packed `material` float (fishing/glrender
// _pack_faces): kind 0 terrain, 1 wood, 2 metal/paint, 3 lamp yellow, +4 the
// player's cockpit, 8+e emissive. Boat-frame occlusion (walls, benches,
// boxes) uses the hull description LandFx passes in `land_hull*`/`land_boxes`.
in vec3 pos, normal, color;
flat in float material;
out vec4 frag;

#if HDR
const float GLOW_BOOST = 2.4;   // lamps and stars bloom past the 0.92 threshold
#else
const float GLOW_BOOST = 1.0;
#endif

vec3 boat_local(vec3 d) { return vec3(dot(d,land_boat_x),d.y,dot(d,land_boat_z)); }
float hull_t(float z) { return clamp((z-land_hull.z)/max(land_hull.w-land_hull.z,0.01),0.0,1.0); }
// Inner half-width (m) at hull fraction `t`: a short stern ramp, a parallel
// middle, then the bow taper (boatfamilies' shape; the handcrafted hulls are
// fitted to it in landfx._hull).
float hull_half_width(float t) {
    float t0 = land_hull_flags.w;
    float ramp = min(t0,land_hull_ramp);
    float f = t<ramp ? mix(land_hull_shape.y,1.0,smoothstep(0.0,1.0,t/max(ramp,1e-3)))
            : 1.0-(1.0-land_hull_shape.z)*pow(max(t-t0,0.0)/max(1.0-t0,1e-3),1.7);
    return land_hull_shape.x*f;
}
float hull_gunwale(float t) { return land_hull.y+land_hull_flags.x*pow(t,2.2); }
float box_sd(vec3 q, vec3 c, vec3 h) {
    vec3 d = abs(q-c)-h;
    return length(max(d,0.0))+min(max(d.x,max(d.y,d.z)),0.0);
}
// Occlusion inside the player's boat at boat-frame point `q`, normal `nl`,
// key light `ll`. x: sky visibility past the walls and fittings; y: key light
// left after the gunwales, bow plate and boxes cast their contact shadows.
vec2 boat_occlusion(vec3 q, vec3 nl, vec3 ll, bool keyed) {
    float amb = 1.0, key = 1.0;
    if (land_hull_flags.y>0.5) {
        float t = hull_t(q.z);
        float gun = hull_gunwale(t);
        float fl = land_hull.x;
        float w = hull_half_width(t)*mix(land_hull_shape.w,1.0,clamp((q.y-fl)/max(gun-fl,0.01),0.0,1.0));
        if (abs(q.x)<=w+0.04 && q.y>fl-0.04 && q.y<gun+0.02
            && q.z>land_hull.z-0.05 && q.z<land_hull.w+0.05) {
            // Cross-section sky slot between the two wall tops, cosine weighted
            // for the normal's tilt and divided by what open air would give.
            float h = max(gun-q.y,0.0);
            float aL = atan(max(w+q.x,0.0),h), aR = atan(max(w-q.x,0.0),h);
            float phi = atan(nl.x,nl.y);
            float lo = max(-aL,phi-1.5708), hi = min(aR,phi+1.5708);
            float vx = hi>lo ? 0.5*(sin(hi-phi)-sin(lo-phi)) : 0.0;
            vx /= max(0.5*(1.0+cos(phi)),0.05);
            float vis = mix(vx,0.5*(sin(aL)+sin(aR)),abs(nl.z));
            if (land_hull_flags.z>0.5) {
                float af = atan(max(land_hull.w-q.z,0.0),h);
                vis *= mix(1.0,sin(af),clamp(0.5+0.6*nl.z,0.0,1.0)*0.9);
            }
            amb = mix(0.40,1.0,clamp(vis,0.0,1.0));
            if (keyed) {
                if (abs(ll.x)>1e-3) {
                    float tt = ((ll.x>0.0 ? w : -w)-q.x)/ll.x;
                    float zh = q.z+ll.z*tt;
                    if (tt>0.002 && zh>land_hull.z && zh<land_hull.w) {
                        float pen = 0.01+0.03*tt;
                        key = min(key,smoothstep(-pen,pen,q.y+ll.y*tt-hull_gunwale(hull_t(zh))));
                    }
                }
                if (land_hull_flags.z>0.5 && ll.z>1e-3) {
                    float tt = (land_hull.w-q.z)/ll.z;
                    if (tt>0.002 && abs(q.x+ll.x*tt)<w) {
                        float pen = 0.01+0.03*tt;
                        key = min(key,smoothstep(-pen,pen,q.y+ll.y*tt-hull_gunwale(1.0)));
                    }
                }
            }
        }
    }
    vec3 inv = 1.0/(ll+vec3(1e-5));
    for (int i=0; i<land_box_count; i++) {
        vec3 c = land_boxes[2*i].xyz, hs = land_boxes[2*i+1].xyz;
        float d = box_sd(q,c,hs);
        if (d>0.6 || d<0.006) continue;   // far away, or a point on this box's own skin
        vec3 dv = clamp(q-c,-hs,hs)+c-q;
        float dist = length(dv);
        float facing = clamp(dot(nl,dv/dist)*0.7+0.3,0.0,1.0);
        float r2 = (hs.x*hs.y+hs.y*hs.z+hs.x*hs.z)*1.2;
        amb *= 1.0-0.85*facing*r2/(r2+dist*dist*4.0);
        if (keyed) {
            vec3 t1 = (c-hs-0.06-q)*inv, t2 = (c+hs+0.06-q)*inv;
            vec3 tn = min(t1,t2), tf = max(t1,t2);
            float tN = max(max(tn.x,tn.y),max(tn.z,0.0)), tF = min(min(tf.x,tf.y),tf.z);
            if (tF>tN) {
                float tm = 0.5*(tN+tF);
                float pen = 0.012+0.035*tm;
                key = min(key,smoothstep(-pen*0.3,pen,box_sd(q+ll*tm,c,hs)));
            }
        }
    }
    return vec2(amb,key);
}
// Pressed seams and dome rivets on the aluminium hull, in boat metres.
// `d` is distance across the seam line, `s` distance along it.
float rivet_line(float d, float s, float fw) {
    float line = 1.0-smoothstep(0.0012,0.0012+fw,abs(d));
    vec2 cell = vec2((fract(s/0.085)-0.5)*0.085,d-0.014);
    float r = length(cell);
    float dome = 1.0-smoothstep(0.0055-fw,0.0055+fw,r);
    float ring = dome*smoothstep(0.0025,0.0055,r);
    float lit = dome*(1.0-r/0.0055)*clamp(0.5-cell.x*90.0+cell.y*90.0,0.0,1.0);
    return -0.22*line-0.20*ring+0.30*lit;
}
float aluminium_detail(vec3 q, vec3 nl) {
    float fw = max(fwidth(q.y),max(fwidth(q.z),fwidth(q.x)));
    float fade = 1.0-smoothstep(0.002,0.006,fw);
    if (fade<=0.0) return 0.0;
    float fl = land_hull.x, gun = hull_gunwale(hull_t(q.z));
    float zz = q.z-land_hull.z;
    float butt = mod(zz+0.61,1.22)-0.61;   // sheet joints every 1.22 m
    float m = 0.0;
    if (abs(nl.x)>0.85) m = rivet_line(q.y-mix(fl,gun,0.5),q.z,fw)+rivet_line(butt,q.y,fw);
    else if (nl.y>0.85) m = rivet_line(butt,q.x,fw);
    else if (abs(nl.z)>0.85) m = rivet_line(q.y-mix(fl,gun,0.5),q.x,fw);
    return m*fade;
}

void main() {
    vec3 n = normalize(normal);
    vec3 c = color;
    float emission = material>=8.0 ? clamp(mod(material,4.0),0.0,1.0) : 0.0;
    float surface = material>=8.0 ? (material>=12.0 ? 6.0 : 2.0) : material;
    float kind = mod(surface,4.0);
    float cockpit = float(surface>=4.0);
    // The reflection pass sees each point from the eye mirrored in the water.
    vec3 v = normalize(vec3(eye.x,eye.y*mirror,eye.z)-pos);
    float dist = distance(pos,eye);
    float ao = 1.0, gloss = 0.0, metal = 0.0;
    vec3 lit_add = vec3(0.0);   // emitted light, added after shading
    vec3 brush = vec3(0.0);
    vec4 occ = land_occlusion(pos,mirror>0.0 ? 1.0 : 0.0);
    vec3 q = boat_local(pos-land_boat_o);
    if (kind<0.5) {
        float sd = shore(pos.xz);
        if (sd<0.0 || in_slip(pos.xz)) discard;
        float near = mirror>0.0 ? 1.0-smoothstep(25.0,80.0,dist) : 0.0;
        LandGround g = land_ground(pos,sd,near);
        c = g.albedo; n = g.n; ao = g.ao; gloss = g.gloss;
        // Nebula crystal clusters glow softly by day and bloom at night.
        lit_add += g.albedo*g.glow*(0.25+1.3*night)*GLOW_BOOST;
        if (nebula_lake() || lake_kind>2.5) {
            // Crystal grit (Nebula) and snow crust catch the light in sparse,
            // fixed points that twinkle slowly as the view shifts.
            vec2 cell = floor(pos.xz*3.0);
            float grit = land_hash(cell);
            float tw = fract(grit*17.0+dot(v,vec3(3.1,5.7,2.3))*4.0+land_anim*0.07);
            float spark = step(0.992,grit)*smoothstep(0.55,0.95,tw)*(1.0-smoothstep(30.0,90.0,dist));
            float snowy = smoothstep(0.62,0.75,land_lum(c));
            float lit = nebula_lake() ? starlight*night*1.4+moon_i*1.2+sun_i*0.15 : snowy*(sun_i*land_sun_weather()+moon_i)*0.9;
            lit_add += vec3(0.75,0.85,1.0)*spark*lit*0.6*GLOW_BOOST;
        }
    } else {
        // Single-sided panels (shells, sails, signs) light from the side seen.
        if (dot(n,v)<0.0) n = -n;
        vec3 nl = boat_local(n);
        float axial = max(abs(nl.x),max(abs(nl.y),abs(nl.z)));
        if (kind<1.5) {
            vec3 axis = abs(n.y)<0.55 ? (cockpit>0.5 ? normalize(cross(vec3(0,1,0),n)) : vec3(0,1,0))
                                      : (cockpit>0.5 ? land_boat_x : vec3(slip_side.x,0.0,slip_side.y));
            vec3 acr = normalize(cross(n,axis));
            float along = dot(pos,axis), across = dot(pos,acr);
            float gfade = 1.0-smoothstep(0.3,0.8,fwidth(across*26.0));
            float warp = land_vnoise(vec2(along*0.9,across*3.0))*2.0;
            float ring = 0.5+0.5*sin((across*26.0+warp)*6.2832);
            float fibre = land_vnoise(vec2(along*1.5,across*170.0));
            float plank = land_hash(vec2(floor(across*7.0),floor(along*0.4)));
            c *= (0.88+0.16*ring*gfade+0.10*(fibre-0.5)*gfade)*(0.93+0.14*plank);
            if (cockpit>0.5) gloss = 0.34;
            else {
                c = mix(c,vec3(land_lum(c))*vec3(1.0,0.97,0.92),0.15);
                gloss = 0.05;
            }
        } else if (kind<2.5) {
            float mx = max(c.r,max(c.g,c.b)), mn = min(c.r,min(c.g,c.b));
            float sat = (mx-mn)/max(mx,1e-3);
            bool alu = sat<0.16 && c.b>=c.r*0.97 && mx>0.38;
            if (alu) {
                gloss = 0.55; metal = 0.65;
                if (cockpit>0.5 && axial>0.97) {
                    float across = abs(nl.y)>0.5 ? q.x : q.y;
                    float sfade = 1.0-smoothstep(0.0006,0.002,fwidth(across));
                    c *= 1.0+(land_vnoise(vec2(q.z*4.0,across*700.0))-0.5)*0.08*sfade;
                    c *= 1.0+aluminium_detail(q,nl);
                    vec3 b = land_boat_z-n*dot(n,land_boat_z);
                    if (dot(b,b)>0.01) brush = normalize(b);
                }
            } else if (mx<0.22) gloss = 0.22;
            else gloss = axial>0.97 ? (sat<0.3 ? 0.42 : 0.34) : 0.10;
            if (cockpit>0.5 && axial>0.97 && !alu && mx>=0.22) c *= 1.0+aluminium_detail(q,nl)*0.6;
        } else {
            gloss = 0.3;
        }
    }
        if (cockpit<0.5) {
            // Built things on land sit in their own contact shade; posts and
            // the slip are wet, dark and a little green at the waterline.
            if (occ.z>0.05) ao *= mix(0.55,1.0,smoothstep(0.0,1.4,pos.y-occ.z));
            float wetb = 1.0-smoothstep(0.05,0.45,pos.y);
            c = mix(c,c*vec3(0.55,0.60,0.48),wetb);
            gloss = max(gloss,wetb*0.45);
        }
    float strength; vec3 keyc;
    vec3 L = land_key(strength,keyc);
    float vis = occ.x;
    ao *= occ.y;
    if (mirror>0.0 && all(lessThan(abs(q-vec3(0.0,0.0,1.2)),vec3(3.5,3.0,5.0)))) {
        // Inside the player's boat (the Bot included): wall, bench and box occlusion.
        vec2 bo = boat_occlusion(q,boat_local(n),boat_local(L),strength>0.002);
        ao *= bo.x;
        vis *= bo.y;
    }
    c = land_light(c,n,v,pos,ao,vis,gloss,metal,cockpit,brush);
    // Night emitters: crystals, lamps, lanterns, the Bot's eye, hull stars.
    // Only the strong ones go past 1.0 so a glowing hull does not bloom whole.
    c += lit_add;
    if (kind>2.5) c += color*night*0.9*GLOW_BOOST;
    c += color*night*emission*0.85*(emission>0.9 ? GLOW_BOOST : 1.0);
    frag = vec4(haze(c,pos),1);
}
