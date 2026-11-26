"""Deterministic tree sprites. No downloaded art or unbounded textures.

`tree(kind, variant)` and `atlas()` are the small 160x256 RGBA sprites the CPU
renderer and tests use; their output is pinned and must not change.
`tree_hd()` records the GL atlas's trees as resolution-free primitive lists
with real structure (trunk, branching, depth-ordered leaf clumps, species
silhouettes); `florafx.PaintBaker` rasterises them on the GPU with the
normal/translucency/AO fields `foliage.frag` lights them with.
Variants differ in silhouette, not only colour, so tree lines stop repeating.
Each lake's species mix (`TREE_MIX`) and palette (`sprites.LAKE_TINT`) keep lakes apart.
"""

from __future__ import annotations

import math
import zlib

import numpy as np

from .sprites import LAKE_TINT, Painter, bake, tint_foliage

W, H = 160, 256
KINDS = ("pine", "oak", "cypress", "larch", "larchgold", "spruce", "hemlock", "whitebark", "deadpine")

# Appended, never reordered: the CPU seeds index _CPU_ORDER, so each existing kind keeps its
# pinned sprite.
_NEW_TREES = ("birch", "cottonwood", "willow")
_CPU_ORDER = KINDS + _NEW_TREES


def _leaf(img, cx, cy, rx, ry, rgb, rng, canopy):
    x0, x1 = max(0, int(cx-rx-2)), min(W, int(cx+rx+3))
    y0, y1 = max(0, int(cy-ry-2)), min(H, int(cy+ry+3))
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    dx, dy = (xx-cx)/rx, (yy-cy)/ry
    r = np.sqrt(dx*dx+dy*dy)
    edge = 0.94 + np.sin(np.arctan2(dy,dx)*11.0+cx)*0.035
    mask = r < edge
    light = np.clip(0.86-dx*0.12-dy*0.17,0.6,1.2)
    speckle = rng.uniform(0.90,1.10, r.shape)
    patch = img[y0:y1,x0:x1]
    color = np.clip(np.array(rgb)[None,None,:]*light[...,None]*speckle[...,None],0,255).astype(np.uint8)
    patch[mask,:3] = color[mask]
    patch[mask,3] = 255
    canopy[y0:y1,x0:x1] |= mask


def tree(kind, variant, *, lake=None):
    """One 160x256 CPU sprite of a tree kind, as RGBA.

    Args:
        kind: A kind in `KINDS`, `_NEW_TREES`, or "larchgold".
        variant: 0-based variant; silhouettes differ per variant.
        lake: When given, the canopy takes that lake's palette (`LAKE_TINT`) as `tree_hd`
            does; None returns the pinned, untinted sprite.

    Returns:
        A uint8 array of shape (256, 160, 4).
    """
    rng = np.random.default_rng(180+variant*17+_CPU_ORDER.index("larch" if kind == "larchgold" else kind)*83)
    img = np.zeros((H,W,4),np.uint8)
    canopy = np.zeros((H,W),bool)
    yy, xx = np.mgrid[0:H,0:W]
    trunk_w = 3.5+(yy/H)**6*(9 if kind=="cypress" else 4)
    trunk = (abs(xx-W/2)<trunk_w)&(yy>65)&(yy<252)
    bark = 0.7+np.sin(xx*1.8+np.sin(yy*0.06))*0.12+(W/2-xx)*0.025
    img[trunk,:3] = np.clip(np.array([111,92,64])*bark[trunk,None],0,255).astype(np.uint8)
    img[trunk,3] = 255
    if kind=="deadpine":
        for tier in range(6):
            cy = 70+tier*22
            spread = 10+tier*5
            for sign in (-1,1):
                branch = (np.abs(yy-(cy+(xx-80)*sign*.18))<1.4) & (xx>=80-spread) & (xx<=80+spread)
                img[branch] = (100,97,88,255)
    elif kind=="oak":
        # An irregular spreading crown built from many overlapping leaf masses.
        for _ in range(90):
            a = rng.uniform(0,2*np.pi)
            r = np.sqrt(rng.random())
            cx = 80+np.cos(a)*r*53
            cy = 89+np.sin(a)*r*49
            radius = rng.uniform(10,23)
            rgb = np.array([65,91,45])+rng.uniform(-12,14,3)
            _leaf(img,cx,cy,radius,radius*0.83,rgb,rng,canopy)
        # Fine branches under the crown.
        for sign in (-1,1):
            branch = (yy>108)&(yy<174)&(abs(xx-(80+sign*(174-yy)*0.35))<2)
            img[branch] = (92,77,54,255)
            canopy[branch] = False
    elif kind in ("pine", "larch", "larchgold", "spruce", "hemlock", "whitebark"):
        for tier in range(11,0,-1):
            cy = 18+tier*14
            spread = 7+tier*4.8
            for j in range(7):
                cx = 80+rng.uniform(-spread,spread)
                base = {"pine": [48,78,54], "larch": [91,118,57],
                        "larchgold": [195,151,49], "spruce": [48,85,81],
                        "hemlock": [38,67,56], "whitebark": [107,125,105]}[kind]
                rgb = np.array(base)+rng.uniform(-8,10,3)
                _leaf(img,cx,cy+rng.uniform(-6,7),rng.uniform(8,16),rng.uniform(7,12),rgb,rng,canopy)
        _leaf(img,80,17,5,11,base if kind != "pine" else [76,99,61],rng,canopy)
    elif kind == "birch":
        # Paper bark over the shared trunk, then slender, airy leaf clumps.
        img[trunk,:3] = np.clip(np.array([218,212,198])*bark[trunk,None],0,255).astype(np.uint8)
        for tier in range(9,0,-1):
            cy = 22+tier*14
            spread = 8+tier*2.6
            for j in range(9):
                cx = 80+rng.uniform(-spread,spread)
                rgb = np.array([124,156,70])+rng.uniform(-10,10,3)
                _leaf(img,cx,cy+rng.uniform(-6,6),rng.uniform(6,11),rng.uniform(7,11),rgb,rng,canopy)
    elif kind == "cottonwood":
        # Pale furrowed bark under a broad crown of large, clumped leaves.
        img[trunk,:3] = np.clip(np.array([156,146,124])*bark[trunk,None],0,255).astype(np.uint8)
        for tier in range(9,0,-1):
            cy = 24+tier*15
            spread = 12+min(tier,6)*4
            for j in range(8):
                cx = 80+rng.uniform(-spread,spread)
                rgb = np.array([104,138,58])+rng.uniform(-10,10,3)
                _leaf(img,cx,cy+rng.uniform(-8,8),rng.uniform(10,17),rng.uniform(9,14),rgb,rng,canopy)
    elif kind == "willow":
        # A rounded crown with long curtains of hanging strands.
        for tier in range(7,0,-1):
            cy = 40+tier*12
            spread = 14+tier*4
            for j in range(7):
                cx = 80+rng.uniform(-spread,spread)
                rgb = np.array([112,146,70])+rng.uniform(-9,9,3)
                _leaf(img,cx,cy+rng.uniform(-6,6),rng.uniform(10,15),rng.uniform(7,11),rgb,rng,canopy)
        for _ in range(26):
            x = int(rng.uniform(40,120))
            y = int(rng.uniform(100,140))
            length = int(rng.uniform(30,80))
            img[y:y+length,x:x+1] = (104,130,66,235)
            canopy[y:y+length,x:x+1] = True
    else:
        for tier in range(10,0,-1):
            cy = 20+tier*15
            spread = 10+min(tier,7)*3.9
            for j in range(7):
                cx = 80+rng.uniform(-spread,spread)
                rgb = np.array([64,91,52])+rng.uniform(-10,10,3)
                _leaf(img,cx,cy+rng.uniform(-9,9),rng.uniform(9,18),rng.uniform(9,16),rgb,rng,canopy)
        # Fine hanging moss remains a detail, rather than a giant bare trunk.
        for _ in range(22):
            x = int(rng.uniform(52,108))
            y = int(rng.uniform(110,165))
            length = int(rng.uniform(9,29))
            img[y:y+length,x:x+1] = (82,94,69,235)
            canopy[y:y+length,x:x+1] = True
    if lake is not None:
        img = tint_foliage(img, canopy, LAKE_TINT[lake])
    return img


def _bleed_edges(img):
    """Keep linear filtering from mixing opaque leaves with transparent black.

    RGB extends two texels into the empty border; alpha and silhouette stay put.
    The same bounded operation works for every small sprite layer.
    """
    out = img.copy()
    occupied = out[:,:,3]>0
    h,w = occupied.shape
    for _ in range(2):
        old = np.pad(out[:,:,:3],((1,1),(1,1),(0,0)),mode="edge")
        mask = np.pad(occupied,1)
        filled = occupied.copy()
        for dy,dx in ((-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)):
            neighbors = mask[1+dy:1+dy+h,1+dx:1+dx+w]
            take = ~filled & neighbors
            out[:,:,:3][take] = old[1+dy:1+dy+h,1+dx:1+dx+w][take]
            filled |= take
        occupied = filled
    return out


def atlas(buoy_rgb, *, alpine=False, caldera=False, nebula=False):
    names, images = [], []
    kinds = () if nebula else (KINDS[6:] if caldera else (KINDS[:6] if alpine else KINDS[:3]))
    for kind in kinds:
        for variant in range(3):
            names.append(f"{kind}{variant}")
            images.append(tree(kind,variant))
    sprites = bake(buoy_rgb)
    if nebula:
        # The lagoon grows no trees: crystal sprites replace the forest layers.
        from .sprites import nebula_sprites
        sprites.update(nebula_sprites())
    for kind, src in sprites.items():
        if kind in KINDS:
            continue
        names.append(kind)
        # All texture-array layers have one bounded size.
        ys = np.minimum(np.arange(H)*src.shape[0]//H,src.shape[0]-1)
        xs = np.minimum(np.arange(W)*src.shape[1]//W,src.shape[1]-1)
        images.append(src[ys[:,None],xs[None,:]])
    return {name:i for i,name in enumerate(names)}, np.stack([_bleed_edges(img) for img in images])[:,::-1].copy()



# --- HD trees for the GL atlas ----------------------------------------------
# Design space is the old 160x256 sprite grid, y down, trunk base on the bottom
# row and the trunk centred at x = 80 (the quad's anchor).

# Atlas layers follow this order; silhouettes are seeded by name (tree_hd), so reordering only moves layers.
TREE_KINDS = ("pine", "oak", "cypress", "larch", "spruce", "hemlock", "whitebark", "deadpine") + _NEW_TREES
CONIFERS = frozenset(("pine", "cypress", "larch", "larchgold", "spruce", "hemlock", "whitebark"))

# Each lake's tree identity: kind weights per role, where a role names a place the lake
# plants (Briar's cypress shore, Cedar's flooded cove). Placement maps exactly one uniform
# draw per tree through `pick_tree`, so positions and the random stream stay as they were.
TREE_MIX = {
    "briar": {
        "cypress_shore": (("cypress", 0.6), ("birch", 0.2), ("oak", 0.2)),
        "north": (("pine", 0.5), ("oak", 0.25), ("birch", 0.25)),
        "main": (("oak", 0.4), ("birch", 0.3), ("pine", 0.3)),
        "outer": (("oak", 0.3), ("birch", 0.3), ("pine", 0.4)),
    },
    "cedar": {
        "main": (("cottonwood", 0.4), ("pine", 0.3), ("willow", 0.2), ("cypress", 0.1)),
        "grove": (("cottonwood", 0.5), ("pine", 0.25), ("willow", 0.25)),
        "flooded": (("cypress", 0.5), ("cottonwood", 0.25), ("willow", 0.25)),
    },
    "flathead": {"main": (("larch", 0.45), ("spruce", 0.30), ("birch", 0.25))},
    "crater": {"main": (("hemlock", 0.50), ("whitebark", 0.25), ("pine", 0.25))},
}


def pick_tree(lake: str, role: str, u: float) -> str:
    """The tree kind that a uniform draw lands on for one lake's placement role.

    Args:
        lake: A key of `TREE_MIX`.
        role: A role of that lake, such as "main".
        u: Uniform draw in [0, 1), from the caller's random stream or `index_draw`.

    Returns:
        A kind from `TREE_KINDS`. Weights are normalised, so rows need not sum to 1.
    """
    row = TREE_MIX[lake][role]
    total = sum(weight for _, weight in row)
    edge = 0.0
    for kind, weight in row:
        edge += weight / total
        if u < edge:
            return kind
    return row[-1][0]


def index_draw(index: int) -> float:
    """A low-discrepancy draw in [0, 1) for candidate `index` (golden-ratio sequence).

    Index-based placement uses this instead of the random stream, so a lake's mix keeps
    its weights over any run of candidates and changing a weight never moves a tree.

    Args:
        index: Candidate index, 0-based.

    Returns:
        A value in [0, 1).
    """
    return (index * 0.6180339887498949) % 1.0


def _mix(a, b, t):
    return tuple(float(x) * (1 - t) + float(y) * t for x, y in zip(a, b))


def _jit(rng, rgb, amount):
    """Colour jitter that keeps hue families together (one shared factor plus a little per channel)."""
    k = 1.0 + float(rng.uniform(-amount, amount))
    return tuple(max(0.0, c * k + float(rng.uniform(-amount, amount)) * 40) for c in rgb)


def _crown(p, rng, cx, cy, rx, ry, count, size, light, dark, *, z0=20.0, depth=None, flat=1.0,
           lobes=3, rough=0.32, gaps=0.0, grain=None, top_bias=0.0):
    """A broadleaf crown: clumps on an ellipsoid shell, lit tops, dark cores.

    Clumps are biased toward the shell so the silhouette is lumpy and the
    middle shows depth; their height (z) follows the shell so front masses
    overlap back ones. `gaps` drops clumps in a few sectors to let sky and
    branches through. Albedo carries only the light/dark mass tendency; the
    shader does the directional light.
    """
    depth = rx * 0.8 if depth is None else depth
    holes = [(float(rng.uniform(-0.6, 0.6)), float(rng.uniform(-0.5, 0.6))) for _ in range(3)]
    placed = 0
    tries = 0
    while placed < count and tries < count * 4:
        tries += 1
        a = float(rng.uniform(0, math.tau))
        r = math.sqrt(float(rng.uniform(0.0, 1.0))) ** 0.8
        ux, uy = math.cos(a) * r, math.sin(a) * r * flat - top_bias * 0.2
        if gaps and any((ux - hx) ** 2 + (uy - hy) ** 2 < gaps * gaps for hx, hy in holes):
            continue
        placed += 1
        x, y = cx + ux * rx, cy + uy * ry
        shell = math.sqrt(max(0.0, 1.0 - r * r))
        z = z0 + shell * depth + float(rng.uniform(-3, 3))
        up = np.clip(0.5 - uy * 0.6 + float(rng.uniform(-0.25, 0.25)), 0.0, 1.0)
        rgb = _jit(rng, _mix(dark, light, float(up) * (0.5 + 0.5 * r)), 0.06)
        s = size * float(rng.uniform(0.7, 1.25)) * (0.8 + 0.3 * r)
        p.blob(x, y, s, s * float(rng.uniform(0.78, 0.95)), rgb, z=z, rough=rough, grain=grain)
        for _ in range(lobes - 1):
            la = float(rng.uniform(0, math.tau))
            lx, ly = x + math.cos(la) * s * 0.75, y + math.sin(la) * s * 0.6
            ls = s * float(rng.uniform(0.45, 0.7))
            p.blob(lx, ly, ls, ls * 0.85, _jit(rng, rgb, 0.05), z=z + float(rng.uniform(-2, 2)),
                   rough=rough, grain=grain)


def _bough(p, rng, x0, y0, length, side, droop, thick, rgb, *, z, tuft=1.0, grain="needle",
           up=0.0, wood=None, step=0.55, rough=0.35):
    """One conifer branch: a sagging run of needle tufts from the trunk outward.

    Args:
        x0, y0: Where it leaves the trunk.
        length: Reach in design units; `side` is -1 or 1.
        droop: Sag of the tip as a fraction of the length (negative lifts).
        thick: Tuft half-height near the trunk.
        up: Initial upward lift as a fraction of the length (larch, pine).
        wood: Bark colour to draw the bare branch under the tufts, if any.
    """
    n = max(2, int(length / max(3.0, thick * 1.6 * step * 2)) + 1)
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append((x0 + side * length * t, y0 - up * length * t + droop * length * t * t))
    if wood is not None:
        p.limb(*pts[0], *pts[-1], max(0.5, thick * 0.18), 0.35, wood, z=z - 1.0)
    for i in range(1, n + 1):
        t = i / n
        x, y = pts[i]
        h = thick * (1.0 - 0.45 * t) * tuft
        w = h * float(rng.uniform(1.25, 1.7))
        # Tips droop a little below the branch line: that skirt is what
        # makes spruce and hemlock read as conifers at a glance.
        p.blob(x - side * w * 0.2, y + h * 0.25, w, h, _jit(rng, rgb, 0.05),
               z=z + (1 - t) * 3.0 + float(rng.uniform(-1, 1)), rough=rough, grain=grain, dome=0.8)


def _trunk(p, x0, y0, x1, y1, r0, r1, rgb, *, z=12.0, segments=3, wobble=0.0, rng=None):
    """A slightly wandering tapered trunk built from a few limbs."""
    pts = [(x0, y0)]
    for i in range(1, segments + 1):
        t = i / segments
        dx = float(rng.uniform(-wobble, wobble)) if (rng is not None and i < segments) else 0.0
        pts.append((x0 + (x1 - x0) * t + dx, y0 + (y1 - y0) * t))
    for i in range(segments):
        t0, t1 = i / segments, (i + 1) / segments
        p.limb(*pts[i], *pts[i + 1], r0 + (r1 - r0) * t0, r0 + (r1 - r0) * t1, rgb, z=z)
    return pts


def _flare(p, x, y, width, height, rgb, *, z=14.0):
    """Root flare where the trunk meets the ground (wood, not foliage)."""
    p.blob(x, y - height * 0.45, width, height * 0.6, rgb, z=z, rough=0.12, leafy=0.0,
           dome=0.5, speck=0.18, grain="bark")


def _paint_oak(p, rng, v):
    """Briar oak: short trunk forking into limbs under a broad lumpy crown."""
    bark = _jit(rng, (92, 78, 60), 0.05)
    lean = float(rng.uniform(-6, 6))
    cx, cy = 80 + lean, float(rng.uniform(96, 112))
    rx, ry = float(rng.uniform(50, 58)), float(rng.uniform(54, 66))
    fork_y = cy + ry * float(rng.uniform(0.45, 0.65))
    _flare(p, 80, 256, 14, 12, bark)
    _trunk(p, 80, 256, 80 + lean * 0.5, fork_y, 7.5, 5.0, bark, rng=rng, wobble=1.5)
    limbs = int(rng.integers(3, 6))
    for i in range(limbs):
        a = -math.pi / 2 + (i - (limbs - 1) / 2) * float(rng.uniform(0.45, 0.7))
        ex, ey = cx + math.cos(a) * rx * 0.62, cy + math.sin(a) * ry * 0.45
        p.limb(80 + lean * 0.5, fork_y, ex, ey, 4.2, 1.6, bark, z=18.0)
        for _ in range(2):
            b = a + float(rng.uniform(-0.9, 0.9))
            p.limb(ex, ey, ex + math.cos(b) * 20, ey + math.sin(b) * 15, 1.6, 0.6, bark, z=19.0)
    light, dark = _jit(rng, (100, 122, 54), 0.05), _jit(rng, (38, 60, 32), 0.05)
    # Two or three sub-crowns make each oak's outline its own.
    for k in range(int(rng.integers(1, 4))):
        ox, oy = float(rng.uniform(-0.35, 0.35)) * rx, float(rng.uniform(-0.25, 0.2)) * ry
        _crown(p, rng, cx + ox, cy + oy, rx * float(rng.uniform(0.55, 0.75)), ry * float(rng.uniform(0.5, 0.7)),
               12, 14.0, light, dark, z0=14.0 + k * 2, lobes=3)
    _crown(p, rng, cx, cy, rx, ry, 24, 15.0, light, dark, z0=12.0, gaps=0.18, lobes=3)


def _paint_cottonwood(p, rng, v):
    """Cedar cottonwood: pale furrowed trunk forking low into a tall, open, clumped crown."""
    bark = _jit(rng, (128, 122, 108), 0.04)
    _flare(p, 80, 256, 15, 12, bark)
    fork = float(rng.uniform(176, 196))
    _trunk(p, 80, 256, 80, fork, 8.0, 6.5, bark, rng=rng)
    light, dark = _jit(rng, (128, 142, 62), 0.05), _jit(rng, (52, 76, 36), 0.05)
    stems = int(rng.integers(2, 4))
    for i in range(stems):
        a = -math.pi / 2 + (i - (stems - 1) / 2) * float(rng.uniform(0.35, 0.55))
        length = float(rng.uniform(80, 110))
        ex, ey = 80 + math.cos(a) * length, fork + math.sin(a) * length
        p.limb(80, fork, ex, ey, 5.5, 2.2, bark, z=16.0)
        for _ in range(3):
            b = a + float(rng.uniform(-0.9, 0.9))
            t = float(rng.uniform(0.4, 0.9))
            sx, sy = 80 + (ex - 80) * t, fork + (ey - fork) * t
            p.limb(sx, sy, sx + math.cos(b) * 26, sy + math.sin(b) * 22, 2.0, 0.7, bark, z=17.0)
        _crown(p, rng, ex, ey + 6, float(rng.uniform(32, 40)), float(rng.uniform(26, 34)), 12, 12.0,
               light, dark, z0=14.0 + i, gaps=0.3, lobes=3, rough=0.4)


def _paint_willow(p, rng, v):
    """Cedar black willow: leaning trunk, rounded crown, hanging curtains."""
    bark = _jit(rng, (96, 84, 66), 0.05)
    lean = float(rng.uniform(-14, 14))
    _flare(p, 80, 256, 13, 11, bark)
    top = (80 + lean, float(rng.uniform(128, 146)))
    _trunk(p, 80, 256, *top, 8.0, 5.0, bark, rng=rng, wobble=2.5)
    for a in (-2.4, -1.6, -0.8):
        a += float(rng.uniform(-0.25, 0.25))
        p.limb(*top, top[0] + math.cos(a) * 50, top[1] + math.sin(a) * 46, 3.2, 1.0, bark, z=16.0)
    light, dark = _jit(rng, (138, 152, 74), 0.04), _jit(rng, (60, 84, 40), 0.04)
    cx, cy = top[0], top[1] - 42
    _crown(p, rng, cx, cy, 60, 40, 22, 13.0, light, dark, z0=12.0, lobes=2, rough=0.38, grain="fine")
    for i in range(7):
        x0 = cx - 62 + i * 18 + float(rng.uniform(-4, 4))
        p.drape(x0, x0 + float(rng.uniform(16, 24)), cy + float(rng.uniform(-6, 18)),
                float(rng.uniform(55, 95)), _jit(rng, _mix(dark, light, 0.6), 0.05),
                z=30.0 + float(rng.uniform(0, 6)), density=0.62, period=1.9, sway=float(rng.uniform(-2, 2)))


def _paint_birch(p, rng, v):
    """Briar birch: two or three pale, black-marked stems under a slender, airy crown."""
    bark = _jit(rng, (222, 216, 204), 0.03)
    _flare(p, 80, 256, 12, 9, bark)
    stems = int(rng.integers(2, 4))
    for i in range(stems):
        base_x = 80 + (i - (stems - 1) / 2) * 7.0
        top = (base_x + float(rng.uniform(-8, 8)), float(rng.uniform(80, 104)))
        _trunk(p, base_x, 256, *top, 5.4 - i * 0.8, 2.8, bark, rng=rng, wobble=1.5)
        # Black lenticel marks spaced up each stem: the birch's signature.
        for _ in range(int(rng.integers(6, 10))):
            t = float(rng.uniform(0.2, 0.9))
            p.blob(base_x + (top[0] - base_x) * t, 256 + (top[1] - 256) * t, 1.5, 0.55,
                   (44, 40, 38), z=14.0, rough=0.3, leafy=0.0, dome=0.3, speck=0.2, grain="bark")
    light = _jit(rng, (150, 178, 84), 0.05)
    dark = _jit(rng, (70, 102, 46), 0.05)
    _crown(p, rng, 80, 74, 46, 62, 34, 9.5, light, dark, z0=18.0, lobes=2, rough=0.36,
           gaps=0.2, top_bias=0.2)


def _paint_pine(p, rng, v):
    """Southern pine: tall clean trunk, tufted crown on upswept limbs (young ones are conical)."""
    bark = _jit(rng, (108, 84, 66), 0.05)
    needles = _jit(rng, (44, 76, 50), 0.05)
    lit = _jit(rng, (92, 122, 66), 0.05)
    lean = float(rng.uniform(-5, 5))
    young = v % 4 == 1
    top_y = float(rng.uniform(10, 22))
    _flare(p, 80, 256, 9, 8, bark)
    _trunk(p, 80, 256, 80 + lean, top_y + 10, 5.2, 1.2, bark, rng=rng, wobble=1.2)
    if young:
        y = top_y + 8
        while y < 196:
            t = (y - top_y) / (196 - top_y)
            length = 6 + t * 40 * float(rng.uniform(0.7, 1.1))
            for side in (-1, 1):
                if rng.random() < 0.2:
                    continue
                _bough(p, rng, 80 + lean * (1 - t), y, length, side, float(rng.uniform(-0.05, 0.12)),
                       6.0 + t * 3, _mix(needles, lit, 0.6 - t * 0.4), z=10.0 + (1 - t) * 4, up=0.25,
                       grain="needle", rough=0.5, step=0.7, wood=bark)
            y += float(rng.uniform(10, 15))
        p.blob(80 + lean, top_y + 4, 4, 10, lit, z=14.0, grain="needle", rough=0.4)
        return
    crown_lo = float(rng.uniform(118, 146))
    arms = int(rng.integers(11, 15))
    for i in range(arms):
        t = i / max(1, arms - 1)
        y = crown_lo - t * (crown_lo - top_y - 14) + float(rng.uniform(-4, 4))
        side = -1 if (i + int(rng.integers(0, 2))) % 2 else 1
        reach = float(rng.uniform(20, 48)) * (1 - 0.45 * t)
        x = 80 + lean * (1 - y / 256)
        ex, ey = x + side * reach, y - float(rng.uniform(8, 22))
        p.limb(x, y, ex, ey, 2.4, 0.9, bark, z=12.0)
        for k in range(5):
            u = float(rng.uniform(0.4, 1.1))
            p.blob(x + (ex - x) * u + float(rng.uniform(-8, 8)), y + (ey - y) * u + float(rng.uniform(-4, 3)),
                   float(rng.uniform(13, 21)), float(rng.uniform(6, 9)),
                   _jit(rng, _mix(needles, lit, float(rng.uniform(0.0, 0.85))), 0.05),
                   z=16.0 + k + float(rng.uniform(-3, 3)), rough=0.5, grain="needle")
    for k in range(8):
        p.blob(80 + lean + float(rng.uniform(-16, 16)), top_y + 12 + float(rng.uniform(-6, 14)),
               float(rng.uniform(11, 18)), float(rng.uniform(8, 11)), _jit(rng, lit, 0.05),
               z=20.0 + k, rough=0.5, grain="needle")


def _paint_cypress(p, rng, v):
    """Bald cypress: buttressed base, tall taper, flat layered sprays, Spanish moss."""
    bark = _jit(rng, (112, 88, 66), 0.05)
    olive = _jit(rng, (70, 94, 48), 0.05)
    amber = _jit(rng, (118, 104, 54), 0.06)
    lit = _jit(rng, (104, 128, 64), 0.05)
    moss = _jit(rng, (132, 138, 110), 0.04)
    lean = float(rng.uniform(-4, 4))
    # Buttress: the fluted flare that stands in the shallows.
    for sx in (-1, 1):
        p.limb(80 + sx * 16, 256, 80 + sx * 4, 214, 5.0, 3.0, _jit(rng, bark, 0.06), z=10.0)
    p.limb(80, 256, 80, 222, 13.0, 7.0, bark, z=12.0)
    top = float(rng.uniform(18, 32))
    _trunk(p, 80, 224, 80 + lean, top, 6.5, 1.4, bark, rng=rng, wobble=1.0)
    span = float(rng.uniform(120, 150))
    flat_top = float(rng.uniform(0.0, 1.0)) < 0.6
    for i in range(int(rng.integers(18, 26))):
        t = float(rng.uniform(0.0, 1.0)) ** 0.85
        y = top + 4 + t * span
        width = (22 + 34 * math.sin(min(1.0, t * 1.2 + 0.12) * math.pi * 0.9)) * float(rng.uniform(0.7, 1.2))
        if flat_top and t < 0.12:
            width *= 1.5
        xc = 80 + lean * (1 - y / 256)
        side = -1 if rng.random() < 0.5 else 1
        reach = width * float(rng.uniform(0.45, 1.0))
        ex, ey = xc + side * reach, y - float(rng.uniform(2, 10))
        p.limb(xc, y + 4, ex, ey, 1.6, 0.6, bark, z=12.0)
        rgb = amber if rng.random() < 0.15 else _mix(olive, lit, float(rng.uniform(0.0, 0.8)))
        for k in range(int(rng.integers(3, 6))):
            ux = xc + side * reach * float(rng.uniform(0.2, 1.05))
            p.blob(ux, ey + float(rng.uniform(-4, 4)), float(rng.uniform(9, 16)),
                   float(rng.uniform(5, 9)), _jit(rng, rgb, 0.05), z=16.0 + float(rng.uniform(-4, 5)),
                   rough=0.5, grain="fine")
        if rng.random() < 0.55:
            mx = xc + side * reach * float(rng.uniform(0.3, 0.8))
            p.drape(mx - 7, mx + 7, ey + 4, float(rng.uniform(16, 40)), moss,
                    z=24.0, density=0.5, period=2.0, sway=float(rng.uniform(-1, 1)))


def _paint_larch(p, rng, v):
    """Western larch: straight spar and a narrow cone of soft, tufted whorls.

    Whorls are dense enough that the cone reads at a glance on a far
    mountainside, with a few gaps where sky shows through the soft needles.
    """
    bark = _jit(rng, (120, 88, 64), 0.05)
    soft = _jit(rng, (112, 140, 66), 0.05)
    deep = _jit(rng, (64, 92, 46), 0.05)
    lean = float(rng.uniform(-3, 3))
    top = float(rng.uniform(6, 14))
    _flare(p, 80, 256, 8, 7, bark)
    _trunk(p, 80, 256, 80 + lean, top, 4.6, 0.8, bark, rng=rng, wobble=0.8)
    bottom = float(rng.uniform(206, 226))
    width = float(rng.uniform(0.82, 1.08))
    y = top + 4
    while y < bottom:
        t = (y - top) / (bottom - top)
        reach = (4 + t * 40 * width) * float(rng.uniform(0.75, 1.1))
        x = 80 + lean * (1 - y / 256)
        for side in (-1, 1):
            if rng.random() < 0.08:
                continue
            _bough(p, rng, x, y, reach, side, float(rng.uniform(0.05, 0.25)),
                   4.6 + t * 2.6, _mix(deep, soft, float(rng.uniform(0.25, 1.0)) * (1 - 0.3 * t)),
                   z=10.0 + (1 - t) * 3, up=0.1, wood=bark, step=0.6, rough=0.5, grain="needle")
        # Inner tufts fill the cone's core so it never reads as a bare pole.
        p.blob(x + float(rng.uniform(-2, 2)), y + 2, 3 + t * 9, 4.5 + t * 2, _mix(deep, soft, 0.2),
               z=8.0, rough=0.5, grain="needle")
        y += float(rng.uniform(5.0, 7.0))
    p.blob(80 + lean, top + 2, 2.2, 6, soft, z=16.0, rough=0.3, grain="needle")


def _paint_spruce(p, rng, v):
    """Engelmann spruce (even variants) or subalpine fir (odd): dense spires, drooping skirts."""
    fir = v % 2 == 1
    bark = _jit(rng, (92, 74, 60), 0.05)
    base = _jit(rng, (36, 68, 56) if fir else (42, 74, 74), 0.05)
    lit = _jit(rng, (66, 104, 78) if fir else (74, 108, 102), 0.05)
    lean = float(rng.uniform(-2, 2))
    top = float(rng.uniform(4, 12))
    _flare(p, 80, 256, 8, 7, bark)
    _trunk(p, 80, 256, 80 + lean, top, 4.6, 1.0, bark)
    bottom = float(rng.uniform(222, 236))
    y = top + 4
    spread = 0.15 if fir else 0.24
    while y < bottom:
        t = (y - top) / (bottom - top)
        reach = (3 + (y - top) * spread) * float(rng.uniform(0.85, 1.1))
        for side in (-1, 1):
            _bough(p, rng, 80 + lean * (1 - y / 256), y, reach, side,
                   float(rng.uniform(0.12, 0.26)) if not fir else float(rng.uniform(0.02, 0.12)),
                   4.0 + t * 3.0, _mix(base, lit, float(rng.uniform(0.0, 0.6)) * (1 - t * 0.5)),
                   z=10.0 + (1 - t) * 4 + float(rng.uniform(0, 2)), step=0.5, rough=0.4)
        y += float(rng.uniform(5.0, 7.0))
    p.blob(80 + lean, top + 3, 2.6, 7, lit, z=18.0, rough=0.3, grain="needle")


def _paint_hemlock(p, rng, v):
    """Mountain hemlock: nodding leader and long sweeping, drooping boughs."""
    bark = _jit(rng, (98, 76, 64), 0.05)
    base = _jit(rng, (34, 62, 54), 0.05)
    lit = _jit(rng, (70, 100, 84), 0.05)
    lean = float(rng.uniform(-3, 3))
    top = float(rng.uniform(10, 18))
    _flare(p, 80, 256, 9, 8, bark)
    _trunk(p, 80, 256, 80 + lean, top + 8, 5.0, 1.2, bark)
    nod = 1 if rng.random() < 0.5 else -1
    p.limb(80 + lean, top + 9, 80 + lean + nod * 7, top + 1, 0.9, 0.4, bark, z=14.0)
    p.blob(80 + lean + nod * 6, top + 4, 4.5, 6, lit, z=16.0, rough=0.4, grain="fine")
    bottom = float(rng.uniform(214, 232))
    y = top + 12
    while y < bottom:
        t = (y - top) / (bottom - top)
        reach = (5 + (y - top) * 0.25) * float(rng.uniform(0.75, 1.15))
        for side in (-1, 1):
            if rng.random() < 0.1:
                continue
            _bough(p, rng, 80 + lean * (1 - y / 256), y, reach, side, float(rng.uniform(0.3, 0.5)),
                   4.0 + t * 2.5, _mix(base, lit, float(rng.uniform(0.0, 0.55))),
                   z=10.0 + (1 - t) * 4, step=0.55, rough=0.45, grain="fine")
        y += float(rng.uniform(6.0, 8.5))


def _paint_whitebark(p, rng, v):
    """Whitebark pine: pale, often forked stems under a broad, flat-topped, tufted crown."""
    bark = _jit(rng, (176, 170, 154), 0.04)
    needles = _jit(rng, (70, 98, 62), 0.05)
    lit = _jit(rng, (118, 140, 86), 0.05)
    _flare(p, 80, 256, 12, 9, bark)
    stems = 1 + int(rng.integers(0, 3))
    crown_y = float(rng.uniform(14, 30))
    tops = []
    for i in range(stems):
        a = -math.pi / 2 + (i - (stems - 1) / 2) * 0.24 + float(rng.uniform(-0.06, 0.06))
        length = (250 - crown_y) / max(0.5, -math.sin(a)) * float(rng.uniform(0.95, 1.05))
        ex, ey = 80 + math.cos(a) * length, 250 + math.sin(a) * length
        p.limb(80, 250, ex, ey, 5.5 / math.sqrt(stems) + 1.5, 1.4, bark, z=12.0)
        tops.append((ex, ey))
    # Limbs leave the upper stems sideways and upward and carry tufts out to
    # a broad, irregular, flat-topped crown.
    for ex, ey in tops:
        for i in range(11):
            t = (i + float(rng.uniform(0, 1))) / 11 * 0.42
            sx, sy = ex + (80 - ex) * t, ey + (250 - ey) * t
            side = -1 if (i + int(rng.integers(0, 2))) % 2 else 1
            b = -math.pi / 2 + side * float(rng.uniform(0.6, 1.45))
            reach = float(rng.uniform(22, 50)) * (0.55 + t * 1.2)
            bx, by = sx + math.cos(b) * reach, sy + math.sin(b) * reach * 0.6
            p.limb(sx, sy, bx, by, 1.9, 0.7, bark, z=14.0)
            for k in range(4):
                u = float(rng.uniform(0.35, 1.05))
                up = float(np.clip(0.8 - t * 1.2 + float(rng.uniform(-0.3, 0.3)), 0, 1))
                p.blob(sx + (bx - sx) * u + float(rng.uniform(-5, 5)), sy + (by - sy) * u + float(rng.uniform(-6, 3)),
                       float(rng.uniform(10, 16)), float(rng.uniform(6.5, 10)),
                       _jit(rng, _mix(needles, lit, up), 0.05),
                       z=18.0 + float(rng.uniform(-3, 4)), rough=0.5, grain="needle")
    # Lower live branches stay sparse: wind and snow strip whitebark's skirt.
    for _ in range(int(rng.integers(2, 5))):
        y = float(rng.uniform(crown_y + 110, 200))
        side = -1 if rng.random() < 0.5 else 1
        reach = float(rng.uniform(12, 26))
        p.limb(80, y, 80 + side * reach, y - reach * 0.4, 1.4, 0.5, bark, z=14.0)
        p.blob(80 + side * reach, y - reach * 0.4, float(rng.uniform(7, 11)), float(rng.uniform(5, 7)),
               _jit(rng, needles, 0.05), z=16.0, rough=0.5, grain="needle")


def _paint_deadpine(p, rng, v):
    """Flooded snag: bleached, split grey spar with a broken top and bare stubs."""
    grey = _jit(rng, (150, 144, 130), 0.05)
    dark = _jit(rng, (96, 92, 84), 0.05)
    lean = float(rng.uniform(-8, 8))
    top = float(rng.uniform(26, 70))
    _flare(p, 80, 256, 11, 8, dark)
    pts = _trunk(p, 80, 256, 80 + lean, top, 6.0, 2.6, grey, rng=rng, wobble=1.2)
    # Jagged break at the top.
    tx, ty = pts[-1]
    p.facet(tx - 2.8, ty + 3, tx + 2.8, ty + 3, tx + float(rng.uniform(-2, 2)), ty - float(rng.uniform(6, 14)),
            grey, (0.2, 0.4, 0.9), z=18.0)
    for _ in range(int(rng.integers(5, 9))):
        y = float(rng.uniform(top + 10, 200))
        side = -1 if rng.random() < 0.5 else 1
        t = (y - top) / (256 - top)
        x = 80 + lean * (1 - t)
        reach = float(rng.uniform(5, 30)) * (1.2 - t)
        p.limb(x, y, x + side * reach, y - reach * float(rng.uniform(0.2, 0.9)), 1.5, 0.5,
               grey if rng.random() < 0.6 else dark, z=14.0)
    # A long dark split down the spar.
    p.limb(80 + lean * 0.3, 240, 80 + lean * 0.8, top + 20, 0.7, 0.4, dark, z=30.0)


_PAINTERS = {
    "oak": _paint_oak, "pine": _paint_pine, "cypress": _paint_cypress, "larch": _paint_larch,
    "spruce": _paint_spruce, "hemlock": _paint_hemlock, "whitebark": _paint_whitebark,
    "deadpine": _paint_deadpine, "cottonwood": _paint_cottonwood, "willow": _paint_willow,
    "birch": _paint_birch,
}


def tree_hd(kind: str, variant: int, *, lake: str = "briar") -> Painter:
    """The recipe for one GL atlas tree, resolution-free (see `sprites.Painter`).

    Args:
        kind: A placed kind (`TREE_KINDS`); "larchgold" is the larch baked
            with gold needles, so it is not accepted here.
        variant: 0-based variant; silhouettes differ per variant.
        lake: Lake id. Seeds this lake's silhouettes, so no two lakes share a tree,
            and applies its palette to the foliage (`sprites.LAKE_TINT`).

    Returns:
        A finished `Painter` on the 160x256 design grid.
    """
    seed = zlib.crc32(f"{lake}:{kind}:{variant}".encode())
    grain = "needle" if kind in ("larch", "spruce", "whitebark") else "leaf"
    p = Painter(W, H, seed, grain=grain)
    _PAINTERS[kind](p, p.rng, variant)
    p.tint(LAKE_TINT[lake])
    deadwood = kind == "deadpine"
    return p.finish(core=0.25 if deadwood else 0.5, cavity=0.45, contact=0.5,
                    thin_floor=0.25 if kind in CONIFERS else 0.3)
