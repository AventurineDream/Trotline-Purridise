// The cat rig (V1-29): blends two built poses, then breathes, sways its tail,
// flicks its ears, waves and turns its head toward the player. The CPU twin of
// this motion is fishing/actors.py animate(); keep the two in step.
in vec3 in_pos_a, in_pos_b, in_nrm_a, in_nrm_b, in_coat, in_coat_n, in_color;
in float in_part, in_along, in_glow, in_rig;
uniform vec3 actor_pos, neck, elbow;
uniform float actor_yaw, blend, head_yaw, breath, tail, tail_phase, flick, wave, wave_weight, cat_size;
out vec3 pos, normal, coat, coat_n, color;
out float along, glow;
flat out float part;

vec3 rot_y(vec3 p, vec3 pivot, float a) {
    vec3 d = p - pivot;
    return vec3(d.x*cos(a) + d.z*sin(a), d.y, -d.x*sin(a) + d.z*cos(a)) + pivot;
}
vec3 rot_z(vec3 p, vec3 pivot, float a) {
    vec3 d = p - pivot;
    return vec3(d.x*cos(a) - d.y*sin(a), d.x*sin(a) + d.y*cos(a), d.z) + pivot;
}

void main() {
    vec3 p = mix(in_pos_a, in_pos_b, blend);
    vec3 n = normalize(mix(in_nrm_a, in_nrm_b, blend) + vec3(1e-5));
    float rig = in_rig;
    if (abs(rig-5.0) < 0.5) { p.x *= 1.0+breath; p.z *= 1.0+breath; }
    if (abs(rig-3.0) < 0.5) {
        float a = in_along;
        p.x += tail*pow(a,1.5)*cos(tail_phase-2.5*a);
    }
    if (abs(rig-2.0) < 0.5) p.z -= flick*in_along*0.03*cat_size;
    if (abs(rig-4.0) < 0.5 && wave_weight > 0.0) p = rot_z(p, elbow, wave*wave_weight);
    if (abs(rig-1.0) < 0.5 || abs(rig-2.0) < 0.5) {
        p = rot_y(p, neck, head_yaw);
        n = rot_y(n, vec3(0.0), head_yaw);
    }
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
