"""Exercise the actual Windows deny-delete failure that stopped the producer."""
import ctypes as C
from ctypes import wintypes as W
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import geometry_stream

class PublicationTest(unittest.TestCase):
    def test_transient_reader_lock_preserves_old_packet_and_recovers(self):
        kernel=C.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
        kernel.CreateFileW.restype=W.HANDLE
        kernel.CloseHandle.argtypes=[W.HANDLE]
        workspace=Path(__file__).resolve().parents[1]
        temporary=(workspace/'local/test-temp').resolve()
        self.assertTrue(temporary.is_relative_to(workspace))
        temporary.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary)as tmp:
            root=Path(tmp);folder=root/'local/bridge';folder.mkdir(parents=True)
            self.assertTrue(root.resolve().is_relative_to(temporary))
            latest=folder/'latest.json';latest.write_text('{"sequence":1}')
            handle=kernel.CreateFileW(str(latest),0x80000000,1,None,3,0,None)
            self.assertNotEqual(handle,C.c_void_p(-1).value)
            with patch.object(geometry_stream,'ROOT',root):
                try:
                    self.assertEqual(geometry_stream.write_latest({'sequence':2}),0)
                    self.assertEqual(json.loads(latest.read_text())['sequence'],1)
                finally:kernel.CloseHandle(handle)
                self.assertGreater(geometry_stream.write_latest({'sequence':3}),0)
                self.assertEqual(json.loads(latest.read_text())['sequence'],3)

if __name__=='__main__':unittest.main()
