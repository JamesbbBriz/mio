"""Render the real GTK/Cairo effect on synthetic tiles; no filesystem operation.

Run with a display: python3 -m scripts.preview_tile_shatter
Pillow is required only for this GIF exporter, not for the application.
"""
from io import BytesIO
from pathlib import Path
import cairo
from PIL import Image
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk
from mio_linux.backend import Entry
from mio_linux.celebration import SlashCelebration
from mio_linux.disk_view import Treemap
from mio_linux.shatter import TileShatter

Gtk.init()
width, height = 800, 520
origin = (30, 65)
treemap = Treemap(lambda _: None, lambda _: None)
entries = [Entry(Path('/演示/下载素材'), size=384 * 1024**2),
           Entry(Path('/演示/图片'), size=240 * 1024**2),
           Entry(Path('/演示/文档'), size=140 * 1024**2)]
treemap.set_entries(entries)
treemap.selected = entries[0]
base = cairo.ImageSurface(cairo.FORMAT_ARGB32, 740, 340)
treemap.draw(treemap, cairo.Context(base), 740, 340)
tile = treemap.tiles[0]
texture = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(tile.width + 1), int(tile.height + 1))
ctx = cairo.Context(texture)
ctx.translate(-tile.x, -tile.y)
treemap.draw_tile(ctx, tile)
effect = TileShatter(texture, tile.width, tile.height,
                     lambda: (origin[0] + tile.x, origin[1] + tile.y, tile.width, tile.height))
treemap.concealed_path = tile.entry.path
animation = SlashCelebration()
animation.animate = True
animation.target = None
animation.tile_effect = effect
animation.caption = '动作预览 · 未操作文件'
output = Path(__file__).resolve().parents[1] / 'artifacts'
output.mkdir(exist_ok=True)
frames = []
for index in range(84):
    t = index / 30
    canvas = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(canvas)
    cr.set_source_rgb(.97, .96, .99)
    cr.paint()
    cr.set_source_rgb(.31, .25, .42)
    animation.text(cr, '斩开 → 碎裂 → 收纳', 20, 18, width - 40, 16)
    cr.save()
    cr.translate(*origin)
    # Keep neighbours in place until the actual UI's refresh point.
    treemap.draw(treemap, cr, 740, 340)
    cr.restore()
    animation.elapsed = t
    animation.draw(animation, cr, width, height)
    buffer = BytesIO()
    canvas.write_to_png(buffer)
    frames.append(Image.open(BytesIO(buffer.getvalue())).convert('RGB'))
    if index == 40:
        canvas.write_to_png(str(output / 'mio-tile-shatter.png'))
frames[0].save(output / 'mio-tile-shatter.gif', save_all=True, append_images=frames[1:],
               duration=[33, 33, 34] * 28, loop=0, disposal=2)
print(output / 'mio-tile-shatter.gif')
