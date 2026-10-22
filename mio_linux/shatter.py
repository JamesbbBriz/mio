"""Visual-only cut and fragments, textured with the selected treemap tile."""
import math

IMPACT_AT = .86
SHATTER_AT = 1.16
SHATTER_END = 1.98
# Allow the last fragments to disappear before reflowing neighbouring tiles.
REFRESH_AFTER_MS = 2050


def clip_half(polygon, width, height, side):
    """Clip to either side of the same diagonal; together they preserve area."""
    def distance(point):
        return side * (point[1] - .82 * height + .64 * height * point[0] / width)
    result = []
    previous = polygon[-1]
    before = distance(previous)
    for current in polygon:
        after = distance(current)
        if (before >= 0) != (after >= 0):
            ratio = before / (before - after)
            result.append(tuple(a + ratio * (b - a) for a, b in zip(previous, current)))
        if after >= 0:
            result.append(current)
        previous, before = current, after
    return result


def fragment_polygons(width, height):
    """A deterministic triangulation cut along the blade, without gaps/overlap."""
    columns, rows = 4, 3
    points = []
    for row in range(rows + 1):
        line = []
        for col in range(columns + 1):
            dx = .16 * math.sin(row * 7 + col * 13) if 0 < col < columns else 0
            dy = .16 * math.cos(row * 11 + col * 3) if 0 < row < rows else 0
            line.append(((col + dx) * width / columns, (row + dy) * height / rows))
        points.append(line)
    fragments = []
    for row in range(rows):
        for col in range(columns):
            a, b = points[row][col:col + 2]
            d, c = points[row + 1][col:col + 2]
            for triangle in ((a, b, c), (a, c, d)):
                for side in (-1, 1):
                    polygon = clip_half(triangle, width, height, side)
                    if len(polygon) >= 3:
                        fragments.append((side, polygon))
    return fragments


class TileShatter:
    def __init__(self, surface, width, height, bounds):
        self.surface = surface
        self.width, self.height = width, height
        self.bounds = bounds  # Current widget coordinates, including window resizing.
        rectangle = [(0, 0), (width, 0), (width, height), (0, height)]
        self.halves = [(side, clip_half(rectangle, width, height, side)) for side in (-1, 1)]
        self.fragments = fragment_polygons(width, height)
        length = math.hypot(.64 * height, width)
        self.normal = (.64 * height / length, width / length)

    @staticmethod
    def phase(t):
        if t < IMPACT_AT:
            return 'intact'
        if t < SHATTER_AT:
            return 'split'
        if t < SHATTER_END:
            return 'shatter'
        return 'gone'

    def piece(self, cr, polygon, dx=0, dy=0, rotation=0, alpha=1):
        cx = sum(p[0] for p in polygon) / len(polygon)
        cy = sum(p[1] for p in polygon) / len(polygon)
        cr.save()
        cr.translate(cx + dx, cy + dy)
        cr.rotate(rotation)
        cr.translate(-cx, -cy)
        cr.move_to(*polygon[0])
        for point in polygon[1:]:
            cr.line_to(*point)
        cr.close_path()
        cr.clip()
        cr.set_source_surface(self.surface, 0, 0)
        cr.paint_with_alpha(alpha)
        cr.restore()

    def draw(self, cr, t):
        bounds = self.bounds()
        if bounds is None or t >= SHATTER_END:
            return
        x, y, width, height = bounds
        cr.save()
        cr.translate(x, y)
        cr.scale(width / self.width, height / self.height)
        if t < IMPACT_AT:
            cr.set_source_surface(self.surface, 0, 0)
            cr.paint()
        elif t < SHATTER_AT:
            progress = (t - IMPACT_AT) / (SHATTER_AT - IMPACT_AT)
            separation = 14 * (1 - (1 - progress) ** 3)
            for side, polygon in self.halves:
                self.piece(cr, polygon, side * self.normal[0] * separation,
                           side * self.normal[1] * separation)
        else:
            for index, (side, polygon) in enumerate(self.fragments):
                age = max(0, t - SHATTER_AT - (index % 5) * .014)
                cx = sum(p[0] for p in polygon) / len(polygon)
                cy = sum(p[1] for p in polygon) / len(polygon)
                # Start at the exact separated-half position, then accelerate
                # into outward motion and gravity. Every shard retains its text.
                dx = side * self.normal[0] * (14 + age * 48) + (cx - self.width / 2) * age * .55
                dy = side * self.normal[1] * (14 + age * 48) + (cy - self.height / 2) * age * .35 + 100 * age * age
                rotation = (index % 7 - 3) * age * age * .8
                alpha = max(0, 1 - age / (SHATTER_END - SHATTER_AT - .056)) ** 1.4
                self.piece(cr, polygon, dx, dy, rotation, alpha)
        cr.restore()

    def draw_cut(self, cr, t):
        bounds = self.bounds()
        if bounds is None or not IMPACT_AT - .06 < t < SHATTER_AT + .08:
            return
        x, y, width, height = bounds
        progress = min(1, (t - IMPACT_AT + .06) / .12)
        alpha = min(1, max(0, (SHATTER_AT + .08 - t) / .25))
        for thickness, color in ((18, (.94, .55, .86)), (8, (.52, .85, 1)), (2.5, (1, 1, 1))):
            cr.set_source_rgba(*color, alpha)
            cr.set_line_width(thickness)
            cr.move_to(x, y + height * .82)
            cr.line_to(x + width * progress, y + height * (.82 - .64 * progress))
            cr.stroke()
