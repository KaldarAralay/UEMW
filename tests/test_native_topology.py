"""Owned buffers for the verified vanilla strip/line draw conventions."""
import struct,tempfile,unittest
from pathlib import Path
import numpy as np
from game_assets import Assets
from live_probe import SceneReadChanged
from native_topology import strip_indices,line_pairs,STRIPS_DATA,LINES_DATA
from scene_reader import SceneReader
from native_attributes import identity


class TopologyTests(unittest.TestCase):
    def test_scene_traversal_recognizes_both_native_geometry_classes(self):
        class M:
            blocks={}
            def u32(self,p):
                if p==0x7c67e0:return 0x10000
                if p==0x1b540:return 0x20000
                return struct.unpack('<I',self.read(p,4))[0]
            def read(self,p,n):
                for start,data in self.blocks.items():
                    if start<=p and p+n<=start+len(data):return bytes(data[p-start:p-start+n])
                return bytes(n)
            def string(self,p,limit=256):return ''
        for name,table in (('NiTriStrips',STRIPS_DATA),('NiLines',LINES_DATA)):
            m=M();m.blocks={};node=bytearray(0xa0);struct.pack_into('<I',node,0,0x99999);struct.pack_into('<I',node,0x98,0x50000)
            struct.pack_into('<13f',node,0x40,1,0,0,0,1,0,0,0,1,0,0,0,1);m.blocks[0x40000]=node
            model=bytearray(0x48);struct.pack_into('<I',model,0,table);struct.pack_into('<H',model,8,3)
            if name=='NiLines':struct.pack_into('<I',model,0x34,0x60000);m.blocks[0x60000]=bytes((1,0,0))
            else:struct.pack_into('<H',model,0x34,1)
            m.blocks[0x50000]=model;scene=SceneReader(m);scene.types={0x99999:[name,'NiGeometry']}
            result=scene.collect(roots=[0x40000]);self.assertFalse(result['errors']);self.assertEqual(len(result['shapes']),1)
            self.assertEqual(result['shapes'][0]['topology'],'lines'if name=='NiLines'else'strips')

    def test_mutable_strip_identity_fences_point_storage_and_line_identity_fences_flags(self):
        r,h=self.strips([3],[0,1,2]);before=identity(h,'strips');struct.pack_into('<I',h,0x40,0x99999)
        self.assertNotEqual(before,identity(h,'strips'))
        h=bytearray(0x38);struct.pack_into('<I',h,0,LINES_DATA);struct.pack_into('<I',h,0x34,0x20000)
        before=identity(h,'lines');struct.pack_into('<I',h,0x34,0x30000);self.assertNotEqual(before,identity(h,'lines'))
    def strips(self,lengths,points,vertices=12,triangles=None):
        h=bytearray(0x48);struct.pack_into('<I',h,0,STRIPS_DATA);struct.pack_into('<H',h,8,vertices)
        struct.pack_into('<H',h,0x34,sum(n-2 for n in lengths)if triangles is None else triangles)
        struct.pack_into('<H',h,0x38,len(lengths));struct.pack_into('<2I',h,0x3c,0x20000,0x30000)
        class M:
            def read(self,p,n):return {0x20000:np.asarray(lengths,dtype='<u2').tobytes(),0x30000:np.asarray(points,dtype='<u2').tobytes()}[p][:n]
        return M(),h

    def test_native_strip_winding_resets_at_each_strip_and_keeps_degenerates(self):
        r,h=self.strips([5,4],[0,1,2,3,4,5,6,6,7])
        output=np.frombuffer(strip_indices(r,0x10000,h,12,5),dtype='<u2').reshape(-1,3)
        np.testing.assert_array_equal(output,[[0,1,2],[2,1,3],[2,3,4],[5,6,6],[6,6,7]])

    def test_strip_corruption_and_recycled_type_cannot_be_translated(self):
        r,h=self.strips([4],[0,1,2,3])
        with self.assertRaises(SceneReadChanged):strip_indices(r,0x10000,h,11,2)
        struct.pack_into('<I',h,0,0x99999)
        with self.assertRaises(SceneReadChanged):strip_indices(r,0x10000,h,12,2)
        for lengths,points in (([4],[0,1,2,12]),([2],[0,1]),([3],[0,1])):
            r,h=self.strips(lengths,points)
            with self.assertRaises(ValueError):strip_indices(r,0x10000,h,12,sum(n-2 for n in lengths))

    def test_line_flags_preserve_disconnected_segments_and_explicit_closure(self):
        h=bytearray(0x38);struct.pack_into('<I',h,0,LINES_DATA);struct.pack_into('<H',h,8,4);struct.pack_into('<I',h,0x34,0x20000)
        class M:
            flags=bytes((1,0,1,1))
            def read(self,p,n):return self.flags[:n]
        r=M();self.assertEqual(line_pairs(r,h,4),[(0,1),(2,3),(3,0)])
        r.flags=bytes(4);self.assertEqual(line_pairs(r,h,4),[])
        r.flags=bytes((1,0,2,0))
        with self.assertRaises(ValueError):line_pairs(r,h,4)
        struct.pack_into('<I',h,0,0x99999)
        with self.assertRaises(SceneReadChanged):line_pairs(r,h,4)

    def test_actual_asset_conversion_uses_line_carrier_and_invalidates_changed_flags(self):
        class M:
            flags=bytes((1,0,1,0))
            def read(self,p,n):
                if p==0x10000:
                    h=bytearray(0x38);struct.pack_into('<I',h,0,LINES_DATA);struct.pack_into('<H',h,8,4)
                    struct.pack_into('<I',h,0x1c,0x20000);struct.pack_into('<I',h,0x34,0x30000);return bytes(h[:n])
                if p==0x20000:return np.asarray([[0,0,0],[10,0,0],[10,10,0],[0,10,0]],dtype='<f4').tobytes()[:n]
                if p==0x30000:return self.flags[:n]
                raise AssertionError((p,n))
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            a=Assets.__new__(Assets);a.r=M();a.out=Path(folder);(a.out/'meshes').mkdir();a.meshes={};a.textures={};a.material_values={};a.archives=[];a.missing=[]
            shape=dict(model='0x10000',topology='lines',vertex_count=4,triangle_count=2,texture='')
            d=a.mesh(shape);raw=(a.out/d['file']).read_bytes();self.assertEqual(raw[:4],b'UML2');self.assertFalse(d['shading']['lit'])
            np.testing.assert_array_equal(np.frombuffer(raw,dtype='<u2',offset=12+4*24),[0,1,1,2,3,3])
            a.r.flags=bytes((0,1,0,1));new=a.mesh(shape);self.assertNotEqual(new['asset'],d['asset'])


if __name__=='__main__':unittest.main()
