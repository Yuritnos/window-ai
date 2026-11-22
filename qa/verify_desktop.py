"""Verify the real Windows z-order using an ordinary covering test window."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QLabel
from desktop_layer import DesktopLayer
from mascot import Controller

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
with tempfile.TemporaryDirectory(prefix="dragon-desktop-check-") as config:
    controller = Controller(app, argparse.Namespace(config_dir=config, status_file=None,
                            show_settings=False, no_settings=True, quit_after=0))
    controller.change(height=120)
    with patch.object(DesktopLayer, "monitor_rect", return_value=None):
        companion = controller.add_companion("claude")
    assert companion.mascot.isVisible()
    assert companion.desktop.screen is None
    app.processEvents()
    layer = controller.desktop
    own = int(controller.mascot.winId())
    original = controller.companions[0]
    assert original.mascot.isVisible() and int(original.mascot.winId()) != own
    assert layer.ready and not layer.status()["topmost"] and not layer.status()["child"], layer.status()
    user32 = layer.user32
    enum_window = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [enum_window, wintypes.LPARAM]
    user32.GetShellWindow.restype = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    cover = QLabel("Checking desktop-only mascot visibility")
    cover.setWindowTitle("window AI visibility test")
    cover.setStyleSheet("background:#222;color:white;padding:30px")
    origin = layer.origin()
    cover.setGeometry(origin.x()-40, origin.y()-40, controller.mascot.width()+160, 240)
    cover.show()
    cover.raise_()
    result = {}
    def check():
        layer.keep_below_apps()
        cover_handle = int(cover.winId())
        shell = user32.GetShellWindow()
        order = []
        @enum_window
        def current(handle, unused):
            order.append(handle)
            return True
        user32.EnumWindows(current, 0)
        result.update(layer.status(),
                      mascot_visible=bool(user32.IsWindowVisible(own)),
                      cover_above_mascot=order.index(cover_handle) < order.index(own),
                      desktop_below_mascot=shell in order and order.index(own) < order.index(shell))
        cover.close()
        controller.quit()
    QTimer.singleShot(300, check)
    app.exec()
    assert result["mascot_visible"] and result["cover_above_mascot"] and result["desktop_below_mascot"], result
    (ROOT/"qa"/"desktop-verification.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
