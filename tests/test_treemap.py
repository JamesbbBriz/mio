import random
import unittest
from pathlib import Path

from mio_linux.backend import Entry
from mio_linux.treemap import layout


class TreemapTests(unittest.TestCase):
    def test_area_proportions_bounds_and_no_overlaps(self):
        random.seed(17)
        for width, height in [(800, 360), (360, 800), (100, 100), (1, 1000)]:
            with self.subTest(width=width, height=height):
                entries = [Entry(Path(str(i)), size=random.randint(1, 10000)) for i in range(50)]
                tiles = layout(entries, width, height)
                total = sum(entry.size for entry in entries)
                self.assertEqual(len(tiles), len(entries))
                self.assertAlmostEqual(sum(tile.width * tile.height for tile in tiles), width * height, places=6)
                for index, tile in enumerate(tiles):
                    self.assertGreaterEqual(tile.x, 0)
                    self.assertGreaterEqual(tile.y, 0)
                    self.assertLessEqual(tile.x + tile.width, width + 1e-7)
                    self.assertLessEqual(tile.y + tile.height, height + 1e-7)
                    self.assertAlmostEqual(tile.width * tile.height / (width * height), tile.entry.size / total, places=7)
                    self.assertTrue(tile.contains(tile.x + tile.width / 2, tile.y + tile.height / 2))
                    for other in tiles[index + 1:]:
                        overlap_x = min(tile.x + tile.width, other.x + other.width) - max(tile.x, other.x)
                        overlap_y = min(tile.y + tile.height, other.y + other.height) - max(tile.y, other.y)
                        self.assertFalse(overlap_x > 1e-7 and overlap_y > 1e-7)

    def test_empty_zero_sized_and_invalid_viewports(self):
        empty = Entry(Path("empty"), size=0)
        self.assertEqual(layout([], 100, 100), [])
        self.assertEqual(layout([empty], 100, 100), [])
        self.assertEqual(layout([Entry(Path("one"), size=1)], 0, 100), [])

    def test_tiny_entries_are_not_dropped(self):
        entries = [Entry(Path("large"), size=10**12), Entry(Path("tiny"), size=1)]
        tiles = layout(entries, 800, 360)
        self.assertEqual(len(tiles), 2)
        self.assertGreater(tiles[1].width * tiles[1].height, 0)


if __name__ == "__main__":
    unittest.main()
