"""Interactive native treemap with hover details and keyboard navigation."""

from __future__ import annotations

import colorsys
import hashlib

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gtk, Pango, PangoCairo

from .backend import Entry, human_size
from .treemap import layout


def color_for(entry):
    digest = hashlib.sha256(str(entry.path).encode("utf-8", errors="surrogatepass")).digest()
    return colorsys.hls_to_rgb(.57 + digest[0] / 255 * .34, .76 + digest[1] / 255 * .08, .45 + digest[2] / 255 * .20)


class Treemap(Gtk.DrawingArea):
    def __init__(self, on_select, on_activate):
        super().__init__(content_width=320, content_height=360, hexpand=True, vexpand=True, focusable=True)
        self.entries = []
        self.tiles = []
        self.selected = None
        self.hovered = None
        self.on_select = on_select
        self.on_activate = on_activate
        self.empty_text = "开始扫描，让空间分布一目了然"
        self.set_draw_func(self.draw)
        self.set_cursor_from_name("pointer")
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self.tooltip)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self.motion)
        self.add_controller(motion)
        click = Gtk.GestureClick()
        click.connect("released", self.clicked)
        self.add_controller(click)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self.key_pressed)
        self.add_controller(keys)

    def set_entries(self, entries):
        self.entries = sorted(entries, key=lambda entry: (-entry.size, entry.path.name.casefold()))
        self.selected = None
        self.tiles = []
        self.queue_draw()

    def tile_at(self, x, y):
        return next((tile for tile in self.tiles if tile.contains(x, y)), None)

    def select(self, entry):
        self.selected = entry
        self.on_select(entry)
        self.queue_draw()

    def motion(self, _, x, y):
        tile = self.tile_at(x, y)
        if tile is not None and (self.selected is None or tile.entry.path != self.selected.path):
            self.hovered = tile.entry
            self.queue_draw()

    def clicked(self, _, presses, x, y):
        self.grab_focus()
        tile = self.tile_at(x, y)
        if tile is not None:
            self.select(tile.entry)
            if presses >= 2 and tile.entry.is_dir:
                self.on_activate(tile.entry.path)

    def key_pressed(self, _, key, code, state):
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.selected is not None:
            if self.selected.is_dir:
                self.on_activate(self.selected.path)
            return True
        if key in (Gdk.KEY_Left, Gdk.KEY_Up, Gdk.KEY_Right, Gdk.KEY_Down) and self.entries:
            index = next((i for i, entry in enumerate(self.entries) if entry is self.selected), -1)
            step = -1 if key in (Gdk.KEY_Left, Gdk.KEY_Up) else 1
            self.select(self.entries[(index + step) % len(self.entries)])
            return True
        return False

    def tooltip(self, _, x, y, keyboard, tooltip):
        tile = self.tile_at(x, y)
        entry = self.selected if keyboard else (tile.entry if tile else None)
        if entry is None:
            return False
        total = sum(item.size for item in self.entries)
        tooltip.set_text(f"{entry.path}\n{human_size(entry.size)} · {entry.size / total:.1%}" if total else str(entry.path))
        return True

    def text(self, cr, value, x, y, width, size=12, bold=False):
        content = PangoCairo.create_layout(cr)
        content.set_text(value, -1)
        font = Pango.FontDescription.from_string(f"Sans {'Bold ' if bold else ''}{size}")
        content.set_font_description(font)
        content.set_width(int(max(0, width) * Pango.SCALE))
        content.set_ellipsize(Pango.EllipsizeMode.END)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, content)

    def draw(self, area, cr, width, height):
        # Reserve space for a finite set of visible tiles. Aggregate the tail
        # without losing its area, and keep every item available in the list.
        positive = [entry for entry in self.entries if entry.size > 0]
        visible = positive[:79]
        if len(positive) > 80:
            tail = positive[79:]
            visible.append(Entry(tail[0].path.parent / f"其余 {len(tail)} 项（见列表）", size=sum(e.size for e in tail), files=sum(e.files for e in tail)))
        else:
            visible = positive
        self.tiles = layout(visible, width, height)
        if not self.tiles:
            cr.set_source_rgb(.42, .50, .45)
            self.text(cr, "此目录没有非空普通文件" if self.entries else self.empty_text, 20, height / 2 - 10, width - 40)
            return
        for tile in self.tiles:
            x, y, w, h = tile.x + 1.5, tile.y + 1.5, max(0, tile.width - 3), max(0, tile.height - 3)
            cr.save()
            cr.rectangle(x, y, w, h)
            cr.clip()
            rgb = color_for(tile.entry)
            selected = self.selected is not None and tile.entry.path == self.selected.path
            if selected:
                rgb = tuple(min(1, c + .09) for c in rgb)
            cr.set_source_rgb(*rgb)
            cr.paint()
            if w >= 55 and h >= 36:
                cr.set_source_rgb(.25, .20, .36)
                self.text(cr, tile.entry.path.name, x + 12, y + 10, w - 24, 11, True)
                if h >= 64:
                    self.text(cr, human_size(tile.entry.size), x + 12, y + 33, w - 24, 10)
                if h >= 92 and tile.entry.is_dir:
                    self.text(cr, "双击浏览  →", x + 12, y + h - 30, w - 24, 9)
            cr.restore()
            if selected:
                cr.set_source_rgb(.57, .35, .64)
                cr.set_line_width(3)
                cr.rectangle(x + 1.5, y + 1.5, max(0, w - 3), max(0, h - 3))
                cr.stroke()
