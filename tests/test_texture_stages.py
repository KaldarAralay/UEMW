import hashlib,struct,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from native_materials import discover,capture,FlipCapture
from native_texture_stages import read,convert
from test_native_materials import MaterialMemory
from live_probe import SceneReadChanged

class StageTests(unittest.TestCase):
    def memory(self,slot=4):
        r=MaterialMemory();r.blocks[0x30000]=bytearray((slot+1)*4)
        struct.pack_into('<I',r.blocks[0x30000],slot*4,0x32000)
        struct.pack_into('<2I',r.blocks[0x10000],0x24,slot+1,slot+1)
        struct.pack_into('<I',r.blocks[0x10000],0x18,2)
        struct.pack_into('<I',r.blocks[0x20000],0x50,slot)
        struct.pack_into('<3I',r.blocks[0x32000],8,3,5,0)
        return r
    def test_secondary_flip_uses_resolved_map_and_fences_slot(self):
        r=self.memory();self.assertIsNone(discover(r,0x10000))
        stages=read(r,0x10000,'native');self.assertEqual([s['slot']for s in stages['maps']],[4])
        self.assertEqual(stages['maps'][0]['kind'],'glow')
        f=stages['maps'][0]['flip'];compiled=FlipCapture({f['id']:f})
        self.assertEqual(capture(r,compiled)['frames'][f['id']],0)
        struct.pack_into('<I',r.blocks[0x32000],4,0x51000)
        self.assertEqual(capture(r,compiled)['frames'][f['id']],1)
        struct.pack_into('<I',r.blocks[0x30000],16,0)
        with self.assertRaises(SceneReadChanged):capture(r,compiled)
    def test_export_is_stable_across_flip_and_retains_original_sampler(self):
        r=self.memory();a=SimpleNamespace(r=r,used_textures=set(),texture=lambda name:'textures/'+name+'.png')
        one,flips=convert(a,{},read(r,0x10000));struct.pack_into('<I',r.blocks[0x32000],4,0x51000)
        two,_=convert(a,{},read(r,0x10000));self.assertEqual(one,two)
        self.assertEqual(one['maps'][0]['animation']['frames'],['textures/water0.dds.png','textures/water1.dds.png'])
        self.assertEqual((one['maps'][0]['clamp'],one['maps'][0]['filter']),(3,5))
        self.assertEqual(len(flips),1)
    def test_map_settings_and_property_replacements_reject(self):
        for address,offset,value in ((0x10000,0,0),(0x10000,0x18,5),(0x10000,0x28,17),(0x32000,8,4),(0x32000,12,6),(0x32000,16,8)):
            r=self.memory();struct.pack_into('<I',r.blocks[address],offset,value)
            with self.subTest(change=(address,offset,value)),self.assertRaises((ValueError,SceneReadChanged)):read(r,0x10000)
        r=self.memory();struct.pack_into('<I',r.blocks[0x10000],0x18,3)
        a=SimpleNamespace(used_textures=set(),texture=lambda name:'textures/'+name+'.png');recipe,_=convert(a,{},read(r,0x10000))
        self.assertEqual(recipe['apply'],3);self.assertIn('modulate fallback',recipe['unsupported'][0]['reason'])
    def test_generated_and_rendered_sources_stay_explicit_without_dropping_geometry(self):
        for generated in (True,False):
            r=self.memory();struct.pack_into('<I',r.blocks[0x10000],0x10,0)
            if generated:r.string=lambda p,n:''
            else:struct.pack_into('<I',r.blocks[0x50000],0,0)
            stages=read(r,0x10000);self.assertFalse(stages['maps'][0]['supported'])
            a=SimpleNamespace(used_textures=set(),texture=lambda name:self.fail('A non-file stage must not invent a source file'))
            recipe,_=convert(a,{},stages);self.assertFalse(recipe['maps'][0]['supported']);self.assertEqual(recipe['maps'][0]['texture'],'');self.assertTrue(recipe['unsupported'])
    def test_uv_sidecar_uses_original_set_and_has_no_skin_index_overlap(self):
        r=self.memory(2);struct.pack_into('<I',r.blocks[0x32000],16,1)
        model=bytearray(0x34);struct.pack_into('<2H',model,8,3,2);struct.pack_into('<I',model,0x28,0x80000);r.blocks[0x70000]=model
        coords=np.asarray([[[0,0],[1,0],[0,1]],[[.25,.5],[2,0],[0,3]]],dtype='<f4');r.blocks[0x80000]=coords.tobytes()
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            root=Path(folder);(root/'meshes').mkdir();a=SimpleNamespace(r=r,out=root,used_textures=set(),texture=lambda name:'textures/'+name+'.png')
            result,_=convert(a,dict(model='0x70000',vertex_count=3),read(r,0x10000))
            raw=(root/result['uv_file']).read_bytes();self.assertEqual(struct.unpack_from('<4sII',raw),(b'UUV1',3,3))
            packed=np.frombuffer(raw,dtype='<f4',offset=12).reshape(3,3,2)
            np.testing.assert_array_equal(packed[:,1],coords[1]);np.testing.assert_array_equal(packed[:,0],coords[0]);np.testing.assert_array_equal(packed[:,2],coords[0])
            self.assertIn(hashlib.sha256(raw).hexdigest(),result['uv_file'])
            dynamic_shape=dict(model='0x70000',vertex_count=3,dynamic_attributes=dict(uvs=True))
            before,_=convert(a,dynamic_shape,read(r,0x10000));coords[0]+=.375;r.blocks[0x80000]=coords.tobytes()
            after,_=convert(a,dynamic_shape,read(r,0x10000));self.assertEqual(before['uv_file'],after['uv_file'])
            r.blocks[0x80000]=np.full((2,3,2),np.nan,dtype='<f4').tobytes()
            with self.assertRaisesRegex(ValueError,'UVs'):convert(a,dict(model='0x70000',vertex_count=3),read(r,0x10000))
