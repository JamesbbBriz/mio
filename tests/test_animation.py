import unittest
from mio_linux.celebration import SLASH_FRAME_MS, slash_frame_at, slash_frame_blend
from mio_linux.shatter import TileShatter, fragment_polygons, SHATTER_END, REFRESH_AFTER_MS


class AnimationTests(unittest.TestCase):
    def test_all_eighteen_frames_in_order_and_final_hold(self):
        self.assertEqual(len(SLASH_FRAME_MS), 18)
        elapsed = 0
        for index, duration in enumerate(SLASH_FRAME_MS):
            self.assertEqual(slash_frame_at((elapsed + duration / 2) / 1000), index)
            elapsed += duration
        self.assertEqual(slash_frame_at(-1), 0)
        self.assertEqual(slash_frame_at(elapsed / 1000 + 10), 17)
        # The blade reaches the tile during the impact poses.
        self.assertIn(slash_frame_at(.95), (9, 10, 11))

    def test_blend_is_continuous_at_pose_boundaries(self):
        elapsed = 0
        for index, duration in enumerate(SLASH_FRAME_MS[:-1]):
            elapsed += duration / 1000
            current, following, weight = slash_frame_blend(elapsed - .000001)
            self.assertEqual((current, following), (index, index + 1))
            self.assertGreater(weight, .999)
            self.assertEqual(slash_frame_blend(elapsed + .000001)[0], index + 1)

    def test_fragments_cover_tile_and_follow_cut(self):
        for width, height in ((320, 180), (2, 600), (1200, 4)):
            area = 0
            for side, polygon in fragment_polygons(width, height):
                area += abs(sum(a[0] * b[1] - b[0] * a[1]
                                for a, b in zip(polygon, polygon[1:] + polygon[:1]))) / 2
                for x, y in polygon:
                    self.assertGreaterEqual(x, -.000001)
                    self.assertLessEqual(x, width + .000001)
                    self.assertGreaterEqual(y, -.000001)
                    self.assertLessEqual(y, height + .000001)
                    self.assertGreaterEqual(side * (y - .82 * height + .64 * height * x / width), -.000001)
            self.assertAlmostEqual(area, width * height)

    def test_actual_tile_texture_splits_then_disappears(self):
        import cairo
        source = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 80)
        cr = cairo.Context(source)
        cr.set_source_rgb(.3, .5, .8)
        cr.paint()
        cr.set_source_rgb(1, 1, 1)
        cr.rectangle(10, 10, 30, 12)
        cr.fill()
        effect = TileShatter(source, 120, 80, lambda: (0, 0, 120, 80))
        def render(t):
            result = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 80)
            effect.draw(cairo.Context(result), t)
            result.flush()
            return bytes(result.get_data())
        source.flush()
        self.assertEqual(render(.5), bytes(source.get_data()))
        self.assertNotEqual(render(1.1), render(.5))
        self.assertNotEqual(render(1.5), render(1.1))
        self.assertFalse(any(render(SHATTER_END)))
        self.assertGreater(REFRESH_AFTER_MS / 1000, SHATTER_END)

    def test_atlas_has_eighteen_bounded_distinct_frames(self):
        import cairo
        import hashlib
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / 'assets'
        metadata = json.loads((root / 'mio-slash-18.json').read_text())
        surface = cairo.ImageSurface.create_from_png(str(root / metadata['image']))
        self.assertEqual(metadata['durations_ms'], list(SLASH_FRAME_MS))
        self.assertEqual(len(metadata['frames']), 18)
        pixels, stride = bytes(surface.get_data()), surface.get_stride()
        hashes = set()
        for x, y, width, height in metadata['frames']:
            self.assertTrue(0 <= x < x + width <= surface.get_width())
            self.assertTrue(0 <= y < y + height <= surface.get_height())
            data = b''.join(pixels[row * stride + x * 4:row * stride + (x + width) * 4] for row in range(y, y + height))
            hashes.add(hashlib.sha256(data).digest())
        self.assertEqual(len(hashes), 18)
