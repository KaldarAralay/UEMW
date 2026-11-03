"""Owned scenery records, exact LAND borders and strict static NIF fixtures."""
import math,struct,tempfile,unittest
from pathlib import Path
import numpy as np
from tes3_world import WorldIndex,heights,references,source_id
from distant_terrain import mesh,texture_grid
from distant_native import NativeStatics,rotation
from nif_static import shapes,parse,UnsupportedNif
from live_probe import SceneReadChanged
from distant_stream import live_source,fingerprint,collect_cache,Worker
from distant_assets import write_mesh


def sub(k,v):return k+struct.pack('<I',len(v))+v
def record(k,v):return struct.pack('<4sIII',k,len(v),0,0)+v
def string(v):v=v.encode();return struct.pack('<I',len(v))+v
def net(name='',controller=-1):return string(name)+struct.pack('<2i',-1,controller)
def av(name='',position=(0,0,0),scale=1,props=(),controller=-1):
    return net(name,controller)+struct.pack('<H',10)+struct.pack('<3f',*position)+np.eye(3,dtype='<f4').tobytes()+struct.pack('<4f',scale,0,0,0)+struct.pack('<I',len(props))+b''.join(struct.pack('<i',i)for i in props)+struct.pack('<I',0)


def nif(controller=-1,bad_index=False,collision=False):
    root=av('RootCollisionNode'if collision else'root',(1,2,3),2,controller=controller)+struct.pack('<3I',1,1,0)
    node=av('owned-shape',(4,5,6))+struct.pack('<2i',2,-1)
    data=struct.pack('<HI',3,0x18d4c20)+np.asarray([[0,0,0],[1,0,0],[0,1,0]],dtype='<f4').tobytes()
    data+=struct.pack('<I',0)+struct.pack('<4f',0,0,0,1)+struct.pack('<IH',0,1)+struct.pack('<I',1)+bytes(3*8)
    data+=struct.pack('<HI3HH',1,3,0,1,3 if bad_index else 2,0)
    return b'NetImmerse File Format, Version 4.0.0.2\n'+struct.pack('<II',0x04000002,3)+string('NiNode')+root+string('NiTriShape')+node+string('NiTriShapeData')+data+struct.pack('<Ii',1,0)


class DistantTests(unittest.TestCase):
    def test_bake_cannot_renew_state_that_changed_during_conversion(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        w=Worker.__new__(Worker);w.pid=42;w.session='owned';w.epoch='epoch';w.key=None;w.prepared=None;w.history=[]
        w.source=lambda:dict(scene_epoch='epoch',cell_grid=[0,0],sample_unix_ns=1)
        ref=dict(position=[1,2,3],disabled=False);a=((0,0),[],{7:ref},{},set(),100)
        b=((0,0),[],{7:{**ref,'disabled':True}},{},set(),200)
        captures=iter((a,b));w.capture=lambda s:next(captures);w.builder=SimpleNamespace(build=lambda *a:dict(catalog='owned',poses='owned'))
        with patch('distant_stream.collect_cache',return_value=100):
            with self.assertRaises(SceneReadChanged):w.tick()
        self.assertIsNone(w.prepared);self.assertEqual(w.history,[])

    def test_distant_lease_requires_current_native_exterior_source(self):
        v=dict(protocol='uemw.live',version=5,status='live',pid=42,session='owned',scene_epoch='epoch',sample_unix_ns=1000000000,cell_flags=126,cell_grid=[-2,-9])
        self.assertTrue(live_source(v,42,'owned',1200000000))
        self.assertFalse(live_source(v,42,'owned',1500000001));self.assertFalse(live_source(v,43,'owned',1200000000))
        self.assertFalse(live_source({**v,'cell_flags':1},42,'owned',1200000000));self.assertFalse(live_source({**v,'status':'no_scene'},42,'owned',1200000000))
        a={7:dict(reference='0x123',target=7,position=[1,2,3],disabled=False)}
        b={7:{**a[7],'reference':'0x456'}}
        self.assertEqual(fingerprint([0,0],a,{},set()),fingerprint([0,0],b,{},set()))
        self.assertNotEqual(fingerprint([0,0],a,{},set()),fingerprint([0,0],{7:{**a[7],'disabled':True}},{},set()))

    def test_exported_mesh_guards_indices_before_unsigned_conversion(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as p:
            folder=Path(p);(folder/'meshes').mkdir()
            points=[[0,0,0],[1,0,0],[0,1,0]];uv=[[0,0]]*3;c=[[255]*4]*3
            d=write_mesh(folder,points,None,uv,c,[[0,1,2]])
            self.assertEqual((folder/d['file']).read_bytes()[:4],b'UEM2')
            for bad in(-1,65536,float('nan'),.5):
                with self.assertRaises(ValueError):write_mesh(folder,points,None,uv,c,[[0,1,bad]])

    def test_cache_collection_preserves_current_resources_and_rejects_oversize(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as p:
            from types import SimpleNamespace
            import json
            f=Path(p);(f/'meshes').mkdir();(f/'meshes/keep.umesh').write_bytes(b'owned');(f/'meshes/old.umesh').write_bytes(b'old');(f/'catalog-current.json').write_text(json.dumps(dict(meshes={'file':'meshes/keep.umesh'})));(f/'poses.udf').write_bytes(b'owned')
            b=SimpleNamespace(folder=f,prototypes={},terrain_cache={},assets=SimpleNamespace(textures={}))
            history=[dict(catalog='catalog-current.json',poses='poses.udf')]
            collect_cache(b,history);self.assertTrue((f/'meshes/keep.umesh').is_file());self.assertFalse((f/'meshes/old.umesh').exists())
            with self.assertRaises(ValueError):collect_cache(b,history,budget=1)

    def test_installed_master_reference_identity_and_partial_override(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as p:
            folder=Path(p);head=record(b'TES3',b'')
            stat=record(b'STAT',sub(b'NAME',b'owned-rock\0')+sub(b'MODL',b'x/owned.nif\0'))
            base=sub(b'NAME',b'')+sub(b'DATA',struct.pack('<I2i',0,-2,-9))
            ref=sub(b'FRMR',struct.pack('<I',7))+sub(b'NAME',b'owned-rock\0')+sub(b'DATA',struct.pack('<6f',1,2,3,.1,.2,.3))
            (folder/'Morrowind.esm').write_bytes(head+stat+record(b'CELL',base+ref))
            override=sub(b'FRMR',struct.pack('<I',0x01000007))+sub(b'XSCL',struct.pack('<f',.5))
            (folder/'Tribunal.esm').write_bytes(record(b'TES3',sub(b'MAST',b'Morrowind.esm\0'))+record(b'CELL',base+override))
            (folder/'Bloodmoon.esm').write_bytes(head)
            w=WorldIndex(folder);actual=w.statics((-2,-9))[0x01000007]
            self.assertEqual(actual['position'],(1,2,3));self.assertEqual(actual['scale'],.5);self.assertEqual(actual['model'],'x/owned.nif')
            (folder/'Morrowind.esm').write_bytes(b'changed')
            with self.assertRaises(RuntimeError):w.statics((-2,-9))

    def test_source_identity_and_corrupt_reference_reject(self):
        self.assertEqual(source_id(0x01000007,3,(1,2)),0x01000007)
        self.assertEqual(source_id(7,3,(1,2)),0x03000007)
        with self.assertRaises(ValueError):source_id(0x03000007,3,(1,2))
        payload=sub(b'FRMR',struct.pack('<I',7))+sub(b'DATA',struct.pack('<6f',float('nan'),0,0,0,0,0))
        with self.assertRaises(ValueError):list(references(payload,1,()))

    def test_height_deltas_and_original_vtex_block_order(self):
        delta=np.zeros((65,65),dtype=np.int8);delta[0,0]=1;delta[1,0]=2;delta[1,1]=-1
        h=heights(struct.pack('<f',3)+delta.tobytes()+bytes(3))
        self.assertEqual(h[0,0],32);self.assertEqual(h[1,0],48);self.assertEqual(h[1,1],40)
        raw=np.arange(256,dtype='<u2').reshape(16,16);out=texture_grid(raw)
        self.assertEqual(out[0,4],16);self.assertEqual(out[4,0],64);self.assertEqual(out[3,3],15)

    def test_terrain_lod_has_all_original_border_samples_and_no_area_gaps(self):
        h=np.arange(65*65,dtype=float).reshape(65,65)
        for step in(1,2,4,8):
            m=mesh(dict(grid=(-2,-9),heights=h),step);samples=set(map(tuple,m['samples']))
            self.assertTrue(all((i,0)in samples and(i,64)in samples and(0,i)in samples and(64,i)in samples for i in range(65)))
            p=m['points'];tri=p[m['indices']];area=np.cross(tri[:,1,:2]-tri[:,0,:2],tri[:,2,:2]-tri[:,0,:2])/2
            self.assertTrue((area>0).all());self.assertAlmostEqual(float(area.sum()),8192**2,delta=1)
            for (x,y),v in zip(m['samples'],p):self.assertEqual(v[2],h[y,x])
            if step>1:self.assertLess(len(p),65*65)

    def test_strict_static_nif_keeps_hierarchy_and_excludes_collision(self):
        out=shapes(nif());self.assertEqual(len(out),1)
        np.testing.assert_array_equal(out[0]['points'],[[9,12,15],[11,12,15],[9,14,15]])
        self.assertEqual(shapes(nif(collision=True)),[])
        with self.assertRaises(UnsupportedNif):shapes(nif(controller=0))
        with self.assertRaises(ValueError):shapes(nif(bad_index=True))
        with self.assertRaises(ValueError):parse(nif()+b'X')

    def test_original_reference_scale_enable_and_identity_guards(self):
        class R:
            data={}
            def read(self,p,n):
                for start,b in self.data.items():
                    if start<=p and p+n<=start+len(b):return bytes(b[p-start:p-start+n])
                return bytes(n)
            def u32(self,p):return struct.unpack('<I',self.read(p,4))[0]
            def string(self,p,limit=256):return 'owned-rock'
        r=R();r.data={0x7c67e0:struct.pack('<I',0x10000),0x10000:struct.pack('<I',0x20000),0x2b264:struct.pack('<I',0x30000),0x30000:struct.pack('<3I',1,0x40000,0x40000),0x40000:struct.pack('<3I',0x50000,0x30004,0x30004)}
        cell=bytearray(0x68);cell[4:8]=b'CELL';struct.pack_into('<2i',cell,0x24,-2,-9);struct.pack_into('<3I',cell,0x40,1,0x60000,0x60000);r.data[0x50000]=cell
        ref=bytearray(0x50);ref[4:8]=b'REFR';struct.pack_into('<I',ref,8,(500<<16)|0x800);struct.pack_into('<I',ref,0x14,0x50040);struct.pack_into('<I',ref,0x28,0x70000);struct.pack_into('<3f',ref,0x38,1,2,3);struct.pack_into('<2I',ref,0x48,0x01000007,7);r.data[0x60000]=ref
        base=bytearray(0x30);base[4:8]=b'STAT';r.data[0x70000]=base
        n=NativeStatics(r);actual=n.overrides([(-2,-9)])[0x01000007]
        self.assertEqual(actual['scale'],.5);self.assertTrue(actual['disabled']);self.assertFalse(actual['deleted'])
        # Native moved references carry their actual current owning cell,
        # including moves into an interior which must suppress old placement.
        struct.pack_into('<I',cell,0x4c,0x50000);struct.pack_into('<I',cell,0x50,0x80000)
        r.data[0x80000]=struct.pack('<4I',0x750000,1,0x81000,0x81000);r.data[0x81000]=struct.pack('<3I',0,0,0x82000);r.data[0x82000]=struct.pack('<4I',0,0x60000,0,0)
        moved,hidden=n.moved();self.assertEqual(moved[0x01000007]['native_grid'],(-2,-9));self.assertFalse(hidden)
        struct.pack_into('<I',cell,0x18,1);moved,hidden=n.moved();self.assertTrue(moved[0x01000007]['interior']);self.assertIsNone(moved[0x01000007]['native_grid']);struct.pack_into('<I',cell,0x18,0)
        r.data[0x82000]=bytes(16);moved,hidden=n.moved();self.assertIn((-2,-9),hidden)
        r.data[0x81000]=struct.pack('<3I',0,0x81000,0x82000)
        with self.assertRaises(SceneReadChanged):n.moved()
        ref[4:8]=b'XXXX'
        with self.assertRaises(SceneReadChanged):n.overrides([(-2,-9)])
        np.testing.assert_allclose(np.asarray(rotation([0,0,math.pi/2])).reshape(3,3)@np.array([1,0,0]),[0,-1,0],atol=1e-7)


if __name__=='__main__':unittest.main()
