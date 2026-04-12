"""Global hotkeys using Windows RegisterHotKey API."""
import ctypes
import ctypes.wintypes
from PyQt5.QtCore import QThread, pyqtSignal

# Virtual key codes
VK_F9 = 0x78
VK_F10 = 0x79
MOD_CTRL = 0x0002
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312

HOTKEY_TOGGLE_VISIBLE = 1
HOTKEY_TOGGLE_CLICKTHROUGH = 2


class HotkeyListener(QThread):
    """Listens for global hotkeys in a background thread."""
    toggle_visible = pyqtSignal()
    toggle_clickthrough = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        user32 = ctypes.windll.user32

        # Ctrl+Alt+F9  = toggle overlay visibility
        # Ctrl+Alt+F10 = toggle click-through
        user32.RegisterHotKey(None, HOTKEY_TOGGLE_VISIBLE,
                              MOD_CTRL | MOD_ALT | MOD_NOREPEAT, VK_F9)
        user32.RegisterHotKey(None, HOTKEY_TOGGLE_CLICKTHROUGH,
                              MOD_CTRL | MOD_ALT | MOD_NOREPEAT, VK_F10)

        msg = ctypes.wintypes.MSG()
        while self._running:
            if user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1):
                if msg.message == WM_HOTKEY:
                    if msg.wParam == HOTKEY_TOGGLE_VISIBLE:
                        self.toggle_visible.emit()
                    elif msg.wParam == HOTKEY_TOGGLE_CLICKTHROUGH:
                        self.toggle_clickthrough.emit()
            else:
                # Don't busy-wait
                import time
                time.sleep(0.05)

        user32.UnregisterHotKey(None, HOTKEY_TOGGLE_VISIBLE)
        user32.UnregisterHotKey(None, HOTKEY_TOGGLE_CLICKTHROUGH)
