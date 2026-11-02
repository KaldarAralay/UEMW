import math
import json
import tempfile
import uuid
from pathlib import Path
import struct
import unittest
from unittest.mock import patch
from camera_lane import capture,committed_base
from live_probe import ROOT

class Memory:
    def __init__(self):
        self.header=bytearray(0x17c);self.camera=bytearray(0x128)
        struct.pack_into('<I',self.header,0x134,0x30000);struct.pack_into('<I',self.header,0x24,99)
        struct.pack_into('<f',self.header,0x13c,75)
        struct.pack_into('<13f',self.camera,0x40,1,0,0,0,1,0,0,0,1,123,456,789,1)
        struct.pack_into('<3f',self.camera,0xdc,0,1,0);struct.pack_into('<3f',self.camera,0xe8,0,0,1)
        self.values={0x7c67dc:0x10000,0x7c67e0:0x20000,0x2b540:0x40000}
    def check_alive(self):pass
    def u32(self,p):return self.values[p]
    def read(self,p,n):return self.header if p==0x10000 else self.camera
    def player_render_state(self,world):return dict(reference='0x50000',first_person=True)

class CameraLaneTests(unittest.TestCase):
    def setUp(self):
        self.r=Memory();self.base=dict(world='0x10000',data='0x20000',cell_ptr='0x40000',camera_ptr='0x30000',player_ref='0x50000',first_person_active=True)
    @patch('camera_lane.loading_state',return_value=(False,0))
    def test_camera_is_copied_directly_from_native_memory(self,unused):
        camera,frame=capture(self.r,self.base)
        self.assertEqual(camera['position'],(123.,456.,789.));self.assertEqual(camera['forward'],(0.,1.,0.));self.assertEqual(frame,99)
    @patch('camera_lane.loading_state',return_value=(False,0))
    def test_changed_cell_camera_and_pass_fail_closed(self,unused):
        for key,value in [('cell_ptr','0x60000'),('camera_ptr','0x60000'),('player_ref','0x60000'),('first_person_active',False)]:
            with self.subTest(key=key),self.assertRaises(ValueError):capture(self.r,{**self.base,key:value})
        struct.pack_into('<f',self.r.camera,0x40,float('nan'))
        with self.assertRaises(ValueError):capture(self.r,self.base)
    @patch('camera_lane.loading_state',return_value=(True,1))
    def test_loading_never_updates_the_last_scene_camera(self,unused):
        with self.assertRaises(ValueError):capture(self.r,self.base)
    def test_only_fresh_committed_matching_source_can_drive_the_camera_child(self):
        session=str(uuid.uuid4());now=1_000_000_000
        packet={**self.base,'protocol':'uemw.live','version':3,'status':'live','session':session,'pid':42,
            'scene_epoch':str(uuid.uuid4()),'sequence':7,'sample_unix_ns':now-10_000_000}
        folder=ROOT/'local/test-temp';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder)as tmp:
            path=Path(tmp)/'latest.json';path.write_text(json.dumps(packet))
            self.assertEqual(committed_base(path,42,session,now)['sequence'],7)
            path.write_text(json.dumps({**packet,'version':4,'state_metadata_version':1}))
            self.assertEqual(committed_base(path,42,session,now)['sequence'],7)
            path.write_text(json.dumps({**packet,'version':4,'state_metadata_version':2}))
            with self.assertRaises(ValueError):committed_base(path,42,session,now)
            invalid=[{'status':'preparing_scene'},{'status':'unavailable'},{'session':str(uuid.uuid4())},{'pid':43},
                {'sample_unix_ns':now-400_000_000},{'sample_unix_ns':now+1},{'sequence':1.5}]
            for change in invalid:
                path.write_text(json.dumps({**packet,**change}))
                with self.subTest(change=change),self.assertRaises(ValueError):committed_base(path,42,session,now)
            path.write_bytes(b' '*(1024*1024+1))
            with self.assertRaises(ValueError):committed_base(path,42,session,now)

if __name__=='__main__':unittest.main()
