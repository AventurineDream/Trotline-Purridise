"""Tests for renderer hot paths and process/GPU memory accounting."""

from __future__ import annotations

import unittest

import numpy as np

from .glrender import LakeRenderer
from .sim import State
from .verify import drm_memory_bytes, rss_bytes
from .world import Face, World


class RendererPerfTests(unittest.TestCase):
    """Keep vector packing and memory-unit contracts explicit."""

    def test_pack_faces_preserves_triangle_order_and_material(self):
        points = np.asarray(((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)), np.float32)
        normal = np.asarray((0, 0, 1), np.float32)
        color = np.asarray((0.8, 0.4, 0.2), np.float32)
        packed = LakeRenderer._pack_faces(object.__new__(LakeRenderer), [Face(points, normal, color)])

        np.testing.assert_array_equal(packed[:, :3], points[[0, 1, 2, 0, 2, 3]])
        np.testing.assert_array_equal(packed[:, 3:6], np.tile(normal, (6, 1)))
        np.testing.assert_array_equal(packed[:, 6:9], np.tile(color, (6, 1)))
        np.testing.assert_array_equal(packed[:, 9], np.full(6, 1.0, np.float32))

    def test_offscreen_render_is_upscaled_on_gpu_to_output_size(self):
        world = World()
        try:
            renderer = LakeRenderer(world, 320, 180, output_size=(640, 360))
        except (ImportError, RuntimeError) as exc:
            self.skipTest(f"OpenGL unavailable: {exc}")
        try:
            if renderer.software_gl:
                self.skipTest("Mesa software GL renders at scene size")
            frame = renderer.render(State.new(world, seed=7))
            self.assertEqual(frame.shape, (360, 640, 3))
            self.assertEqual((renderer.w, renderer.h), (320, 180))
        finally:
            renderer.close()

    def test_drm_accounting_counts_each_client_once_in_bytes(self):
        shared = ("drm-driver:\ti915\ndrm-client-id:\t340\ndrm-pdev:\t0000:00:02.0\n"
                  "drm-total-system0:\t98696 KiB\ndrm-resident-system0:\t90000 KiB\n"
                  "drm-resident-stolen-system0:\t0\ndrm-engine-render:\t6883448 ns\n")
        other = ("drm-client-id:\t7\ndrm-pdev:\t0000:01:00.0\n"
                 "drm-total-vram0:\t2 MiB\n")
        plain = "pos:\t0\nflags:\t02100002\n"
        self.assertEqual(drm_memory_bytes([shared, shared, plain, shared]), 90000 * 1024)
        self.assertEqual(drm_memory_bytes([shared, other]), 90000 * 1024 + 2 * 1024**2)
        self.assertIsNone(drm_memory_bytes([plain]))

    def test_process_peak_rss_is_reported_in_bytes(self):
        """The memory budget receives a positive byte count on every supported OS."""
        self.assertGreater(rss_bytes(), 0)


if __name__ == "__main__":
    unittest.main()
