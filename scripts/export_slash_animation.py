"""Package the generated atlas as 18 crop rectangles and a looping GIF preview.

The source illustration is preserved. Pillow is needed only to run this exporter.
"""
import json
from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
# Keep in sync with celebration.SLASH_FRAME_MS; no GTK needed for asset export.
DURATIONS = [90, 90, 90, 90, 90, 90, 100, 100, 100, 60, 60, 60, 90, 90, 90, 150, 150, 300]
source = Image.open(ROOT / 'assets/mio-slash-18.png').convert('RGBA')
width, height = source.size
alpha = source.getchannel('A')


def safe_cut(expected, start, end, vertical):
    # Generated art can miss a mathematical grid edge by a few pixels. Read
    # the transparent gutter, so no hair or sword gets clipped into a neighbour.
    def cost(position):
        bounds = (position, start, position + 1, end) if vertical else (start, position, end, position + 1)
        histogram = alpha.crop(bounds).histogram()
        return sum(i * count for i, count in enumerate(histogram)), abs(position - expected)
    return min(range(max(1, expected - 25), expected + 26), key=cost)


ys = [0] + [safe_cut(round(row * height / 3), 0, width, False) for row in (1, 2)] + [height]
rectangles, previews = [], []
for row in range(3):
    top, bottom = ys[row:row + 2]
    xs = [0] + [safe_cut(round(col * width / 6), top, bottom, True) for col in range(1, 6)] + [width]
    for col in range(6):
        left, right = xs[col:col + 2]
        rectangles.append([left, top, right - left, bottom - top])
        frame = ImageOps.contain(source.crop((left, top, right, bottom)), (384, 384), Image.Resampling.LANCZOS)
        preview = Image.new('RGBA', (384, 384), '#f8f2ff')
        preview.alpha_composite(frame, ((384 - frame.width) // 2, (384 - frame.height) // 2))
        previews.append(preview.convert('RGB'))
metadata = {'image': 'mio-slash-18.png', 'canvas': [width, height], 'frames': rectangles, 'durations_ms': DURATIONS}
(ROOT / 'assets/mio-slash-18.json').write_text(json.dumps(metadata, indent=2) + '\n')
previews[0].save(ROOT / 'assets/mio-slash-18.gif', save_all=True, append_images=previews[1:], duration=DURATIONS, loop=0, disposal=2, optimize=False)
with Image.open(ROOT / 'assets/mio-slash-18.gif') as result:
    assert result.n_frames == 18
print('Exported 18 distinct poses; runtime atlas retains transparency; GIF uses a light preview background.')
