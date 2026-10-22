"""Non-blocking character animation, driven only by completed operations."""
import math
import json
from pathlib import Path
import cairo
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import GLib, Gtk, Pango, PangoCairo


# One playthrough: anticipation, fast impact, slower recovery. The final pose
# stays visible for the existing receipt/fade; no animation drives a mutation.
SLASH_FRAME_MS = (90, 90, 90, 90, 90, 90, 100, 100, 100, 60, 60, 60, 90, 90, 90, 150, 150, 300)
SLASH_FRAME_COUNT = len(SLASH_FRAME_MS)


def slash_frame_at(seconds):
    milliseconds = max(0, seconds * 1000)
    boundary = 0
    for index, duration in enumerate(SLASH_FRAME_MS):
        boundary += duration
        if milliseconds < boundary:
            return index
    return SLASH_FRAME_COUNT - 1


def slash_frame_blend(seconds):
    """Briefly blend adjacent poses while motion follows the display frame clock."""
    frame = slash_frame_at(seconds)
    end = sum(SLASH_FRAME_MS[:frame + 1]) / 1000
    weight = min(1, max(0, (seconds - end + .028) / .028))
    weight = weight * weight * (3 - 2 * weight)
    return frame, min(frame + 1, SLASH_FRAME_COUNT - 1), weight


class SlashCelebration(Gtk.DrawingArea):
    def __init__(self):
        super().__init__(hexpand=True, vexpand=True, can_target=False)
        self.sprite = cairo.ImageSurface.create_from_png(str(Path(__file__).resolve().parents[1] / 'assets/mio-slash-18.png'))
        atlas = json.loads((Path(__file__).resolve().parents[1] / 'assets/mio-slash-18.json').read_text())
        self.frame_rects = atlas['frames']
        assert len(self.frame_rects) == SLASH_FRAME_COUNT
        assert atlas['durations_ms'] == list(SLASH_FRAME_MS)
        self.set_draw_func(self.draw)
        self.set_visible(False)
        self.tick_id = None
        self.elapsed = 0
        self.play_count = 0
        self.caption = ''
        self.enabled = True
        self.tile_effect = None

    def play(self, completed=0, total=0, preview=False, target=None, tile_effect=None):
        if not preview and completed <= 0:
            return
        self.stop()
        self.target = target
        self.tile_effect = tile_effect
        self.play_count += 1
        self.caption = '动作预览 · 未操作文件' if preview else f'已收纳 {completed} 项 · 可在系统回收站恢复'
        if not preview and completed < total:
            self.caption += f'\n另有 {total - completed} 项未处理'
        self.animate = self.enabled and Gtk.Settings.get_default().get_property('gtk-enable-animations')
        self.elapsed = 0
        self.started = GLib.get_monotonic_time() / 1_000_000
        self.set_visible(True)
        self.tick_id = self.add_tick_callback(self.tick)
        self.queue_draw()

    def stop(self):
        if self.tick_id is not None:
            self.remove_tick_callback(self.tick_id)
            self.tick_id = None
        self.set_visible(False)
        self.tile_effect = None

    def tick(self, widget, clock):
        now = clock.get_frame_time() / 1_000_000
        self.elapsed = max(0, now - self.started)
        if self.elapsed > (2.8 if self.animate else 2):
            self.tick_id = None
            self.set_visible(False)
            self.tile_effect = None
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

    def draw_pose(self, cr, frame, display_size, alpha):
        sx, sy, frame_width, frame_height = self.frame_rects[frame]
        cr.save()
        scale = min(display_size / frame_width, display_size / frame_height)
        cr.translate((display_size - frame_width * scale) / 2, (display_size - frame_height * scale) / 2)
        cr.scale(scale, scale)
        cr.rectangle(0, 0, frame_width, frame_height)
        cr.clip()
        cr.set_source_surface(self.sprite, -sx, -sy)
        cr.paint_with_alpha(alpha)
        cr.restore()

    def draw(self, area, cr, width, height):
        t = self.elapsed
        fade = min(1, max(0, (2.8 - t) / .45)) if self.animate else 1
        cx, cy = self.target if self.target else (width * .58, min(height * .56, height - 180))
        if self.tile_effect:
            bounds = self.tile_effect.bounds()
            if bounds:
                x, y, w, h = bounds
                cx, cy = x + w / 2, y + h / 2
        cx, cy = max(60, min(width - 60, cx)), max(90, min(height - 100, cy))
        if self.animate:
            if self.tile_effect:
                self.tile_effect.draw(cr, t)
            # Abstract cache fragments: a visual receipt, not a second file operation.
            burst = max(0, min(1, (t - .75) / .9))
            if self.tile_effect is None and .75 < t < 1.7:
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
            # Clip one of the 18 genuinely distinct poses from the 6×3 atlas.
            frame, next_frame, blend = slash_frame_blend(t)
            display_size = min(360, width * .44)
            approach = min(1, t / .54)
            destination = cx - display_size / 2
            x = width + 30 + (destination - width - 30) * (1 - (1 - approach) ** 3)
            y = cy - display_size / 2
            # Continuous follow-through between illustrated poses avoids a
            # static cutout sliding across the screen. No file work runs here.
            impulse = math.sin(min(1, max(0, (t - .78) / .48)) * math.pi)
            x += 18 * impulse
            y -= 8 * math.sin(min(1, t / .54) * math.pi)
            cr.save()
            cr.translate(x, y)
            # Add premultiplied images inside a group so matching opaque pixels
            # stay opaque during the short dissolve (no brightness flicker).
            cr.push_group()
            self.draw_pose(cr, frame, display_size, 1 - blend)
            if blend:
                cr.set_operator(cairo.OPERATOR_ADD)
                self.draw_pose(cr, next_frame, display_size, blend)
            pattern = cr.pop_group()
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.set_source(pattern)
            cr.paint_with_alpha(fade)
            cr.restore()
            if self.tile_effect:
                self.tile_effect.draw_cut(cr, t)
            elif .84 < t < 1.14:
                stroke = math.sin((t - .84) / .30 * math.pi)
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
            x, y = (width - panel_w) / 2, min(cy + 155, height - 90)
            cr.set_source_rgba(.98, .95, 1, .97 * fade)
            radius = 16
            cr.new_sub_path()
            for px, py, angle in [(x + panel_w - radius, y + radius, -math.pi / 2), (x + panel_w - radius, y + 70 - radius, 0), (x + radius, y + 70 - radius, math.pi / 2), (x + radius, y + radius, math.pi)]:
                cr.arc(px, py, radius, angle, angle + math.pi / 2)
            cr.close_path()
            cr.fill()
            cr.set_source_rgba(.38, .29, .53, fade)
            self.text(cr, self.caption, x + 10, y + 16, panel_w - 20, 12)
