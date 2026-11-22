"""Place a transparent tool window at the bottom of the desktop's window order."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication

HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010


class MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


class DesktopLayer:
    def __init__(self, widget):
        self.widget = widget
        self.screen = None
        self.enabled = sys.platform == "win32" and QGuiApplication.platformName() == "windows"
        self.ready = not self.enabled
        if not self.enabled:
            return
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.get_style = self.user32.GetWindowLongPtrW
        self.get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        self.get_style.restype = ctypes.c_ssize_t
        self.monitor_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                                   wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        self.user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p,
                                                    self.monitor_callback, wintypes.LPARAM]
        self.user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]

    def keep_below_apps(self):
        if self.enabled:
            self.ready = bool(self.user32.SetWindowPos(int(self.widget.winId()), HWND_BOTTOM,
                                                       0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE))
        return self.ready

    def monitor_rect(self, screen):
        found = []
        device = screen.name().casefold()
        @self.monitor_callback
        def visit(monitor, dc, rectangle, unused):
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if (self.user32.GetMonitorInfoW(monitor, ctypes.byref(info))
                    and info.szDevice.casefold() == device):
                found.append(info.rcMonitor)
                return False
            return True
        self.user32.EnumDisplayMonitors(None, None, visit, 0)
        return found[0] if found else None

    def place(self, point, screen=None):
        if self.enabled:
            screen = screen or QGuiApplication.screenAt(point) or self.widget.screen()
            native = self.monitor_rect(screen)
            if native is not None:
                logical, dpr = screen.geometry(), screen.devicePixelRatio()
                # Keep the alpha-rendered Qt window top-level and independent of Explorer.
                if self.user32.SetWindowPos(int(self.widget.winId()), HWND_BOTTOM,
                                            round(native.left + (point.x() - logical.x()) * dpr),
                                            round(native.top + (point.y() - logical.y()) * dpr),
                                            round(self.widget.width() * dpr), round(self.widget.height() * dpr),
                                            SWP_NOACTIVATE):
                    self.screen, self.ready = screen, True
                    return
        self.screen = None
        self.widget.move(point)
        self.keep_below_apps()

    def origin(self):
        if self.enabled and self.screen is not None:
            rectangle = wintypes.RECT()
            logical, native = self.screen.geometry(), self.monitor_rect(self.screen)
            if native is not None and self.user32.GetWindowRect(int(self.widget.winId()), ctypes.byref(rectangle)):
                dpr = self.screen.devicePixelRatio()
                return QPoint(round(logical.x() + (rectangle.left - native.left) / dpr),
                              round(logical.y() + (rectangle.top - native.top) / dpr))
        return self.widget.pos()

    def status(self):
        if not self.enabled:
            return {"mode": "headless", "attached": False, "topmost": False}
        handle = int(self.widget.winId())
        return {"mode": "desktop-bottom", "attached": self.ready,
                "child": bool(self.get_style(handle, -16) & 0x40000000),
                "topmost": bool(self.get_style(handle, -20) & 0x00000008),
                "window": handle}
