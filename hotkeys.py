"""Global hotkeys using Windows RegisterHotKey API."""
import time
import ctypes
import ctypes.wintypes
from PyQt5.QtCore import QThread, pyqtSignal

# Virtual key codes
VK_F9 = 0x78
VK_F10 = 0x79
VK_LEFT = 0x25
VK_RIGHT = 0x27
VK_0 = 0x30

MOD_CTRL = 0x0002
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312

HK_TOGGLE_VISIBLE = 1
HK_TOGGLE_CLICKTHROUGH = 2
HK_OFFSET_DOWN = 3
HK_OFFSET_UP = 4
HK_OFFSET_RESET = 5


class HotkeyListener(QThread):
    toggle_visible = pyqtSignal()
    toggle_clickthrough = pyqtSignal()
    offset_changed = pyqtSignal(int)  # delta in ms (0 = reset)

    def __init__(self):
        super().__init__()
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        user32 = ctypes.windll.user32

        modifiers = MOD_CTRL | MOD_ALT | MOD_NOREPEAT

        # Ctrl+Alt+F9  = toggle visibility
        # Ctrl+Alt+F10 = toggle click-through
        # Ctrl+Alt+Left  = sync offset -100ms (lyrics later)
        # Ctrl+Alt+Right = sync offset +100ms (lyrics earlier)
        # Ctrl+Alt+0 = reset sync offset
        user32.RegisterHotKey(None, HK_TOGGLE_VISIBLE, modifiers, VK_F9)
        user32.RegisterHotKey(None, HK_TOGGLE_CLICKTHROUGH, modifiers, VK_F10)
        user32.RegisterHotKey(None, HK_OFFSET_DOWN, modifiers, VK_LEFT)
        user32.RegisterHotKey(None, HK_OFFSET_UP, modifiers, VK_RIGHT)
        user32.RegisterHotKey(None, HK_OFFSET_RESET, modifiers, VK_0)

        msg = ctypes.wintypes.MSG()
        while self._running:
            if user32.PeekMessageW(ctypes.byref(msg), None, WM_HOTKEY, WM_HOTKEY, 1):
                if msg.message == WM_HOTKEY:
                    hk_id = msg.wParam
                    if hk_id == HK_TOGGLE_VISIBLE:
                        self.toggle_visible.emit()
                    elif hk_id == HK_TOGGLE_CLICKTHROUGH:
                        self.toggle_clickthrough.emit()
                    elif hk_id == HK_OFFSET_DOWN:
                        self.offset_changed.emit(-100)
                    elif hk_id == HK_OFFSET_UP:
                        self.offset_changed.emit(100)
                    elif hk_id == HK_OFFSET_RESET:
                        self.offset_changed.emit(0)  # 0 = reset
            else:
                time.sleep(0.05)

        for hk in (HK_TOGGLE_VISIBLE, HK_TOGGLE_CLICKTHROUGH,
                    HK_OFFSET_DOWN, HK_OFFSET_UP, HK_OFFSET_RESET):
            user32.UnregisterHotKey(None, hk)
