import struct
import unittest
import numpy as np
from live_probe import Reader,SceneReadChanged
from pose_frame import PoseFrame,PoseLayout
from test_pose_frame import header,CAMERA
from water_test_fixture import heights,select_point


class WaterTests(unittest.TestCase):
    def test_original_water_pass_visibility_preserves_bound_roots_and_rejects_bad_flag(self):
        class Memory:
            shown=1
            def u32(self,p):return 0x30000 if p==0x2b4ec else 0
            def read(self,p,n):
                raw=bytearray(n);raw[5]=self.shown;struct.pack_into('<2I',raw,0xb0,0x40000,0x50000);return bytes(raw)
        r=Memory()
        a=Reader.auxiliary_roots(r,0x10000,0x20000,header=bytes(0x80),visual={'root':None})
        self.assertEqual([v['visible']for v in a],[True,True]);r.shown=0
        b=Reader.auxiliary_roots(r,0x10000,0x20000,header=bytes(0x80),visual={'root':None})
        self.assertEqual([v['root']for v in a],[v['root']for v in b]);self.assertFalse(any(v['visible']for v in b))
        r.shown=2
        with self.assertRaises(SceneReadChanged):Reader.auxiliary_roots(r,0x10000,0x20000,header=bytes(0x80),visual={'root':None})

    def test_native_water_visibility_changes_without_hiding_other_world_geometry(self):
        records=[(p,(p+4,0),(p,),None,None)for p in(0x10000,0x20000,0x30000)]
        raw={r[0]:header(r[1])for r in records};layout=PoseLayout(records,water_pointers={0x10000,0x20000})
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA,water_visible=False).visible,[False,False,True])
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA,water_visible=True).visible,[True,True,True])

    def test_native_land_signed_delta_rows_and_columns(self):
        raw=bytearray(4232);struct.pack_into('<f',raw,0,-100);raw[4]=2;raw[5]=255;raw[4+65]=3
        result=heights(raw)
        self.assertEqual(result[0,0],-784);self.assertEqual(result[0,1],-792);self.assertEqual(result[1,0],-760)
        with self.assertRaises(ValueError):heights(bytes(100))

    def test_placement_requires_an_actual_deep_neighborhood(self):
        land=np.full((65,65),-1024.);land[20:45,20:45]=0
        p=select_point(land,(-2,-9),[-11000,-71000,0])
        x,y=p['sample'];self.assertLessEqual(np.max(land[y-1:y+2,x-1:x+2]),-512)
        with self.assertRaises(RuntimeError):select_point(np.zeros((65,65)),(-2,-9),[0,0,0])

if __name__=='__main__':unittest.main()
