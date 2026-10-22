"""Whole-button character artwork with native accessible labels and controls."""
from pathlib import Path
import cairo
from gi.repository import Gtk

ROLES = {
    'overview': ('星见', '星空导航员'),
    'cache': ('绯羽', '净空剑士'),
    'disk': ('月织', '星图绘师'),
    'apps': ('青叶', '应用图书馆员'),
    'trash': ('琥珀', '归还守护者'),
    'memory': ('琥珀', '内存巡查员'),
    'maintenance': ('苍音', '机械工程师'),
}


class CharacterNav(Gtk.Button):
    def __init__(self, key, title):
        super().__init__(css_classes=['nav', 'character-nav', 'nav-' + key])
        self.art_path = Path(__file__).resolve().parents[1] / 'assets/navigation' / (('trash' if key == 'memory' else key) + '.png')
        name, role = ROLES[key]
        self.set_tooltip_text(f'{title} · {name} / {role}')
        self.update_property([Gtk.AccessibleProperty.LABEL], [f'{title}，{name}，{role}'])
        self.set_overflow(Gtk.Overflow.HIDDEN)
        scene = Gtk.Overlay()
        scene.set_overflow(Gtk.Overflow.HIDDEN)
        # A drawing area keeps source pixel dimensions out of GTK's size negotiation.
        self.artwork = cairo.ImageSurface.create_from_png(str(self.art_path))
        art = Gtk.DrawingArea(content_width=230, content_height=80, can_target=False)
        art.set_draw_func(self.draw_artwork)
        scene.set_child(art)
        shade = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.FILL,
                        halign=Gtk.Align.START, css_classes=['nav-copy'], can_target=False)
        shade.set_size_request(132, -1)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, valign=Gtk.Align.CENTER, vexpand=True,
                       margin_start=14, margin_end=12)
        title_label = Gtk.Label(label=title, xalign=0, css_classes=['nav-title'])
        title_label.set_ellipsize(3)
        text.append(title_label)
        text.append(Gtk.Label(label=f'{name} / {role}', xalign=0, css_classes=['nav-role']))
        shade.append(text)
        scene.add_overlay(shade)
        marker = Gtk.Box(halign=Gtk.Align.START, valign=Gtk.Align.FILL, css_classes=['nav-marker'], can_target=False)
        marker.set_size_request(4, -1)
        scene.add_overlay(marker)
        self.set_child(scene)

    def draw_artwork(self, area, cr, width, height):
        scale = max(width / self.artwork.get_width(), height / self.artwork.get_height())
        cr.translate((width - self.artwork.get_width() * scale) / 2,
                     (height - self.artwork.get_height() * scale) / 2)
        cr.scale(scale, scale)
        cr.set_source_surface(self.artwork, 0, 0)
        cr.paint()
