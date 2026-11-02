import struct
import unittest
import numpy as np
from node_ownership import identity,discover,player_owner
from live_probe import SceneReadChanged
from pose_frame import PoseLayout,PoseFrame
from test_pose_frame import header,CAMERA


def reference(node=0x10000,flags=0,target=12):
    raw=bytearray(0x50);raw[4:8]=b'REFR';struct.pack_into('<I',raw,8,flags)
    struct.pack_into('<I',raw,0x10,node);struct.pack_into('<I',raw,0x28,0x70000);struct.pack_into('<2I',raw,0x48,7,target)
    return bytes(raw)


class OwnershipTests(unittest.TestCase):
    def test_actor_render_parent_can_change_but_native_reference_and_node_identity_must_match(self):
        root=bytearray(header());struct.pack_into('<2I',root,0,0x1234,0);struct.pack_into('<I',root,0x18,0x90000)
        raw={0x10000:bytes(root),0x20000:header((3,0)),0x60000:reference()}
        layout=PoseLayout([(0x20000,(3,0),(0x10000,),None,None)],node_identities={0x10000:(0x1234,0x80000)},actor_owners={0x10000:dict(reference=0x60000,identity=identity(reference()))})
        self.assertTrue(PoseFrame(raw,layout,CAMERA).visible[0])
        for bad in(reference(node=0),reference(target=13),reference(flags=1<<5),reference(flags=1<<11),b''):
            raw[0x60000]=bad;self.assertFalse(PoseFrame(raw,layout,CAMERA).visible[0])
        raw[0x60000]=reference();struct.pack_into('<I',root,0,0x9876);raw[0x10000]=bytes(root)
        self.assertFalse(PoseFrame(raw,layout,CAMERA).visible[0])
    def test_native_hidden_actor_still_hides_when_reference_is_valid(self):
        root=bytearray(header(flags=1));struct.pack_into('<I',root,0,0x1234)
        raw={0x10000:bytes(root),0x20000:header((3,0)),0x60000:reference()}
        layout=PoseLayout([(0x20000,(3,0),(0x10000,),None,None)],node_identities={0x10000:(0x1234,0)},actor_owners={0x10000:dict(reference=0x60000,identity=identity(reference()))})
        self.assertFalse(PoseFrame(raw,layout,CAMERA).visible[0])
    def test_reference_owned_actor_is_discovered_even_when_absent_from_cell_children(self):
        class Memory:
            def read(self,p,n):
                if p==0x50030:return struct.pack('<3I',1,0x60000,0x60000)
                if p in(0x50040,0x50058):return bytes(12)
                if p==0x60000:return reference()
                if p==0x70004:return b'NPC_'
                raise AssertionError(hex(p))
        owners=discover(Memory(),[(0x50000,0x80000,'cell')])
        self.assertEqual(owners[0x10000]['cell_root'],0x80000)
        self.assertEqual(discover(Memory(),[(0x50000,0x80000,'cell')],excluded={0x10000}),{})

    def test_player_pass_parent_changes_keep_body_visible_and_camera_mode_still_gates_it(self):
        class Memory:
            def read(self,p,n):return reference()if p==0x60000 else b'NPC_'
        owner=player_owner(Memory(),0x60000,0x10000,0x80000)
        self.assertEqual(owner['role'],'aux:player')
        root=bytearray(header());struct.pack_into('<I',root,0,0x1234)
        child=header((3,0));raw={0x10000:bytes(root),0x20000:child,0x60000:reference()}
        layout=PoseLayout([(0x20000,(3,0),(0x10000,),None,None)],player_pointers={0x20000},node_identities={0x10000:(0x1234,0x80000)},actor_owners={0x10000:owner})
        for parent in(0x80000,0x90000,0,0x80000):
            struct.pack_into('<I',root,0x18,parent);raw[0x10000]=bytes(root)
            self.assertTrue(PoseFrame(raw,layout,CAMERA,first_person=False).visible[0])
            self.assertFalse(PoseFrame(raw,layout,CAMERA,first_person=True).visible[0])
        struct.pack_into('<H',root,0x14,1);raw[0x10000]=bytes(root)
        self.assertFalse(PoseFrame(raw,layout,CAMERA,first_person=False).visible[0])
        struct.pack_into('<H',root,0x14,0);raw[0x10000]=bytes(root)
        raw[0x20000]=header((3,0),flags=1)
        self.assertFalse(PoseFrame(raw,layout,CAMERA,first_person=False).visible[0])
        raw[0x20000]=child
        for bad in(reference(node=0),reference(target=13),reference(flags=1<<5),reference(flags=1<<11)):
            raw[0x60000]=bad
            self.assertFalse(PoseFrame(raw,layout,CAMERA,first_person=False).visible[0])

    def test_player_owner_rejects_stale_disabled_deleted_and_non_actor_references(self):
        class Memory:
            raw=reference();kind=b'NPC_'
            def read(self,p,n):return self.raw if p==0x60000 else self.kind
        memory=Memory()
        for bad in(reference(node=0),reference(flags=1<<5),reference(flags=1<<11),bytes(0x50)):
            memory.raw=bad
            with self.assertRaises(SceneReadChanged):player_owner(memory,0x60000,0x10000,0x80000)
        memory.raw=reference();memory.kind=b'STAT'
        with self.assertRaises(SceneReadChanged):player_owner(memory,0x60000,0x10000,0x80000)

    def test_player_traversal_uses_owning_cell_instead_of_borrowed_pass_ancestry(self):
        from scene_reader import SceneReader
        class Memory:
            def u32(self,p):
                if p==0x7c67e0:return 0x40000
                if p==0x40000+0xb540:return 0x30000
                return struct.unpack('<I',self.read(p,4))[0]
            def string(self,p,*args):return 'room'
            def read(self,p,n):
                if p==0x30014:
                    raw=bytearray(0x1c);struct.pack_into('<2I',raw,0,0x80000,1);return bytes(raw)
                if p==0x30010:return bytes(4)
                if p==0x60000:return reference()
                if p==0x70004:return b'NPC_'
                if p==0x10000:
                    raw=bytearray(0x90);struct.pack_into('<I',raw,0x18,0x90000);return bytes(raw[:n])
                if p in(0x80000,0x80018,0x800a8,0x10094):return bytes(n)
                raise AssertionError('Borrowed ancestry must not be read: '+hex(p))
        graph=SceneReader(Memory());graph.ancestry=lambda *args:['NiNode']
        scene=graph.collect(roots=[],aux_roots=[dict(layer='player',root='0x10000',owner_ref='0x60000')])
        self.assertEqual(scene['actor_owners'][0x10000]['cell_root'],0x80000)
        self.assertEqual(scene['actor_owners'][0x10000]['role'],'aux:player')
        self.assertIn(0x80000,scene['node_identities'])
        self.assertNotIn(0x90000,scene['node_identities'])
        self.assertEqual(scene['errors'],[])


if __name__=='__main__':unittest.main()
