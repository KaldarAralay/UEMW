import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import numpy as np
import check_native_motion as probe
from live_binary import encode
from frame_transport import FrameStore


class MotionProofTests(unittest.TestCase):
    def test_falling_without_horizontal_travel_cannot_count_as_walking(self):
        self.assertEqual(probe.planar_motion([[0,0,100],[0,0,-1000]]),0)
        self.assertEqual(probe.planar_motion([[0,0,100],[30,40,-1000]]),50)
    def test_rigid_actor_turn_and_translation_cannot_count_as_bone_articulation(self):
        palette=np.asarray([np.eye(4)[:3],np.eye(4)[:3]],dtype='<f4')
        moved=palette.copy();rotation=np.asarray([[0,-1,0],[1,0,0],[0,0,1]])
        moved[:,:,:3]=rotation@palette[:,:,:3];moved[:,:,3]=[1000,2000,-500]
        np.testing.assert_allclose(probe.relative_rotations(palette),probe.relative_rotations(moved),atol=1e-6)
        moved[1,:,:3]=np.eye(3)
        self.assertGreater(np.max(np.abs(probe.relative_rotations(palette)-probe.relative_rotations(moved))),.01)

    def fixture(self,root):
        packet=dict(protocol='uemw.live',version=1,status='live',session=str(uuid.uuid4()),scene_epoch=str(uuid.uuid4()),sequence=12,
            sample_unix_ns=1793516400123456789,pid=42,geometry_version=5,instance_states=[[True,[1,0,0,0,1,0,0,0,1,0,0,0,1]]])
        store=FrameStore(root/'local/bridge');manifest,name=store.prepare(packet,encode(packet),True);store.commit(name)
        return manifest,root/'local/bridge'/manifest['frame_ref']['file']

    def test_witness_resolves_only_its_exact_immutable_source_identity(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as temporary:
            root=Path(temporary);manifest,path=self.fixture(root)
            with patch.object(probe,'ROOT',root):
                decoded,digest=probe.source_frame(manifest)
                self.assertEqual(decoded['sequence'],12);self.assertEqual(digest,manifest['frame_ref']['md5'])
                for key,value in (('session',str(uuid.uuid4())),('scene_epoch',str(uuid.uuid4())),('pid',43),('sequence',13),('sample_unix_ns',manifest['sample_unix_ns']+4096)):
                    with self.subTest(key=key),self.assertRaises(ValueError):probe.source_frame({**manifest,key:value})

    def test_witness_rejects_body_corruption_even_when_it_would_be_numeric(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as temporary:
            root=Path(temporary);manifest,path=self.fixture(root);body=bytearray(path.read_bytes());body[-1]^=1;path.write_bytes(body)
            with patch.object(probe,'ROOT',root),self.assertRaisesRegex(ValueError,'digest'):probe.source_frame(manifest)

    def test_witness_rejects_oversized_or_escaping_body_references(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as temporary:
            root=Path(temporary);manifest,path=self.fixture(root)
            for changes in ({'bytes':4*1024*1024+1},{'file':'../outside.bin'},{'md5':'0'*32}):
                bad=copy.deepcopy(manifest);bad['frame_ref'].update(changes)
                with patch.object(probe,'ROOT',root),self.assertRaises(ValueError):probe.source_frame(bad)


if __name__=='__main__':unittest.main()
