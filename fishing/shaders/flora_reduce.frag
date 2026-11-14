// Atlas bake: block means for the soft canopy fields (fishing/sprites.py
// soft_fields). Each output texel averages a kx x ky block of the painted
// layer: coverage (any primitive there) and the winning height where covered.
// Blocks follow the layer's top-down rows; a remainder at the bottom is
// dropped, as the NumPy reference does.
uniform sampler2D t_cov, t_z;
uniform ivec2 block, low;   // block size, output size (texels)
uniform int layer_h;
out vec4 o_soft;
void main() {
    ivec2 o = ivec2(gl_FragCoord.xy);
    int top_row = (low.y-1-o.y)*block.y;     // top-down row of the block's first line
    float c = 0.0, z = 0.0;
    for (int dy = 0; dy < block.y; dy++) {
        int row = layer_h-1-(top_row+dy);
        for (int dx = 0; dx < block.x; dx++) {
            ivec2 ij = ivec2(o.x*block.x+dx, row);
            float hit = step(0.02, texelFetch(t_cov, ij, 0).r);
            c += hit;
            z += hit*texelFetch(t_z, ij, 0).r;
        }
    }
    float n = float(block.x*block.y);
    o_soft = vec4(c/n, z/n, 0.0, 1.0);
}
