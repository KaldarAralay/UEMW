import struct
import unittest
from live_probe import SceneReadChanged
from scene_reader import SceneReader
from native_switches import SwitchLayout
from pose_frame import PoseFrame,PoseLayout
from read_batch import ReadPlan,capture_ranges
from test_pose_frame import header,CAMERA


class Memory:
    def __init__(self):
        self.bytes={}
        self.put(0x7c67e0,struct.pack('<I',0x10000));self.put(0x1b540,struct.pack('<I',0x20000))
        self.switch(0x30000,(0x40000,0x50000),0)
        self.switch(0x50000,(0x60000,0x70000),0)
        for p,parent in((0x40000,0x30000),(0x60000,0x50000),(0x70000,0x50000)):
            raw=bytearray(header((p+0x100,0)));struct.pack_into('<2I',raw,0,0xbbb,0)
            struct.pack_into('<I',raw,0x18,parent);self.put(p,raw)
            model=bytearray(0x36);struct.pack_into('<H',model,8,3);struct.pack_into('<H',model,0x34,1);self.put(p+0x100,model)
        self.put(0x50018,struct.pack('<I',0x30000))
    def switch(self,p,children,index):
        raw=bytearray(header());raw.extend(bytes(0xb4-len(raw)));struct.pack_into('<I',raw,0,0xaaa)
        struct.pack_into('<3I',raw,0x94,p+0x400,len(children),len(children));struct.pack_into('<i',raw,0xb0,index)
        self.put(p,raw);self.put(p+0x400,struct.pack('<'+'I'*len(children),*children))
    def put(self,p,data):self.bytes.update({p+i:v for i,v in enumerate(data)})
    def read(self,p,n):return bytes(self.bytes.get(p+i,0)for i in range(n))
    def u32(self,p):return struct.unpack('<I',self.read(p,4))[0]
    def string(self,*args):return ''


class SwitchTests(unittest.TestCase):
    def prepare(self):
        m=Memory();reader=SceneReader(m);reader.types={0xaaa:['NiSwitchNode','NiNode'],0xbbb:['NiTriShape']}
        scene=reader.collect(roots=[0x30000]);self.assertFalse(scene['errors'])
        shapes=sorted(scene['shapes'],key=lambda s:s['id']);self.assertEqual(len(shapes),3)
        switches=SwitchLayout(shapes,scene['switches'])
        records=[(int(s['id'],16),(int(s['model'],16),0),s['parents'],None,None)for s in shapes]
        requests={p:0xac for p in(0x30000,0x40000,0x50000,0x60000,0x70000)}
        for p,n in switches.requests():requests[p]=max(requests.get(p,0),n)
        plan=ReadPlan(sorted(requests.items()))
        return m,PoseLayout(records,read_plan=plan,switches=switches),plan
    def frame(self,m,layout,plan):return PoseFrame(capture_ranges(m.read,plan,{}),layout,CAMERA)
    def test_all_branches_are_converted_but_current_native_selection_alone_is_visible(self):
        m,layout,plan=self.prepare()
        self.assertEqual(self.frame(m,layout,plan).visible.tolist(),[True,False,False])
        m.put(0x300b0,struct.pack('<i',1))
        self.assertEqual(self.frame(m,layout,plan).visible.tolist(),[False,True,False])
        m.put(0x500b0,struct.pack('<i',1))
        self.assertEqual(self.frame(m,layout,plan).visible.tolist(),[False,False,True])
        # No discovery, catalog conversion or UE selection was involved.
        m.put(0x300b0,struct.pack('<i',0))
        self.assertEqual(self.frame(m,layout,plan).visible.tolist(),[True,False,False])
    def test_none_selected_and_native_hidden_ancestors_hide_every_descendant(self):
        for index in(-1,4):
            m,layout,plan=self.prepare();m.put(0x300b0,struct.pack('<i',index))
            self.assertFalse(self.frame(m,layout,plan).visible.any())
        m,layout,plan=self.prepare();m.put(0x30014,struct.pack('<H',1))
        self.assertFalse(self.frame(m,layout,plan).visible.any())
    def test_replaced_switch_identity_or_children_fail_before_old_geometry_is_visible(self):
        for p,data in((0x30000,struct.pack('<I',0xccc)),(0x30400,struct.pack('<I',0x80000)),(0x30094,struct.pack('<I',0x90000))):
            m,layout,plan=self.prepare();m.put(p,data)
            with self.assertRaises(SceneReadChanged):self.frame(m,layout,plan)
    def test_scene_root_also_inherits_selection_from_a_native_switch_above_it(self):
        m=Memory();reader=SceneReader(m);reader.types={0xaaa:['NiSwitchNode','NiNode'],0xbbb:['NiTriShape']}
        scene=reader.collect(roots=[0x60000]);shape=scene['shapes'][0]
        self.assertEqual(set(shape['switch_gates']),{(0x50000,0x60000),(0x30000,0x50000)})

if __name__=='__main__':unittest.main()
