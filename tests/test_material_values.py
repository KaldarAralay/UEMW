import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from material_values import MATERIAL,discover,capture
from live_probe import SceneReadChanged
from geometry_stream import Geometry
from game_assets import Assets
from test_scene_lifecycle import Memory,Graph


class MaterialMemory(Memory):
    def __init__(self):
        self.material=bytearray(0x54);struct.pack_into('<I',self.material,0,MATERIAL)
        self.set_values()
    def set_values(self,rgb=(.2,.3,.4),alpha=.5,emission=(.1,.2,.3)):
        struct.pack_into('<3f',self.material,0x28,*rgb);struct.pack_into('<3f',self.material,0x40,*emission);struct.pack_into('<f',self.material,0x50,alpha)
    def read(self,p,n):
        if 0xb0000<=p and p+n<=0xb0054:return bytes(self.material[p-0xb0000:p-0xb0000+n])
        if p==0x50024 and n==4:return struct.pack('<I',0)
        return super().read(p,n)
    def u32(self,p):return struct.unpack('<I',self.read(p,4))[0]
    def shape(self):return dict(material='0xb0000',model='0x50000',cell_key='aux:sky',generation='a1')


class MaterialValueTests(unittest.TestCase):
    def test_static_player_materials_need_no_live_reads_but_animated_materials_keep_fences(self):
        for layer in('view:first-person','aux:player'):
            r=MaterialMemory();shape={**r.shape(),'cell_key':layer}
            self.assertIsNone(discover(r,shape))
            struct.pack_into('<I',r.material,0x10,0xc0000)
            group=discover(r,shape)
            self.assertIsNotNone(group)
            self.assertEqual(capture(r,{group['id']:group})['values'][group['id']][3],.5)
            struct.pack_into('<I',r.material,0x10,0xd0000)
            with self.assertRaises(SceneReadChanged):capture(r,{group['id']:group})

    def test_emissive_only_rain_ignores_white_diffuse_and_keeps_native_alpha(self):
        r=MaterialMemory();r.set_values(rgb=(1,1,1),emission=(.196,.216,.263),alpha=.4)
        group=discover(r,{**r.shape(),'cell_key':'aux:weather','lighting_mode':0})
        row=capture(r,{group['id']:group})['values'][group['id']]
        for actual,wanted in zip(row,[.196,.216,.263,.4,0,0,0,0]):self.assertAlmostEqual(actual,wanted)
        r.set_values(rgb=(1,1,1),emission=(0,0,0),alpha=.25)
        self.assertEqual(capture(r,{group['id']:group})['values'][group['id']],[0,0,0,.25,0,0,0,0])

    def test_vertex_emissive_mode_uses_native_vertex_rgb_once(self):
        r=MaterialMemory();group=discover(r,{**r.shape(),'lighting_mode':0});group['vertex_color']=True
        self.assertEqual(capture(r,{group['id']:group})['values'][group['id']],[1,1,1,.5,0,0,0,0])

    def test_vertex_lighting_property_is_inherited_with_source_mode(self):
        from scene_reader import SceneReader
        class M:
            def read(self,p,n):
                return {0x10088:struct.pack('<2I',0x30000,0),0x20088:bytes(8),0x30018:struct.pack('<2I',0,0)}[p]
        scene=SceneReader(M());scene.ancestry=lambda ptr:['NiVertexColorProperty']
        props=scene.render_properties(0x10000,(1,2,3,2))
        self.assertEqual(props,(1,2,3,0,0));self.assertEqual(scene.render_properties(0x20000,props),props)

    def test_resolved_color_alpha_and_emission_follow_native_values(self):
        r=MaterialMemory();group=discover(r,r.shape());groups={group['id']:group}
        row=capture(r,groups)['values'][group['id']]
        for actual,wanted in zip(row,[.2,.3,.4,.5,.1,.2,.3,1]):self.assertAlmostEqual(actual,wanted)
        # Changes include reversals; the bridge does not compute controller time.
        r.set_values(rgb=(0,0,0),alpha=.25,emission=(.7,.5,.2))
        row=capture(r,groups)['values'][group['id']]
        for actual,wanted in zip(row,[.7,.5,.2,.25,0,0,0,0]):self.assertAlmostEqual(actual,wanted)

    def test_vertex_color_precedence_and_static_materials_are_preserved(self):
        r=MaterialMemory();self.assertIsNone(discover(r,{**r.shape(),'cell_key':'interior:1'}))
        struct.pack_into('<I',r.material,0x10,0xc0000)
        self.assertIsNotNone(discover(r,{**r.shape(),'cell_key':'interior:1'}))
        group=discover(r,r.shape());group['vertex_color']=True
        self.assertEqual(capture(r,{group['id']:group})['values'][group['id']][:3],[1,1,1])

    def test_replaced_or_nonfinite_material_fails_closed(self):
        for offset,value in ((0,MATERIAL+4),(0x10,0xc0000),(0x28,float('nan'))):
            r=MaterialMemory();group=discover(r,r.shape())
            struct.pack_into('<f'if offset==0x28 else'<I',r.material,offset,value)
            with self.subTest(offset=offset),self.assertRaises((SceneReadChanged,ValueError)):capture(r,{group['id']:group})

    def test_real_converter_keeps_catalog_and_mesh_stable_through_native_fades(self):
        r=MaterialMemory()
        class G(Graph):
            def collect(self):
                scene=super().collect();scene['shapes'][0].update(material='0xb0000',cell_key='aux:sky');return scene
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            out=Path(folder);(out/'meshes').mkdir();(out/'textures').mkdir()
            a=Assets.__new__(Assets);a.r=r;a.out=out;a.meshes={};a.textures={};a.missing=[];a.archives=[]
            with patch('geometry_stream.SceneReader',return_value=G(r)),patch('geometry_stream.Assets',return_value=a):g=Geometry(r)
            base=dict(world='0x10000',data='0x20000',cell_ptr=hex(r.cell))
            g.refresh(base);catalog=g.catalog;asset=g.shapes[0]['asset']
            data=json.loads((out/catalog).read_text());definition=data['meshes'][asset];mesh=(out/definition['file']).read_bytes()
            for alpha in (.9,.01,.65,0,1):
                r.set_values(rgb=(.9,.8,.7),alpha=alpha);g.refresh(base)
                self.assertEqual(g.catalog,catalog);self.assertEqual(g.shapes[0]['asset'],asset)
                self.assertEqual((out/definition['file']).read_bytes(),mesh)
                self.assertAlmostEqual(next(iter(capture(r,g.material_values)['values'].values()))[3],alpha)
            self.assertEqual(len(a.meshes),1)
            self.assertEqual(mesh[-18:-6],bytes([255])*12) # raw vertex RGBA stays untinted
            self.assertEqual(definition['material_state'],next(iter(g.material_values)))


if __name__=='__main__':unittest.main()
