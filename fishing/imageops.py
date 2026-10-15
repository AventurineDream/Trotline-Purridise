"""Bounded frame scaling shared by both rendering backends."""

import numpy as np


def resize_rgb(rgb, width, height):
    if rgb.shape[:2] == (height,width):
        return rgb.copy()
    ih, iw = rgb.shape[:2]
    xs = np.clip((np.arange(width,dtype=np.float32)+0.5)*iw/width-0.5,0,iw-1)
    ys = np.clip((np.arange(height,dtype=np.float32)+0.5)*ih/height-0.5,0,ih-1)
    x0, y0 = xs.astype(np.int32), ys.astype(np.int32)
    x1, y1 = np.minimum(x0+1,iw-1),np.minimum(y0+1,ih-1)
    wx, wy = (xs-x0)[None,:,None],(ys-y0)[:,None,None]
    rows = rgb[:,x0].astype(np.float32)*(1-wx)+rgb[:,x1].astype(np.float32)*wx
    return (rows[y0]*(1-wy)+rows[y1]*wy+0.5).astype(np.uint8)
