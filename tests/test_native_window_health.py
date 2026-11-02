"""Real owned Windows message queues exercise the cutoff without a game."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import subprocess
import sys
import queue
import threading
import time
import unittest

from native_window_health import NativeWindowDeadline, probe_native_window


def fixture(hung):
    api=C.WinDLL('user32',use_last_error=True)
    kernel=C.WinDLL('kernel32',use_last_error=True)
    proc=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
    api.DefWindowProcW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM]
    api.DefWindowProcW.restype=C.c_ssize_t
    @proc
    def callback(window,message,wparam,lparam):
        return api.DefWindowProcW(window,message,wparam,lparam)
    class WindowClass(C.Structure):
        _fields_=[('style',W.UINT),('callback',proc),('class_extra',C.c_int),('window_extra',C.c_int),
                  ('instance',W.HINSTANCE),('icon',W.HICON),('cursor',W.HANDLE),('background',W.HBRUSH),
                  ('menu',W.LPCWSTR),('name',W.LPCWSTR)]
    kernel.GetModuleHandleW.argtypes=[W.LPCWSTR];kernel.GetModuleHandleW.restype=W.HMODULE
    wc=WindowClass();wc.callback=callback;wc.instance=kernel.GetModuleHandleW(None);wc.name='Morrowind'
    api.RegisterClassW.argtypes=[C.POINTER(WindowClass)];api.RegisterClassW.restype=W.WORD
    if not api.RegisterClassW(C.byref(wc)):raise C.WinError(C.get_last_error())
    api.CreateWindowExW.argtypes=[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,
                                 W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
    api.CreateWindowExW.restype=W.HWND
    window=api.CreateWindowExW(0,'Morrowind','Owned hidden responsiveness fixture',0,0,0,100,100,None,None,wc.instance,None)
    if not window:raise C.WinError(C.get_last_error())
    print(json.dumps({'window':int(window)}),flush=True)
    if hung:time.sleep(30);return
    api.PeekMessageW.argtypes=[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT]
    api.DispatchMessageW.argtypes=[C.POINTER(W.MSG)];api.DispatchMessageW.restype=C.c_ssize_t
    message=W.MSG()
    while True:
        while api.PeekMessageW(C.byref(message),None,0,0,1):
            api.DispatchMessageW(C.byref(message))
        time.sleep(.001)


class NativeWindowTests(unittest.TestCase):
    def test_continuous_hang_required_and_recovery_resets_deadline(self):
        p=NativeWindowDeadline()
        bad=dict(window=12,responding=False)
        self.assertIsNone(p.poll(bad,1))
        self.assertIsNone(p.poll(bad,3.99))
        self.assertIsNone(p.poll(dict(window=12,responding=True),4))
        self.assertIsNone(p.poll(bad,5))
        self.assertEqual(p.poll(bad,8),'native_window_unresponsive')

    def test_missing_or_replaced_window_does_not_inherit_a_hang(self):
        p=NativeWindowDeadline()
        p.poll(dict(window=12,responding=False),1)
        self.assertIsNone(p.poll(dict(window=None,responding=None),20))
        self.assertIsNone(p.poll(dict(window=13,responding=False),30))
        self.assertIsNone(p.poll(dict(window=13,responding=False),32.9))
        self.assertEqual(p.poll(dict(window=13,responding=False),33),'native_window_unresponsive')

    def test_loading_grace_is_latched_but_cannot_renew_its_deadline(self):
        p=NativeWindowDeadline()
        bad=dict(window=12,responding=False,native_loading=True)
        self.assertIsNone(p.poll(bad,1))
        self.assertIsNone(p.poll(dict(bad,native_loading=False),6))
        self.assertIsNone(p.poll(bad,20.99))
        self.assertEqual(p.poll(bad,21),'native_window_unresponsive')

    def test_recovery_and_replacement_clear_loading_grace(self):
        for recovery in (dict(window=12,responding=True),dict(window=13,responding=False)):
            p=NativeWindowDeadline()
            p.poll(dict(window=12,responding=False,native_loading=True),1)
            self.assertIsNone(p.poll(recovery,6))
            bad=dict(window=recovery['window'],responding=False)
            self.assertIsNone(p.poll(bad,7))
            self.assertEqual(p.poll(bad,10),'native_window_unresponsive')

    def test_only_explicit_loading_boolean_grants_grace(self):
        for value in (None,False,1,'true'):
            p=NativeWindowDeadline()
            bad=dict(window=12,responding=False,native_loading=value)
            p.poll(bad,1)
            self.assertEqual(p.poll(bad,4),'native_window_unresponsive')

    def test_real_responsive_and_hung_owned_queues_and_pid_isolation(self):
        for hung in (False,True):
            child=subprocess.Popen([getattr(sys,'_base_executable',sys.executable),'-S',str(Path(__file__).resolve()),'--fixture',str(int(hung))],
                stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
            lines=queue.Queue()
            reader=threading.Thread(target=lambda:lines.put(child.stdout.readline()),daemon=True)
            reader.start()
            try:
                ready=json.loads(lines.get(timeout=5))
                began=time.monotonic()
                record=probe_native_window(child.pid)
                self.assertLess(time.monotonic()-began,1)
                self.assertEqual(record['window'],ready['window'])
                self.assertIs(record['responding'],not hung)
                self.assertFalse(record['foreground'])
                self.assertIsNone(probe_native_window(0)['responding'])
                self.assertIsNone(child.poll())
            finally:
                child.terminate();child.wait(3);reader.join(1);child.stdout.close();child.stderr.close()


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--fixture':fixture(bool(int(sys.argv[2])))
    else:unittest.main()
