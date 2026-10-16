"""Area-preserving squarified treemap layout; independent of GTK."""

from __future__ import annotations

from dataclasses import dataclass

from .backend import Entry


@dataclass(frozen=True)
class Tile:
    entry: Entry
    x: float
    y: float
    width: float
    height: float

    def contains(self, x: float, y: float) -> bool:
        return self.x <= x < self.x + self.width and self.y <= y < self.y + self.height


def layout(entries: list[Entry], width: float, height: float) -> list[Tile]:
    """Zero-size entries stay in the list but get no area. Never drop tiny items."""
    positive = sorted((entry for entry in entries if entry.size > 0), key=lambda entry: (-entry.size, str(entry.path)))
    total = sum(entry.size for entry in positive)
    if not total or width <= 0 or height <= 0:
        return []
    scale = width * height / total
    pending = [(entry, entry.size * scale) for entry in positive]
    tiles = []
    x = y = 0.0
    w, h = width, height

    def worst(row, side):
        areas = [area for _, area in row]
        summed = sum(areas)
        if not summed or side <= 0:
            return float("inf")
        return max(side * side * max(areas) / (summed * summed), summed * summed / (side * side * min(areas)))

    def place(row):
        nonlocal x, y, w, h
        area = sum(area for _, area in row)
        if w >= h:
            strip = min(w, area / h) if h else 0
            offset = y
            for index, (entry, size) in enumerate(row):
                length = max(0, y + h - offset) if index == len(row) - 1 else (size / strip if strip else 0)
                tiles.append(Tile(entry, x, offset, strip, length))
                offset += length
            x += strip
            w = max(0, w - strip)
        else:
            strip = min(h, area / w) if w else 0
            offset = x
            for index, (entry, size) in enumerate(row):
                length = max(0, x + w - offset) if index == len(row) - 1 else (size / strip if strip else 0)
                tiles.append(Tile(entry, offset, y, length, strip))
                offset += length
            y += strip
            h = max(0, h - strip)

    row = []
    for item in pending:
        side = min(w, h)
        if row and worst(row + [item], side) > worst(row, side):
            place(row)
            row = []
        row.append(item)
    if row:
        place(row)
    return tiles
