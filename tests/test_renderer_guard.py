import unittest
import ctypes as C
import hashlib
from pathlib import Path
import subprocess
import sys
from renderer_guard import HeartbeatDeadline,source_stop_matches,renderer_stop_matches,open_exact,K


class RendererGuardTests(unittest.TestCase):
    def test_explicit_view_stop_rejects_old_guard_tokens_and_other_processes(self):
        record=dict(protocol='uemw.renderer-stop',version=1,run_token='fresh',game_pid=12,renderer_pid=23)
        self.assertTrue(renderer_stop_matches(record,'fresh',12,23))
        for key,value in (('run_token','old'),('game_pid',13),('renderer_pid',24),('version',2)):
            self.assertFalse(renderer_stop_matches({**record,key:value},'fresh',12,23))
    def heartbeat(self,stamp=1e9,**changes):
        return dict(version=1,renderer_pid=23,pid=12,unix_ns=stamp,**changes)
    def test_deadline_uses_monotonic_time_and_recovers_from_a_short_hitch(self):
        p=HeartbeatDeadline(0,23,12)
        self.assertIsNone(p.poll(self.heartbeat(),1,1e9))
        self.assertIsNone(p.poll({},3.9,4e9))
        self.assertIsNone(p.poll(self.heartbeat(4e9),3.99,4e9))
        self.assertEqual(p.poll({},7,8e9),'renderer_heartbeat_timeout')
    def test_repeated_forged_future_stale_or_wrong_identity_cannot_renew(self):
        for field,value in (('renderer_pid',24),('pid',13),('version',2),('unix_ns',20e9),('unix_ns',0),('unix_ns',float('nan'))):
            p=HeartbeatDeadline(0,23,12)
            self.assertIsNone(p.poll(self.heartbeat(),1,1e9))
            bad=self.heartbeat(4e9);bad[field]=value
            self.assertEqual(p.poll(bad,4,4e9),'renderer_heartbeat_timeout')
        p=HeartbeatDeadline(0,23,12);p.poll(self.heartbeat(),1,1e9)
        self.assertEqual(p.poll(self.heartbeat(),4,1e9),'renderer_heartbeat_timeout')
    def test_bootstrap_pid_zero_is_allowed_without_requiring_loaded_gameplay(self):
        p=HeartbeatDeadline(0,23,12)
        h=self.heartbeat();h['pid']=0
        self.assertIsNone(p.poll(h,1,1e9));self.assertEqual(p.last,1)
        self.assertEqual(HeartbeatDeadline(0,23,12).poll({},45,45e9),'renderer_startup_timeout')
    def test_source_stop_is_bound_to_current_game_and_unique_bridge_session(self):
        stop=dict(protocol='uemw.source-stop',version=1,session='current',game_pid=12)
        self.assertTrue(source_stop_matches(stop,'current',12))
        for key,value in (('session','old'),('game_pid',13),('protocol','wrong'),('version',2)):
            self.assertFalse(source_stop_matches({**stop,key:value},'current',12))
        self.assertFalse(source_stop_matches(None,'current',12))
    def test_held_handle_rejects_other_path_and_hash_then_stops_only_owned_child(self):
        executable=Path(sys.executable).resolve();digest=hashlib.sha256(executable.read_bytes()).hexdigest()
        child=subprocess.Popen([str(executable),'-c','import time; time.sleep(20)'],creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with self.assertRaisesRegex(RuntimeError,'path'):
                open_exact(child.pid,executable.with_name('different.exe'),digest,True)
            with self.assertRaisesRegex(RuntimeError,'hash'):
                open_exact(child.pid,executable,'0'*64,True)
            self.assertIsNone(child.poll())
            handle=open_exact(child.pid,executable,digest,True)
            try:self.assertTrue(K.TerminateProcess(handle,0))
            finally:K.CloseHandle(handle)
            self.assertEqual(child.wait(3),0)
        finally:
            if child.poll() is None:child.terminate();child.wait(3)

    def test_exited_held_process_reports_exit_code_before_querying_image(self):
        executable=Path(sys.executable).resolve();digest=hashlib.sha256(executable.read_bytes()).hexdigest()
        child=subprocess.Popen([str(executable),'-c','import time;time.sleep(.1);raise SystemExit(7)'],creationflags=subprocess.CREATE_NO_WINDOW)
        held=K.OpenProcess(0x1000|0x100000,False,child.pid)
        self.assertTrue(held)
        try:
            self.assertEqual(child.wait(3),7)
            with self.assertRaisesRegex(RuntimeError,'exited with code 0x00000007'):
                open_exact(child.pid,executable,digest)
        finally:K.CloseHandle(held)


if __name__=='__main__':unittest.main()
