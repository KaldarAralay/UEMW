"""Contract tests for exit-code handling; no real process is opened or controlled."""
import ctypes as C
from ctypes import wintypes as W
import unittest
from unittest.mock import patch
import live_probe

class ExitApi:
    def __init__(self,code):self.code=code
    def GetExitCodeProcess(self,handle,out):
        C.cast(out,C.POINTER(W.DWORD))[0]=self.code
        return True

class LivenessTests(unittest.TestCase):
    def reader(self):
        reader=live_probe.Reader.__new__(live_probe.Reader);reader.handle=123;reader.pid=456;return reader
    def test_active_handle_is_accepted(self):
        with patch.object(live_probe,'K',ExitApi(259)):self.reader().check_alive()
    def test_crash_code_is_preserved(self):
        with patch.object(live_probe,'K',ExitApi(0xc0000005)):
            with self.assertRaisesRegex(RuntimeError,'456 exited with code 0xc0000005'):self.reader().check_alive()
    def test_clean_exit_is_not_live(self):
        with patch.object(live_probe,'K',ExitApi(0)):
            with self.assertRaisesRegex(RuntimeError,'exited with code 0x00000000'):self.reader().check_alive()

if __name__=='__main__':unittest.main()
