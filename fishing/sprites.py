"""Procedural shore sprites. Baked once, tinted when drawn.

Shapes are big on purpose. A tree on the far bank is only a few dozen
pixels tall, so the silhouette has to read before the texture does.

Two families live here. The small RGBA sprites (`bake`, `nebula_sprites`)
feed the CPU renderer and tests and must keep their exact pixels. The
`Painter` below records the GL foliage atlas sprites as resolution-free
primitive lists that `florafx.PaintBaker` rasterises on the GPU: every
primitive also carries a height, normal, translucency and leaf/wood mask so
`foliage.frag` can light the sprite instead of trusting baked shading.
Only the small soft fields (canopy AO, openness) are NumPy, on a grid of
about one texel per design unit.
"""

from __future__ import annotations

import zlib

import numpy as np


def _img(w, h) -> np.ndarray:
    return np.zeros((h, w, 4), dtype=np.uint8)


def _stamp(img, color, mask):
    img[mask] = color


def _tri(img, ax, ay, bx, by, cx, cy, color):
    h, w, _ = img.shape
    minx = max(int(min(ax, bx, cx)), 0)
    maxx = min(int(max(ax, bx, cx)) + 1, w - 1)
    miny = max(int(min(ay, by, cy)), 0)
    maxy = min(int(max(ay, by, cy)) + 1, h - 1)
    if minx > maxx or miny > maxy:
        return
    ys, xs = np.mgrid[miny:maxy + 1, minx:maxx + 1]
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if abs(area) < 1:
        return
    w0 = (bx - xs) * (cy - ys) - (by - ys) * (cx - xs)
    w1 = (cx - xs) * (ay - ys) - (cy - ys) * (ax - xs)
    w2 = (ax - xs) * (by - ys) - (ay - ys) * (bx - xs)
    if area < 0:
        mask = (w0 <= 0) & (w1 <= 0) & (w2 <= 0)
    else:
        mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    region = img[miny:maxy + 1, minx:maxx + 1]
    region[mask] = color


def _ellipse(img, cx, cy, rx, ry, color):
    h, w, _ = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    mask = (xx - cx) ** 2 / (rx * rx) + (yy - cy) ** 2 / (ry * ry) <= 1
    _stamp(img, color, mask)


def pine() -> np.ndarray:
    img = _img(56, 112)
    img[78:108, 25:32] = (96, 68, 42, 255)
    img[100:110, 22:35] = (78, 54, 34, 255)
    tiers = (
        (8, 24, 48, 18, 86, 46),
        (22, 10, 46, 14, 74, 40),
        (38, 6, 50, 16, 96, 46),
        (54, 4, 52, 12, 68, 34),
        (70, 8, 48, 20, 58, 30),
    )
    for apex_y, left, right, g0, g1, g2 in tiers:
        mid = 28
        base = apex_y + 28
        _tri(img, mid, apex_y, left, base, right, base, (g0, g1, g2, 255))
        _tri(img, mid, apex_y + 10, left + 2, base, right - 2, base, (g0 - 6, g1 - 18, g2 - 8, 255))
    return img


def oak() -> np.ndarray:
    img = _img(72, 88)
    # Canopy first, trunk stamped over it so the stem stays visible.
    _ellipse(img, 36, 36, 28, 24, (28, 78, 36, 255))
    _ellipse(img, 28, 30, 16, 14, (46, 108, 48, 255))
    _ellipse(img, 46, 42, 14, 12, (18, 58, 26, 255))
    _ellipse(img, 34, 26, 10, 8, (62, 124, 58, 255))
    img[52:84, 32:41] = (102, 72, 46, 255)
    img[76:86, 28:46] = (86, 60, 38, 255)
    img[54:80, 33:36] = (128, 96, 64, 255)
    return img


def cypress() -> np.ndarray:
    img = _img(48, 128)
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    # Flared buttress. Wide at the water, narrow through the middle.
    t = np.clip((yy - 28) / 96.0, 0.0, 1.0)
    half = 3.0 + t * t * 14.0
    trunk = (np.abs(xx - 24) <= half) & (yy >= 26) & (yy < 126)
    _stamp(img, (86, 64, 44, 255), trunk)
    _stamp(img, (118, 90, 62, 255), trunk & (xx < 22) & (yy > 40))
    _stamp(img, (62, 46, 32, 255), trunk & (xx > 28) & (yy > 70))
    _ellipse(img, 24, 24, 12, 20, (16, 58, 36, 255))
    _ellipse(img, 22, 18, 7, 10, (28, 78, 44, 255))
    # Moss hangs off the crown in a few strands.
    drape = (yy > 20) & (yy < 78) & (np.abs(xx - 24) < 11) & (((xx * 3 + yy) % 5) == 0)
    _stamp(img, (14, 42, 28, 255), drape)
    return img


def rock() -> np.ndarray:
    img = _img(48, 32)
    _ellipse(img, 24, 18, 20, 12, (92, 90, 82, 255))
    _ellipse(img, 18, 16, 10, 8, (128, 124, 112, 255))
    _ellipse(img, 30, 20, 9, 6, (68, 66, 60, 255))
    h, w, _ = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    shadow = (yy > 20) & (img[:, :, 3] > 0)
    img[shadow, 0] = (img[shadow, 0].astype(np.int16) * 0.65).astype(np.uint8)
    img[shadow, 1] = (img[shadow, 1].astype(np.int16) * 0.65).astype(np.uint8)
    img[shadow, 2] = (img[shadow, 2].astype(np.int16) * 0.65).astype(np.uint8)
    return img


def stump() -> np.ndarray:
    img = _img(28, 24)
    _ellipse(img, 14, 10, 11, 6, (140, 104, 68, 255))
    img[10:22, 6:22] = (102, 74, 48, 255)
    img[12:20, 8:14] = (78, 54, 34, 255)
    img[11:13, 10:18] = (64, 44, 28, 255)
    return img


def knee() -> np.ndarray:
    img = _img(18, 32)
    img[8:30, 7:12] = (92, 68, 46, 255)
    img[4:12, 5:14] = (118, 88, 58, 255)
    img[14:28, 8:11] = (70, 50, 34, 255)
    img[26:31, 5:15] = (62, 48, 32, 255)
    return img


def reed() -> np.ndarray:
    img = _img(24, 48)
    for x, lean in ((6, 0), (11, 1), (16, -1)):
        for y in range(16, 46):
            xx = x + lean * (y // 16)
            if 0 <= xx < 24:
                img[y, xx] = (48, 78, 36, 255)
        img[12:18, x - 1:x + 2] = (92, 64, 36, 255)
        img[10:13, x:x + 1] = (120, 86, 48, 255)
    return img


def buoy(rgb: tuple[int, int, int], flagged: bool) -> np.ndarray:
    img = _img(16, 28)
    img[12:22, 4:12] = (*rgb, 255)
    img[10:13, 6:10] = (40, 36, 32, 255)
    img[14:18, 5:7] = (min(rgb[0] + 40, 255), min(rgb[1] + 40, 255), min(rgb[2] + 40, 255), 255)
    img[22:25, 6:10] = (30, 30, 28, 255)
    if flagged:
        img[2:12, 8:10] = (40, 32, 24, 255)
        img[3:8, 10:15] = (170, 40, 32, 255)
    return img


# World-space aspect ratios match the small CPU sprites and the shared GL atlas.
PROP_ASPECTS = {
    "cattail": 2/3, "grass": 1.5, "flowers": 1.2, "shrub": 7/6,
    "palmetto": 1.5,
    "driftwood": 7/3, "shore_stone": 2.4, "heron": 3/7, "duck": 5/3,
    "spire": 40/112, "starlily": 4/3, "kelp": 28/96, "meteor": 1.3, "lightreed": 1/2,
}
WATERLINE_KINDS = frozenset(("reed", "knee", "cattail", "heron", "duck", "kelp", "meteor", "lightreed"))

# Per-lake palettes: channel gains that `Painter.tint` applies to each lake's leafy
# primitives, so one species reads warmer, cooler or greyer from lake to lake.
# Nebula's flora glows and stays neutral.
LAKE_TINT = {
    "briar": (1.00, 1.04, 0.90),
    "cedar": (1.12, 1.02, 0.78),
    "flathead": (0.84, 1.00, 1.16),
    "crater": (0.90, 0.98, 1.14),
    "nebula": (1.00, 1.00, 1.00),
}


def _stroke(img, a, b, width, color):
    """A bounded rounded line, used for stems, twigs and bird silhouettes."""
    h, w = img.shape[:2]
    ax, ay = a
    bx, by = b
    x0, x1 = max(0, int(min(ax,bx)-width-1)), min(w, int(max(ax,bx)+width+2))
    y0, y1 = max(0, int(min(ay,by)-width-1)), min(h, int(max(ay,by)+width+2))
    if x0>=x1 or y0>=y1:
        return
    yy, xx = np.mgrid[y0:y1,x0:x1]
    dx, dy = bx-ax, by-ay
    t = np.clip(((xx-ax)*dx+(yy-ay)*dy)/max(dx*dx+dy*dy,0.001),0,1)
    mask = (xx-ax-t*dx)**2+(yy-ay-t*dy)**2<=width*width
    img[y0:y1,x0:x1][mask] = color


def cattail() -> np.ndarray:
    img = _img(64,96)
    rng = np.random.default_rng(1003)
    for i in range(15):
        x = float(rng.uniform(15,50))
        tip = float(rng.uniform(20,65))
        lean = float(rng.uniform(-23,23))
        c = (int(rng.uniform(55,90)),int(rng.uniform(89,121)),45,255)
        _tri(img,x,94,x+lean,tip,x+3,92,c)
        if i%3==0:
            _stroke(img,(x+1,92),(x+lean*0.75,tip+12),0.5,(115,136,65,255))
    for x,tip,lean in ((16,24,-3),(30,13,1),(44,28,5),(37,38,3)):
        _stroke(img,(x,94),(x+lean,tip),0.8,(87,105,53,255))
        _stroke(img,(x+lean,tip+1),(x+lean,tip-11),2.2,(89,60,35,255))
        _stroke(img,(x+lean-0.8,tip),(x+lean-0.8,tip-9),0.6,(135,97,55,255))
        _stroke(img,(x+lean,tip-11),(x+lean,tip-16),0.5,(125,116,72,255))
    return img


def grass() -> np.ndarray:
    img = _img(96,64)
    rng = np.random.default_rng(1041)
    for i in range(27):
        x = float(rng.uniform(22,75))
        lean = float(rng.uniform(-29,26))
        tip = float(rng.uniform(5,45))
        c = ((64,99,46,255),(87,119,55,255),(117,129,66,255))[i%3]
        _tri(img,x,62,x+lean,tip,x+float(rng.uniform(1.5,3.5)),62,c)
        if i%5==0:
            _stroke(img,(x,61),(x+lean,tip+2),0.6,(138,137,83,255))
            _ellipse(img,x+lean,tip+2,1.5,4,(153,140,86,255))
    return img


def flowers() -> np.ndarray:
    img = _img(96,80)
    rng = np.random.default_rng(1097)
    for i in range(14):
        x = float(rng.uniform(14,83))
        y = float(rng.uniform(14,54))
        base = 47+(x-47)*0.55
        _stroke(img,(base,78),(x,y),0.7,(55,95,48,255))
        _ellipse(img,(base+x)*0.5-3,(78+y)*0.5,5,2,(74,116,53,255))
        _ellipse(img,(base+x)*0.5+4,(78+y)*0.5+8,5,2,(63,103,45,255))
        petal = ((201,183,104,255),(213,204,159,255),(151,151,174,255))[i%3]
        for a in np.linspace(0,np.pi*2,6,endpoint=False):
            _ellipse(img,x+np.cos(a)*2.5,y+np.sin(a)*2.5,2.2,2.1,petal)
        _ellipse(img,x,y,1.6,1.6,(148,110,46,255))
    return img


def shrub() -> np.ndarray:
    img = _img(112,96)
    rng = np.random.default_rng(1129)
    for dx in (-22,-9,9,24):
        _stroke(img,(56,94),(56+dx,35),1.3,(89,75,48,255))
    for _ in range(105):
        a = float(rng.uniform(0,np.pi*2));r = float(np.sqrt(rng.random()))
        x,y = 54+np.cos(a)*r*44,49+np.sin(a)*r*33
        green = int(rng.uniform(73,113))
        shade = 0.83+(70-y)/120
        c = (int(58*shade),int(green*shade),int(41*shade),255)
        _ellipse(img,x,y,float(rng.uniform(4,9)),float(rng.uniform(3,7)),c)
    return img


def driftwood() -> np.ndarray:
    img = _img(112,48)
    # Sun-bleached fallen timber with forks, dark split and exposed end grain.
    for a,b,width in (((13,36),(99,26),6),((42,32),(32,9),2),((74,28),(91,10),2.2),((31,35),(14,43),2)):
        _stroke(img,a,b,width,(116,103,76,255))
        _stroke(img,(a[0],a[1]-2),(b[0],b[1]-2),max(0.7,width*0.45),(168,151,111,255))
    _stroke(img,(23,35),(77,28),0.9,(79,72,55,255))
    _ellipse(img,98,26,4,5,(178,158,113,255))
    _ellipse(img,98,26,2,3,(109,92,66,255))
    _ellipse(img,57,29,4,2,(83,74,53,255))
    return img


def shore_stone() -> np.ndarray:
    img = _img(96,40)
    for x,y,rx,ry,c in ((26,27,20,10,(108,110,99,255)),(59,25,27,12,(119,119,104,255)),(76,32,14,6,(88,94,86,255))):
        _ellipse(img,x,y,rx,ry,c)
        _ellipse(img,x-rx*0.2,y-ry*0.35,rx*0.7,ry*0.45,(150,149,128,255))
        _stroke(img,(x-rx*0.4,y),(x+rx*0.5,y+2),0.6,(98,101,89,255))
    return img


def palmetto() -> np.ndarray:
    """Dwarf palmetto: a fan of stiff fronds rising from one crown (CPU fallback sprite)."""
    img = _img(96, 64)
    rng = np.random.default_rng(1171)
    for k in range(11):
        a = -np.pi * (0.08 + 0.84 * k / 10)
        length = float(rng.uniform(22, 34))
        tip = (48 + np.cos(a) * length, 60 + np.sin(a) * length)
        _stroke(img, (48, 60), tip, 1.6, (70, 108, 52, 255))
        _ellipse(img, tip[0], tip[1], 5, 2.8, (96, 128, 64, 255))
    return img


def heron() -> np.ndarray:
    img = _img(48,112)
    # Still wader at the water's edge: long legs, folded wing and an S neck.
    for x in (19,26):
        _stroke(img,(x,74),(x-1,108),0.8,(107,100,73,255))
        _stroke(img,(x-1,108),(x+4,109),0.6,(92,89,68,255))
    _ellipse(img,22,65,10,15,(111,128,132,255))
    _ellipse(img,20,66,7,10,(82,105,116,255))
    _stroke(img,(28,61),(34,44),3,(164,173,165,255))
    _stroke(img,(34,44),(25,29),2.4,(180,185,171,255))
    _stroke(img,(25,29),(30,17),2.5,(173,181,168,255))
    _ellipse(img,33,16,6,4,(184,190,175,255))
    _tri(img,37,16,47,19,37,20,(172,143,75,255))
    _stroke(img,(28,14),(20,19),0.8,(49,66,72,255))
    _ellipse(img,35,15,0.9,0.9,(31,39,32,255))
    _tri(img,14,69,13,83,20,77,(84,104,113,255))
    return img


def duck() -> np.ndarray:
    img = _img(80,48)
    _ellipse(img,37,33,27,11,(114,98,72,255))
    _ellipse(img,34,29,19,8,(149,135,102,255))
    _ellipse(img,32,31,14,5,(92,87,73,255))
    _stroke(img,(52,31),(59,19),5,(96,98,73,255))
    _ellipse(img,60,16,8,8,(50,85,60,255))
    _stroke(img,(54,24),(63,27),1.3,(210,203,173,255))
    _tri(img,66,16,78,20,66,22,(184,143,62,255))
    _tri(img,14,31,4,24,9,36,(81,81,65,255))
    _ellipse(img,63,15,1,1,(25,31,26,255))
    _stroke(img,(19,42),(58,42),0.6,(149,162,146,210))
    return img

def spire() -> np.ndarray:
    """A cluster of three crystal shards on a stardust bank."""
    img = _img(40, 112)
    for apex, left, right, base, color, facet in (
            ((20, 2), 10, 30, 108, (104, 84, 176, 255), (156, 132, 222, 255)),
            ((9, 34), 1, 18, 108, (56, 132, 160, 255), (104, 190, 212, 255)),
            ((31, 46), 23, 39, 108, (138, 72, 168, 255), (192, 128, 218, 255))):
        _tri(img, apex[0], apex[1], left, base, right, base, color)
        # The lit facet runs from the tip down the left of each shard.
        _tri(img, apex[0], apex[1], left, base, (left+right)//2, base, facet)
        img[apex[1]+6:base-4, apex[0]:apex[0]+1] = (214, 222, 255, 255)
    return img


def starlily() -> np.ndarray:
    """Floating pads around one star-shaped bloom."""
    img = _img(32, 24)
    _ellipse(img, 10, 17, 9, 5, (40, 120, 120, 255))
    _ellipse(img, 22, 18, 8, 4, (54, 136, 130, 255))
    _ellipse(img, 16, 15, 7, 4, (66, 150, 140, 255))
    for k in range(5):
        a = k * 2 * np.pi / 5 - np.pi / 2
        _tri(img, 16, 10, 16 + np.cos(a) * 7, 10 + np.sin(a) * 6,
             16 + np.cos(a + 0.6) * 3, 10 + np.sin(a + 0.6) * 3, (250, 200, 240, 255))
    _ellipse(img, 16, 10, 2, 2, (255, 245, 210, 255))
    return img


def kelp() -> np.ndarray:
    """Three wavering crystal fronds standing out of the water."""
    img = _img(28, 96)
    for x, phase, color, edge in ((8, 0.0, (70, 160, 190, 255), (180, 240, 250, 255)),
                                  (15, 1.7, (120, 110, 200, 255), (210, 190, 250, 255)),
                                  (21, 3.1, (80, 180, 170, 255), (190, 250, 230, 255))):
        for y in range(6, 94):
            sway = int(round(np.sin(y * 0.11 + phase) * 2.5))
            width = 1 + int(2.2 * np.sin(np.pi * (y - 6) / 88))
            xs = slice(max(0, x + sway - width), min(28, x + sway + width + 1))
            img[y, xs] = color
            img[y, min(27, x + sway + width)] = edge
    return img


def meteor() -> np.ndarray:
    """A dark meteorite boulder with glowing ember seams."""
    img = _img(40, 28)
    # Widest at the waterline (the bottom edge), with a jagged broken crown.
    _ellipse(img, 20, 27, 19, 15, (58, 50, 66, 255))
    _tri(img, 13, 6, 4, 22, 22, 22, (70, 61, 80, 255))
    _tri(img, 27, 9, 18, 22, 36, 22, (48, 42, 56, 255))
    _ellipse(img, 14, 18, 6, 5, (90, 80, 100, 255))
    for (ax, ay), (bx, by) in (((8, 21), (19, 16)), ((19, 16), (30, 22)), ((15, 9), (19, 16))):
        _stroke(img, (ax, ay), (bx, by), 0.9, (255, 150, 80, 255))
    return img


def lightreed() -> np.ndarray:
    """Luminous reeds whose tips hold a little starlight."""
    img = _img(24, 48)
    for x, lean in ((5, 0), (10, 1), (15, -1), (19, 1)):
        for y in range(14, 46):
            xx = x + lean * (y // 16)
            if 0 <= xx < 24:
                img[y, xx] = (80, 200, 190, 255)
        img[9:15, x - 1:x + 2] = (235, 250, 200, 255)
    return img


def nebula_sprites() -> dict[str, np.ndarray]:
    return {"spire": spire(), "starlily": starlily(), "kelp": kelp(),
            "meteor": meteor(), "lightreed": lightreed()}


def bake(buoy_rgb: tuple[int, int, int]) -> dict[str, np.ndarray]:
    r, g, b = [int(c * 255) for c in buoy_rgb]
    return {
        "pine": pine(),
        "oak": oak(),
        "cypress": cypress(),
        "rock": rock(),
        "stump": stump(),
        "knee": knee(),
        "reed": reed(),
        "cattail": cattail(),
        "grass": grass(),
        "flowers": flowers(),
        "shrub": shrub(),
        "driftwood": driftwood(),
        "shore_stone": shore_stone(),
        "palmetto": palmetto(),
        "heron": heron(),
        "duck": duck(),
        "buoy": buoy((r, g, b), False),
        "buoy_flag": buoy((r, g, b), True),
    }



# --- HD painter for the GL atlas -------------------------------------------
# Units: primitives take *design* coordinates (the old sprite's pixel grid,
# y down); the bake maps them onto any layer size, so one design paints
# crisply at every detail tier and non-uniform layer aspects cancel out when
# the quad is drawn at the design's aspect.

F4 = np.float32


def box_blur(img: np.ndarray, rx: int, ry: int | None = None) -> np.ndarray:
    """Mean over a (2r+1)^2 box with zero padding, via integral images (O(n)).

    Zero padding is deliberate: outside the sprite is empty, so coverage near
    the border reads as an edge.
    """
    ry = rx if ry is None else ry
    rx, ry = max(1, int(rx)), max(1, int(ry))
    h, w = img.shape
    c = np.zeros((h + 2 * ry + 1, w), np.float64)
    c[ry + 1:ry + 1 + h] = img
    np.cumsum(c, axis=0, out=c)
    v = c[2 * ry + 1:] - c[:h]
    d = np.zeros((h, w + 2 * rx + 1), np.float64)
    d[:, rx + 1:rx + 1 + w] = v
    np.cumsum(d, axis=1, out=d)
    return ((d[:, 2 * rx + 1:] - d[:, :w]) / ((2 * rx + 1) * (2 * ry + 1))).astype(F4)


# Grain kinds the paint shader knows (index = id in `flora_paint.frag`).
GRAINS = ("leaf", "needle", "fine", "bark", "stone")
# Primitive type ids (must match `flora_paint.frag`).
BLOB, LIMB, DRAPE, BLADE, FACET = range(5)
# Floats per recorded primitive: 8 vec4s, laid out as `flora_paint.vert` reads them.
ROW = 32


class Painter:
    """Records a sprite as rounded primitives for the GPU atlas bake.

    A painter is a resolution-independent recipe: each call appends one
    primitive (a leaf clump, limb, curtain, blade or facet) in design units,
    and `florafx.PaintBaker` rasterises the list at the atlas layer size.
    Every primitive is a rounded volume with a height, so the bake's depth
    test keeps the surface that stands highest at each texel no matter the
    call order, and that texel keeps its normal, translucency and wood/leaf
    flag for `foliage.frag` to light.

    Args:
        base_w, base_h: Design size (the coordinate space of every call).
        seed: Seeds `self.rng` (shapes) and the grain offset (texture).
        grain: Default grain kind for clumps (one of `GRAINS`).

    Attributes:
        rows: Recorded primitives, `ROW` floats each.
        options: Finishing options passed to `finish`.
    """

    def __init__(self, base_w, base_h, seed, grain="leaf"):
        self.base_w, self.base_h = float(base_w), float(base_h)
        self.rng = np.random.default_rng(seed)
        # The grain offset has its own generator so shapes do not depend on it.
        self.grain_seed = tuple(float(v) for v in np.random.default_rng(seed + 7919).uniform(0, 512, 2))
        self.grain = grain
        self.rows: list[tuple] = []
        self.options: dict = {}

    def _add(self, box, kind, grain, z, leafy, rgb, glow, p0, p1=(0, 0, 0, 0), p2=(0, 0, 0, 0),
             mat=(0, 0, 0, 0), tip=None):
        r, g, b = (float(c) / 255.0 for c in rgb)
        tr, tg, tb = (r, g, b) if tip is None else (float(c) / 255.0 for c in tip)
        self.rows.append((*box, float(kind), float(GRAINS.index(grain)), float(z), float(leafy),
                          r, g, b, float(glow), *p0, *p1, *p2, *mat, tr, tg, tb, 0.0))

    def blob(self, cx, cy, rx, ry, rgb, *, z=0.0, rough=0.3, leafy=1.0, dome=1.0,
             speck=0.12, bump=0.55, grain=None, glow=0.0):
        """A leaf clump (or stone): an ellipsoid with a grain-ragged rim.

        Args:
            cx, cy, rx, ry: Centre and radii in design units.
            rgb: Base colour, 0-255.
            z: Height of the clump's centre toward the viewer (design units);
                bigger is in front.
            rough: Rim raggedness as a fraction of the radius.
            leafy: 1 for foliage (translucent), 0 for wood or stone.
            dome: Height of the bulge as a fraction of the radius.
            speck: Brightness variation from the grain.
            bump: Grain strength in the normal.
            grain: Grain kind, defaults to the painter's.
            glow: Emission mask value (Nebula flora only).
        """
        pad = 1.0 + abs(rough)
        self._add((cx - rx * pad, cy - ry * pad, cx + rx * pad, cy + ry * pad), BLOB, grain or self.grain,
                  z, leafy, rgb, glow, (cx, cy, rx, ry), mat=(rough, dome, speck, bump))

    def limb(self, x0, y0, x1, y1, r0, r1, rgb, *, z=0.0, leafy=0.0, bark=0.22, glow=0.0,
             grain="bark"):
        """A tapered round limb from (x0, y0) radius r0 to (x1, y1) radius r1 (design units)."""
        rm = max(r0, r1) + 0.6
        self._add((min(x0, x1) - rm, min(y0, y1) - rm, max(x0, x1) + rm, max(y0, y1) + rm), LIMB, grain,
                  z, leafy, rgb, glow, (x0, y0, x1, y1), (r0, r1, 0, 0), mat=(0, 0, bark, 0))

    def drape(self, x0, x1, ytop, length, rgb, *, z=0.0, density=0.45, period=2.2,
              leafy=1.0, glow=0.0, sway=0.0):
        """Hanging strands (Spanish moss, willow curtains) below a line.

        Strands are a stripe pattern across x whose lengths vary by column;
        `density` is the strand width fraction, `period` the spacing and
        `sway` how far tips wander sideways (all design units).
        """
        self._add((x0, ytop, x1, ytop + length * 1.15), DRAPE, "fine", z, leafy, rgb, glow,
                  (x0, x1, ytop, length), (density, period, sway, 0))

    def blade(self, x0, y0, x1, y1, width, rgb, *, bend=0.0, z=0.0, leafy=1.0, glow=0.0,
              tip_rgb=None):
        """A tapered grass/reed blade from base (x0, y0) up to tip (x1, y1).

        `bend` pushes the tip sideways (design units) along a quadratic, so the
        blade stands at its base and arches toward the tip.
        """
        if y1 >= y0:
            return
        xs = (x0, x1, x1 + bend)
        self._add((min(xs) - width - 1, y1, max(xs) + width + 1, y0), BLADE, "fine", z, leafy, rgb, glow,
                  (x0, y0, x1, y1), (width, bend, 0, 0), tip=tip_rgb)

    def facet(self, ax, ay, bx, by, cx, cy, rgb, normal, *, z=0.0, glow=0.0, leafy=0.0):
        """A flat triangle with one normal (x right, y up, z toward the viewer): crystal faces."""
        n = np.asarray(normal, np.float64)
        n = n / np.linalg.norm(n)
        self._add((min(ax, bx, cx), min(ay, by, cy), max(ax, bx, cx), max(ay, by, cy)), FACET, "fine",
                  z, leafy, rgb, glow, (ax, ay, bx, by), (cx, cy, float(n[0]), float(n[1])),
                  (float(n[2]), 0, 0, 0))

    def finish(self, *, core=0.5, cavity=0.45, contact=0.0, thin_floor=0.25, edge_glow=0.0):
        """Store the finishing options and return the recipe.

        Args:
            core: How much the dense middle of a mass darkens (canopy cores).
            cavity: How much gaps between clumps darken.
            contact: Darkening of the bottom rows (trunk base meets ground).
            thin_floor: Translucency of the densest foliage; edges reach 1.
            edge_glow: For emissive sprites, extra glow near silhouettes.

        Returns:
            self, ready for `florafx.PaintBaker.bake`.
        """
        self.options = dict(core=core, cavity=cavity, contact=contact, thin_floor=thin_floor,
                            edge_glow=edge_glow)
        return self

    def array(self) -> np.ndarray:
        """The recorded primitives as a (n, ROW) float32 array."""
        return np.asarray(self.rows, F4).reshape(-1, ROW)

    def tint(self, gain) -> "Painter":
        """Multiply the leafy primitives' colours by a lake's palette gain.

        Wood and stone (leafy 0) keep their colour, so a palette changes foliage
        without repainting trunks. Channels clamp to 1 after scaling.

        Args:
            gain: Per-channel (r, g, b) multipliers, from `LAKE_TINT`.

        Returns:
            self, so calls chain with `finish`.
        """
        if not self.rows:
            return self
        rows = np.asarray(self.rows, F4).reshape(-1, ROW)
        leafy = rows[:, 7] > 0.5
        g = np.asarray(gain, F4)
        rows[leafy, 8:11] = np.clip(rows[leafy, 8:11] * g, 0.0, 1.0)
        rows[leafy, 28:31] = np.clip(rows[leafy, 28:31] * g, 0.0, 1.0)
        self.rows = [tuple(float(v) for v in row) for row in rows]
        return self


def soft_fields(cov: np.ndarray, z: np.ndarray, gx: float, gy: float, *, core: float,
                cavity: float) -> np.ndarray:
    """Canopy AO, openness and edge on a grid of about one texel per design unit.

    These vary over several design units, so they are computed small and
    filtered up by the bake's finishing shader.

    Args:
        cov: (h, w) fraction of each block any primitive covers, top row first.
        z: (h, w) block mean of the winning height times coverage.
        gx, gy: Grid texels per design unit (about 1).
        core, cavity: See `Painter.finish`.

    Returns:
        (h, w, 3) float32: ambient occlusion, openness (how much sky shows
        around the texel), edge (nearness to the silhouette); top row first.
    """
    near = box_blur(cov, int(3 * gx), int(3 * gy))
    far = box_blur(box_blur(cov, int(12 * gx), int(12 * gy)), int(10 * gx), int(10 * gy))
    zb = box_blur(z, int(5 * gx), int(5 * gy)) / np.maximum(box_blur(cov, int(5 * gx), int(5 * gy)), 1e-3)
    zl = z / np.maximum(cov, 1e-3)
    cav = np.clip((zl - zb) / 6.0, -1.0, 0.4)
    out = np.empty(cov.shape + (3,), F4)
    out[..., 0] = (1.0 - core * np.clip((far - 0.45) * 1.8, 0.0, 1.0)) * (1.0 + cavity * np.minimum(cav, 0.0))
    edge = np.clip((1.0 - near) * 2.2, 0.0, 1.0)
    out[..., 1] = np.maximum(edge, np.clip(1.0 - far * 1.1, 0.0, 1.0))
    out[..., 2] = edge
    return out


def upscale(src: np.ndarray, width: int, height: int) -> np.ndarray:
    """Nearest-neighbour resize: crisp texels, no blur (atlas layers share one size)."""
    ys = np.minimum(np.arange(height) * src.shape[0] // height, src.shape[0] - 1)
    xs = np.minimum(np.arange(width) * src.shape[1] // width, src.shape[1] - 1)
    return src[ys[:, None], xs[None, :]]


def auto_light(rgba: np.ndarray, *, lift: float = 0.55, sx: float = 1.0, sy: float = 1.0) -> np.ndarray:
    """A pillow normal and open AO for a sprite painted without light fields.

    Used for buoys, birds and cat impostors: their rims round off gently and
    the face tips toward the sky (`lift`) so midday reads like today's flat
    look while low sun still models them.

    Returns:
        (H, W, 4) float32 light layer (normal x, normal y, 0, AO).
    """
    a = rgba[..., 3].astype(F4) / 255.0
    soft = box_blur(box_blur(a, max(1, int(2 * sx)), max(1, int(2 * sy))), max(1, int(sx)), max(1, int(sy)))
    gy, gx = np.gradient(soft)
    nx, ny = -gx * 6.0 * sx, gy * 6.0 * sy + lift
    nz = np.ones_like(nx)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    light = np.zeros(rgba.shape[:2] + (4,), F4)
    light[..., 0] = nx / norm
    light[..., 1] = ny / norm
    light[..., 3] = 0.82 + 0.18 * np.clip(soft * 1.4, 0, 1)
    return light



# --- HD shore and lagoon sprites -------------------------------------------
# Each painter draws in its old sprite's pixel grid (so the quad aspects in
# PROP_ASPECTS still hold) at whatever resolution the Painter was given.

def _tone(rgb, k):
    return tuple(float(c) * k for c in rgb)


def _hd_reed(p, rng, v):
    """Reed stems in two layers: cool dark ones behind, sunlit ones in front, some with plumes."""
    for layer, (z, rgb) in enumerate(((0.0, (54, 82, 44)), (6.0, (84, 112, 56)))):
        for _ in range(5 + layer * 2):
            x = float(rng.uniform(4, 20))
            tip = float(rng.uniform(4, 18))
            lean = float(rng.uniform(-4, 4))
            p.blade(x, 47.5, x + lean, tip, float(rng.uniform(0.55, 0.85)), _tone(rgb, float(rng.uniform(0.85, 1.12))),
                    bend=float(rng.uniform(-2, 2)), z=z + float(rng.uniform(0, 2)), tip_rgb=(150, 140, 86))
            if rng.random() < 0.45:
                p.blob(x + lean, tip + 1.5, 1.4, 3.6, (122, 92, 58), z=z + 3, rough=0.4, grain="fine")


def _hd_cattail(p, rng, v):
    """A dense cattail stand: three depth layers of arching blades and brown heads."""
    layers = ((0.0, (46, 72, 42), 14), (5.0, (66, 98, 48), 12), (10.0, (98, 126, 60), 10))
    for z, rgb, count in layers:
        for _ in range(count):
            x = float(rng.uniform(10, 54))
            tip = float(rng.uniform(14, 62))
            lean = float(rng.uniform(-18, 18))
            p.blade(x, 95.5, x + lean * 0.4, tip, float(rng.uniform(1.3, 2.3)),
                    _tone(rgb, float(rng.uniform(0.85, 1.12))), bend=lean * 0.6,
                    z=z + float(rng.uniform(0, 3)), tip_rgb=_tone(rgb, 1.25))
    for _ in range(int(rng.integers(4, 8))):
        x = float(rng.uniform(16, 48))
        tip = float(rng.uniform(10, 34))
        lean = float(rng.uniform(-4, 4))
        p.limb(x, 95, x + lean, tip, 0.8, 0.6, (88, 106, 56), z=12.0, leafy=1.0, grain="fine")
        p.limb(x + lean, tip + 13, x + lean, tip + 2, 2.4, 2.2, (96, 64, 38), z=14.0, bark=0.12, grain="fine")
        p.limb(x + lean, tip + 2, x + lean, tip - 5, 0.5, 0.3, (140, 128, 82), z=14.0, grain="fine")


def _hd_grass(p, rng, v):
    """Shore grass tussock: layered blades, paler sun-cured tips and a few seed heads."""
    base = ((60, 94, 46), (86, 116, 54), (118, 128, 66))[v % 3]
    for z, k, count in ((0.0, 0.72, 16), (4.0, 0.9, 16), (8.0, 1.08, 14)):
        for _ in range(count):
            x = float(rng.uniform(18, 78))
            tip = float(rng.uniform(6, 44))
            lean = float(rng.uniform(-24, 24))
            p.blade(x, 63.5, x + lean * 0.35, tip, float(rng.uniform(1.0, 1.9)), _tone(base, k * float(rng.uniform(0.9, 1.1))),
                    bend=lean * 0.65, z=z + float(rng.uniform(0, 2)), tip_rgb=_tone((164, 156, 96), k))
    for _ in range(4):
        x = float(rng.uniform(30, 66))
        tip = float(rng.uniform(4, 16))
        p.limb(x, 62, x + float(rng.uniform(-6, 6)), tip + 4, 0.45, 0.3, (138, 134, 84), z=12.0, leafy=1.0, grain="fine")
        p.blob(x, tip + 3, 1.4, 3.8, (164, 148, 96), z=13.0, rough=0.5, grain="fine")


def _hd_flowers(p, rng, v):
    """Wildflowers: low leaves and stems under small rayed heads (yellow, white, lilac by variant)."""
    petals, centre = (((226, 190, 72), (150, 96, 40)), ((236, 232, 214), (214, 170, 60)),
                      ((180, 152, 210), (236, 214, 120)))[v % 3]
    for _ in range(18):
        x = float(rng.uniform(16, 80))
        p.blade(x, 79.5, x + float(rng.uniform(-10, 10)), float(rng.uniform(44, 66)), float(rng.uniform(1.2, 2.0)),
                _tone((62, 100, 48), float(rng.uniform(0.75, 1.1))), bend=float(rng.uniform(-8, 8)),
                z=float(rng.uniform(0, 4)))
    for _ in range(int(rng.integers(10, 16))):
        x, y = float(rng.uniform(16, 80)), float(rng.uniform(14, 52))
        base = 48 + (x - 48) * 0.5
        p.limb(base, 79, x, y, 0.6, 0.45, (60, 98, 48), z=6.0, leafy=1.0, grain="fine")
        z = 10.0 + float(rng.uniform(0, 4))
        size = float(rng.uniform(2.2, 3.4))
        for a in np.linspace(0, np.pi * 2, 7, endpoint=False) + float(rng.uniform(0, 1)):
            p.blob(x + np.cos(a) * size, y + np.sin(a) * size * 0.75, size * 0.7, size * 0.45,
                   _tone(petals, float(rng.uniform(0.9, 1.08))), z=z, rough=0.15, grain="fine", dome=0.5)
        p.blob(x, y, size * 0.45, size * 0.4, centre, z=z + 1.5, rough=0.2, grain="fine")


def _hd_shrub(p, rng, v):
    """A low shrub: a few stems under many small, lit-topped leaf clumps."""
    light = _tone((112, 136, 62), float(rng.uniform(0.92, 1.08)))
    dark = _tone((42, 70, 36), float(rng.uniform(0.92, 1.08)))
    for dx in (-24, -10, 8, 22):
        p.limb(56, 94, 56 + dx + float(rng.uniform(-4, 4)), 40, 1.6, 0.6, (84, 70, 50), z=8.0)
    for _ in range(46):
        a = float(rng.uniform(0, np.pi * 2))
        r = float(np.sqrt(rng.random()))
        x, y = 56 + np.cos(a) * r * 42, 50 + np.sin(a) * r * 30
        up = float(np.clip(0.55 - np.sin(a) * r * 0.6, 0, 1))
        rgb = tuple(d + (l - d) * up for d, l in zip(dark, light))
        s = float(rng.uniform(6, 11))
        p.blob(x, y, s, s * 0.8, rgb, z=10 + float(np.sqrt(max(0.0, 1 - r * r))) * 20, rough=0.35)


def _hd_palmetto(p, rng, v):
    """Dwarf palmetto: a fan of stiff, arching fronds rising from one crown on the bank."""
    deep, lit = (36, 74, 40), (98, 130, 66)
    base_x, base_y = 48.0, 60.0
    count = int(rng.integers(9, 13))
    for k in range(count):
        a = -np.pi * (0.08 + 0.84 * (k + float(rng.uniform(0, 0.8))) / count)
        length = float(rng.uniform(24, 34))
        tip_x = base_x + float(np.cos(a)) * length
        tip_y = base_y + float(np.sin(a)) * length
        p.blade(base_x, base_y, tip_x, tip_y, float(rng.uniform(1.5, 2.1)),
                _tone(deep, float(rng.uniform(0.9, 1.1))), bend=float(rng.uniform(-4, 4)),
                z=float(rng.uniform(0, 4)), tip_rgb=_tone(lit, float(rng.uniform(0.9, 1.1))))
        # Each frond ends in a pleated fan of leaf.
        p.blob(tip_x, tip_y + 1.0, 5.6, 2.6, _tone(lit, float(rng.uniform(0.9, 1.1))),
               z=8.0 + float(rng.uniform(0, 4)), rough=0.35, dome=0.6)


def _hd_knee(p, rng, v):
    """A cypress knee: a rounded woody cone, dark and wet at the waterline."""
    bark = (128, 98, 68)
    p.limb(9, 31.5, 9 + float(rng.uniform(-1, 1)), 7, 5.6, 2.4, bark, z=4.0, bark=0.3)
    p.blob(9, 7, 3.4, 3.6, _tone(bark, 1.12), z=6.0, leafy=0.0, rough=0.12, grain="bark", dome=0.8)
    p.limb(9, 31.5, 9, 26, 6.2, 5.6, _tone(bark, 0.55), z=5.0)


def _hd_stump(p, rng, v):
    """An old stump: bark sides and a pale cut top with rings."""
    bark = (100, 74, 50)
    p.limb(14, 22, 14, 11, 10.5, 9.8, bark, z=2.0, bark=0.3)
    p.blob(14, 10, 10.5, 4.6, (156, 120, 80), z=14.0, leafy=0.0, rough=0.08, grain="bark", dome=0.15)
    p.blob(14, 10, 5.5, 2.3, (122, 90, 58), z=15.0, leafy=0.0, rough=0.1, grain="bark", dome=0.1)


def _hd_rock(p, rng, v):
    """A few weathered boulders, lit from above by their normals, lichen flecks."""
    for i in range(int(rng.integers(2, 4))):
        cx, cy = 24 + float(rng.uniform(-10, 10)), 20 + float(rng.uniform(-2, 4))
        rx, ry = float(rng.uniform(9, 19)), float(rng.uniform(7, 11))
        grey = _tone((106, 104, 96), float(rng.uniform(0.8, 1.1)))
        p.blob(cx, cy, rx, ry, grey, z=i * 2.0, leafy=0.0, rough=0.12, grain="stone", dome=0.7, speck=0.18,
               bump=0.9)


def _hd_shore_stone(p, rng, v):
    """Rounded shore cobbles in a loose row."""
    for i in range(int(rng.integers(3, 6))):
        cx, cy = float(rng.uniform(14, 82)), float(rng.uniform(26, 33))
        rx, ry = float(rng.uniform(8, 20)), float(rng.uniform(5, 10))
        grey = _tone((120, 118, 104), float(rng.uniform(0.78, 1.12)))
        p.blob(cx, cy, rx, ry, grey, z=float(rng.uniform(0, 4)), leafy=0.0, rough=0.08, grain="stone",
               dome=0.6, speck=0.14)


def _hd_driftwood(p, rng, v):
    """Sun-bleached fallen timber with forks and a split."""
    pale, dark = (150, 136, 106), (92, 82, 62)
    p.limb(12, 37, 100, 26, 5.5, 4.2, pale, z=6.0, bark=0.3)
    for a, b, w in (((42, 32), (32, 9), 2.0), ((74, 28), (91, 10), 2.2), ((31, 35), (14, 43), 1.8)):
        p.limb(*a, *b, w, w * 0.5, pale, z=4.0, bark=0.3)
    p.limb(23, 35, 77, 28, 0.8, 0.6, dark, z=20.0)
    p.blob(100, 26, 3.6, 4.4, (182, 162, 118), z=12.0, leafy=0.0, rough=0.1, grain="bark", dome=0.3)


def _shard(p, rng, cx, base, top, half, rgb, z):
    """A two-faced crystal shard with a glowing core ridge."""
    lit, dim = _tone(rgb, 1.35), _tone(rgb, 0.8)
    p.facet(cx, top, cx - half, base, cx, base, lit, (-0.65, 0.25, 0.72), z=z, glow=0.35)
    p.facet(cx, top, cx, base, cx + half, base, dim, (0.6, 0.3, 0.74), z=z, glow=0.25)
    p.limb(cx, base - 2, cx, top + 4, half * 0.12 + 0.3, 0.2, (226, 230, 255), z=z + 2.0, glow=1.0, grain="fine")


def _hd_spire(p, rng, v):
    """Lagoon crystal spires: a cluster of faceted shards that glow from within."""
    palette = ((104, 84, 176), (56, 132, 160), (138, 72, 168), (90, 150, 190))
    for i in range(int(rng.integers(3, 6))):
        cx = 20 + float(rng.uniform(-13, 13))
        top = float(rng.uniform(2, 56)) if i else float(rng.uniform(1, 10))
        half = float(rng.uniform(4, 9)) * (1.4 if i == 0 else 1.0)
        rgb = palette[int(rng.integers(0, len(palette)))]
        _shard(p, rng, cx, 111.5, top, half, rgb, z=float(rng.uniform(0, 10)) + (5 if i == 0 else 0))


def _hd_starlily(p, rng, v):
    """Floating pads around one luminous star bloom."""
    for cx, cy, rx, ry, rgb in ((10, 17, 9, 5, (40, 120, 120)), (22, 18, 8, 4, (54, 136, 130)),
                                (16, 15, 7, 4, (66, 150, 140))):
        p.blob(cx, cy, rx, ry, rgb, z=0.0, rough=0.08, dome=0.3, grain="fine")
    for k in range(5):
        a = k * 2 * np.pi / 5 - np.pi / 2 + float(rng.uniform(-0.1, 0.1))
        p.facet(16, 10, 16 + np.cos(a) * 7, 10 + np.sin(a) * 6, 16 + np.cos(a + 0.6) * 3, 10 + np.sin(a + 0.6) * 3,
                (250, 200, 240), (np.cos(a) * 0.4, -np.sin(a) * 0.4, 0.8), z=6.0, glow=0.75)
    p.blob(16, 10, 2.0, 2.0, (255, 245, 210), z=8.0, rough=0.05, glow=1.0, leafy=0.0, grain="fine")


def _hd_kelp(p, rng, v):
    """Crystal kelp: three wavering fronds with bright glassy edges."""
    for x, phase, rgb in ((8, 0.0, (70, 160, 190)), (15, 1.7, (120, 110, 200)), (21, 3.1, (80, 180, 170))):
        x += float(rng.uniform(-1.5, 1.5))
        pts = [(x + np.sin(y * 0.11 + phase) * 2.5, y) for y in np.linspace(94, 6, 12)]
        for i in range(len(pts) - 1):
            t = i / (len(pts) - 1)
            w = 0.6 + 2.0 * np.sin(np.pi * (0.1 + 0.85 * t))
            p.limb(*pts[i], *pts[i + 1], w, w * 0.95, rgb, z=t, glow=0.45, grain="fine", bark=0.1)


def _hd_meteor(p, rng, v):
    """A dark meteorite boulder split by glowing ember seams."""
    p.blob(20, 20, 18, 11, (58, 50, 66), z=0.0, leafy=0.0, rough=0.14, grain="stone", dome=0.6)
    p.blob(14, 15, 8, 7, (82, 72, 94), z=3.0, leafy=0.0, rough=0.2, grain="stone", dome=0.6)
    p.blob(28, 17, 7, 6, (48, 42, 56), z=2.0, leafy=0.0, rough=0.2, grain="stone", dome=0.6)
    for a, b in (((8, 21), (19, 16)), ((19, 16), (30, 22)), ((15, 9), (19, 16))):
        p.limb(*a, *b, 0.8, 0.6, (255, 150, 80), z=30.0, glow=1.0, grain="fine")


def _hd_lightreed(p, rng, v):
    """Luminous reeds whose tips hold a little starlight."""
    for _ in range(6):
        x = float(rng.uniform(4, 20))
        tip = float(rng.uniform(8, 16))
        lean = float(rng.uniform(-3, 3))
        p.blade(x, 47.5, x + lean, tip, 0.7, (80, 200, 190), bend=float(rng.uniform(-1.5, 1.5)), z=float(rng.uniform(0, 4)),
                glow=0.3)
        p.blob(x + lean, tip - 1, 1.5, 3.2, (235, 250, 200), z=8.0, glow=1.0, rough=0.2, grain="fine")


# kind: (design w, design h, painter, finish options)
HD_SPRITES = {
    "reed": (24, 48, _hd_reed, {}),
    "cattail": (64, 96, _hd_cattail, {}),
    "grass": (96, 64, _hd_grass, {}),
    "palmetto": (96, 64, _hd_palmetto, {}),
    "flowers": (96, 80, _hd_flowers, {}),
    "shrub": (112, 96, _hd_shrub, {"contact": 0.4}),
    "knee": (18, 32, _hd_knee, {}),
    "stump": (28, 24, _hd_stump, {}),
    "rock": (48, 32, _hd_rock, {"core": 0.2}),
    "shore_stone": (96, 40, _hd_shore_stone, {"core": 0.2}),
    "driftwood": (112, 48, _hd_driftwood, {}),
    "spire": (40, 112, _hd_spire, {"core": 0.0, "edge_glow": 0.4}),
    "starlily": (32, 24, _hd_starlily, {"core": 0.0}),
    "kelp": (28, 96, _hd_kelp, {"core": 0.0, "edge_glow": 0.3}),
    "meteor": (40, 28, _hd_meteor, {"core": 0.1}),
    "lightreed": (24, 48, _hd_lightreed, {"core": 0.0}),
}


def sprite_hd(kind: str, variant: int, *, lake: str = "briar") -> Painter:
    """The recipe for one HD shore/lagoon sprite.

    Args:
        kind: A key of `HD_SPRITES`.
        variant: 0-based variant (seeds shape and, for flowers and grass, colour).
        lake: Lake id. Seeds this lake's arrangement, so no two lakes share a sprite,
            and applies its palette to the leafy primitives (`LAKE_TINT`).

    Returns:
        A finished `Painter` for `florafx.PaintBaker.bake`.
    """
    base_w, base_h, paint, finish = HD_SPRITES[kind]
    seed = zlib.crc32(f"{lake}:{kind}:{variant}".encode())
    p = Painter(base_w, base_h, seed, grain="stone" if kind in ("rock", "shore_stone", "meteor") else "leaf")
    paint(p, p.rng, variant)
    p.tint(LAKE_TINT[lake])
    return p.finish(**finish)
