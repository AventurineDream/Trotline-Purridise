in vec3 in_pos;
out vec3 pos;
void main() {
    pos = in_pos;
    gl_Position = project(pos);
}
