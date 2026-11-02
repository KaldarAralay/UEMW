import struct
from types import SimpleNamespace
import unittest
import numpy as np
from pose_frame import PoseLayout,PoseFrame
from test_pose_frame import header,CAMERA
from geometry_stream import Geometry,changed_effect_layers
from native_materials import FlipCapture
from native_switches import SwitchLayout

class ContinuityTests(unittest.TestCase):
    def test_other_effect_creation_does_not_retire_an_unchanged_flying_projectile(self):
        projectile=('projectile','0x10000',b'header',b'owned child')
        before=(projectile,('world_effect','0x20000',b'header',b'casting glow'))
        after=(projectile,('world_effect','0x20000',b'header',b'impact effect'))
        self.assertEqual(changed_effect_layers(before,after),{'aux:world_effect'})
        self.assertEqual(changed_effect_layers(before,(before[1],)),{'aux:projectile'})

    def test_replaced_model_and_detached_parent_hide_only_affected_objects(self):
        records=[(0x20000,(3,0),(0x10000,),None,None),(0x40000,(5,0),(0x30000,),None,None)]
        raw={p:header(i)for p,i in((0x10000,(0,0)),(0x20000,(3,0)),(0x30000,(0,0)),(0x40000,(5,0)))}
        layout=PoseLayout(records,node_identities={p:(0,0)for p in raw})
        raw[0x20000]=header((99,0));frame=PoseFrame(raw,layout,CAMERA)
        np.testing.assert_array_equal(frame.visible,[False,True]);self.assertGreater(frame.invalid_count,0)
        raw[0x20000]=header((3,0));changed=bytearray(raw[0x10000]);struct.pack_into('<I',changed,0x18,0x90000);raw[0x10000]=bytes(changed)
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA).visible,[False,True])

    def test_retired_bone_hides_its_skin_without_hiding_other_geometry(self):
        skin=SimpleNamespace(shape=0x20000,root=0x10000,bones=(0x50000,))
        records=[(0x20000,(3,4),(0x10000,),skin,None),(0x30000,(5,0),(),None,None)]
        raw={p:header(i)for p,i in((0x10000,(0,0)),(0x20000,(3,4)),(0x30000,(5,0)),(0x50000,(0,0)))}
        layout=PoseLayout(records,node_identities={p:(0,0)for p in raw})
        changed=bytearray(raw[0x50000]);struct.pack_into('<I',changed,0,0x99);raw[0x50000]=bytes(changed)
        np.testing.assert_array_equal(PoseFrame(raw,layout,CAMERA).visible,[False,True])

    def test_replaced_switch_masks_only_its_own_branch(self):
        shapes=[dict(switch_gates=((0x20000,0x50000),)),dict(switch_gates=())]
        switch=SwitchLayout(shapes,{0x20000:dict(node=0x20000,vtable=0x1234,storage=0x30000,capacity=1,children=(0x50000,))})
        np.testing.assert_array_equal(switch.blocked({},2,tolerate=True),[True,False]);self.assertEqual(switch.invalid_count,1)

    def test_changed_auxiliary_roots_are_not_read_and_world_poses_keep_advancing(self):
        class Probe(Geometry):
            def snapshot(self,base,prepared):
                self.assertion(all(p==0x20000 for p,n in self.pose_requests))
                raw={0x20000:header((3,0),transform=(1,0,0,0,1,0,0,0,1,base['pose'],10,0,1))}
                frame=PoseFrame(raw,self.pose_layout,CAMERA)
                self.assertion(set(self.native_light_membership)=={0xa0000})
                self.assertion(frame.visible[self.native_light_membership[0xa0000]].all())
                return dict(instance_states=[(True,frame.nodes['transform'][0].tolist())],geometry_stats={})
        g=Probe.__new__(Probe);g.assertion=self.assertTrue;g.continuity_views={};g.topology_dirty=False
        g.shapes=[dict(id=hex(p),cell_key=role)for p,role in((0x20000,'interior:1'),(0x30000,'view:first-person'),(0x40000,'aux:projectile'))]
        g.shapes[0]['native_lights']=['0xa0000'];g.shapes[2]['native_lights']=['0xa0000','0xb0000']
        g.native_light_membership={0xa0000:np.array([0,2]),0xb0000:np.array([2])}
        g.records=[(p,(m,0),(),None,None)for p,m in((0x20000,3),(0x30000,4),(0x40000,5))]
        g.material_flips=FlipCapture({});g.material_values={};g.native_attributes={};g.skins={};g.light_pointers=[];g.light_owners={}
        g.native_switches={};g.node_identities={};g.view_pointers={0x30000};g.water_pointers=set()
        for pose in(1,8,16):
            packet=g.snapshot_retained(dict(cell_ptr='0x60000',pose=pose),{'view:first-person','aux:projectile'})
            self.assertEqual(len(packet['instance_states']),3);self.assertEqual(packet['instance_states'][0][1][9],pose)
            self.assertEqual(packet['instance_states'][1:],[(False,),(False,)])
        self.assertEqual(len(g.records),3);self.assertEqual(len(g.continuity_views),1)

if __name__=='__main__':unittest.main()
