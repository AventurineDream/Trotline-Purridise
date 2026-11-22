// The cat rig (V1-29): blends the idle pose and its gesture pose, then gives the cat its
// idle life: breathing, a layered tail sway with a tip flick, each ear's twitch and perk,
// blinks, a head that turns, nods and tilts, arms at work (cast and reel, a page, the
// wheel), the wave, and a whole-body weight shift. Every parameter comes from
// fishing/actors.py pose_state(); animate() there is the CPU twin of this shader, step for
// step and in the same order, and test_cats checks the two by transform feedback.
//
// in_rig is a rig channel plus 16 per cat in the actor (Pebble, Pip's twin, is cat 1), so
// each cat works about its own pivots. Angles are radians: positive head pitch is nose
// down, positive arm angle lowers the paws; lengths are metres at size 1.
in vec3 in_pos_a, in_pos_b, in_nrm_a, in_nrm_b, in_coat, in_coat_n, in_color;
in float in_part, in_along, in_glow, in_rig;
uniform vec3 actor_pos;
uniform float actor_yaw, blend;
uniform float breath, rise, tail, tail_phase, tail_curl, tail_lift, ear_l, ear_r, ear_perk, blink;
uniform float head_yaw, head_pitch, head_roll, forearm, arm, body_roll, body_pitch;
uniform vec3 neck[2], elbow[2], arm_pivot[2], arm_axis[2], head_up[2], seat[2];
uniform float eye_open[2], cat_yaw[2], cat_size[2];
out vec3 pos, normal, coat, coat_n, color;
out float along, glow;
flat out float part;

const float PI = 3.14159265;
const float HEAD_SCALE = 1.15;  // catmesh.HEAD_SCALE
const float PUPIL = 20.0;       // catmesh.PUPIL

// Rodrigues: v turned by a about the unit axis k.
vec3 turn(vec3 v, vec3 k, float a) {
    float c = cos(a), s = sin(a);
    return v*c + cross(k, v)*s + k*dot(k, v)*(1.0 - c);
}

bool is(float channel, float value) { return abs(channel - value) < 0.5; }

void main() {
    vec3 p = mix(in_pos_a, in_pos_b, blend);
    vec3 n = normalize(mix(in_nrm_a, in_nrm_b, blend) + vec3(1e-5));
    int i = int(floor((in_rig + 0.5) / 16.0));
    float ch = in_rig - 16.0*float(i);
    float size = cat_size[i];
    // This cat's own axes within the actor frame (a twin sits turned by cat_yaw): its x (the
    // side catmesh names "l") and its facing. They map to world by the actor frame below.
    vec3 xa = vec3(cos(cat_yaw[i]), 0.0, -sin(cat_yaw[i]));
    vec3 za = vec3(sin(cat_yaw[i]), 0.0, cos(cat_yaw[i]));
    vec3 up = vec3(0.0, 1.0, 0.0);
    // Breathing widens the torso about the cat's own axis.
    if (is(ch, 5.0)) {
        p.x = neck[i].x + (p.x - neck[i].x)*(1.0 + breath);
        p.z = neck[i].z + (p.z - neck[i].z)*(1.0 + breath);
    }
    // The tail: a sway travelling to the tip, a tip curl, a lift when greeting.
    if (is(ch, 3.0)) {
        float a = in_along;
        float lateral = tail*pow(a, 1.5)*cos(tail_phase - 2.5*a) + tail_curl*a*a*a;
        p += (xa*lateral + up*(tail_lift*a*a))*size;
    }
    // Ears swivel back and out one at a time, and perk up together for the player.
    if (is(ch, 2.0) || is(ch, 6.0)) {
        float twitch = is(ch, 2.0) ? ear_l : ear_r;
        float side = is(ch, 2.0) ? 1.0 : -1.0;
        p += (-za*(0.03*twitch) + xa*(side*0.012*twitch) + za*(0.004*ear_perk) + up*(0.006*ear_perk))*(in_along*size);
    }
    // Blinks: each eye's top and bottom meet along the head's up axis.
    if (is(ch, 7.0)) {
        float k = abs(in_part - PUPIL) < 0.5 ? 0.016 : 0.019;
        p -= head_up[i]*(blink*eye_open[i]*k*size*HEAD_SCALE*cos(PI*in_along));
    }
    // The head tilts, nods and turns about the neck, then rises with the breath.
    if (is(ch, 1.0) || is(ch, 2.0) || is(ch, 6.0) || is(ch, 7.0)) {
        p = neck[i] + turn(p - neck[i], za, head_roll);
        n = turn(n, za, head_roll);
        p = neck[i] + turn(p - neck[i], xa, head_pitch);
        n = turn(n, xa, head_pitch);
        p = neck[i] + turn(p - neck[i], up, head_yaw);
        n = turn(n, up, head_yaw);
        p.y += rise*size;
    }
    // The right forearm waves (or reels) about its elbow...
    if (is(ch, 4.0)) {
        p = elbow[i] + turn(p - elbow[i], za, forearm);
        n = turn(n, za, forearm);
    }
    // ...and both arms, with what they hold, work about the shoulders or the wheel.
    if (is(ch, 4.0) || is(ch, 8.0)) {
        p = arm_pivot[i] + turn(p - arm_pivot[i], arm_axis[i], arm);
        n = turn(n, arm_axis[i], arm);
        p.y += 0.6*rise*size;
    }
    // The whole cat settles its weight (and leans into the helm's turns).
    p = seat[i] + turn(p - seat[i], xa, body_pitch);
    n = turn(n, xa, body_pitch);
    p = seat[i] + turn(p - seat[i], za, body_roll);
    n = turn(n, za, body_roll);
    // The actor frame: x to the boat's right, z along its bow.
    float c = cos(actor_yaw), s = sin(actor_yaw);
    vec3 right = vec3(c, 0.0, -s), fwd = vec3(s, 0.0, c);
    pos = actor_pos + right*p.x + vec3(0.0, p.y, 0.0) + fwd*p.z;
    normal = right*n.x + vec3(0.0, n.y, 0.0) + fwd*n.z;
    coat = in_coat;
    coat_n = in_coat_n;
    color = in_color;
    part = in_part;
    along = in_along;
    glow = in_glow;
    vec3 q = pos;
    q.y *= mirror;
    gl_Position = project(q);
}
