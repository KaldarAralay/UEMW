"""Scratch reuse cannot alias returned bytes or concurrent reader threads."""
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from unittest.mock import patch
from live_probe import Reader


class BuffersTests(unittest.TestCase):
    def reader(self):r=Reader.__new__(Reader);r.handle=123;r._scratch=threading.local();return r

    def test_reused_buffer_returns_exact_independent_byte_strings(self):
        addresses=[]
        class Api:
            def ReadProcessMemory(self,handle,source,buffer,count,out):
                addresses.append(C.addressof(buffer));C.memmove(buffer,bytes([source&255])*count,count)
                C.cast(out,C.POINTER(C.c_size_t))[0]=count;return True
        r=self.reader()
        with patch('live_probe.K',Api()):
            first=r.read(0x10001,172);second=r.read(0x10002,4);third=r.read(0x10003,172)
        self.assertEqual(len(set(addresses)),1);self.assertEqual(first,bytes([1])*172)
        self.assertEqual(second,bytes([2])*4);self.assertEqual(third,bytes([3])*172)

    def test_concurrent_calls_use_different_buffers(self):
        gate=threading.Barrier(2);addresses=[]
        class Api:
            def ReadProcessMemory(self,handle,source,buffer,count,out):
                addresses.append(C.addressof(buffer));C.memmove(buffer,bytes([source&255])*count,count)
                gate.wait(timeout=2);C.cast(out,C.POINTER(C.c_size_t))[0]=count;return True
        r=self.reader()
        with patch('live_probe.K',Api()),ThreadPoolExecutor(max_workers=2)as pool:
            a=pool.submit(r.read,0x10001,172);b=pool.submit(r.read,0x10002,172)
            self.assertEqual(a.result(timeout=3),bytes([1])*172);self.assertEqual(b.result(timeout=3),bytes([2])*172)
        self.assertEqual(len(set(addresses)),2)


if __name__=='__main__':unittest.main()
