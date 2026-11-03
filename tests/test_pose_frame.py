import struct
import unittest
import numpy as np
from pose_frame import PoseFrame,PoseLayout
from render_culling import View
from skin_math import matrix
from live_probe import SceneReadChanged

CAMERA=dict(position=[0,0,0],forward=[0,1,0],up=[0,0,1],frustum=[-1,1,1,-1,1,1000],fov=90)

def header(identity=(0,0),flags=0,bound=(0,10,0,1),transform=None):
    raw=bytearray(0xac);struct.pack_into('<H',raw,0x14,flags);struct.pack_into('<4f',raw,0x1c,*bound);struct.pack_into('<2I',raw,0x98,*identity)
    struct.pack_into('<13f',raw,0x40,*(transform or(1,0,0,0,1,0,0,0,1,0,0,0,1)))
    return bytes(raw)

class PoseFrameTests(unittest.TestCase):
    def test_reflected_only_geometry_is_fresh_without_bypassing_native_retirement(self):
        cam={**CAMERA,'position':[0,0,100],'forward':[0,1,-.75],'up':[0,.75,1],'frustum':[-.3,.3,.3,-.3,1,2000]}
        records=[(p,(3,0),(),None,None)for p in(0x20000,0x30000,0x40000,0x50000,0x60000)]
        raw={p:header((99 if p==0x40000 else 3,0),flags=1 if p==0x30000 else 0,bound=(0,500,300,1))for p in(0x20000,0x30000,0x40000,0x50000,0x60000)}
        layout=PoseLayout(records,view_pointers={0x50000},node_identities={p:(0,0)for p in raw},reflection_excluded={0x60000})
        self.assertFalse(PoseFrame(raw,layout,cam).visible.any())
        frame=PoseFrame(raw,layout,cam,reflection_plane=0)
        np.testing.assert_array_equal(frame.visible,[True,False,False,False,False])
        np.testing.assert_array_equal(frame.offscreen_reflections,[True,False,False,False,False])
        # Underwater and source-hidden water never enable the mirror view.
        self.assertFalse(PoseFrame(raw,layout,{**cam,'position':[0,0,-100]},reflection_plane=0).offscreen_reflections.any())
        self.assertFalse(PoseFrame(raw,layout,cam,water_visible=False,reflection_plane=0).offscreen_reflections.any())
    def test_cell_slots_own_borrowed_render_roots_and_retirement_still_wins(self):
        root=bytearray(header());struct.pack_into('<I',root,0x18,0x90000)
        records=[(0x20000,(3,0),(0x10000,),None,None),(0x30000,(4,0),(0x10000,),None,None)]
        raw={0x10000:bytes(root),0x20000:header((3,0)),0x30000:header((4,0)),0x60014:struct.pack('<I',0x10000)}
        layout=PoseLayout(records,node_identities={0x10000:(0,0x80000)},cell_root_owners={0x10000:((0x60014,0x10000),)})
        frame=PoseFrame(raw,layout,CAMERA)
        np.testing.assert_array_equal(frame.visible,[True,True]);self.assertEqual(frame.invalid_count,0)
        raw[0x30000]=header((4,0),flags=1)
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA).visible,[True,False])
        raw[0x60014]=struct.pack('<I',0x70000)
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA).visible,[False,False])
        raw[0x60014]=struct.pack('<I',0x10000);struct.pack_into('<I',root,0,99);raw[0x10000]=bytes(root)
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA).visible,[False,False])
        struct.pack_into('<I',root,0,0);struct.pack_into('<H',root,0x14,1);raw[0x10000]=bytes(root)
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA).visible,[False,False])

    def test_land_root_requires_both_the_cell_land_slot_and_land_root_slot(self):
        records=[(0x20000,(3,0),(0x10000,),None,None)]
        raw={0x10000:header(),0x20000:header((3,0)),0x60020:struct.pack('<I',0x70000),0x70010:struct.pack('<I',0x10000)}
        layout=PoseLayout(records,node_identities={0x10000:(0,0x90000)},cell_root_owners={0x10000:((0x60020,0x70000),(0x70010,0x10000))})
        self.assertTrue(PoseFrame(raw,layout,CAMERA).visible[0])
        for address in (0x60020,0x70010):
            old=raw.pop(address);self.assertFalse(PoseFrame(raw,layout,CAMERA).visible[0]);raw[address]=old

    def test_offscreen_casters_survive_camera_turns_but_native_hiding_wins(self):
        records=[(p,(3,0),(),None,None)for p in(0x20000,0x30000,0x40000)]
        raw={p:header((3,0),bound=(0,-400,0,10),flags=1 if p==0x30000 else 0)for p in(0x20000,0x30000,0x40000)}
        layout=PoseLayout(records,shadow_casters={0x20000,0x30000},shadow_distance=1000)
        frame=PoseFrame(raw,layout,CAMERA)
        np.testing.assert_array_equal(frame.visible,[True,False,False])
        np.testing.assert_array_equal(frame.offscreen_casters,[True,False,False])
        turned={**CAMERA,'forward':[0,-1,0]}
        np.testing.assert_array_equal(PoseFrame(raw,layout,turned).visible,[True,False,True])

    def test_shadow_reach_is_bounded_and_retired_or_first_person_shapes_do_not_cast(self):
        records=[(p,(3,0),(),None,None)for p in(0x20000,0x30000,0x40000)]
        raw={0x20000:header((3,0),bound=(0,-6000,0,10)),0x30000:header((99,0),bound=(0,-400,0,10)),0x40000:header((3,0),bound=(0,-400,0,10))}
        layout=PoseLayout(records,view_pointers={0x40000},shadow_casters=set(raw),shadow_distance=1000,node_identities={p:(0,0)for p in raw})
        frame=PoseFrame(raw,layout,CAMERA)
        np.testing.assert_array_equal(frame.visible,[False,False,False])
        self.assertGreater(frame.invalid_count,0)

    def test_water_controller_visibility_replaces_only_transient_water_root_cull(self):
        records=[(0x20000,(3,0),(0x10000,),None,None),(0x30000,(4,0),(0x10000,),None,None)]
        raw={0x10000:header(flags=27),0x20000:header((3,0)),0x30000:header((4,0))}
        layout=PoseLayout(records,water_pointers={0x20000},water_visibility_roots={0x10000})
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA).visible,[True,False])
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA,water_visible=False).visible,[False,False])
        raw[0x20000]=header((3,0),flags=1)
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA).visible,[False,False])
    def test_native_view_mode_selects_first_person_arms_or_third_person_body(self):
        records=[(p,(i,0),(),None,None)for p,i in((0x10000,1),(0x20000,2),(0x30000,3))]
        raw={p:header((i,0))for p,i in((0x10000,1),(0x20000,2),(0x30000,3))}
        layout=PoseLayout(records,view_pointers={0x20000},player_pointers={0x30000})
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA,first_person=True).visible,[True,True,False])
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA,first_person=False).visible,[True,False,True])
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA,first_person=True,first_person_items_active=False).visible,[True,False,False])
    def test_prepared_visibility_matches_independent_legacy_rules_and_bounds(self):
        rng=np.random.default_rng(42);parents=[0x10000+i*0x100 for i in range(20)];raw={p:header(flags=int(i%7==0))for i,p in enumerate(parents)};records=[];views=set()
        for i in range(700):
            p=0x20000+i*0x100;identity=(0x500000+i,0);ancestors=(parents[i%20],parents[(i+1)%20],p);records.append((p,identity,ancestors,None,None))
            bound=(*rng.uniform(-2000,2000,3),float(rng.uniform(0,50)));raw[p]=header(identity,i%13==0,bound)
            if i%17==0:views.add(p)
        layout=PoseLayout(records,views);view=View(CAMERA)
        for first_person in(True,False):
            frame=PoseFrame(raw,layout,CAMERA,first_person);hidden={p for p,b in raw.items()if struct.unpack_from('<H',b,0x14)[0]&1}
            expected=[hidden.isdisjoint(row[2])and(first_person or row[0]not in views)and view.includes(struct.unpack_from('<4f',raw[row[0]],0x1c))for row in records]
            np.testing.assert_array_equal(frame.visible,expected)
            for i,row in enumerate(records):self.assertEqual(frame.shape_visible(row[0]),expected[i])
    def test_identity_change_on_hidden_shape_rejects_whole_capture(self):
        records=[(0x20000,(3,4),(0x10000,0x20000),None,None)]
        raw={0x10000:header(flags=1),0x20000:header((3,5),flags=1)}
        with self.assertRaisesRegex(SceneReadChanged,'identity'):PoseFrame(raw,PoseLayout(records),CAMERA)
    def test_missing_or_short_parents_and_shapes_never_become_visible_defaults(self):
        records=[(0x20000,(3,4),(0x10000,0x20000),None,None)];layout=PoseLayout(records)
        for raw in({0x20000:header((3,4))},{0x10000:b'\0'*50,0x20000:header((3,4))},{0x10000:header(),0x20000:header((3,4))[:0x99]}):
            with self.subTest(keys=list(raw)),self.assertRaises(SceneReadChanged):PoseFrame(raw,layout,CAMERA)
    def test_owned_world_matrices_equal_scalar_native_math_and_survive_next_frame(self):
        rng=np.random.default_rng(4);raw={};records=[]
        for i in range(80):
            p=0x10000+i*0x100;t=rng.uniform(-8,8,13);t[12]=(-1 if i%2 else 1)*1.125;raw[p]=header((i+1,0),transform=t.tolist());records.append((p,(i+1,0),(p,),None,None))
        frame=PoseFrame(raw,PoseLayout(records),CAMERA);worlds=frame.worlds(raw)
        for p,w in worlds.items():np.testing.assert_array_equal(w,matrix(struct.unpack_from('<13f',raw[p],0x40)))
        saved={p:w.copy()for p,w in worlds.items()}
        for p in raw:raw[p]=header((1,0))
        for p in worlds:np.testing.assert_array_equal(worlds[p],saved[p])
    def test_invalid_bounds_fail_open_but_native_hidden_flags_still_apply(self):
        records=[(0x10000,(1,0),(0x10000,),None,None)];layout=PoseLayout(records)
        for bound in((float('nan'),0,0,1),(1e9,0,0,1),(0,0,0,-1)):
            self.assertTrue(PoseFrame({0x10000:header((1,0),bound=bound)},layout,CAMERA).visible[0])
            self.assertFalse(PoseFrame({0x10000:header((1,0),flags=1,bound=bound)},layout,CAMERA).visible[0])

if __name__=='__main__':unittest.main()
