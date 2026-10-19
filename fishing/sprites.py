"""Procedural shore sprites. Baked once, tinted when drawn.

Shapes are big on purpose. A tree on the far bank is only a few dozen
pixels tall, so the silhouette has to read before the texture does.
"""

from __future__ import annotations

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
    "driftwood": 7/3, "shore_stone": 2.4, "heron": 3/7, "duck": 5/3,
}
WATERLINE_KINDS = frozenset(("reed", "knee", "cattail", "heron", "duck"))


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
        "heron": heron(),
        "duck": duck(),
        "buoy": buoy((r, g, b), False),
        "buoy_flag": buoy((r, g, b), True),
    }
