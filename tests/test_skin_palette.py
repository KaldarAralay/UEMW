import struct,unittest
import numpy as np
from skin_math import Skin,matrix
from skin_palette import PalettePlan
from pose_frame import PoseLayout,PoseFrame
from test_pose_frame import header


class PalettePlanTests(unittest.TestCase):
    def fixture(self,count=40):
        rng=np.random.default_rng(72);records=[];raw={}
        def transform():
            rotation=np.linalg.qr(rng.normal(size=(3,3)))[0]
            return [*rotation.reshape(-1),*rng.uniform(-10000,10000,3),-1.125 if rng.random()<.3 else .925]
        roots=[0x10000,0x11000,0x12000];bones=[0x20000+i*0x100 for i in range(24)]
        for p in roots+bones:raw[p]=header(transform=transform())
        for i in range(count):
            p=0x50000+i*0x100;skin=Skin.__new__(Skin);skin.shape=p;skin.root=roots[i%len(roots)];skin.bones=tuple(bones[:i%16+1])
            skin.skin_transform=matrix(transform());skin.binds=[matrix(transform())for _ in skin.bones]
            records.append((p,(3,4),(),skin,None));raw[p]=header((3,4),transform=transform())
        return PoseLayout(records),raw

    def test_batched_palettes_match_scalar_native_equation_with_shared_roots(self):
        layout,raw=self.fixture();frame=PoseFrame(raw,layout,dict(frustum=[]));result=PalettePlan(layout).capture(frame)
        needed={p for _,_,_,s,_ in layout.records for p in(s.shape,s.root,*s.bones)};worlds=frame.worlds(needed)
        self.assertEqual(len(result),len(layout.records))
        for row,palette in result.items():
            expected=layout.records[row][3].palette(worlds)
            np.testing.assert_array_equal(palette,expected)

    def test_next_capture_is_fresh_and_old_results_keep_owned_bytes(self):
        layout,raw=self.fixture(6);plan=PalettePlan(layout);first=plan.capture(PoseFrame(raw,layout,dict(frustum=[])))
        old={k:v.copy()for k,v in first.items()};bone=layout.records[0][3].bones[0]
        changed=bytearray(raw[bone]);struct.pack_into('<f',changed,0x40+9*4,12345);raw[bone]=bytes(changed)
        second=plan.capture(PoseFrame(raw,layout,dict(frustum=[])),{layout.records[1][0]})
        self.assertNotIn(1,second);self.assertFalse(np.array_equal(second[0],first[0]))
        for row,value in first.items():np.testing.assert_array_equal(value,old[row])
        other,_=self.fixture(6)
        with self.assertRaisesRegex(ValueError,'another'):plan.capture(PoseFrame(raw,other,dict(frustum=[])))

    def test_hidden_singular_skins_skip_work_but_visible_invalid_poses_reject(self):
        layout,raw=self.fixture(1);shape=layout.records[0][0];root=layout.records[0][3].root
        changed=bytearray(raw[root]);struct.pack_into('<f',changed,0x40+12*4,0);raw[root]=bytes(changed)
        changed=bytearray(raw[shape]);struct.pack_into('<H',changed,0x14,1);raw[shape]=bytes(changed)
        plan=PalettePlan(layout);self.assertEqual(plan.capture(PoseFrame(raw,layout,dict(frustum=[]))),{})
        struct.pack_into('<H',changed,0x14,0);raw[shape]=bytes(changed)
        with self.assertRaises(np.linalg.LinAlgError):plan.capture(PoseFrame(raw,layout,dict(frustum=[])))

