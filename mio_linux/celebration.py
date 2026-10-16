"""Non-blocking character animation, driven only by completed operations."""
import math
from pathlib import Path
import cairo
from gi.repository import Gtk, Pango, PangoCairo


class SlashCelebration(Gtk.DrawingArea):
    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, can_target=False)
        self.sprite = cairo.ImageSurface.create_from_png(str(Path(__file__).resolve().parents[1] / 'assets/mio-slash.png'))
        self.set_draw_func(self.draw)
        self.set_visible(False)
        self.tick_id = None
        self.elapsed = 0
        self.play_count = 0
        self.caption = ''
        self.enabled = True

    def play(self, completed=0, total=0, preview=False):
        if not preview and completed <= 0:
            return
        self.stop()
        self.play_count += 1
        self.caption = '动作预览 · 未操作文件' if preview else f'已收纳 {completed} 项 · 可在系统回收站恢复'
        if not preview and completed < total:
            self.caption += f'\n另有 {total - completed} 项未处理'
        self.animate = self.enabled and Gtk.Settings.get_default().get_property('gtk-enable-animations')
        self.elapsed = 0
        self.started = None
        self.set_visible(True)
        self.tick_id = self.add_tick_callback(self.tick)
        self.queue_draw()

    def stop(self):
        if self.tick_id is not None:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = None
        self.set_visible(False)

    def tick(self, widget, clock):
        now = clock.get_frame_time() / 1_000_000
        if self.started is None:
            self.started = now
        self.elapsed = now - self.started
        if self.elapsed > (2.8 if self.animate else 2):
            self.tick_id = None
            self.set_visible(False)
            return False
        self.queue_draw()
        return True

    @staticmethod
    def text(cr, text, x, y, width, size=16):
        layout = PangoCairo.create_layout(cr)
        layout.set_text(text, -1)
        layout.set_font_description(Pango.FontDescription.from_string(f'Sans Bold {size}'))
        layout.set_width(int(width * Pango.SCALE))
        layout.set_alignment(Pango.Alignment.CENTER)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, layout)

    def draw(self, area, cr, width, height):
        t = self.elapsed
        fade = min(1, max(0, (2.8 - t) / .45)) if self.animate else 1
        cx, cy = width * .58, min(height * .56, height - 180)
        if self.animate:
            # Abstract cache fragments: a visual receipt, not a second file operation.
            burst = max(0, min(1, (t - .75) / .9))
            if t < 1.7:
                for i in range(14):
                    angle = i * 2.399
                    distance = 22 + burst * (65 + i * 6)
                    x = cx - 50 + math.cos(angle) * distance
                    y = cy + math.sin(angle) * distance
                    cr.save()
                    cr.translate(x, y)
                    cr.rotate(burst * (i % 3 - 1))
                    cr.set_source_rgba(.76, .66 + .015 * i, .94, (1 - burst) * .85)
                    cr.rectangle(-10, -10, 20, 20)
                    cr.fill()
                    cr.restore()
            # Character dashes from the right, then settles alongside the slash.
            approach = min(1, t / .72)
            x = width + 40 + (cx - 65 - width - 40) * (1 - (1 - approach) ** 3)
            y = cy - 150 + (math.sin(t * 30) * 7 if t < .72 else 0)
            scale = min(320, width * .31) / self.sprite.get_width()
            cr.save()
            cr.translate(x, y)
            cr.rotate(-.09 * math.sin(min(1, max(0, (t - .65) / .5)) * math.pi))
            cr.scale(scale, scale)
            cr.set_source_surface(self.sprite)
            cr.paint_with_alpha(fade)
            cr.restore()
            if .65 < t < 1.3:
                stroke = math.sin((t - .65) / .65 * math.pi)
                for line_width, color in [(22, (.95, .55, .83)), (11, (.55, .83, 1)), (4, (1, 1, 1))]:
                    cr.set_source_rgba(*color, stroke * fade)
                    cr.set_line_width(line_width)
                    cr.move_to(cx - 180, cy + 90)
                    cr.curve_to(cx - 110, cy - 10, cx + 30, cy - 35, cx + 190, cy - 100)
                    cr.stroke()
            if t > .8:
                for i in range(18):
                    angle = i * 2.399
                    distance = 40 + (t - .8) * (38 + i * 3)
                    x, y = cx + math.cos(angle) * distance, cy + math.sin(angle) * distance
                    alpha = max(0, 1 - (t - .8) / 1.8) * fade
                    cr.set_source_rgba(.91 if i % 2 else .45, .55 if i % 2 else .76, .95, alpha)
                    cr.move_to(x - 4, y)
                    cr.line_to(x, y - 8)
                    cr.line_to(x + 4, y)
                    cr.line_to(x, y + 8)
                    cr.close_path()
                    cr.fill()
        if t > .75 or not self.animate:
            panel_w = min(470, width - 40)
            x, y = (width - panel_w) / 2 + 50, min(cy + 155, height - 90)
            cr.set_source_rgba(.98, .95, 1, .97 * fade)
            radius = 16
            cr.new_sub_path()
            for px, py, angle in [(x + panel_w - radius, y + radius, -math.pi / 2), (x + panel_w - radius, y + 70 - radius, 0), (x + radius, y + 70 - radius, math.pi / 2), (x + radius, y + radius, math.pi)]:
                cr.arc(px, py, radius, angle, angle + math.pi / 2)
            cr.close_path()
            cr.fill()
            cr.set_source_rgba(.38, .29, .53, fade)
            self.text(cr, self.caption, x + 10, y + 16, panel_w - 20, 12)
