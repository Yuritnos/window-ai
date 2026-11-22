"""Verify the real Windows z-order using an ordinary covering test window."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel
from mascot import Controller

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
with tempfile.TemporaryDirectory(prefix="dragon-desktop-check-") as config:
    controller = Controller(app, argparse.Namespace(config_dir=config, status_file=None,
                            show_settings=False, no_settings=True, quit_after=0))
    controller.change(height=120)
    app.processEvents()
    layer = controller.desktop
    assert layer.ready, layer.status()
    assert not layer.status()["topmost"], layer.status()
    order = []
    @layer.callback_type
    def record(handle, unused):
        order.append(handle)
        return True
    layer.user32.EnumWindows(record, 0)
    own = int(controller.mascot.winId())
    hierarchy = {"mascot_index": order.index(own) if own in order else None,
                 "desktop_index": order.index(layer.parent_handle) if layer.parent_handle in order else None}
    if layer.owner_mode:
        assert hierarchy["mascot_index"] < hierarchy["desktop_index"], hierarchy
    cover = QLabel("Checking desktop-only mascot visibility")
    cover.setWindowTitle("Window Dragon visibility test")
    cover.setStyleSheet("background:#222;color:white;padding:30px")
    origin = layer.origin()
    cover.setGeometry(origin.x()-40, origin.y()-40, controller.mascot.width()+160, 240)
    cover.show()
    cover.raise_()
    result = {}
    def check():
        layer.keep_below_apps()
        cover_handle = int(cover.winId())
        rectangle = wintypes.RECT()
        layer.user32.GetWindowRect(own, ctypes.byref(rectangle))
        layer.user32.WindowFromPoint.argtypes = [wintypes.POINT]
        layer.user32.WindowFromPoint.restype = wintypes.HWND
        top = layer.user32.WindowFromPoint(wintypes.POINT((rectangle.left+rectangle.right)//2,
                                                         (rectangle.top+rectangle.bottom)//2))
        layer.user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
        current_order = []
        @layer.callback_type
        def current(handle, unused):
            current_order.append(handle)
            return True
        layer.user32.EnumWindows(current, 0)
        result.update(layer.status(), z_order=hierarchy,
                      hit_window_class=layer.class_name(top),
                      cover_above_mascot=current_order.index(cover_handle) < current_order.index(own),
                      covered_by_normal_window=bool(top != own and layer.class_name(top) not in ("Progman", "WorkerW", "#32769")))
        cover.close()
        controller.quit()
    QTimer.singleShot(300, check)
    app.exec()
    assert result["covered_by_normal_window"] and result["cover_above_mascot"], result
    (ROOT/"qa"/"desktop-verification.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
