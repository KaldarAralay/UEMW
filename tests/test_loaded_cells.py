import struct
import unittest
from geometry_stream import Geometry
from loaded_cells import loaded_exteriors,render_cells,desired_grids
from scene_reader import SceneReader
from supported_scenes import supported

class Memory:
    data=0x10000
    pointers=(0x20000,0x21000)
    cell_pointers=(0x30000,0x31000)
    grids=((-2,-8),(-2,-9)) # Intentionally not a presumed spatial slot order.
    states=[1,1]
    roots=[0x40000,0x50000]
    changed=False
    def read(self,address,count):
        if address==self.data+4:return struct.pack('<9I',*self.pointers,*([0]*7))
        if address in self.pointers:
            i=self.pointers.index(address);return struct.pack('<B3xII',self.states[i],self.cell_pointers[i],0)
        if address in self.cell_pointers:
            i=self.cell_pointers.index(address);raw=bytearray(0x30);raw[4:8]=b'CELL'
            struct.pack_into('<I',raw,0x10,0x70000+i*0x100)
            struct.pack_into('<4I2iI',raw,0x14,self.roots[i],26,0,0x80000+i*0x100,*self.grids[i],self.roots[i]+0x100)
            return bytes(raw)
        if address-0x14 in self.cell_pointers:return self.read(address-0x14,0x30)[0x14:0x30]
        raise AssertionError((address,count))
    def u32(self,address):
        if address in (0x80010,0x80110):return 0x60000+(address-0x80010)*0x10
        raise AssertionError(address)
    def string(self,address):return '' if address==0x70000 else 'Seyda Neen'
    def base(self,index):return dict(world='0x90000',data=hex(self.data),cell_ptr=hex(self.cell_pointers[index]),cell_grid=self.grids[index],cell_flags=26,cell=self.string(0x70000+index*0x100),camera=dict(position=[-12288,-65700,300],forward=[0,1,0],up=[0,0,1],frustum=[-.7,.7,.5,-.5,1,4000]))

class ResidencyTests(unittest.TestCase):
    def setUp(self):
        self.m=Memory();self.m.states=[1,1];self.m.roots=[0x40000,0x50000]
    def test_both_cells_selected_by_coordinates_not_slot_order(self):
        cells=render_cells(self.m,self.m.base(1))
        self.assertEqual([c['grid'] for c in cells],[(-2,-9),(-2,-8)])
        self.assertEqual(len(cells[0]['roots']),3)
        self.assertTrue(supported(self.m.base(0)))
        self.assertTrue(supported({**self.m.base(0),'cell_grid':(-2,-10)}))
        self.assertFalse(supported({**self.m.base(0),'cell_grid':(-2,40000)}))
    def test_pair_key_survives_active_cell_cross_but_not_retired_roots(self):
        geometry=Geometry.__new__(Geometry);geometry.r=self.m
        before=geometry.key(self.m.base(1));self.assertEqual(before,geometry.key(self.m.base(0)))
        self.m.roots[0]+=0x1000
        self.assertNotEqual(before,geometry.key(self.m.base(0)))
    def test_completed_background_graph_cannot_be_adopted_for_replaced_roots(self):
        geometry=Geometry.__new__(Geometry);geometry.r=self.m;geometry.scene_key='retained'
        old=dict(shapes=[{}],roots=['0xdeadbeef'],cell_ptr=self.m.base(1)['cell_ptr'])
        with self.assertRaisesRegex(RuntimeError,'retired roots'):geometry.refresh(self.m.base(1),prepared_scene=old)
        self.assertEqual(geometry.scene_key,'retained')
    def test_missing_or_pending_neighbor_is_never_replaced_by_old_geometry(self):
        for state in (0,2,3,4,5):
            self.m.states[0]=state
            with self.subTest(state=state):
                cells=render_cells(self.m,self.m.base(1))
                self.assertEqual([c['grid']for c in cells],[(-2,-9)])
                self.assertFalse(render_cells(self.m,self.m.base(1),[dict(cell_ptr=hex(self.m.cell_pointers[0]),roots=[hex(self.m.roots[0]),hex(self.m.roots[0]+0x100),hex(0x60000)])])[1])
        self.m.states=[1,1]
        self.assertEqual(len(render_cells(self.m,self.m.base(1))),2)
    def test_duplicate_grid_and_nonmember_active_cell_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'Active cell is not committed'):render_cells(self.m,{**self.m.base(1),'cell_ptr':'0xdeadbeef'})
        self.m.grids=((-2,-9),(-2,-9))
        with self.assertRaisesRegex(RuntimeError,'changed during capture'):loaded_exteriors(self.m,self.m.data)

    def test_approaching_view_prefetches_before_visible_boundary_and_caps_cells(self):
        base=self.m.base(1);base['camera']['position']=[-16100,-65700,300]
        base['camera']['frustum']=[-.01,.01,.01,-.01,1,100]
        self.assertEqual(desired_grids(base,False),{(-2,-9)})
        self.assertEqual(desired_grids(base),{(-3,-9),(-3,-8),(-2,-9),(-2,-8)})
        base['camera']['frustum']=[-10,10,10,-10,1,10000]
        self.assertEqual(len(desired_grids(base)),6)
        base['camera']['frustum'][-1]=25000
        with self.assertRaisesRegex(ValueError,'Unsupported streaming frustum'):desired_grids(base)

    def test_retained_roots_are_checked_against_all_native_residents(self):
        base=self.m.base(1);old=render_cells(self.m,base)
        base.pop('camera');selected,safe=render_cells(self.m,base,old)
        self.assertEqual(len(selected),1);self.assertTrue(safe)
        self.m.roots[0]+=0x1000
        self.assertFalse(render_cells(self.m,base,old)[1])

    def test_retained_cell_generation_survives_selection_and_reentry_gets_new_id(self):
        geometry=Geometry.__new__(Geometry);geometry.cell_generations={};geometry.generation_counter=0
        cells=render_cells(self.m,self.m.base(1));first=geometry.assign_cells(cells).copy()
        kept=geometry.assign_cells(cells[1:]).copy()
        self.assertEqual(first[cells[1]['key']],kept[cells[1]['key']])
        reentered=geometry.assign_cells(cells)
        self.assertNotEqual(first[cells[0]['key']],reentered[cells[0]['key']])
        self.assertEqual(first[cells[1]['key']],reentered[cells[1]['key']])
        self.assertEqual(len(geometry.cell_generations),2)

class GraphTests(unittest.TestCase):
    def test_each_cells_land_root_is_terrain_and_ownership_is_retained(self):
        class GraphMemory:
            def __init__(self):self.bytes={}
            def put(self,address,data):self.bytes.update({address+i:v for i,v in enumerate(data)})
            def read(self,address,size):return bytes(self.bytes.get(address+i,0)for i in range(size))
            def u32(self,address):return struct.unpack('<I',self.read(address,4))[0]
            def string(self,address,limit=256):return ''
        m=GraphMemory();m.put(0x7c67e0,struct.pack('<I',0x10000));m.put(0x1b540,struct.pack('<I',0x20000))
        cells=[]
        for index,grid in enumerate(((-2,-9),(-2,-8))):
            root=0x30000+index*0x10000;roots=[]
            for j in range(3):
                p=root+j*0x1000;roots.append(hex(p));header=bytearray(0xa4);struct.pack_into('<I',header,0,0xaaa)
                if j!=1:
                    struct.pack_into('<3I',header,0x94,p+0x400,1,1);m.put(p+0x400,struct.pack('<I',p+0x200))
                    shape=bytearray(0xa0);struct.pack_into('<I',shape,0,0xbbb)
                    struct.pack_into('<13f',shape,0x40,1,0,0,0,1,0,0,0,1,0,0,0,1)
                    struct.pack_into('<2I',shape,0x98,p+0x600,0);m.put(p+0x200,shape)
                    model=bytearray(0x36);struct.pack_into('<H',model,8,3);struct.pack_into('<H',model,0x34,1);m.put(p+0x600,model)
                m.put(p,header)
            cell=0x20000+index*0x1000;land=cell+0x400
            header=bytearray(0x1c);struct.pack_into('<I',header,0,int(roots[0],16));struct.pack_into('<I',header,0xc,land);struct.pack_into('<I',header,0x18,int(roots[1],16))
            m.put(cell+0x14,header);m.put(land+0x10,struct.pack('<I',int(roots[2],16)))
            cells.append(dict(key=f'exterior:{grid[0]},{grid[1]}',roots=roots,cell_ptr=hex(cell)))
        reader=SceneReader(m);reader.types={0xaaa:['NiNode'],0xbbb:['NiTriShape']}
        scene=reader.collect(cells=cells)
        self.assertFalse(scene['errors']);self.assertEqual(len(scene['shapes']),4)
        self.assertEqual(len(scene['cell_root_owners']),6)
        for c in cells:
            members=[s for s in scene['shapes'] if s['cell_key']==c['key']]
            self.assertEqual(len(members),2);self.assertEqual(sum(s['terrain']for s in members),1)

if __name__=='__main__':unittest.main()
