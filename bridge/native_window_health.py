"""Bounded WM_NULL responsiveness probes; no input or native-game writes."""
import ctypes as C
from ctypes import wintypes as W
import time

U = C.WinDLL('user32', use_last_error=True)
CALLBACK = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
U.EnumWindows.argtypes = [CALLBACK, W.LPARAM]
U.EnumWindows.restype = W.BOOL
U.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
U.GetWindowThreadProcessId.restype = W.DWORD
U.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
U.GetClassNameW.restype = C.c_int
U.GetForegroundWindow.restype = W.HWND
U.SendMessageTimeoutW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM,
                                W.UINT, W.UINT, C.POINTER(C.c_size_t)]
U.SendMessageTimeoutW.restype = C.c_ssize_t


def window_owner(window):
    pid = W.DWORD()
    U.GetWindowThreadProcessId(window, C.byref(pid))
    return pid.value


def probe_native_window(pid, timeout_ms=100):
    """Probe only a top-level Morrowind-class HWND belonging to the held PID.

    The caller retains the verified process handle throughout this operation.
    WM_NULL has no gameplay/UI action. A missing or ambiguous HWND is unknown,
    not evidence of a hung native window.
    """
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= 250:
        raise ValueError('Window probe timeout must be 1..250 ms')
    windows = []
    @CALLBACK
    def visit(window, unused):
        if window_owner(window) == pid:
            name = C.create_unicode_buffer(256)
            if U.GetClassNameW(window, name, len(name)) and name.value == 'Morrowind':
                windows.append(int(window))
        return True
    if not U.EnumWindows(visit, 0):
        raise C.WinError(C.get_last_error())
    if len(windows) != 1:
        return dict(window=None, responding=None, foreground=False, probe_ms=0.)
    window = windows[0]
    if window_owner(window) != pid:
        return dict(window=None, responding=None, foreground=False, probe_ms=0.)
    result = C.c_size_t()
    began = time.monotonic()
    # SMTO_BLOCK | SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT. Never use
    # SMTO_NOTIMEOUTIFNOTHUNG: that can extend an apparently bounded wait.
    responding = bool(U.SendMessageTimeoutW(window, 0, 0, 0, 0x23, timeout_ms, C.byref(result)))
    if window_owner(window) != pid:
        return dict(window=None, responding=None, foreground=False, probe_ms=0.)
    return dict(window=window, responding=responding,
                foreground=U.GetForegroundWindow() == window,
                probe_ms=round((time.monotonic()-began)*1000, 3))


class NativeWindowDeadline:
    """Bound a hung HWND, allowing one longer native-loading episode.

    Loading is read from the original MenuLoading, independently of the scene.
    A loading flag can extend this episode's deadline once, never renew it.
    """
    def __init__(self, timeout=3, loading_timeout=20):
        self.timeout = timeout
        self.loading_timeout = loading_timeout
        self.window = None
        self.failed_since = None
        self.loading_seen = False

    def poll(self, record, now):
        window = record.get('window')
        responding = record.get('responding')
        if window != self.window or responding is not False:
            self.window = window
            self.failed_since = None
            self.loading_seen = False
        if window and responding is False:
            if self.failed_since is None:
                self.failed_since = now
            if record.get('native_loading') is True:
                self.loading_seen = True
            timeout = self.loading_timeout if self.loading_seen else self.timeout
            if now-self.failed_since >= timeout:
                return 'native_window_unresponsive'
        return None
