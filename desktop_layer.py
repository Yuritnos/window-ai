"""Keep our mascot window inside Explorer's desktop, below application windows."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys

from PySide6.QtCore import QPoint
from PySide6.QtGui import QGuiApplication


class MonitorInfo(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                ("szDevice", wintypes.WCHAR * 32)]


class DesktopLayer:
    def __init__(self, widget):
        self.widget = widget
        self.parent_handle = 0
        self.screen = None
        self.attach_error = 0
        self.owner_mode = False
        self.enabled = sys.platform == "win32" and QGuiApplication.platformName() == "windows"
        self.ready = not self.enabled
        if not self.enabled:
            return
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self.user32.EnumWindows.argtypes = [self.callback_type, wintypes.LPARAM]
        self.user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.user32.FindWindowExW.restype = wintypes.HWND
        self.user32.GetParent.argtypes = [wintypes.HWND]
        self.user32.GetParent.restype = wintypes.HWND
        self.user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
        self.user32.SetParent.restype = wintypes.HWND
        self.user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
        self.user32.GetWindow.restype = wintypes.HWND
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.IsWindow.argtypes = [wintypes.HWND]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.get_style = self.user32.GetWindowLongPtrW
        self.get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        self.get_style.restype = ctypes.c_ssize_t
        self.set_style = self.user32.SetWindowLongPtrW
        self.set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.set_style.restype = ctypes.c_ssize_t
        self.monitor_callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                                   wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        self.user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p,
                                                    self.monitor_callback, wintypes.LPARAM]
        self.user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]

    def class_name(self, handle):
        buffer = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(handle, buffer, len(buffer))
        return buffer.value

    def desktop_host(self):
        hosts = []
        @self.callback_type
        def visit(handle, unused):
            if self.class_name(handle) in ("Progman", "WorkerW") and self.user32.FindWindowExW(
                    handle, None, "SHELLDLL_DefView", None):
                hosts.append(handle)
            return True
        self.user32.EnumWindows(visit, 0)
        return hosts[0] if hosts else 0

    def attach(self):
        if not self.enabled:
            return True
        handle = int(self.widget.winId())
        if (self.parent_handle and self.user32.IsWindow(self.parent_handle)
                and (self.owner_mode or self.user32.GetParent(handle) == self.parent_handle)):
            self.ready = True
            return True
        host = self.desktop_host()
        if not host:
            self.widget.hide()
            self.ready = False
            return False
        # QWidget must retain its Qt ownership; only its native window belongs to Explorer.
        self.set_style(handle, -16, (self.get_style(handle, -16) & ~0x80000000) | 0x40000000)
        self.set_style(handle, -20, self.get_style(handle, -20) & ~0x00000008)
        ctypes.set_last_error(0)
        self.user32.SetParent(handle, host)
        self.attach_error = ctypes.get_last_error()
        self.parent_handle = host
        self.ready = self.user32.GetParent(handle) == host
        if not self.ready:
            # Restricted launches may not modify Explorer's child-window list.
            # Keep an owned tool window immediately above the desktop and below apps.
            self.set_style(handle, -16, (self.get_style(handle, -16) & ~0x40000000) | 0x80000000)
            self.user32.SetParent(handle, None)
            self.set_style(handle, -8, host)
            self.owner_mode = True
            self.ready = self.keep_below_apps()
            if not self.ready:
                self.widget.hide()
        return self.ready

    def keep_below_apps(self):
        if not self.enabled or not self.owner_mode:
            return True
        handle = int(self.widget.winId())
        return bool(self.user32.SetWindowPos(handle, 1, 0, 0, 0, 0,
                                             0x0001 | 0x0002 | 0x0010))

    def monitor_rect(self, screen):
        found = []
        @self.monitor_callback
        def visit(monitor, dc, rectangle, unused):
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if self.user32.GetMonitorInfoW(monitor, ctypes.byref(info)) and info.szDevice == screen.name():
                found.append(info.rcMonitor)
            return True
        self.user32.EnumDisplayMonitors(None, None, visit, 0)
        if not found:
            raise RuntimeError("The selected desktop monitor is unavailable.")
        return found[0]

    def place(self, point, screen=None):
        if not self.attach():
            return False
        if self.enabled:
            self.screen = screen or QGuiApplication.screenAt(point) or self.widget.screen()
            logical, native = self.screen.geometry(), self.monitor_rect(self.screen)
            dpr = self.screen.devicePixelRatio()
            client = wintypes.POINT(round(native.left + (point.x() - logical.x()) * dpr),
                                    round(native.top + (point.y() - logical.y()) * dpr))
            if not self.owner_mode:
                self.user32.ScreenToClient(self.parent_handle, ctypes.byref(client))
            # Raise only within the desktop's child windows; never into an app's band.
            self.user32.SetWindowPos(int(self.widget.winId()), None, client.x, client.y,
                                     round(self.widget.width() * dpr), round(self.widget.height() * dpr),
                                     (0x0004 if self.owner_mode else 0) | 0x0010 | 0x0020)
            if self.owner_mode:
                self.keep_below_apps()
        else:
            self.widget.move(point)
        return True

    def origin(self):
        if self.enabled and self.screen is not None:
            rectangle = wintypes.RECT()
            self.user32.GetWindowRect(int(self.widget.winId()), ctypes.byref(rectangle))
            logical, native = self.screen.geometry(), self.monitor_rect(self.screen)
            dpr = self.screen.devicePixelRatio()
            return QPoint(round(logical.x() + (rectangle.left - native.left) / dpr),
                          round(logical.y() + (rectangle.top - native.top) / dpr))
        return self.widget.pos()

    def status(self):
        if not self.enabled:
            return {"mode": "headless", "attached": False, "topmost": False}
        handle = int(self.widget.winId())
        parent = self.user32.GetParent(handle)
        return {"mode": "desktop-bottom" if self.owner_mode else "desktop", "attached": bool(self.ready),
                "parent": int(parent or 0), "parent_class": self.class_name(parent),
                "expected_parent": int(self.parent_handle or 0), "attach_error": self.attach_error,
                "child": bool(self.get_style(handle, -16) & 0x40000000),
                "topmost": bool(self.get_style(handle, -20) & 0x00000008),
                "window": handle}
