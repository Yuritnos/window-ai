"""Alpha-preserving, high-DPI artwork anchored by the seated hips."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math
from pathlib import Path
import sys

from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import QImage, QPixmap, QTransform

from geometry import Point

ASSET_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"


@dataclass
class SpriteFrame:
    pixmap: QPixmap
    size: QSize
    anchor: Point
    contacts: tuple[Point, Point]


class Artwork:
    def __init__(self, skin):
        metadata = json.loads((ASSET_ROOT / "artwork.json").read_text(encoding="utf-8"))[skin]
        image = QImage(str(ASSET_ROOT / metadata["file"]))
        if image.isNull() or not image.hasAlphaChannel():
            raise RuntimeError("The transparent mascot artwork could not be loaded.")
        crop = QRect(*metadata["display_rect"])
        self.image = image.copy(crop).convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        mirror = metadata.get("mirror", False)
        if mirror:
            self.image = self.image.flipped(Qt.Orientation.Horizontal)

        def source_point(x, y):
            local_x = x - crop.x()
            return QPointF(crop.width() - local_x if mirror else local_x, y - crop.y())

        self.source_anchor = source_point(*metadata["seat"])
        self.anchor = Point(self.source_anchor.x() / crop.width(), self.source_anchor.y() / crop.height())
        # Reflect the seated axis with the image, keeping the endpoints in left-to-right order.
        seat_line = metadata["seat_line"]
        if mirror:
            seat_line = reversed(seat_line)
        self.seat_line = tuple(source_point(x, y) for x, y in seat_line)
        self.skin = skin

    @lru_cache(maxsize=48)
    def frame(self, height, dpr=1.0, slope=0.0):
        left, right = self.seat_line
        source_angle = math.atan2(right.y() - left.y(), right.x() - left.x())
        rotation = QTransform().rotate(math.degrees(math.atan(slope) - source_angle))
        mapping = QImage.trueMatrix(rotation, self.image.width(), self.image.height())
        oriented = self.image.transformed(rotation, Qt.TransformationMode.SmoothTransformation)
        physical_height = max(1, round(height * dpr))
        # Smooth area downsampling preserves fine outlines at small display sizes.
        scaled = oriented.scaledToHeight(physical_height, Qt.TransformationMode.SmoothTransformation)
        effective_dpr = physical_height / height
        pixmap = QPixmap.fromImage(scaled)
        pixmap.setDevicePixelRatio(effective_dpr)
        logical_width = scaled.width() / effective_dpr
        sx, sy = logical_width / oriented.width(), height / oriented.height()
        def mapped(point):
            at = mapping.map(point)
            return Point(at.x() * sx, at.y() * sy)
        return SpriteFrame(pixmap, QSize(math.ceil(logical_width), height),
                           mapped(self.source_anchor), tuple(mapped(p) for p in self.seat_line))

    def pixmap(self, height, dpr=1.0):
        return self.frame(height, dpr).pixmap
