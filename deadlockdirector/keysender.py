"""Windows-only: tap a key with SendInput, only while Deadlock is focused.

This is the same mechanism macro tools (AutoHotkey, keyboard vendor software)
use. Nothing is read from or written to the game process; the only thing
checked is which program owns the foreground window.
"""
import ctypes
import sys

from deadlockdirector.settings import DEADLOCK_PROCESS_NAMES

AVAILABLE = sys.platform == 'win32'

if AVAILABLE:
    from ctypes import wintypes

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    winmm = ctypes.WinDLL('winmm')

    INPUT_KEYBOARD = 1
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_SCANCODE = 0x0008

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                    ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_size_t)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [('type', wintypes.DWORD), ('u', _INPUTUNION)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))


def tap(scancode, extended=False):
    """Press and release one key. Returns True if Windows accepted both events."""
    if not AVAILABLE:
        return False
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    events = (INPUT * 2)()
    for i, extra in enumerate((0, KEYEVENTF_KEYUP)):
        events[i].type = INPUT_KEYBOARD
        events[i].u.ki = KEYBDINPUT(0, scancode, flags | extra, 0, 0)
    return user32.SendInput(2, events, ctypes.sizeof(INPUT)) == 2


def foreground_is_deadlock():
    if not AVAILABLE:
        return False
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        import psutil
        return psutil.Process(pid.value).name().lower() in DEADLOCK_PROCESS_NAMES
    except Exception:
        return False


class precise_timer(object):
    """Raise the Windows timer resolution to 1 ms so sleep() is accurate."""

    def __enter__(self):
        if AVAILABLE:
            winmm.timeBeginPeriod(1)
        return self

    def __exit__(self, *args):
        if AVAILABLE:
            winmm.timeEndPeriod(1)
