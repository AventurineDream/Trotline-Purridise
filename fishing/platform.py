"""SDL2 window, a shared OpenGL presenter, keyboard, and SDL_ttf text."""

from __future__ import annotations

import ctypes
from collections import OrderedDict
from ctypes import c_char_p, c_int, c_uint8, c_uint16, c_uint32, c_void_p
from pathlib import Path

import numpy as np

from .bundle import bundled_library, is_frozen, platform_library_name
from .gamepad import (
    Gamepad, SDL_ControllerAxisEvent, SDL_ControllerButtonEvent,
    SDL_ControllerDeviceEvent, SDL_CONTROLLERDEVICEADDED,
    SDL_CONTROLLERDEVICEREMAPPED, SDL_CONTROLLERDEVICEREMOVED,
    SDL_INIT_GAMECONTROLLER, SDL_INIT_JOYSTICK,
)

SDL_INIT_AUDIO = 0x00000010
SDL_INIT_VIDEO = 0x00000020
SDL_WINDOWPOS_CENTERED = 0x2FFF0000
SDL_WINDOW_SHOWN = 0x00000004
SDL_WINDOW_OPENGL = 0x00000002
SDL_QUIT = 0x100
SDL_WINDOWEVENT = 0x200
SDL_WINDOWEVENT_FOCUS_GAINED = 12
SDL_WINDOWEVENT_FOCUS_LOST = 13
SDL_KEYDOWN = 0x300
SDL_KEYUP = 0x301
SDL_MOUSEBUTTONDOWN = 0x401
SDL_MOUSEWHEEL = 0x403
RGB24 = 0x17101803
ARGB8888 = 0x16362004

SCAN = {
    "a": 4, "b": 5, "c": 6, "d": 7, "e": 8, "f": 9, "g": 10,
    "h": 11, "i": 12, "j": 13, "k": 14, "l": 15, "m": 16,
    "n": 17, "o": 18, "p": 19, "q": 20, "r": 21, "s": 22,
    "t": 23, "u": 24, "v": 25, "w": 26, "x": 27, "y": 28, "z": 29,
    "1": 30, "2": 31, "3": 32, "4": 33, "5": 34,
    "6": 35, "7": 36, "8": 37, "9": 38, "0": 39,
    "return": 40, "esc": 41, "backspace": 42, "tab": 43, "space": 44,
    "minus": 45, "equals": 46, "left_bracket": 47,
    "right_bracket": 48, "backslash": 49, "semicolon": 51,
    "apostrophe": 52, "grave": 53, "comma": 54, "period": 55, "slash": 56,
    "right": 79, "left": 80, "down": 81, "up": 82,
    "shift": 225, "rshift": 229,
}
_SCAN_NAMES = {code: name for name, code in SCAN.items()}

# Monospace faces first: the HUD and help pages are measured and laid out for a
# monospace "mono" family. The proportional DejaVuSans entries come last, as a
# final fallback only, so a machine with no mono font still starts.
FONT_CANDIDATES = (
    "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationMono-Regular.ttf",
    "/usr/share/fonts/TTF/LiberationMono-Regular.ttf",
    "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf",
    "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
)


class SDL_Rect(ctypes.Structure):
    _fields_ = [("x", c_int), ("y", c_int), ("w", c_int), ("h", c_int)]


class SDL_DisplayMode(ctypes.Structure):
    _fields_ = [
        ("format", c_uint32), ("w", c_int), ("h", c_int),
        ("refresh_rate", c_int), ("driverdata", c_void_p),
    ]


class SDL_Surface(ctypes.Structure):
    _fields_ = [
        ("flags", c_uint32),
        ("format", c_void_p),
        ("w", c_int),
        ("h", c_int),
        ("pitch", c_int),
        ("pixels", c_void_p),
        ("userdata", c_void_p),
        ("locked", c_int),
        ("list_blitmap", c_void_p),
        ("clip_x", c_int),
        ("clip_y", c_int),
        ("clip_w", c_int),
        ("clip_h", c_int),
        ("map", c_void_p),
        ("refcount", c_int),
    ]


class SDL_Color(ctypes.Structure):
    _fields_ = [("r", c_uint8), ("g", c_uint8), ("b", c_uint8), ("a", c_uint8)]


class SDL_Keysym(ctypes.Structure):
    _fields_ = [("scancode", c_int), ("sym", c_int), ("mod", c_uint16), ("unused", c_uint32)]


class SDL_KeyboardEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("windowID", c_uint32),
        ("state", c_uint8), ("repeat", c_uint8), ("padding2", c_uint8), ("padding3", c_uint8),
        ("keysym", SDL_Keysym),
    ]


class SDL_WindowEvent(ctypes.Structure):
    _fields_ = [
        ("type", c_uint32), ("timestamp", c_uint32), ("windowID", c_uint32),
        ("event", c_uint8), ("padding1", c_uint8), ("padding2", c_uint8), ("padding3", c_uint8),
        ("data1", c_int), ("data2", c_int),
    ]


class SDL_MouseButtonEvent(ctypes.Structure):
    # SDL2: https://wiki.libsdl.org/SDL2/SDL_MouseButtonEvent
    _fields_ = [("type", c_uint32), ("timestamp", c_uint32), ("windowID", c_uint32),
                ("which", c_uint32), ("button", c_uint8), ("state", c_uint8),
                ("clicks", c_uint8), ("padding1", c_uint8), ("x", c_int), ("y", c_int)]


class SDL_MouseWheelEvent(ctypes.Structure):
    # Only the stable SDL2 prefix is read; later precision fields are optional.
    _fields_ = [("type", c_uint32), ("timestamp", c_uint32), ("windowID", c_uint32),
                ("which", c_uint32), ("x", c_int), ("y", c_int), ("direction", c_uint32)]


class SDL_Event(ctypes.Union):
    _fields_ = [
        ("type", c_uint32), ("key", SDL_KeyboardEvent), ("window", SDL_WindowEvent),
        ("caxis", SDL_ControllerAxisEvent),
        ("button", SDL_MouseButtonEvent), ("wheel", SDL_MouseWheelEvent),
        ("cbutton", SDL_ControllerButtonEvent),
        ("cdevice", SDL_ControllerDeviceEvent), ("pad", c_uint8 * 56),
    ]


class SDL_AudioSpec(ctypes.Structure):
    _fields_ = [
        ("freq", c_int),
        ("format", c_uint16),
        ("channels", c_uint8),
        ("silence", c_uint8),
        ("samples", c_uint16),
        ("padding", c_uint16),
        ("size", c_uint32),
        ("callback", c_void_p),
        ("userdata", c_void_p),
    ]


def _load(name: str):
    """Load an SDL library. A PyInstaller build tries its own copy first."""
    bundled = bundled_library(name)
    if bundled is not None:
        try:
            return ctypes.CDLL(str(bundled))
        except OSError:
            pass
    try:
        return ctypes.CDLL(name)
    except OSError as error:
        own_name = platform_library_name(name)
        if own_name != name:
            try:
                return ctypes.CDLL(own_name)
            except OSError:
                pass
        local_path = Path.home() / ".local" / "lib" / name
        if local_path.exists():
            return ctypes.CDLL(str(local_path))
        # A source clone on Windows or macOS keeps its SDL libraries beside the game.
        beside = Path(__file__).resolve().parents[1] / own_name
        if beside.is_file():
            return ctypes.CDLL(str(beside))
        raise error


# Fonts a build carries (scripts/build_package.py), tried before the system's when frozen.
BUNDLED_FONTS = {
    "sans": ("LiberationSans-Regular.ttf", "DejaVuSans.ttf"),
    "serif": ("LiberationSerif-Regular.ttf", "DejaVuSerif.ttf"),
    "mono": ("LiberationMono-Regular.ttf", "DejaVuSansMono.ttf", "DejaVuSans.ttf"),
}


def find_font(family="mono") -> str:
    import os
    fonts = Path(__file__).with_name("assets") / "fonts"
    bundled_dyslexia = fonts / "AtkinsonHyperlegible-Regular.ttf"
    preferred = {
        "dyslexia": (str(bundled_dyslexia),),
        "sans": ("/usr/share/fonts/noto/NotoSans-Regular.ttf",
                 "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        "serif": ("/usr/share/fonts/liberation/LiberationSerif-Regular.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
    }.get(family, ())
    if is_frozen():
        packaged = tuple(str(fonts / name) for name in BUNDLED_FONTS.get(family, ()))
        preferred = packaged + preferred
    for path in preferred + FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("No TTF font found for the HUD")


class Text:
    """Cached SDL_ttf draws. Works without a window."""

    def __init__(self):
        self.sdl = _load("libSDL2-2.0.so.0")
        self.ttf = _load("libSDL2_ttf-2.0.so.0")
        self.sdl.SDL_Init.argtypes = [c_uint32]
        self.sdl.SDL_Init.restype = c_int
        self.sdl.SDL_GetError.restype = c_char_p
        self.ttf.TTF_Init.restype = c_int
        self.ttf.TTF_OpenFont.argtypes = [c_char_p, c_int]
        self.ttf.TTF_OpenFont.restype = c_void_p
        self.ttf.TTF_CloseFont.argtypes = [c_void_p]
        self.ttf.TTF_RenderUTF8_Blended.argtypes = [c_void_p, c_char_p, SDL_Color]
        self.ttf.TTF_RenderUTF8_Blended.restype = ctypes.POINTER(SDL_Surface)
        self.sdl.SDL_ConvertSurfaceFormat.argtypes = [ctypes.POINTER(SDL_Surface), c_uint32, c_uint32]
        self.sdl.SDL_ConvertSurfaceFormat.restype = ctypes.POINTER(SDL_Surface)
        self.sdl.SDL_FreeSurface.argtypes = [ctypes.POINTER(SDL_Surface)]
        if self.sdl.SDL_Init(0) < 0:
            raise RuntimeError(self._err())
        if self.ttf.TTF_Init() < 0:
            raise RuntimeError(self._err())
        self.fonts: dict[tuple, c_void_p] = {}
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.cache_limit = 8 * 1024 * 1024

    def _err(self) -> str:
        err = self.sdl.SDL_GetError()
        return err.decode() if err else "sdl error"

    def font(self, size: int, family="mono"):
        key = (size, family)
        if key not in self.fonts:
            ptr = self.ttf.TTF_OpenFont(find_font(family).encode(), size)
            if not ptr:
                raise RuntimeError(self._err())
            self.fonts[key] = ptr
        return self.fonts[key]

    def render(self, text: str, size: int, color: tuple[int, int, int], family="mono") -> np.ndarray:
        key = (text, size, color, family)
        hit = self.cache.get(key)
        if hit is not None:
            self.cache.move_to_end(key)
            return hit
        if "✦" in text:
            rgba = self._sparkle_text(text, size, color, family)
            self._cache_image(key, rgba)
            return rgba
        col = SDL_Color(color[0], color[1], color[2], 255)
        surf = self.ttf.TTF_RenderUTF8_Blended(self.font(size, family), text.encode("utf-8"), col)
        if not surf:
            img = np.zeros((size, max(8, size // 2), 4), np.uint8)
            return img
        conv = self.sdl.SDL_ConvertSurfaceFormat(surf, ARGB8888, 0)
        self.sdl.SDL_FreeSurface(surf)
        if not conv:
            img = np.zeros((size, 8, 4), np.uint8)
            return img
        s = conv.contents
        # Little-endian ARGB8888 is B, G, R, A in memory.
        buf = ctypes.string_at(s.pixels, s.h * s.pitch)
        raw = np.frombuffer(buf, dtype=np.uint8).reshape(s.h, s.pitch)
        pix = raw[:, : s.w * 4].reshape(s.h, s.w, 4)
        rgba = np.empty_like(pix)
        rgba[:, :, 0] = pix[:, :, 2]
        rgba[:, :, 1] = pix[:, :, 1]
        rgba[:, :, 2] = pix[:, :, 0]
        rgba[:, :, 3] = pix[:, :, 3]
        rgba = rgba.copy()
        self.sdl.SDL_FreeSurface(conv)
        self._cache_image(key, rgba)
        return rgba

    def _sparkle_text(self, text, size, color, family):
        """Supply the shiny marker even in fonts without U+2726 coverage."""
        parts = [self.render(part, size, color, family) if part else None
                 for part in text.split("✦")]
        height = max(self.render("M", size, color, family).shape[0],
                     max((part.shape[0] for part in parts if part is not None), default=0))
        width = max(5, round(size * .7))
        # A tiny antialiased four-point sparkle, with the font's line height.
        yy, xx = np.mgrid[:height * 4, :width * 4]
        dx = np.abs((xx + .5) / 4 - width / 2) / (width * .46)
        dy = np.abs((yy + .5) / 4 - height / 2) / (width * .46)
        mask = (dx ** .65 + dy ** .65 <= 1).reshape(height, 4, width, 4)
        sparkle = np.zeros((height, width, 4), np.uint8)
        sparkle[:, :, :3] = color
        sparkle[:, :, 3] = np.rint(mask.mean(axis=(1, 3)) * 255).astype(np.uint8)
        pieces = []
        for index, part in enumerate(parts):
            if index:
                pieces.append(sparkle)
            if part is not None:
                # SDL_ttf can extend a surface for descenders/overhangs. Keep
                # the common font baseline and pad its transparent bottom.
                pieces.append(np.pad(part, ((0, height - part.shape[0]), (0, 0), (0, 0))))
        return np.concatenate(pieces, axis=1)

    def _cache_image(self, key, rgba):
        if rgba.nbytes <= self.cache_limit:
            while self.cache and (self.cache_bytes + rgba.nbytes > self.cache_limit or len(self.cache)>=512):
                _old_key, old = self.cache.popitem(last=False)
                self.cache_bytes -= old.nbytes
            self.cache[key] = rgba
            self.cache_bytes += rgba.nbytes

    def close(self):
        self.cache.clear()
        self.cache_bytes = 0
        for font in self.fonts.values():
            self.ttf.TTF_CloseFont(font)
        self.fonts.clear()


class Input:
    def __init__(self):
        self.held: set[str] = set()
        self.pressed: set[str] = set()
        self.keyboard_held: set[str] = set()
        self.keyboard_pressed: set[str] = set()
        self.keyboard_press_order: list[str] = []
        self.gamepad_held: set[str] = set()
        self.gamepad_pressed: set[str] = set()
        self.device = "keyboard"
        self.quit = False
        self.focused = True
        self.mouse_click = None
        self.mouse_wheel = 0
        self.viewport = (1280, 720)
        self._rep: dict[str, float] = {}

    def tap(self, name: str, dt: float) -> bool:
        if name in self.pressed:
            self._rep[name] = 0.0
            return True
        if name in self.held:
            self._rep[name] = self._rep.get(name, 0.0) + dt
            if self._rep[name] > 0.38:
                self._rep[name] = 0.26
                return True
            return False
        self._rep.pop(name, None)
        return False


class Platform:
    def __init__(self, w: int, h: int, title: str = "Briar Lake", *, graphics=True, verify_pixels=False):
        self.sdl = _load("libSDL2-2.0.so.0")
        s = self.sdl
        s.SDL_Init.argtypes = [c_uint32]
        s.SDL_Init.restype = c_int
        s.SDL_GetError.restype = c_char_p
        s.SDL_CreateWindow.argtypes = [c_char_p, c_int, c_int, c_int, c_int, c_uint32]
        s.SDL_CreateWindow.restype = c_void_p
        s.SDL_GetWindowSurface.argtypes = [c_void_p]
        s.SDL_GetWindowSurface.restype = ctypes.POINTER(SDL_Surface)
        s.SDL_UpdateWindowSurface.argtypes = [c_void_p]
        s.SDL_UpdateWindowSurface.restype = c_int
        s.SDL_CreateRGBSurfaceWithFormatFrom.argtypes = [c_void_p, c_int, c_int, c_int, c_int, c_uint32]
        s.SDL_CreateRGBSurfaceWithFormatFrom.restype = ctypes.POINTER(SDL_Surface)
        s.SDL_UpperBlit.argtypes = [
            ctypes.POINTER(SDL_Surface), ctypes.POINTER(SDL_Rect),
            ctypes.POINTER(SDL_Surface), ctypes.POINTER(SDL_Rect),
        ]
        s.SDL_UpperBlit.restype = c_int
        s.SDL_FreeSurface.argtypes = [ctypes.POINTER(SDL_Surface)]
        s.SDL_ConvertSurfaceFormat.argtypes = [ctypes.POINTER(SDL_Surface),c_uint32,c_uint32]
        s.SDL_ConvertSurfaceFormat.restype = ctypes.POINTER(SDL_Surface)
        s.SDL_PollEvent.argtypes = [ctypes.POINTER(SDL_Event)]
        s.SDL_PollEvent.restype = c_int
        s.SDL_GetKeyboardState.argtypes = [ctypes.POINTER(c_int)]
        s.SDL_GetKeyboardState.restype = ctypes.POINTER(c_uint8)
        s.SDL_GetTicks64.restype = ctypes.c_uint64
        s.SDL_Delay.argtypes = [c_uint32]
        s.SDL_GetCurrentDisplayMode.argtypes = [c_int, ctypes.POINTER(SDL_DisplayMode)]
        s.SDL_GetCurrentDisplayMode.restype = c_int
        s.SDL_DestroyWindow.argtypes = [c_void_p]
        s.SDL_Quit.argtypes = []
        s.SDL_GL_SetAttribute.argtypes = [c_int,c_int]
        s.SDL_GL_SetAttribute.restype = c_int
        s.SDL_GL_CreateContext.argtypes = [c_void_p]
        s.SDL_GL_CreateContext.restype = c_void_p
        s.SDL_GL_MakeCurrent.argtypes = [c_void_p,c_void_p]
        s.SDL_GL_MakeCurrent.restype = c_int
        s.SDL_GL_SwapWindow.argtypes = [c_void_p]
        s.SDL_GL_GetDrawableSize.argtypes = [c_void_p,ctypes.POINTER(c_int),ctypes.POINTER(c_int)]
        s.SDL_GL_DeleteContext.argtypes = [c_void_p]
        s.SDL_GL_GetProcAddress.argtypes = [c_char_p]
        s.SDL_GL_GetProcAddress.restype = c_void_p
        self.context = None
        self.gl_context = None
        self._gl_objects = []
        self._shown_pixels = None
        self.verify_pixels = verify_pixels
        self.w,self.h = w,h
        # Video and audio initialization are idempotent.
        if s.SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO | SDL_INIT_JOYSTICK
                      | SDL_INIT_GAMECONTROLLER) < 0:
            raise RuntimeError(self._err())
        self.gamepad = Gamepad(s)
        self._last_device = "keyboard"
        self.window = None
        if graphics:
            try:
                import moderngl
                # SDL owns the only window context. Both scenery and final
                # presentation use it; no SDL surface creates another renderer.
                for attr,value in ((17,3),(18,3),(21,1),(5,1)):
                    if s.SDL_GL_SetAttribute(attr,value)<0:
                        raise RuntimeError(self._err())
                self.window = s.SDL_CreateWindow(title.encode(),SDL_WINDOWPOS_CENTERED,
                    SDL_WINDOWPOS_CENTERED,w,h,SDL_WINDOW_SHOWN|SDL_WINDOW_OPENGL)
                if not self.window:
                    raise RuntimeError(self._err())
                self.gl_context = s.SDL_GL_CreateContext(self.window)
                if not self.gl_context:
                    raise RuntimeError(self._err())
                self.context = moderngl.create_context(require=330)
                self._setup_presenter()
            except (ImportError,RuntimeError,ValueError) as exc:
                self._close_graphics()
                if self.window:
                    s.SDL_DestroyWindow(self.window)
                    self.window = None
                import sys
                print(f"Window graphics unavailable ({exc}); using CPU scenery.",file=sys.stderr)
        if not self.window:
            self.window = s.SDL_CreateWindow(title.encode(),SDL_WINDOWPOS_CENTERED,
                SDL_WINDOWPOS_CENTERED,w,h,SDL_WINDOW_SHOWN)
        if not self.window:
            raise RuntimeError(self._err())
        self._input = Input()
        self._focused = True

    def _setup_presenter(self):
        import moderngl
        ctx = self.context
        self._present_program = ctx.program(
            vertex_shader="""#version 330
                in vec2 xy;
                out vec2 uv;
                void main() { uv=xy*0.5+0.5; gl_Position=vec4(xy,0,1); }""",
            fragment_shader="""#version 330
                uniform sampler2D image;
                in vec2 uv;
                out vec4 color;
                void main() { color=vec4(texture(image,vec2(uv.x,1.0-uv.y)).rgb,1); }""")
        self._gl_objects.append(self._present_program)
        self._present_buffer = ctx.buffer(np.array([[-1,-1],[3,-1],[-1,3]],np.float32).tobytes())
        self._gl_objects.append(self._present_buffer)
        self._present_vao = ctx.vertex_array(self._present_program,[(self._present_buffer,"2f","xy")])
        self._gl_objects.append(self._present_vao)
        self._present_texture = ctx.texture((self.w,self.h),3,alignment=1)
        self._gl_objects.append(self._present_texture)
        self._present_texture.filter = (moderngl.NEAREST,moderngl.NEAREST)
        self._present_program["image"] = 0
        # Read the window's back buffer directly for verification. An offscreen
        # framebuffer uses COLOR_ATTACHMENT0; the default window uses GL_BACK.
        def proc(name, args):
            address = self.sdl.SDL_GL_GetProcAddress(name)
            if not address:
                raise RuntimeError(f"Missing OpenGL function {name.decode()}")
            return ctypes.CFUNCTYPE(None,*args)(address)
        self._read_buffer = proc(b"glReadBuffer",[c_uint32])
        self._pixel_store = proc(b"glPixelStorei",[c_uint32,c_int])
        self._read_pixels = proc(b"glReadPixels",[c_int,c_int,c_int,c_int,c_uint32,c_uint32,c_void_p])

    def make_current(self):
        if self.gl_context and self.sdl.SDL_GL_MakeCurrent(self.window,self.gl_context)<0:
            raise RuntimeError(self._err())

    def _close_graphics(self):
        if self.context is not None:
            self.make_current()
            for obj in reversed(self._gl_objects):
                obj.release()
            self._gl_objects.clear()
            self.context.release()
            self.context = None
        if self.gl_context:
            self.sdl.SDL_GL_DeleteContext(self.gl_context)
            self.gl_context = None

    def _err(self) -> str:
        err = self.sdl.SDL_GetError()
        return err.decode() if err else "sdl error"

    @staticmethod
    def display_size() -> tuple[int, int]:
        sdl = _load("libSDL2-2.0.so.0")
        sdl.SDL_Init.argtypes = [c_uint32]
        sdl.SDL_Init.restype = c_int
        sdl.SDL_GetCurrentDisplayMode.argtypes = [c_int, ctypes.POINTER(SDL_DisplayMode)]
        sdl.SDL_GetCurrentDisplayMode.restype = c_int
        # Init is idempotent if Platform already did it. Calling before the
        # window is fine: SDL_Init of an already-initialized subsystem succeeds.
        sdl.SDL_Init(SDL_INIT_VIDEO)
        mode = SDL_DisplayMode()
        if sdl.SDL_GetCurrentDisplayMode(0, ctypes.byref(mode)) != 0 or mode.w <= 0:
            return 1280, 720
        return int(mode.w), int(mode.h)

    def ticks(self) -> int:
        return int(self.sdl.SDL_GetTicks64())

    def delay(self, ms: int):
        if ms > 0:
            self.sdl.SDL_Delay(ms)

    def poll(self, dt: float = 0.0) -> Input:
        # Reuse one Input so key-repeat timers survive across frames.
        inp = self._input
        inp.quit = False
        inp.mouse_click = None
        inp.mouse_wheel = 0
        inp.viewport = (self.w, self.h)
        keyboard_pressed: set[str] = set()
        keyboard_press_order: list[str] = []
        event = SDL_Event()
        while self.sdl.SDL_PollEvent(ctypes.byref(event)):
            if event.type == SDL_QUIT:
                inp.quit = True
            elif event.type == SDL_WINDOWEVENT:
                if event.window.event == SDL_WINDOWEVENT_FOCUS_LOST:
                    self._focused = False
                    keyboard_pressed.clear()
                    keyboard_press_order.clear()
                    inp._rep.clear()
                    self.gamepad.clear_input()
                    inp.mouse_click = None
                    inp.mouse_wheel = 0
                elif event.window.event == SDL_WINDOWEVENT_FOCUS_GAINED:
                    self._focused = True
            elif event.type == SDL_MOUSEBUTTONDOWN and self._focused:
                if event.button.button == 1:
                    inp.mouse_click = (event.button.x, event.button.y)
                    self._last_device = "mouse"
            elif event.type == SDL_MOUSEWHEEL and self._focused:
                inp.mouse_wheel += event.wheel.y * (-1 if event.wheel.direction == 1 else 1)
                self._last_device = "mouse"
            elif event.type == SDL_KEYDOWN and self._focused and not event.key.repeat:
                name = _SCAN_NAMES.get(event.key.keysym.scancode)
                if name is not None:
                    # A press and release can both arrive between slow frames.
                    # Keep that edge even though the final keyboard state is up.
                    keyboard_pressed.add(name)
                    keyboard_press_order.append(name)
                    self._last_device = "keyboard"
            elif self._focused or event.type in (
                SDL_CONTROLLERDEVICEADDED, SDL_CONTROLLERDEVICEREMOVED,
                SDL_CONTROLLERDEVICEREMAPPED,
            ):
                if self.gamepad.handle_event(event):
                    self._last_device = "gamepad"
        n = c_int()
        state = self.sdl.SDL_GetKeyboardState(ctypes.byref(n))
        keyboard_held: set[str] = set()
        if state and self._focused:
            for name, code in SCAN.items():
                if code < n.value and state[code]:
                    keyboard_held.add(name)
        gamepad_pressed, gamepad_held, gamepad_activity = self.gamepad.sample(
            dt, now_ms=self.ticks(),
        )
        if gamepad_activity:
            self._last_device = "gamepad"
        inp.keyboard_pressed = keyboard_pressed
        inp.keyboard_held = keyboard_held
        inp.keyboard_press_order = keyboard_press_order
        inp.gamepad_pressed = gamepad_pressed
        inp.gamepad_held = gamepad_held
        inp.pressed = keyboard_pressed | gamepad_pressed
        inp.held = keyboard_held | gamepad_held
        inp.device = self._last_device
        # SDL's held snapshot still controls throttle/steering and menu repeat.
        # OS key-repeat events must never become additional one-shot actions.
        for name in inp._rep.keys() - inp.held:
            inp._rep.pop(name, None)
        inp.focused = self._focused
        return inp

    def present(self, rgb: np.ndarray):
        """rgb is uint8 (H, W, 3), matching the window."""
        if rgb.shape[0] != self.h or rgb.shape[1] != self.w:
            raise ValueError(f"frame is {rgb.shape}, window is {self.h}x{self.w}")
        frame = np.ascontiguousarray(rgb)
        if self.context is not None:
            import moderngl
            self.make_current()
            ctx = self.context
            self._present_texture.write(frame.tobytes(),alignment=1)
            self._present_texture.use(0)
            ctx.screen.use()
            width,height = c_int(),c_int()
            self.sdl.SDL_GL_GetDrawableSize(self.window,ctypes.byref(width),ctypes.byref(height))
            ctx.viewport = (0,0,width.value,height.value)
            ctx.disable(moderngl.DEPTH_TEST|moderngl.BLEND|moderngl.CULL_FACE)
            self._present_vao.render()
            if self.verify_pixels:
                pixels = np.empty((height.value,width.value,3),np.uint8)
                self._read_buffer(0x0405)  # GL_BACK
                self._pixel_store(0x0D05,1)  # GL_PACK_ALIGNMENT
                self._read_pixels(0,0,width.value,height.value,0x1907,0x1401,
                                  pixels.ctypes.data_as(c_void_p))  # RGB / UNSIGNED_BYTE
                self._shown_pixels = pixels[::-1].copy()
            error = ctx.error
            if error!="GL_NO_ERROR":
                raise RuntimeError(f"Window presentation failed: {error}")
            self.sdl.SDL_GL_SwapWindow(self.window)
            return
        src = self.sdl.SDL_CreateRGBSurfaceWithFormatFrom(
            frame.ctypes.data_as(c_void_p), self.w, self.h, 24, self.w * 3, RGB24,
        )
        if not src:
            raise RuntimeError(self._err())
        dst = self.sdl.SDL_GetWindowSurface(self.window)
        if not dst:
            self.sdl.SDL_FreeSurface(src)
            raise RuntimeError(self._err())
        rect = SDL_Rect(0, 0, self.w, self.h)
        try:
            if self.sdl.SDL_UpperBlit(src,ctypes.byref(rect),dst,ctypes.byref(rect))<0:
                raise RuntimeError(self._err())
        finally:
            self.sdl.SDL_FreeSurface(src)
        if self.sdl.SDL_UpdateWindowSurface(self.window)<0:
            raise RuntimeError(self._err())

    def read_surface(self):
        """Read back the pixels actually submitted to this SDL window."""
        if self.context is not None:
            if self._shown_pixels is None:
                raise RuntimeError("Enable verify_pixels to capture the displayed window")
            return self._shown_pixels.copy()
        dst = self.sdl.SDL_GetWindowSurface(self.window)
        if not dst:
            raise RuntimeError(self._err())
        converted = self.sdl.SDL_ConvertSurfaceFormat(dst,RGB24,0)
        if not converted:
            raise RuntimeError(self._err())
        try:
            surf = converted.contents
            data = ctypes.string_at(surf.pixels,surf.h*surf.pitch)
            raw = np.frombuffer(data,np.uint8).reshape(surf.h,surf.pitch)
            return raw[:,:surf.w*3].reshape(surf.h,surf.w,3).copy()
        finally:
            self.sdl.SDL_FreeSurface(converted)

    def close(self):
        self.gamepad.close()
        self._close_graphics()
        if self.window:
            self.sdl.SDL_DestroyWindow(self.window)
            self.window = None
        self.sdl.SDL_Quit()
