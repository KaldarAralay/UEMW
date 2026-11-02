import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
import uuid
from unittest.mock import patch
import geometry_stream
from frame_transport import FrameStore,MAX_FRAME_BYTES,resolve
from scene_reader import scene_roots
from supported_scenes import supported,TRADEHOUSE,PRISON


class FrameTests(unittest.TestCase):
    def setUp(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=scratch);self.root=Path(self.tmp.name)
        self.folder=self.root/'local/bridge';self.folder.mkdir(parents=True)
        self.frames=FrameStore(self.folder)
        self.packet=dict(protocol='uemw.live',version=1,status='live',session=str(uuid.uuid4()),sequence=0,
            pid=42,sample_unix_ns=123,scene_epoch=str(uuid.uuid4()),geometry_version=1,read_ms=1,
            objects=[],instances=[dict(id='0x10000',asset='mesh',deformed=[0.1234]*150000)])
    def tearDown(self):self.tmp.cleanup()
    def publish(self,packet):
        with patch.object(geometry_stream,'ROOT',self.root):return geometry_stream.publish(packet,self.frames)
    def test_large_frame_is_committed_and_resolves_with_full_pose(self):
        original=copy.deepcopy(self.packet)
        self.assertGreater(self.publish(self.packet),0)
        self.assertEqual(self.packet['version'],2)
        self.assertLess((self.folder/'latest.json').stat().st_size,1024*1024)
        self.assertGreater(self.packet['frame_ref']['bytes'],1024*1024)
        self.assertEqual(resolve(self.packet,self.folder),original)
    def test_medium_geometry_keeps_watchdog_commit_small_and_preserves_full_pose(self):
        self.packet['instances'][0]['deformed']=[0.1234]*20000
        original=copy.deepcopy(self.packet)
        self.publish(self.packet)
        self.assertEqual(self.packet['version'],2)
        self.assertLess((self.folder/'latest.json').stat().st_size,4096)
        self.assertLess(self.packet['frame_ref']['bytes'],1024*1024)
        self.assertEqual(resolve(self.packet,self.folder),original)
    def test_bad_paths_lengths_digests_and_mixed_identities_fail_closed(self):
        self.publish(self.packet)
        for failure in ('path','length','digest','identity'):
            manifest=copy.deepcopy(self.packet)
            if failure=='path':manifest['frame_ref']['file']='../latest.json'
            elif failure=='length':manifest['frame_ref']['bytes']+=1
            elif failure=='digest':manifest['frame_ref']['md5']='0'*32
            else:
                p=self.folder/manifest['frame_ref']['file'];body=json.loads(p.read_bytes());body['pid']=99
                raw=json.dumps(body,separators=(',',':')).encode();p.write_bytes(raw)
                manifest['frame_ref'].update(bytes=len(raw),md5=hashlib.md5(raw).hexdigest())
            with self.subTest(failure=failure),self.assertRaises(ValueError):resolve(manifest,self.folder)
    def test_history_and_failed_commits_do_not_accumulate_bodies(self):
        for sequence in range(14):
            value={**self.packet,'sequence':sequence};self.publish(value)
        self.assertLessEqual(len(list(self.frames.folder.glob('frame-*.json'))),8)
        self.assertLessEqual(len(self.frames.history),8)
        failed={**self.packet,'sequence':15}
        with patch.object(geometry_stream,'write_latest',side_effect=[ValueError('large'),0]):
            self.assertEqual(geometry_stream.publish(failed,self.frames),0)
        self.assertLessEqual(len(list(self.frames.folder.glob('frame-*.json'))),8)
    def test_oversize_body_falls_back_and_next_frame_recovers(self):
        bad={**self.packet,'instances':['x'*(MAX_FRAME_BYTES+1)]}
        self.publish(bad);self.assertEqual(bad['status'],'unavailable')
        self.assertFalse(list(self.frames.folder.iterdir()))
        self.publish(self.packet);self.assertEqual(resolve(self.packet,self.folder)['status'],'live')
    def test_new_session_retires_only_generated_previous_bodies(self):
        self.publish(copy.deepcopy(self.packet))
        (self.frames.folder/'user-notes.json').write_text('{}')
        newer=FrameStore(self.folder);packet={**self.packet,'session':str(uuid.uuid4())}
        with patch.object(geometry_stream,'ROOT',self.root):geometry_stream.publish(packet,newer)
        self.assertEqual(len(list(newer.folder.glob('frame-*.json'))),1)
        self.assertTrue((newer.folder/'user-notes.json').exists())

    def test_reconnect_preserves_the_committed_body_until_new_commit(self):
        old=copy.deepcopy(self.packet);self.publish(old)
        newer=FrameStore(self.folder);packet={**self.packet,'session':str(uuid.uuid4())}
        with patch.object(geometry_stream,'ROOT',self.root),patch.object(geometry_stream,'write_latest',side_effect=[ValueError('large'),0]):
            self.assertEqual(geometry_stream.publish(packet,newer),0)
        self.assertEqual(resolve(old,self.folder)['session'],self.packet['session'])

    def test_held_retired_files_hit_a_fixed_bound_then_fail_softly(self):
        with patch.object(self.frames,'remove'):
            for sequence in range(22):
                packet={**self.packet,'sequence':sequence};self.publish(packet)
            self.assertLessEqual(len(list(self.frames.folder.glob('frame-*.json'))),16)
            self.assertEqual(packet['status'],'unavailable')


class ExteriorScopeTests(unittest.TestCase):
    def test_scope_requires_the_exact_exterior_grid(self):
        self.assertTrue(supported(dict(cell='Seyda Neen',cell_flags=126,cell_grid=[-2,-9])))
        self.assertTrue(supported(dict(cell='Seyda Neen',cell_flags=126,cell_grid=[-2,-10])))
        self.assertFalse(supported(dict(cell='Seyda Neen',cell_flags=1,cell_grid=[-2,-9])))
        for name in (TRADEHOUSE,PRISON):self.assertTrue(supported(dict(cell=name,cell_flags=1)))
    def test_exterior_uses_the_active_cells_real_landscape_root(self):
        class Memory:
            def read(self,address,count):
                self_test.assertEqual((address,count),(0x10014,0x1c))
                raw=bytearray(count);struct.pack_into('<I',raw,0,0x20000);struct.pack_into('<I',raw,0xc,0x40000);struct.pack_into('<I',raw,0x18,0x30000);return raw
            def u32(self,address):
                self_test.assertEqual(address,0x40010);return 0x50000
        self_test=self
        self.assertEqual(scene_roots(Memory(),0x10000),[0x20000,0x30000,0x50000])

if __name__=='__main__':unittest.main()
