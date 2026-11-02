import struct,unittest
import numpy as np
from native_view_pose import ViewPoseCapture
from read_batch import ReadPlan,RangeCapture
from pose_frame import PoseFrame,PoseLayout
from test_pose_frame import header,CAMERA
from live_probe import SceneReadChanged


class NearPassTests(unittest.TestCase):
    def test_small_capture_replaces_only_near_nodes_and_uses_its_own_camera(self):
        plan=ReadPlan([(0x20000,0xac),(0x30000,0xac)],max_gap=0)
        records=[(0x20000,(3,0),(),None,None),(0x30000,(4,0),(),None,None)]
        old=RangeCapture(plan,header((3,0))+header((4,0)))
        new=bytearray(header((3,0)));struct.pack_into('<f',new,0x64,42)
        cam=bytearray(0x128);struct.pack_into('<13f',cam,0x40,1,0,0,0,1,0,0,0,1,42,10,20,1)
        struct.pack_into('<3f',cam,0xdc,0,1,0);struct.pack_into('<3f',cam,0xe8,0,0,1);struct.pack_into('<6f',cam,0x100,-1,1,1,-1,1,1000)
        class Memory:
            def u32(self,p):return 1
            def read_many(self,p):return {0x20000:bytes(new),0x40000:bytes(cam)}
        capture=ViewPoseCapture(records,{0x20000},plan,0x40000)
        result,camera,stamp,metrics=capture.capture(Memory(),old,0x10000)
        self.assertIsInstance(result,RangeCapture);self.assertEqual(result[0x30000],old[0x30000]);self.assertEqual(result[0x20000],bytes(new));self.assertNotEqual(old[0x20000],bytes(new))
        self.assertEqual(camera['position'],(42,10,20));self.assertGreater(stamp,0);self.assertEqual(metrics['nodes'],1)
        struct.pack_into('<f',cam,0xdc,float('nan'))
        with self.assertRaises(SceneReadChanged):capture.capture(Memory(),old,0x10000)

    def test_native_near_camera_retains_weapons_without_changing_hide_or_body_rules(self):
        records=[(0x20000,(3,0),(),None,None)]
        layout=PoseLayout(records,view_pointers={0x20000},near_pass_camera=True)
        raw={0x20000:header((3,0),bound=(0,-400,0,10))}
        frame=PoseFrame(raw,layout,CAMERA);self.assertTrue(frame.visible[0]);self.assertFalse(frame.offscreen_casters[0])
        self.assertFalse(PoseFrame(raw,layout,CAMERA,first_person=False).visible[0])
        self.assertFalse(PoseFrame(raw,layout,CAMERA,first_person_items_active=False).visible[0])
        raw[0x20000]=header((3,0),flags=1,bound=(0,-400,0,10));self.assertFalse(PoseFrame(raw,layout,CAMERA).visible[0])


if __name__=='__main__':unittest.main()
