"""Screen-independent geometry for a mascot sitting on a wallpaper window."""
from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Point:
    x: float
    y: float


DEFAULT_CORNERS = (
    Point(1195 / 1920, 433 / 1080),
    Point(1540 / 1920, 383 / 1080),
    Point(1540 / 1920, 738 / 1080),
    Point(1195 / 1920, 690 / 1080),
)
EDGES = ("upper", "middle", "lower")


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))


def interpolate(a: Point, b: Point, position: float) -> Point:
    t = clamp(position)
    return Point(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t)


def validate_corners(corners: tuple[Point, ...]) -> bool:
    if len(corners) != 4 or any(
        not math.isfinite(v) or not 0 <= v <= 1
        for p in corners for v in (p.x, p.y)
    ):
        return False
    tl, tr, br, bl = corners
    # Wallpaper panes have an upright, non-crossing quadrilateral outline.
    return (min(tr.x, br.x) - max(tl.x, bl.x) > 0.015
            and min(bl.y, br.y) - max(tl.y, tr.y) > 0.02)


def rail(corners: tuple[Point, ...], edge: str) -> tuple[Point, Point]:
    tl, tr, br, bl = corners
    if edge == "upper":
        return tl, tr
    if edge == "lower":
        return bl, br
    if edge == "middle":
        # The reference has a level central crossbar at y=560/1080.
        left = interpolate(tl, bl, 0.5)
        right = interpolate(tr, br, 0.5)
        return left, right
    raise ValueError("Unknown edge: " + edge)


def to_screen(point: Point, screen: tuple[float, float, float, float]) -> Point:
    x, y, width, height = screen
    return Point(x + point.x * width, y + point.y * height)


def seat_point(corners: tuple[Point, ...], edge: str, position: float,
               screen: tuple[float, float, float, float]) -> Point:
    a, b = rail(corners, edge)
    return to_screen(interpolate(a, b, position), screen)


def project(point: Point, a: Point, b: Point) -> tuple[float, Point, float]:
    dx, dy = b.x - a.x, b.y - a.y
    denominator = dx * dx + dy * dy
    t = 0.0 if denominator == 0 else clamp(
        ((point.x - a.x) * dx + (point.y - a.y) * dy) / denominator
    )
    closest = interpolate(a, b, t)
    return t, closest, math.hypot(point.x - closest.x, point.y - closest.y)


def nearest_rail(point: Point, corners: tuple[Point, ...],
                 screen: tuple[float, float, float, float]) -> tuple[str, float, Point, float]:
    candidates = []
    for edge in EDGES:
        a, b = rail(corners, edge)
        t, closest, distance = project(point, to_screen(a, screen), to_screen(b, screen))
        candidates.append((edge, t, closest, distance))
    return min(candidates, key=lambda item: item[3])


def sprite_origin(seat: Point, anchor: Point, width: int, height: int,
                  offset: float = 0) -> Point:
    """Resizing always preserves the contact point, including sloping rails."""
    return Point(seat.x - anchor.x * width,
                 seat.y - anchor.y * height + offset)
