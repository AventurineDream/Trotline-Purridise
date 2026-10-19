"""Small, deterministic foliage atlas. No downloaded art or unbounded textures."""

from __future__ import annotations

import numpy as np

from .sprites import bake

W, H = 160, 256
KINDS = ("pine", "oak", "cypress")


def _leaf(img, cx, cy, rx, ry, rgb, rng):
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


def tree(kind, variant):
    rng = np.random.default_rng(180+variant*17+KINDS.index(kind)*83)
    img = np.zeros((H,W,4),np.uint8)
    yy, xx = np.mgrid[0:H,0:W]
    trunk_w = 3.5+(yy/H)**6*(9 if kind=="cypress" else 4)
    trunk = (abs(xx-W/2)<trunk_w)&(yy>65)&(yy<252)
    bark = 0.7+np.sin(xx*1.8+np.sin(yy*0.06))*0.12+(W/2-xx)*0.025
    img[trunk,:3] = np.clip(np.array([111,92,64])*bark[trunk,None],0,255).astype(np.uint8)
    img[trunk,3] = 255
    if kind=="oak":
        # An irregular spreading crown built from many overlapping leaf masses.
        for _ in range(90):
            a = rng.uniform(0,2*np.pi)
            r = np.sqrt(rng.random())
            cx = 80+np.cos(a)*r*53
            cy = 89+np.sin(a)*r*49
            radius = rng.uniform(10,23)
            rgb = np.array([65,91,45])+rng.uniform(-12,14,3)
            _leaf(img,cx,cy,radius,radius*0.83,rgb,rng)
        # Fine branches under the crown.
        for sign in (-1,1):
            branch = (yy>108)&(yy<174)&(abs(xx-(80+sign*(174-yy)*0.35))<2)
            img[branch] = (92,77,54,255)
    elif kind=="pine":
        for tier in range(11,0,-1):
            cy = 18+tier*14
            spread = 7+tier*4.8
            for j in range(7):
                cx = 80+rng.uniform(-spread,spread)
                rgb = np.array([48,78,54])+rng.uniform(-8,10,3)
                _leaf(img,cx,cy+rng.uniform(-6,7),rng.uniform(8,16),rng.uniform(7,12),rgb,rng)
        _leaf(img,80,17,5,11,[76,99,61],rng)
    else:
        for tier in range(10,0,-1):
            cy = 20+tier*15
            spread = 10+min(tier,7)*3.9
            for j in range(7):
                cx = 80+rng.uniform(-spread,spread)
                rgb = np.array([64,91,52])+rng.uniform(-10,10,3)
                _leaf(img,cx,cy+rng.uniform(-9,9),rng.uniform(9,18),rng.uniform(9,16),rgb,rng)
        # Fine hanging moss remains a detail, rather than a giant bare trunk.
        for _ in range(22):
            x = int(rng.uniform(52,108))
            y = int(rng.uniform(110,165))
            length = int(rng.uniform(9,29))
            img[y:y+length,x:x+1] = (82,94,69,235)
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


def atlas(buoy_rgb):
    names, images = [], []
    for kind in KINDS:
        for variant in range(3):
            names.append(f"{kind}{variant}")
            images.append(tree(kind,variant))
    for kind, src in bake(buoy_rgb).items():
        if kind in KINDS:
            continue
        names.append(kind)
        # All texture-array layers have one bounded size.
        ys = np.minimum(np.arange(H)*src.shape[0]//H,src.shape[0]-1)
        xs = np.minimum(np.arange(W)*src.shape[1]//W,src.shape[1]-1)
        images.append(src[ys[:,None],xs[None,:]])
    return {name:i for i,name in enumerate(names)}, np.stack([_bleed_edges(img) for img in images])[:,::-1].copy()
