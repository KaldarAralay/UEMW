"""Integration tests of the x86 launcher on its separate disposable test EXE."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import struct
import subprocess
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
HELPER=ROOT/'local/bin/watchdog-test.exe'
TARGET=ROOT/'local/diagnostics-tests/crash-target.exe'

@unittest.skipUnless(HELPER.is_file() and TARGET.is_file(),'Build diagnostics with -IncludeTests first')
class CrashCaptureTests(unittest.TestCase):
    def setUp(self):self.old_folders=set((ROOT/'local/crashes').glob('*'))
    def launch(self,mode):
        return subprocess.Popen([str(HELPER),mode],cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)

    def events(self,process):
        folders=[p for p in (ROOT/'local/crashes').glob(f'*-{process.pid}')if p not in self.old_folders]
        self.assertEqual(len(folders),1)
        return folders[0],[json.loads(line) for line in (folders[0]/'events.jsonl').read_text().splitlines()]

    def test_handled_exception_reaches_original_handler(self):
        process=self.launch('--handled')
        self.assertEqual(process.wait(timeout=10),17)
        folder,events=self.events(process)
        self.assertFalse((folder/'crash.dmp').exists())
        self.assertFalse(any(event['event']=='unhandled_exception' for event in events))
        self.assertEqual(events[-1]['exit_code'],'0x11')

    def test_unhandled_access_violation_has_x86_exception_context(self):
        process=self.launch('--crash');process.wait(timeout=15)
        folder,events=self.events(process)
        crash=next(event for event in events if event['event']=='unhandled_exception')
        self.assertEqual(crash['code'],'0xc0000005')
        self.assertTrue(crash['dump_written']);self.assertTrue(crash['context_captured'])
        dump=(folder/'crash.dmp').read_bytes()
        self.assertEqual(dump[:4],b'MDMP')
        count,directory=struct.unpack_from('<II',dump,8)
        streams={}
        for i in range(count):
            kind,size,offset=struct.unpack_from('<III',dump,directory+i*12)
            streams[kind]=(offset,size)
        self.assertEqual(struct.unpack_from('<H',dump,streams[7][0])[0],0) # PROCESSOR_ARCHITECTURE_INTEL
        offset=streams[6][0]
        self.assertEqual(struct.unpack_from('<I',dump,offset+8)[0],0xc0000005)
        address=struct.unpack_from('<Q',dump,offset+24)[0]
        size,context=struct.unpack_from('<II',dump,offset+160)
        self.assertGreaterEqual(size,204)
        self.assertEqual(struct.unpack_from('<I',dump,context+184)[0],address)

    def test_attach_to_running_test_process_and_capture_its_exit(self):
        target=subprocess.Popen([str(TARGET),'--wait'],creationflags=subprocess.CREATE_NO_WINDOW)
        helper=subprocess.Popen([str(HELPER),'--attach',str(target.pid)],creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            attached=False
            for _ in range(100):
                folders=[p for p in (ROOT/'local/crashes').glob(f'*-{helper.pid}')if p not in self.old_folders]
                # The helper creates its session directory before opening the
                # event log. Observe both steps instead of racing file creation.
                if folders:
                    try:started='"event":"started"' in (folders[0]/'events.jsonl').read_text()
                    except FileNotFoundError:started=False
                    if started:attached=True;break
                time.sleep(.02)
            self.assertTrue(attached)
            target.terminate();target.wait(timeout=5)
            helper.wait(timeout=5)
            self.assertEqual(self.events(helper)[1][-1]['event'],'exited')
        finally:
            if target.poll() is None:target.terminate();target.wait(timeout=5)
            if helper.poll() is None:helper.terminate();helper.wait(timeout=5)

    def test_stopping_watchdog_leaves_its_test_child_alive(self):
        pid_file=ROOT/'local/diagnostics-tests/child.pid'
        previous=pid_file.read_text() if pid_file.exists() else ''
        process=self.launch('--wait')
        try:
            for _ in range(100):
                if pid_file.exists() and pid_file.read_text()!=previous:break
                time.sleep(.02)
            child=int(pid_file.read_text())
            kernel=C.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
            kernel.QueryFullProcessImageNameW.argtypes=[W.HANDLE,W.DWORD,W.LPWSTR,C.POINTER(W.DWORD)]
            kernel.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)]
            kernel.TerminateProcess.argtypes=[W.HANDLE,W.UINT];kernel.CloseHandle.argtypes=[W.HANDLE]
            handle=kernel.OpenProcess(0x0400|0x0001,False,child)
            self.assertTrue(handle)
            try:
                path=C.create_unicode_buffer(32768);size=W.DWORD(len(path))
                self.assertTrue(kernel.QueryFullProcessImageNameW(handle,0,path,C.byref(size)))
                self.assertEqual(Path(path.value).resolve(),TARGET.resolve()) # never stop a game or arbitrary PID
                process.terminate();process.wait(timeout=5);time.sleep(.1)
                code=W.DWORD();self.assertTrue(kernel.GetExitCodeProcess(handle,C.byref(code)))
                self.assertEqual(code.value,259)
                kernel.TerminateProcess(handle,0)
            finally:kernel.CloseHandle(handle)
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=5)

if __name__=='__main__':unittest.main()
