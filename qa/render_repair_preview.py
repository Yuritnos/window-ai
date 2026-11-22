"""Render the actual app's frames at 150% display scale, without resizing PNG assets."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter, QPen
from preferences import CHARACTER_LABELS
from rendering import Artwork

app = QApplication([])
font_dir = Path(os.environ["SystemRoot"]) / "Fonts"
for filename in ("segoeui.ttf", "msyh.ttc"):
    QFontDatabase.addApplicationFont(str(font_dir / filename))
columns = 4
rows = (len(CHARACTER_LABELS) + columns - 1) // columns
image = QImage(columns * 300, rows * 320, QImage.Format.Format_ARGB32_Premultiplied)
image.fill(QColor("#edf4fc"))
p = QPainter(image)
font = QFont("Segoe UI", 11)
font.setFamilies(["Segoe UI", "Microsoft YaHei UI"])
p.setFont(font)
for index, (skin, label) in enumerate(CHARACTER_LABELS.items()):
    art = Artwork(skin)
    row, column = divmod(index, columns)
    left, top = column*300, row*320
    p.fillRect(left+8, top+8, 284, 304, QColor("#087ed0"))
    p.setPen(QColor("#ffffff"))
    p.drawText(left+22, top+34, label)
    slope = (-50/345, 0, 48/345, -.08)[column]
    dpr = 1.5
    frame = art.frame(158, dpr, slope)
    anchor = QPointF(left+156, top+239)
    # Painter works in physical pixels here; draw frames at their native pixel sizes.
    p.setPen(QPen(QColor("#78e2fd"), 2))
    p.drawLine(QPointF(left+12, anchor.y()-slope*144), QPointF(left+288, anchor.y()+slope*132))
    pixmap = frame.pixmap.copy()
    pixmap.setDevicePixelRatio(1)
    p.drawPixmap(QPointF(anchor.x()-frame.anchor.x*dpr, anchor.y()-frame.anchor.y*dpr), pixmap)
p.end()
assert image.save(str(ROOT/"qa"/"repair-preview.png"))
print(ROOT/"qa"/"repair-preview.png")
