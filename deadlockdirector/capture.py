"""Grab the Deadlock window's pixels from the screen, like OBS window capture.

Only the finished image on the desktop is read (GDI BitBlt via mss). The game
process is never opened. Deadlock must run in borderless or windowed mode so
its frames are composited onto the desktop.
"""
import ctypes
import sys

from deadlockdirector import keysender

AVAILABLE = sys.platform == 'win32'


def even(value):
    return int(value) - (int(value) % 2)


def foreground_client_rect():
    """(left, top, width, height) of the foreground window's client area in
    screen pixels, trimmed to even sizes for the H.264 encoder."""
    if not AVAILABLE:
        return None
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    width, height = even(rect.right - rect.left), even(rect.bottom - rect.top)
    if width <= 0 or height <= 0:
        return None
    return origin.x, origin.y, width, height


def deadlock_rect():
    return foreground_client_rect() if keysender.foreground_is_deadlock() else None


class Grabber(object):

    def __init__(self, rect):
        import mss
        self.sct = mss.mss()
        left, top, width, height = rect
        self.region = {'left': left, 'top': top, 'width': width, 'height': height}
        self.size = (width, height)

    def grab(self):
        """One frame as raw BGRA bytes."""
        return bytes(self.sct.grab(self.region).bgra)

    def close(self):
        self.sct.close()
