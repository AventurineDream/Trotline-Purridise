in vec2 in_xy;
out vec2 uv;
void main() {
    uv = in_xy*0.5+0.5;
    gl_Position = vec4(in_xy,0.999999,1);
}
