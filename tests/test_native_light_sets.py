import struct
import unittest
from live_probe import SceneReadChanged
from native_light_sets import capture


class Memory:
    def __init__(self):
        self.blocks={0x10000:struct.pack('<3I',0x7469b4,8,0x20000),0x20000:struct.pack('<2I',0x20010,0x30000),0x20010:struct.pack('<2I',0,0x31000),0x30000:struct.pack('<I',0x749d40),0x31000:struct.pack('<I',0x74ffe0)}
    def read(self,p,n):return self.blocks[p][:n]
    def u32(self,p):return struct.unpack('<I',self.read(p,4))[0]


class NativeLightSetTests(unittest.TestCase):
    def test_original_membership_is_preserved_without_a_distance_or_camera_cutoff(self):
        reader=Memory();cache={};self.assertEqual(capture(reader,0x10000,cache),('0x30000','0x31000'))
        reader.blocks.clear();self.assertEqual(capture(reader,0x10000,cache),('0x30000','0x31000'))
        self.assertIsNone(capture(reader,0,cache))
    def test_retired_state_and_cyclic_native_lists_fail_closed(self):
        reader=Memory();reader.blocks[0x10000]=bytes(12)
        with self.assertRaises(SceneReadChanged):capture(reader,0x10000,{})
        reader=Memory();reader.blocks[0x20010]=struct.pack('<2I',0x20000,0x31000)
        with self.assertRaises(SceneReadChanged):capture(reader,0x10000,{})

    def test_native_membership_change_requests_refresh_without_hiding_live_geometry(self):
        from pose_frame import PoseLayout,PoseFrame
        from test_pose_frame import header,CAMERA
        raw=bytearray(header((3,0)));struct.pack_into('<I',raw,0x94,0x50000)
        layout=PoseLayout([(0x10000,(3,0),(),None,None)],native_light_states={0x10000:0x50000})
        self.assertFalse(PoseFrame({0x10000:bytes(raw)},layout,CAMERA).light_membership_changed)
        struct.pack_into('<I',raw,0x94,0x60000);pose=PoseFrame({0x10000:bytes(raw)},layout,CAMERA)
        self.assertTrue(pose.light_membership_changed);self.assertTrue(pose.visible[0])

    def test_prepared_flat_capture_detects_the_same_membership_change(self):
        from pose_frame import PoseLayout,PoseFrame
        from read_batch import ReadPlan,RangeCapture
        from test_pose_frame import header,CAMERA
        raw=bytearray(header((3,0)));struct.pack_into('<I',raw,0x94,0x60000)
        plan=ReadPlan([(0x10000,len(raw))]);layout=PoseLayout([(0x10000,(3,0),(),None,None)],read_plan=plan,native_light_states={0x10000:0x50000})
        pose=PoseFrame(RangeCapture(plan,bytes(raw)),layout,CAMERA)
        self.assertTrue(pose.light_membership_changed);self.assertTrue(pose.visible[0])


if __name__=='__main__':unittest.main()
