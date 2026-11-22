"""A transparent, draggable Windows wallpaper companion."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import logging
import os
import math
from pathlib import Path
import sys

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QColor, QIcon, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QScrollArea,
    QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QSlider, QSpinBox,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from geometry import (DEFAULT_CORNERS, EDGES, Point, clamp, interpolate,
                      nearest_rail, rail, seat_point, sprite_origin, to_screen,
                      validate_corners)
from preferences import (CHARACTER_LABELS, MascotRecord, Preferences, configuration_directory,
                         load_session, save_session)
from desktop_layer import DesktopLayer
from rendering import Artwork


APP_NAME = "window AI"
CONTROLS_OPENED = b"\x01"
EDGE_LABELS = {"upper": "Upper edge", "lower": "Lower edge",
               "middle": "Middle rail", "free": "Free placement"}
ASSET_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets"


def screen_rect(screen):
    r = screen.geometry()
    return r.x(), r.y(), r.width(), r.height()


class Mascot(QWidget):
    def __init__(self, controller):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnBottomHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.controller = controller
        self.setWindowTitle(f"{APP_NAME} mascot")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.art = Artwork(controller.pref.skin)
        self.sprite = QPixmap()
        self.drag_offset = None
        self.refresh_art()

    def refresh_art(self):
        if self.art.skin != self.controller.pref.skin:
            self.art = Artwork(self.controller.pref.skin)
        self.frame = self.art.frame(self.controller.pref.height,
                                   self.controller.screen().devicePixelRatio(),
                                   self.controller.edge_slope())
        self.sprite = self.frame.pixmap
        self.setFixedSize(self.frame.size)
        self.clearMask()
        self.sync_input_state()
        self.update()

    def sync_input_state(self):
        panel_open = self.controller.manager.controls_open()
        can_drag = panel_open and not self.controller.pref.locked
        if not can_drag:
            self.drag_offset = None
        if self.drag_offset is not None:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            self.setCursor(Qt.CursorShape.OpenHandCursor if can_drag else Qt.CursorShape.ArrowCursor)
        if can_drag:
            tooltip = "Drag to move · Scroll to resize · Double-click for controls"
        elif panel_open:
            tooltip = "Scroll to resize · Double-click for controls"
        else:
            tooltip = "Double-click to open controls and adjust mascots"
        self.setToolTip(tooltip)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self.sprite)

    def mousePressEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and not self.controller.pref.locked
                and self.controller.manager.controls_open()):
            self.controller.manager.select(self.controller.id)
            self.drag_offset = event.globalPosition().toPoint() - self.controller.desktop.origin()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_offset is None or not self.controller.manager.controls_open():
            return
        origin = event.globalPosition().toPoint() - self.drag_offset
        anchor = self.frame.anchor
        seat = Point(origin.x() + anchor.x,
                     origin.y() + anchor.y - self.controller.pref.offset)
        self.controller.drag_to(seat, bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.drag_offset is not None:
            self.drag_offset = None
            self.sync_input_state()
            self.controller.schedule_save()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = None
            self.controller.show_controls()
            self.sync_input_state()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta and self.controller.resize_from_desktop(self.controller.pref.height + (4 if delta > 0 else -4)):
            event.accept()
        else:
            event.ignore()

    def contextMenuEvent(self, event):
        menu = self.controller.make_menu()
        menu.exec(event.globalPos())


class WindowGuide(QWidget):
    def __init__(self, controller):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowTransparentForInput)
        self.controller = controller
        self.setWindowTitle(f"{APP_NAME} window outline")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def refresh(self):
        self.setGeometry(self.controller.screen().geometry())
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for edge in EDGES:
            a, b = rail(self.controller.pref.points(), edge)
            p.setPen(QPen(QColor("#dfbfff"), 2, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(a.x * self.width(), a.y * self.height()),
                       QPointF(b.x * self.width(), b.y * self.height()))


class Calibrator(QWidget):
    """An interactive transparent overlay; Esc cancels without saving."""
    def __init__(self, controller):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.controller = controller
        self.setWindowTitle("Align wallpaper window outline")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(controller.screen().geometry())
        self.points = list(controller.pref.points())
        self.active = None
        self.setMouseTracking(True)
        bar = QWidget(self)
        bar.setObjectName("calibrationBar")
        bar.setStyleSheet("#calibrationBar{background:#f6f2ff;border:1px solid #a78abb;border-radius:12px;}"
                         "QLabel{color:#33283c;} QPushButton{padding:7px 15px;}")
        row = QHBoxLayout(bar)
        row.addWidget(QLabel("Drag the four corners onto the wallpaper window."))
        apply = QPushButton("Apply")
        apply.setAccessibleName("Apply window outline")
        apply.clicked.connect(self.apply)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.close)
        reset = QPushButton("Reset")
        reset.clicked.connect(self.reset)
        row.addWidget(reset)
        row.addWidget(cancel)
        row.addWidget(apply)
        bar.adjustSize()
        bar.move(max(10, (self.width() - bar.width()) // 2), 28)
        self.bar = bar

    def reset(self):
        self.points = list(DEFAULT_CORNERS)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(12, 10, 25, 38))
        polygon = QPolygonF([QPointF(a.x * self.width(), a.y * self.height()) for a in self.points])
        p.setBrush(QColor(185, 145, 245, 24))
        p.setPen(QPen(QColor("#dfbfff"), 3))
        p.drawPolygon(polygon)
        for index, a in enumerate(self.points):
            center = QPointF(a.x * self.width(), a.y * self.height())
            p.setBrush(QColor("#f9f4ff"))
            p.setPen(QPen(QColor("#815da7"), 2))
            p.drawEllipse(center, 10, 10)
            p.setPen(QColor("#ffffff"))
            p.drawText(center + QPointF(14, -12), ("Top left", "Top right", "Bottom right", "Bottom left")[index])

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            candidates = [(math.hypot(event.position().x() - a.x * self.width(),
                                      event.position().y() - a.y * self.height()), i)
                          for i, a in enumerate(self.points)]
            distance, index = min(candidates)
            if distance <= 25:
                self.active = index

    def mouseMoveEvent(self, event):
        if self.active is not None:
            self.points[self.active] = Point(clamp(event.position().x() / self.width()),
                                             clamp(event.position().y() / self.height()))
            self.update()

    def mouseReleaseEvent(self, event):
        self.active = None

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.apply()

    def apply(self):
        if not validate_corners(tuple(self.points)):
            QMessageBox.information(self, "Check the outline", "Keep left corners to the left, and top corners above the bottom corners.")
            return
        self.controller.change(corners=[[a.x, a.y] for a in self.points])
        self.close()


class RailPreview(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setMinimumHeight(190)
        self.setAccessibleName("Window edge placement preview")
        self.setToolTip("Click or drag on any upper, middle, or lower edge to place her.")

    def mapping(self):
        points = self.controller.pref.points()
        left, right = min(p.x for p in points), max(p.x for p in points)
        top, bottom = min(p.y for p in points), max(p.y for p in points)
        width, height = self.width() - 90, self.height() - 72
        return left, top, right - left, bottom - top, width, height

    def mapped(self, point):
        left, top, span_x, span_y, width, height = self.mapping()
        return QPointF(45 + (point.x - left) / span_x * width,
                       42 + (point.y - top) / span_y * height)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#edf4ff"))
        corners = self.controller.pref.points()
        p.setPen(QPen(QColor("#82badc"), 1))
        p.setBrush(QColor("#d8edfc"))
        p.drawPolygon(QPolygonF([self.mapped(a) for a in corners]))
        p.setPen(QPen(QColor("#82badc"), 2))
        p.drawLine(self.mapped(interpolate(corners[0], corners[1], .5)),
                   self.mapped(interpolate(corners[3], corners[2], .5)))
        for edge in EDGES:
            a, b = rail(corners, edge)
            color = "#8052ad" if self.controller.pref.edge == edge else "#8ec4e1"
            p.setPen(QPen(QColor(color), 3 if self.controller.pref.edge == edge else 2))
            p.drawLine(self.mapped(a), self.mapped(b))
        for companion in self.controller.companions:
            if (not companion.pref.visible or companion.pref.edge == "free"
                    or companion.screen().name() != self.controller.screen().name()):
                continue
            a, b = rail(companion.pref.points(), companion.pref.edge)
            at = self.mapped(interpolate(a, b, companion.pref.position))
            pa, pb = self.mapped(a), self.mapped(b)
            slope = (pb.y() - pa.y()) / (pb.x() - pa.x())
            frame = companion.mascot.art.frame(60 if companion is self.controller.active else 46,
                                               self.devicePixelRatioF(), slope)
            p.drawPixmap(QPointF(at.x() - frame.anchor.x, at.y() - frame.anchor.y), frame.pixmap)

    def choose(self, position):
        candidates = []
        from geometry import project
        for edge in EDGES:
            a, b = (self.mapped(q) for q in rail(self.controller.pref.points(), edge))
            t, _, distance = project(Point(position.x(), position.y()),
                                     Point(a.x(), a.y()), Point(b.x(), b.y()))
            candidates.append((distance, edge, t))
        _, edge, fraction = min(candidates)
        self.controller.change(edge=edge, position=fraction)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.choose(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.choose(event.position())


class Controls(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.syncing = False
        self.setWindowTitle(f"{APP_NAME} — Controls")
        self.setWindowIcon(controller.icon)
        self.setMinimumWidth(510)
        self.setStyleSheet("QWidget{font-family:'Segoe UI';font-size:12px;color:#392d48;background:#faf8fd;}"
                           "QLabel#heading{font-size:26px;font-weight:600;} QLabel#muted{color:#807288;}"
                           "QPushButton{background:#efe7f6;border:1px solid #ddcce9;border-radius:7px;padding:7px 12px;}"
                           "QPushButton:hover{background:#e3d5ef;} QComboBox,QSpinBox,QDoubleSpinBox{padding:5px;background:white;border:1px solid #ddcce9;border-radius:5px;}"
                           "QSlider::groove:horizontal{height:5px;background:#e6ddee;border-radius:2px;}"
                           "QSlider::handle:horizontal{background:#9069b5;width:14px;margin:-5px 0;border-radius:7px;}"
                           "QCheckBox{spacing:7px;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        root.addWidget(scroll)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(13)
        header = QHBoxLayout()
        self.portrait = QLabel()
        self.portrait.setPixmap(controller.mascot.art.pixmap(74))
        header.addWidget(self.portrait)
        titles = QVBoxLayout()
        heading = QLabel(APP_NAME)
        heading.setObjectName("heading")
        titles.addWidget(heading)
        muted = QLabel("Minimize open windows to see your mascots.")
        muted.setObjectName("muted")
        titles.addWidget(muted)
        header.addLayout(titles)
        header.addStretch()
        layout.addLayout(header)
        selection_row = QHBoxLayout()
        selection_row.addWidget(QLabel("On desktop"))
        self.instances = QComboBox()
        self.instances.setAccessibleName("Selected desktop mascot")
        selection_row.addWidget(self.instances, 1)
        self.remove_button = QPushButton("Remove selected")
        self.remove_button.clicked.connect(lambda: controller.remove_companion(controller.active.id))
        selection_row.addWidget(self.remove_button)
        layout.addLayout(selection_row)
        add_row = QHBoxLayout()
        self.new_character = QComboBox()
        self.new_character.setAccessibleName("Character to add")
        for key, label in CHARACTER_LABELS.items():
            self.new_character.addItem(label, key)
        add_row.addWidget(self.new_character, 1)
        self.add_button = QPushButton("Add mascot")
        self.add_button.clicked.connect(lambda: controller.add_companion(self.new_character.currentData()))
        add_row.addWidget(self.add_button)
        layout.addLayout(add_row)
        self.preview = RailPreview(controller)
        layout.addWidget(self.preview)
        form = QFormLayout()
        form.setSpacing(10)
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(32, 320)
        self.size_slider.setAccessibleName("Mascot size slider")
        self.size_number = QSpinBox()
        self.size_number.setRange(32, 320)
        self.size_number.setSuffix(" px")
        self.size_number.setAccessibleName("Mascot size")
        size_row = QHBoxLayout()
        size_row.addWidget(self.size_slider, 1)
        size_row.addWidget(self.size_number)
        form.addRow("Size", size_row)
        self.edge = QComboBox()
        for key in ("upper", "lower", "middle", "free"):
            self.edge.addItem(EDGE_LABELS[key], key)
        self.edge.setAccessibleName("Sitting edge")
        form.addRow("Sit on", self.edge)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 1000)
        self.position_slider.setAccessibleName("Position along edge slider")
        self.position_number = QDoubleSpinBox()
        self.position_number.setDecimals(1)
        self.position_number.setRange(0, 100)
        self.position_number.setSuffix(" %")
        self.position_number.setAccessibleName("Position along edge")
        position_row = QHBoxLayout()
        position_row.addWidget(self.position_slider, 1)
        position_row.addWidget(self.position_number)
        form.addRow("Along edge", position_row)
        self.offset = QSpinBox()
        self.offset.setRange(-100, 100)
        self.offset.setSuffix(" px")
        self.offset.setAccessibleName("Seat height adjustment")
        form.addRow("Seat adjustment", self.offset)
        layout.addLayout(form)
        self.snap = QCheckBox("Snap to the window edges while dragging")
        self.locked = QCheckBox("Lock dragging")
        self.guide = QCheckBox("Show window edge guide")
        self.visible = QCheckBox("Show this mascot on desktop")
        for box in (self.visible, self.snap, self.locked, self.guide):
            layout.addWidget(box)
        buttons = QHBoxLayout()
        align = QPushButton("Align window outline…")
        align.clicked.connect(controller.calibrate)
        reset = QPushButton("Reset placement")
        reset.clicked.connect(controller.reset)
        buttons.addWidget(align)
        buttons.addWidget(reset)
        layout.addLayout(buttons)
        help_text = QLabel("Keep these controls open to drag a mascot or scroll over it to resize.\nHold Shift while dragging for free placement. Settings save automatically.")
        help_text.setObjectName("muted")
        layout.addWidget(help_text)
        footer = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("muted")
        footer.addWidget(self.status, 1)
        hide = QPushButton("Hide controls")
        hide.clicked.connect(self.hide)
        quit_button = QPushButton("Exit all mascots")
        quit_button.clicked.connect(controller.quit)
        footer.addWidget(hide)
        footer.addWidget(quit_button)
        layout.addLayout(footer)
        self.size_slider.valueChanged.connect(lambda n: self.set_pref(height=n))
        self.size_number.valueChanged.connect(lambda n: self.set_pref(height=n))
        self.edge.currentIndexChanged.connect(lambda _: self.set_pref(edge=self.edge.currentData()))
        self.position_slider.valueChanged.connect(lambda n: self.set_pref(position=n / 1000))
        self.position_number.valueChanged.connect(lambda n: self.set_pref(position=n / 100))
        self.offset.valueChanged.connect(lambda n: self.set_pref(offset=n))
        self.snap.toggled.connect(lambda value: self.set_pref(snapping=value))
        self.locked.toggled.connect(lambda value: self.set_pref(locked=value))
        self.guide.toggled.connect(lambda value: None if self.syncing else controller.toggle_guide(value))
        self.visible.toggled.connect(lambda value: self.set_pref(visible=value))
        self.instances.currentIndexChanged.connect(lambda _: self.choose_instance())
        for control in (self.instances, self.new_character, self.size_slider, self.size_number,
                        self.edge, self.position_slider, self.position_number, self.offset):
            control.installEventFilter(self)
        self.sync()
        available = QApplication.primaryScreen().availableGeometry()
        self.resize(min(560, available.width() - 40), min(880, available.height() - 60))

    def set_pref(self, **values):
        if not self.syncing:
            self.controller.change(**values)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
            event.ignore()
            return True
        return super().eventFilter(watched, event)

    def choose_instance(self):
        if not self.syncing:
            self.controller.select(self.instances.currentData())

    def sync(self):
        self.syncing = True
        pref = self.controller.pref
        self.instances.clear()
        for companion in self.controller.companions:
            self.instances.addItem(self.controller.label_for(companion), companion.id)
        self.instances.setCurrentIndex(self.instances.findData(self.controller.active.id))
        self.remove_button.setEnabled(len(self.controller.companions) > 1)
        self.add_button.setEnabled(len(self.controller.companions) < 64)
        self.portrait.setPixmap(self.controller.mascot.art.pixmap(74))
        self.size_slider.setValue(pref.height)
        self.size_number.setValue(pref.height)
        self.edge.setCurrentIndex(self.edge.findData(pref.edge))
        self.position_slider.setValue(round(pref.position * 1000))
        self.position_number.setValue(pref.position * 100)
        self.position_slider.setEnabled(pref.edge != "free")
        self.position_number.setEnabled(pref.edge != "free")
        self.offset.setValue(pref.offset)
        self.snap.setChecked(pref.snapping)
        self.locked.setChecked(pref.locked)
        self.visible.setChecked(pref.visible)
        self.guide.setChecked(self.controller.guide.isVisible())
        self.preview.update()
        self.status.setText(f"{len(self.controller.companions)} on desktop · " + EDGE_LABELS[pref.edge]
                            + (f" · {pref.position:.0%}" if pref.edge != "free" else ""))
        self.syncing = False

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self.controller.sync_mascot_input()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.controller.sync_mascot_input()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.controller.sync_mascot_input()


class Companion(QObject):
    def __init__(self, manager, record):
        super().__init__(manager)
        self.manager, self.record = manager, record
        self.app, self.args = manager.app, manager.args
        self.pref, self.id = record.preferences, record.id
        self.mascot = Mascot(self)
        self.desktop = DesktopLayer(self.mascot)
        self.guide = WindowGuide(self)
        self.guide_layer = DesktopLayer(self.guide)
        self.calibration = None

    def screen(self):
        return next((s for s in self.app.screens() if s.name() == self.pref.screen_name),
                    self.app.primaryScreen())

    def screen_changed(self, *args):
        if self.screen() is not None:
            self.apply()

    def seat(self):
        r = screen_rect(self.screen())
        if self.pref.edge == "free":
            return to_screen(Point(self.pref.free_x, self.pref.free_y), r)
        return seat_point(self.pref.points(), self.pref.edge, self.pref.position, r)

    def edge_slope(self):
        if self.pref.edge == "free":
            return 0.0
        a, b = (to_screen(p, screen_rect(self.screen())) for p in rail(self.pref.points(), self.pref.edge))
        return (b.y - a.y) / (b.x - a.x)

    def check_desktop(self):
        if self.desktop.enabled and self.pref.visible:
            if not self.mascot.isVisible():
                self.apply()
            else:
                self.desktop.keep_below_apps()

    def apply(self):
        self.mascot.refresh_art()
        self.mascot.setWindowTitle(CHARACTER_LABELS[self.pref.skin] + " — Desktop mascot")
        at = self.seat()
        anchor = self.mascot.frame.anchor
        origin = QPoint(round(at.x - anchor.x), round(at.y - anchor.y + self.pref.offset))
        self.mascot.setVisible(self.pref.visible)
        self.desktop.place(origin, self.screen())
        self.guide.refresh()
        if self.guide.isVisible():
            self.guide_layer.place(self.screen().geometry().topLeft(), self.screen())
        self.manager.instance_changed(self)

    def change(self, **values):
        if "skin" in values and values["skin"] not in CHARACTER_LABELS:
            raise ValueError("Unknown mascot character")
        for key, value in values.items():
            setattr(self.pref, key, value)
        self.apply()
        self.schedule_save()

    def resize_from_desktop(self, height):
        if not self.manager.controls_open():
            return False
        self.change(height=int(clamp(height, 32, 320)))
        return True

    def drag_to(self, at, bypass_snap=False):
        screen = self.app.screenAt(QPoint(round(at.x), round(at.y))) or self.screen()
        self.pref.screen_name = screen.name()
        rectangle = screen_rect(screen)
        edge, fraction, nearest, distance = nearest_rail(at, self.pref.points(), rectangle)
        if self.pref.snapping and not bypass_snap and distance <= max(22, min(48, self.pref.height * .45)):
            self.pref.edge, self.pref.position = edge, fraction
        else:
            self.pref.edge = "free"
            self.pref.free_x = clamp((at.x - rectangle[0]) / rectangle[2])
            self.pref.free_y = clamp((at.y - rectangle[1]) / rectangle[3])
        self.apply()

    def schedule_save(self):
        self.manager.schedule_save()

    def save(self):
        self.manager.save()

    def status(self):
        at = self.seat()
        origin = self.desktop.origin()
        frame = self.mascot.frame
        status = {"id": self.id, "character": CHARACTER_LABELS[self.pref.skin],
                      "enabled": self.pref.visible, "visible": self.mascot.isVisible(),
                      "height": self.pref.height, "edge": self.pref.edge,
                      "position": self.pref.position, "skin": self.pref.skin,
                      "seat": [at.x, at.y], "sprite": [origin.x(), origin.y(),
                      self.mascot.width(), self.mascot.height()],
                      "anchor": [frame.anchor.x / self.mascot.width(), frame.anchor.y / self.mascot.height()],
                      "contacts": [[origin.x() + p.x, origin.y() + p.y] for p in frame.contacts],
                      "slope": self.edge_slope(), "dpr": frame.pixmap.devicePixelRatio(),
                      "desktop": self.desktop.status(),
                      "display": self.screen().name()}
        return status

    def toggle_guide(self, visible):
        self.guide.refresh()
        self.guide.setVisible(visible)
        if visible:
            self.guide_layer.place(self.screen().geometry().topLeft(), self.screen())

    def calibrate(self):
        if self.calibration is not None:
            self.calibration.close()
        self.calibration = Calibrator(self)
        self.calibration.show()
        self.calibration.activateWindow()

    def reset(self):
        self.change(edge="upper", position=.91, offset=0,
                    corners=[[p.x, p.y] for p in DEFAULT_CORNERS],
                    height=max(32, round(self.screen().geometry().height() * .055)))

    def show_controls(self):
        self.manager.select(self.id)
        self.manager.show_controls()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.show_controls()

    def toggle_visible(self):
        self.change(visible=not self.pref.visible)

    def make_menu(self):
        return self.manager.make_menu_for(self)

    def quit(self):
        self.manager.quit()

    def close_windows(self):
        if self.calibration is not None:
            self.calibration.close()
        self.guide.close()
        self.mascot.close()



class Controller(QObject):
    """One control panel and saved session, with an independent window per mascot."""
    def __init__(self, app, args):
        super().__init__(app)
        self.app, self.args = app, args
        self.config_dir = Path(args.config_dir)
        self.path = self.config_dir / "settings.json"
        first_launch = not self.path.exists()
        self.session = load_session(self.path)
        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.timeout.connect(self.save)
        self.controls = None
        self.companions = [Companion(self, record) for record in self.session.mascots]
        self.active = next((item for item in self.companions if item.id == self.session.selected_id),
                           self.companions[0])
        self.session.selected_id = self.active.id
        if first_launch:
            self.pref.height = int(clamp(round(self.screen().geometry().height() * .055), 32, 320))
        self.icon = QIcon(self.mascot.art.pixmap(64))
        app.setWindowIcon(self.icon)
        self.controls = Controls(self)
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip(f"{APP_NAME} · Desktop companions")
        self.tray.activated.connect(self.tray_activated)
        self._tray_key = None
        self.refresh_tray()
        self.tray.show()
        app.screenAdded.connect(self.screen_changed)
        app.screenRemoved.connect(self.screen_changed)
        for screen in app.screens():
            screen.geometryChanged.connect(self.screen_changed)
        for item in self.companions:
            item.apply()
        self.desktop_timer = QTimer(self)
        self.desktop_timer.timeout.connect(self.check_desktop)
        self.desktop_timer.start(2000)
        app.aboutToQuit.connect(self.save)
        if args.show_settings or not args.no_settings:
            QTimer.singleShot(100, self.show_controls)
        if args.quit_after:
            QTimer.singleShot(round(args.quit_after * 1000), self.quit)

    @property
    def pref(self):
        return self.active.pref

    @property
    def mascot(self):
        return self.active.mascot

    @property
    def desktop(self):
        return self.active.desktop

    @property
    def guide(self):
        return self.active.guide

    def label_for(self, companion):
        return f"{CHARACTER_LABELS[companion.pref.skin]} · {self.companions.index(companion) + 1}"

    def select(self, key):
        selected = next((item for item in self.companions if item.id == key), None)
        if selected is None:
            return
        self.active = selected
        self.session.selected_id = selected.id
        if self.controls is not None:
            self.controls.sync()
        self.refresh_tray()
        self.schedule_save()
        self.write_status()

    def add_companion(self, character):
        if character not in CHARACTER_LABELS:
            raise ValueError("Unknown mascot character")
        if len(self.companions) >= 64:
            return None
        pref = Preferences(**asdict(self.pref))
        pref.skin, pref.visible = character, True
        if pref.edge == "free":
            pref.edge = "upper"
        occupied = [item.pref.position for item in self.companions
                    if item.pref.edge == pref.edge and item.screen().name() == self.screen().name()]
        candidates = [step / 20 for step in range(2, 19)]
        pref.position = max(candidates, key=lambda t: min((abs(t - p) for p in occupied), default=1))
        record = MascotRecord(preferences=pref)
        companion = Companion(self, record)
        self.session.mascots.append(record)
        self.companions.append(companion)
        self.active = companion
        self.session.selected_id = companion.id
        companion.apply()
        self.refresh_tray()
        self.schedule_save()
        return companion

    def remove_companion(self, key):
        if len(self.companions) <= 1:
            return False
        companion = next((item for item in self.companions if item.id == key), None)
        if companion is None:
            return False
        index = self.companions.index(companion)
        companion.close_windows()
        self.companions.remove(companion)
        self.session.mascots = [record for record in self.session.mascots if record.id != key]
        if self.active is companion:
            self.active = self.companions[min(index, len(self.companions) - 1)]
        self.session.selected_id = self.active.id
        companion.mascot.deleteLater()
        companion.guide.deleteLater()
        companion.deleteLater()
        self.instance_changed(self.active)
        self.schedule_save()
        return True

    def instance_changed(self, companion):
        if self.controls is not None:
            self.controls.sync()
            self.controls.add_button.setEnabled(len(self.companions) < 64)
        self.refresh_tray()
        self.write_status()

    def refresh_tray(self):
        if not hasattr(self, "tray"):
            return
        key = self.active.id, self.pref.skin, len(self.companions)
        if key != self._tray_key:
            previous = getattr(self, "tray_menu", None)
            self.tray_menu = self.make_menu_for(self.active)
            self.tray.setContextMenu(self.tray_menu)
            self._tray_key = key
            if previous is not None:
                previous.deleteLater()

    def screen(self):
        return self.active.screen()

    def seat(self):
        return self.active.seat()

    def edge_slope(self):
        return self.active.edge_slope()

    def change(self, **values):
        return self.active.change(**values)

    def drag_to(self, at, bypass_snap=False):
        return self.active.drag_to(at, bypass_snap)

    def toggle_guide(self, visible):
        return self.active.toggle_guide(visible)

    def calibrate(self):
        return self.active.calibrate()

    def reset(self):
        return self.active.reset()

    def toggle_visible(self):
        return self.active.toggle_visible()

    def screen_changed(self, *args):
        for companion in self.companions:
            companion.apply()

    def check_desktop(self):
        for companion in self.companions:
            companion.check_desktop()

    def controls_open(self):
        return self.controls is not None and self.controls.isVisible() and not self.controls.isMinimized()

    def sync_mascot_input(self):
        for companion in self.companions:
            companion.mascot.sync_input_state()

    def schedule_save(self):
        self.save_timer.start(300)

    def save(self):
        try:
            save_session(self.path, self.session)
        except OSError:
            logging.exception("Could not save desktop companions")

    def write_status(self):
        if self.args.status_file:
            states = [item.status() for item in self.companions]
            status = dict(next(state for state in states if state["id"] == self.active.id))
            status.update(count=len(states), selected_id=self.active.id, mascots=states,
                          controls_visible=self.controls_open(),
                          pid=os.getpid())
            Path(self.args.status_file).write_text(json.dumps(status, indent=2), encoding="utf-8")

    def show_controls(self):
        window = self.controls
        if window.isMinimized():
            window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
        window.show()

        frame = window.frameGeometry()
        title_bar = QRect(frame.left(), frame.top(), frame.width(), 30)
        if not any(title_bar.intersected(screen.availableGeometry()).width() >= 100
                   for screen in self.app.screens()):
            work_area = self.screen().availableGeometry()
            window.move(work_area.center() - window.rect().center())

        window.raise_()
        window.activateWindow()
        self.app.alert(window, 3000)
        self.write_status()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick, QSystemTrayIcon.ActivationReason.Trigger):
            self.show_controls()

    def make_menu_for(self, companion):
        menu = QMenu()
        menu.addAction("Controls…", companion.show_controls)
        characters = menu.addMenu("Character")
        for key, label in CHARACTER_LABELS.items():
            action = characters.addAction(label, lambda checked=False, skin=key: companion.change(skin=skin))
            action.setCheckable(True)
            action.setChecked(companion.pref.skin == key)
        add = menu.addMenu("Add mascot")
        for key, label in CHARACTER_LABELS.items():
            add.addAction(label, lambda checked=False, skin=key: self.add_companion(skin))
        edges = menu.addMenu("Sit on")
        for key in ("upper", "lower", "middle"):
            edges.addAction(EDGE_LABELS[key], lambda checked=False, edge=key: companion.change(edge=edge))
        larger = menu.addAction("Larger", lambda: companion.resize_from_desktop(companion.pref.height + 8))
        smaller = menu.addAction("Smaller", lambda: companion.resize_from_desktop(companion.pref.height - 8))

        def sync_resize_actions():
            can_resize = self.controls_open()
            larger.setEnabled(can_resize)
            smaller.setEnabled(can_resize)

        menu.aboutToShow.connect(sync_resize_actions)
        sync_resize_actions()
        menu.addAction("Show / hide this mascot", companion.toggle_visible)
        remove = menu.addAction("Remove this mascot", lambda: self.remove_companion(companion.id))
        remove.setEnabled(len(self.companions) > 1)
        menu.addSeparator()
        menu.addAction("Exit all mascots", self.quit)
        return menu

    def make_menu(self):
        return self.make_menu_for(self.active)

    def quit(self):
        self.save()
        for companion in self.companions:
            companion.close_windows()
        self.controls.hide()
        self.tray.hide()
        self.app.quit()


def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} desktop mascots")
    parser.add_argument("--config-dir")
    parser.add_argument("--status-file")
    parser.add_argument("--show-settings", action="store_true")
    parser.add_argument("--no-settings", action="store_true")
    parser.add_argument("--quit-after", type=float, default=0)
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    portable_root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
    try:
        config = configuration_directory(args.config_dir, portable_root)
    except OSError:
        QMessageBox.critical(None, APP_NAME, f"{APP_NAME} could not save its settings. Move the app folder to a writable location and try again.")
        return 1
    args.config_dir = str(config)
    name = "WindowDragon-" + hashlib.sha256(os.path.normcase(str(config)).encode()).hexdigest()[:16]
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.state() == QLocalSocket.LocalSocketState.ConnectedState or socket.waitForConnected(500):
        if (socket.bytesAvailable() or socket.waitForReadyRead(5000)) and bytes(socket.read(1)) == CONTROLS_OPENED:
            return 0
        QMessageBox.warning(None, APP_NAME, f"The running copy of {APP_NAME} did not confirm that the controls opened. Exit it from Task Manager, then open {APP_NAME} again.")
        return 1
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        QMessageBox.warning(None, APP_NAME, f"{APP_NAME} could not start its control panel. Close any running copy from Task Manager and try again.")
        return 1
    logging.basicConfig(filename=str(config / "app.log"), level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    controller = Controller(app, args)

    def incoming():
        while server.hasPendingConnections():
            client = server.nextPendingConnection()
            controller.show_controls()
            client.disconnected.connect(client.deleteLater)
            client.write(CONTROLS_OPENED)
            client.flush()
            client.disconnectFromServer()

    server.newConnection.connect(incoming)
    if server.hasPendingConnections():
        QTimer.singleShot(0, incoming)
    try:
        return app.exec()
    finally:
        controller.tray.hide()
        server.close()


if __name__ == "__main__":
    import logging
    import math
    raise SystemExit(main())
