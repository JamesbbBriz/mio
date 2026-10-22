import unittest
from mio_linux.celebration import SLASH_FRAME_MS, slash_frame_at


class AnimationTests(unittest.TestCase):
    def test_all_eighteen_frames_in_order_and_final_hold(self):
        self.assertEqual(len(SLASH_FRAME_MS), 18)
        elapsed = 0
        for index, duration in enumerate(SLASH_FRAME_MS):
            self.assertEqual(slash_frame_at((elapsed + duration / 2) / 1000), index)
            elapsed += duration
        self.assertEqual(slash_frame_at(-1), 0)
        self.assertEqual(slash_frame_at(elapsed / 1000 + 10), 17)
        # Confirmed disk moves refresh at .95 s, during the impact poses.
        self.assertIn(slash_frame_at(.95), (9, 10, 11))

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
