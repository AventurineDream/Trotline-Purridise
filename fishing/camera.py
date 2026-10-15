"""First-person camera. Yaw 0 looks north. Positive yaw turns east.

The ray builder and the projector are inverses of each other. A unit test
checks that a world point along a pixel's ray projects back onto that pixel.
"""

from __future__ import annotations

import numpy as np


class Camera:
    def __init__(self, x, y, z, yaw, pitch, roll, fov_x, w, h, *, build_rays=True):
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.roll = float(roll)
        self.fov_x = float(fov_x)
        self.w = int(w)
        self.h = int(h)
        self.build_rays = bool(build_rays)
        self.eye = np.array([self.x, self.y, self.z], dtype=np.float32)
        self._build()

    def _build(self):
        w, h = self.w, self.h
        if not self.build_rays:
            # Mesh rendering needs only the camera basis, not one NumPy ray
            # per pixel. Avoid a large CPU allocation on every GL frame.
            self.tanx = float(np.tan(self.fov_x*0.5))
            self.tany = self.tanx*h/w
            self.forward = np.array([np.sin(self.yaw),0,np.cos(self.yaw)],np.float32)
            self.right = np.array([np.cos(self.yaw),0,-np.sin(self.yaw)],np.float32)
            self.up = np.array([0,1,0],np.float32)
            self._cp,self._sp = float(np.cos(self.pitch)),float(np.sin(self.pitch))
            self._cr,self._sr = float(np.cos(self.roll)),float(np.sin(self.roll))
            self.dirs = None
            return
        xs = (np.arange(w, dtype=np.float32) + 0.5) / w * 2.0 - 1.0
        ys = 1.0 - (np.arange(h, dtype=np.float32) + 0.5) / h * 2.0
        tanx = np.float32(np.tan(self.fov_x * 0.5))
        tany = np.float32(tanx * (h / w))
        self.tanx = float(tanx)
        self.tany = float(tany)
        cx = xs[None, :] * tanx
        cy = ys[:, None] * tany
        cz = np.ones((h, w), dtype=np.float32)
        cr = np.float32(np.cos(self.roll))
        sr = np.float32(np.sin(self.roll))
        x1 = cx * cr + cy * sr
        y1 = -cx * sr + cy * cr
        cp = np.float32(np.cos(self.pitch))
        sp = np.float32(np.sin(self.pitch))
        y0 = y1 * cp + cz * sp
        z0 = -y1 * sp + cz * cp
        x0 = x1
        self.forward = np.array([np.sin(self.yaw), 0.0, np.cos(self.yaw)], dtype=np.float32)
        self.right = np.array([np.cos(self.yaw), 0.0, -np.sin(self.yaw)], dtype=np.float32)
        self.up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        dirs = (
            self.right[0] * x0 + self.up[0] * y0 + self.forward[0] * z0,
            self.right[1] * x0 + self.up[1] * y0 + self.forward[1] * z0,
            self.right[2] * x0 + self.up[2] * y0 + self.forward[2] * z0,
        )
        d = np.stack(dirs, axis=-1).astype(np.float32)
        n = np.linalg.norm(d, axis=-1, keepdims=True)
        self.dirs = d / np.maximum(n, 1e-8)
        self._cp = float(cp)
        self._sp = float(sp)
        self._cr = float(cr)
        self._sr = float(sr)

    def world_to_cam(self, pts: np.ndarray) -> np.ndarray:
        v = np.asarray(pts, dtype=np.float32) - self.eye
        cx = v @ self.right
        cy = v @ self.up
        cz = v @ self.forward
        y2 = cy * self._cp - cz * self._sp
        z2 = cy * self._sp + cz * self._cp
        x2 = cx
        x3 = x2 * self._cr - y2 * self._sr
        y3 = x2 * self._sr + y2 * self._cr
        return np.stack([x3, y3, z2], axis=-1).astype(np.float32)

    def cam_to_screen(self, cam_pts: np.ndarray):
        z = cam_pts[:, 2]
        ndc_x = (cam_pts[:, 0] / z) / self.tanx
        ndc_y = (cam_pts[:, 1] / z) / self.tany
        sx = (ndc_x * 0.5 + 0.5) * self.w
        sy = (1.0 - (ndc_y * 0.5 + 0.5)) * self.h
        return sx, sy, z

    def project_world(self, x, y, z):
        cam = self.world_to_cam(np.array([[x, y, z]], dtype=np.float32))[0]
        if cam[2] < 0.25:
            return None
        sx, sy, zz = self.cam_to_screen(cam[None, :])
        return float(sx[0]), float(sy[0]), float(zz[0])


def self_check() -> None:
    cam = Camera(0, 1.22, 0, yaw=0.0, pitch=0.0, roll=0.0, fov_x=np.deg2rad(78), w=400, h=300)
    d = cam.dirs[150, 200]
    assert d[2] > 0.9 and abs(d[0]) < 0.05, d
    point = cam.eye + d * np.float32(12.0)
    hit = cam.project_world(float(point[0]), float(point[1]), float(point[2]))
    assert hit is not None
    assert abs(hit[0] - 200.5) < 1.5 and abs(hit[1] - 150.5) < 1.5, hit
    right = cam.project_world(4.0, 1.22, 10.0)
    assert right is not None and right[0] > 220, right
    # Positive yaw looks east. A point due east of the eye should be near center.
    cam2 = Camera(0, 1.22, 0, yaw=np.pi / 2, pitch=-0.1, roll=0.05, fov_x=np.deg2rad(78), w=400, h=300)
    d2 = cam2.dirs[150, 200]
    point = cam2.eye + d2 * np.float32(15.0)
    hit = cam2.project_world(float(point[0]), float(point[1]), float(point[2]))
    assert hit is not None
    assert abs(hit[0] - 200.5) < 1.5 and abs(hit[1] - 150.5) < 1.5, hit
