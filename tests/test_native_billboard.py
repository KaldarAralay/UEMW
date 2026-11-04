import struct
import unittest
import numpy as np
from native_billboard import rigid_points,glare_owners
from live_probe import SceneReadChanged
from native_attributes import discover
from test_native_attributes import AttributeMemory


class SunBillboardTests(unittest.TestCase):
    def header(self,flags=0x40):
        raw=bytearray(0x74);struct.pack_into('<H',raw,0x14,flags);return raw
    def test_native_rigid_mode_uses_captured_camera_not_temporary_draw_rotation(self):
        local=np.array([[-2,-3,0],[2,-3,0],[-2,3,0],[2,3,0.]])
        camera=dict(forward=[0,.6,.8],up=[0,-.8,.6])
        # Independent expected corners: right +X, up=(0,-.8,.6).
        expected=np.array([[8,22.4,28.2],[12,22.4,28.2],[8,17.6,31.8],[12,17.6,31.8]])
        for rotation in([1,0,0,0,1,0,0,0,1],[0,-1,0,1,0,0,0,0,1]):
            points=rigid_points(local,[*rotation,10,20,30,1],camera,self.header())
            np.testing.assert_allclose(points,expected,atol=1e-6)
    def test_native_translation_and_scale_survive_camera_changes(self):
        local=np.array([[-2,-3,0],[2,3,0.]])
        camera=dict(forward=[1,0,0],up=[0,0,1]);m=[1,0,0,0,1,0,0,0,1,100,200,300,2]
        points=rigid_points(local,m,camera,self.header())
        np.testing.assert_allclose(points,[[100,204,294],[100,196,306]])
    def test_changed_native_mode_and_degenerate_camera_fail_closed(self):
        m=[1,0,0,0,1,0,0,0,1,0,0,0,1];camera=dict(forward=[0,1,0],up=[0,0,1])
        for flags in(0,0x20):
            with self.assertRaises(SceneReadChanged):rigid_points([[0,0,0]],m,camera,self.header(flags))
        with self.assertRaises(SceneReadChanged):rigid_points([[0,0,0]],m,dict(forward=[0,1,0],up=[0,1,0]),self.header())
    def test_weather_owned_glare_keeps_mutable_alpha_uv_and_billboard_identity(self):
        r=AttributeMemory();shape={**r.shape(), 'controller':'0x0','cell_key':'aux:sun_glare','texture':'Textures/tx_sun_flash_grey_05.dds','rigid_billboard':1234}
        item=discover(r,shape);self.assertEqual(item['billboard'],1234);self.assertTrue(item['colors']);self.assertTrue(item['uvs'])
        self.assertIsNone(discover(r,{**shape,'cell_key':'interior:1'}))
    def test_native_weather_controller_owns_glare_independently_of_equipment(self):
        from live_probe import Reader
        class Memory:
            def read(self,p,n):
                if p==0x20000:
                    v=bytearray(0x80);struct.pack_into('<I',v,8,0x30000);struct.pack_into('<I',v,0x4c,0x40000);return bytes(v[:n])
                raise AssertionError(hex(p))
            def u32(self,p):return 0
        h=bytearray(0x80);struct.pack_into('<I',h,0x58,0x20000)
        roots=Reader.auxiliary_roots(Memory(),0x10000,0x50000,h,dict(root=None))
        self.assertIn(dict(layer='sun_glare',root='0x30000'),roots)
        self.assertIn(dict(layer='sky',root='0x40000'),roots)
    def test_glare_owner_survives_pass_borrowing_but_not_retirement_or_native_hide(self):
        from pose_frame import PoseLayout,PoseFrame
        from test_pose_frame import header,CAMERA
        class Memory:
            def u32(self,p):return {0x7c67dc:0x10000,0x10058:0x20000,0x20008:0x30000}[p]
        owners=glare_owners(Memory(),[dict(layer='sun_glare',root='0x30000')])
        layout=PoseLayout([(0x40000,(1,2),(0x30000,),None,None)],node_identities={0x30000:(0,0x80000),0x40000:(0,0x30000)},cell_root_owners=owners)
        root=bytearray(header());struct.pack_into('<I',root,0x18,0x90000)
        shape=bytearray(header(identity=(1,2)));struct.pack_into('<I',shape,0x18,0x30000)
        raw={0x30000:bytes(root),0x40000:bytes(shape),0x10058:struct.pack('<I',0x20000),0x20008:struct.pack('<I',0x30000)}
        self.assertTrue(PoseFrame(raw,layout,CAMERA,first_person=False,first_person_items_active=False).visible[0])
        raw[0x20008]=struct.pack('<I',0);self.assertFalse(PoseFrame(raw,layout,CAMERA).visible[0])
        raw[0x20008]=struct.pack('<I',0x30000);struct.pack_into('<H',root,0x14,1);raw[0x30000]=bytes(root)
        self.assertFalse(PoseFrame(raw,layout,CAMERA).visible[0])
