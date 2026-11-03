"""Regression checks for actual failure modes, without controlling the game."""
import ctypes as C
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import geometry_stream as stream
import input_backend as inputs
from skin_math import Skin


class PacketTests(unittest.TestCase):
    def test_oversize_and_nonfinite_packets_publish_unavailable_and_recover(self):
        workspace=Path(__file__).resolve().parents[1]
        scratch=workspace/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            root=Path(directory);(root/'local/bridge').mkdir(parents=True)
            envelope=dict(protocol='uemw.live',version=1,session='test',sequence=4,sample_unix_ns=123,pid=456,status='live',read_ms=5)
            with patch.object(stream,'ROOT',root):
                for extra in ({'instances':['x'*(stream.MAX_PACKET_BYTES+1)]},{'instances':[float('nan')]}):
                    packet={**envelope,**extra}
                    self.assertGreater(stream.publish(packet),0)
                    failed=json.loads((root/'local/bridge/latest.json').read_text())
                    self.assertEqual(failed['status'],'unavailable')
                    self.assertEqual(failed['sequence'],4)
                    self.assertNotIn('instances',failed)
                self.assertGreater(stream.publish({**envelope,'sequence':5,'instances':[]}),0)
                self.assertEqual(json.loads((root/'local/bridge/latest.json').read_text())['status'],'live')


class PoseTests(unittest.TestCase):
    def test_classification_cannot_invalidate_already_owned_node_capture(self):
        class R:
            attempts=0;frame=100
            def camera_sample(self):self.attempts+=1;return dict(world='0x10000',data='0x20000',cell_ptr='0x30000',frame_ms=100)
            def read(self,p,n):return bytes(n)
            def u32(self,p):return self.frame if p==0x10024 else 0x10000 if p==0x7c67dc else 0x30000
        g=stream.Geometry.__new__(stream.Geometry);g.r=R();g.cell='0x30000';g.shapes=[dict(id='0x40000',parents=())];g.skins={};g.light_pointers=[];g.light_owners={};g.material_flips={};g.material_values={};g.native_attributes={}
        g.records=[(0x40000,(0,0),(0x40000,),None,None)];g.pose_layout=stream.PoseLayout(g.records)
        original=stream.PoseFrame
        class Classify(original):
            def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);g.r.frame=101
        with patch.object(stream,'PoseFrame',Classify),patch.object(stream,'capture_environment',return_value={}):
            *_,metrics=g.capture_pose(dict(world='0x10000',data='0x20000',cell_ptr='0x30000'))
        self.assertEqual(g.r.attempts,1);self.assertFalse(metrics['nodes_spanned_frames']);self.assertTrue(metrics['pose_spanned_frames'])
        self.assertEqual(metrics['nodes_frame_ms_end'],100);self.assertEqual(metrics['pose_frame_ms_end'],101)

    def test_metadata_frame_advance_does_not_recapture_a_completed_pose(self):
        class R:
            attempts=0;frame=100
            def camera_sample(self):self.attempts+=1;return dict(world='0x10000',data='0x20000',cell_ptr='0x30000',frame_ms=100)
            def read(self,p,n):return bytes(n)
            def u32(self,p):return self.frame if p==0x10024 else 0x10000 if p==0x7c67dc else 0x30000
        g=stream.Geometry.__new__(stream.Geometry);g.r=R();g.cell='0x30000';g.shapes=[dict(id='0x40000',parents=())];g.skins={};g.light_pointers=[];g.light_owners={};g.material_flips={};g.material_values={};g.native_attributes={}
        g.records=[(0x40000,(0,0),(0x40000,),None,None)];g.pose_layout=stream.PoseLayout(g.records)
        def environment(*args):g.r.frame=101;return {}
        with patch.object(stream,'capture_environment',side_effect=environment):
            anchor,raw,particles,attributes,metrics=g.capture_pose(dict(world='0x10000',data='0x20000',cell_ptr='0x30000'))
        self.assertEqual(g.r.attempts,1);self.assertFalse(metrics['pose_spanned_frames']);self.assertTrue(metrics['sample_spanned_frames'])
        self.assertEqual(metrics['pose_frame_ms_end'],100);self.assertEqual(metrics['source_frame_ms_end'],101)

    def test_slow_spanned_capture_is_not_repeated_as_a_false_atomicity_fix(self):
        clock=[0.]
        class R:
            attempts=0
            def camera_sample(self):self.attempts+=1;return dict(world='0x10000',data='0x20000',cell_ptr='0x30000',frame_ms=100)
            def read(self,p,n):clock[0]+=.02;return bytes(n)
            def u32(self,p):return 101 if p==0x10024 else 0x10000 if p==0x7c67dc else 0x30000
        g=stream.Geometry.__new__(stream.Geometry);g.r=R();g.cell='0x30000';g.shapes=[dict(id='0x40000',parents=())];g.skins={};g.light_pointers=[];g.light_owners={};g.material_flips={};g.material_values={};g.native_attributes={}
        g.records=[(0x40000,(0,0),(0x40000,),None,None)];g.pose_layout=stream.PoseLayout(g.records)
        with patch.object(stream,'capture_environment',return_value={}),patch.object(stream.time,'perf_counter',side_effect=lambda:clock[0]):
            anchor,raw,particles,attributes,metrics=g.capture_pose(dict(world='0x10000',data='0x20000',cell_ptr='0x30000'))
        self.assertEqual(g.r.attempts,1);self.assertTrue(metrics['sample_spanned_frames']);self.assertTrue(metrics['retry_skipped_for_budget'])
        self.assertEqual(metrics['pose_attempts'],1);self.assertEqual(set(raw),{0x40000})

    def test_hidden_particle_capacity_never_reads_or_consumes_the_visible_budget(self):
        camera=dict(position=[0,0,0],forward=[0,1,0],up=[0,0,1],frustum=[-1,1,1,-1,1,100],fov=90)
        class FakeReader:
            def camera_sample(self):return dict(world='0x10000',data='0x20000',cell_ptr='0x30000',frame_ms=100,camera=camera)
            def u32(self,p):return 100 if p==0x10024 else 0x10000 if p==0x7c67dc else 0x30000
            def read(self,p,n):
                if p in(0x40000,0x41000):
                    h=bytearray(0xac);struct.pack_into('<H',h,0x14,int(p==0x41000));struct.pack_into('<4f',h,0x1c,0,10,0,1);struct.pack_into('<2I',h,0x98,0x50000 if p==0x40000 else 0x51000,0);return bytes(h)
                if p==0x50000:
                    h=bytearray(0x44);struct.pack_into('<H',h,8,1024);struct.pack_into('<I',h,0x1c,0x60000);struct.pack_into('<f',h,0x38,1);return bytes(h)
                raise AssertionError('Hidden emitter buffer must not be read: '+hex(p))
        geometry=stream.Geometry.__new__(stream.Geometry);geometry.r=FakeReader();geometry.cell='0x30000';geometry.skins={};geometry.view_pointers=set()
        geometry.shapes=[dict(id=hex(p),model=hex(m),parents=(),visibility_nodes=(p,),particles=True,particle_capacity=1024)for p,m in((0x40000,0x50000),(0x41000,0x51000))]
        geometry.light_pointers=[];geometry.light_owners={};geometry.material_flips={};geometry.material_values={};geometry.native_attributes={}
        geometry.records=[(p,(m,0),(p,),None,None)for p,m in((0x40000,0x50000),(0x41000,0x51000))];geometry.pose_layout=stream.PoseLayout(geometry.records)
        with patch.object(stream,'capture_environment',return_value={}):
            anchor,raw,particles,attributes,metrics=geometry.capture_pose(dict(world='0x10000',data='0x20000',cell_ptr='0x30000'))
        self.assertEqual(set(particles),{0x40000});self.assertEqual(set(raw),{0x40000,0x41000})

    def test_frame_fence_retries_once_and_nodes_are_captured_before_skinning(self):
        class FakeReader:
            attempts=0
            reads=[]
            def camera_sample(self):
                self.attempts+=1
                return dict(world='0x10000',data='0x20000',cell_ptr='0x30000',frame_ms=100)
            def read(self,address,count):
                self.reads.append((self.attempts,address,count))
                return bytes(count)
            def u32(self,address):
                if address==0x10024:return 101 if self.attempts==1 else 100
                return 0x10000 if address==0x7c67dc else 0x30000
        reader=FakeReader();geometry=stream.Geometry.__new__(stream.Geometry)
        geometry.r=reader;geometry.cell='0x30000'
        geometry.shapes=[dict(id='0x40000',parents=(0x50000,))]
        class FakeSkin:shape=0x40000;root=0x50000;bones=(0x60000,0x50000)
        geometry.skins={'skin':FakeSkin()}
        geometry.light_pointers=[];geometry.light_owners={};geometry.material_flips={};geometry.material_values={};geometry.native_attributes={}
        geometry.records=[(0x40000,(0,0),(0x40000,0x50000),geometry.skins['skin'],None)];geometry.pose_layout=stream.PoseLayout(geometry.records)
        with patch.object(stream,'capture_environment',return_value={}):
            anchor,raw,particles,attributes,metrics=geometry.capture_pose(dict(world='0x10000',data='0x20000',cell_ptr='0x30000'))
        self.assertEqual(metrics['pose_attempts'],2)
        self.assertFalse(metrics['sample_spanned_frames'])
        self.assertEqual(set(raw),{0x40000,0x50000,0x60000})
        self.assertEqual(len(reader.reads),6) # shared root/bone read only once per attempt

    def test_strict_deformation_never_fetches_a_missing_live_bone(self):
        skin=Skin.__new__(Skin);skin.shape=1;skin.root=2;skin.skin_transform=np.eye(4)
        with self.assertRaisesRegex(ValueError,'Missing captured bone/node'):
            skin.deform({},strict=True)


class InputTests(unittest.TestCase):
    def test_lost_focus_releases_injected_key_immediately(self):
        events=[]
        with patch.object(inputs,'require_foreground',side_effect=[None,RuntimeError('focus lost')]),patch.object(inputs,'enqueue',side_effect=lambda event:events.append(event.keyboard.flags)),patch.object(inputs.U,'GetAsyncKeyState',return_value=0):
            with self.assertRaisesRegex(RuntimeError,'focus lost'):
                inputs.pulse(object(),'key',0x11,.8)
        self.assertEqual(events,[0x8,0xA])

    def test_mouse_test_does_not_release_an_already_held_physical_button(self):
        with patch.object(inputs,'require_foreground'),patch.object(inputs.U,'GetAsyncKeyState',return_value=0x8000),patch.object(inputs,'enqueue') as send:
            with self.assertRaisesRegex(RuntimeError,'already held'):inputs.pulse(object(),'left')
            send.assert_not_called()


if __name__=='__main__':unittest.main()
