import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from native_attributes import MORPH,discover,capture,AttributeCapture
from geometry_stream import Geometry
from game_assets import Assets
from live_probe import SceneReadChanged
from live_binary import encode,decode
from skin_math import Skin
from test_scene_lifecycle import Memory,Graph


class AttributeMemory(Memory):
    colors=True;uv=0.;controller_type=MORPH;target=0x40000
    color=bytes([10,20,30,40])*3
    indices=(0,1,2)
    def read(self,p,n):
        if p==0x50000:
            raw=bytearray(super().read(p,n));struct.pack_into('<H',raw,8,3);struct.pack_into('<H',raw,0x34,1)
            struct.pack_into('<I',raw,0x24,0x80000 if self.colors else 0);struct.pack_into('<I',raw,0x28,0x90000);return bytes(raw)
        if p==0x80000:return self.color
        if p==0x70000:return struct.pack('<3H',*self.indices)
        if p==0x90000:return struct.pack('<6f',self.uv,0,1,0,0,1)
        if p==0xc0000:
            raw=bytearray(0x30);struct.pack_into('<I',raw,0,self.controller_type);struct.pack_into('<I',raw,0x28,self.target);return bytes(raw)
        return super().read(p,n)
    def u32(self,p):
        if p==0x7c67e0:return 0x20000
        if p==0x2b540:return self.cell
        return struct.unpack('<I',self.read(p,4))[0]
    def shape(self):return dict(id='0x40000',model='0x50000',skin='0x0',controller='0xc0000',vertex_count=3,triangle_count=1,cell_key='aux:sky')


class AttributeTests(unittest.TestCase):
    def test_native_near_pass_sun_flare_streams_current_vertices_alpha_and_uv_without_world_false_positives(self):
        r=AttributeMemory();shape={**r.shape(),'controller':'0x0','cell_key':'view:first-person','texture':'Textures\\tx_sun_flash_grey_05.dds'}
        item=discover(r,shape);self.assertIsNotNone(item);self.assertTrue(item['colors']);self.assertTrue(item['uvs'])
        prepared=AttributeCapture([item]);r.coordinate=12;r.uv=.25;first=capture(r,prepared)[item['shape']]
        r.coordinate=13;r.uv=.5;r.color=bytes([1,2,3,90])*3;second=capture(r,prepared)[item['shape']]
        self.assertEqual(first[0][0,0],12);self.assertEqual(second[0][0,0],13);self.assertEqual(second[2][0,0],.5)
        self.assertAlmostEqual(float(second[1][0,3]),90/255)
        self.assertIsNone(discover(r,{**shape,'cell_key':'interior:1'}))
    def test_native_water_and_ripples_copy_current_vertices_colors_and_uvs_without_controllers(self):
        r=AttributeMemory()
        for layer in('aux:water','aux:ripple'):
            item=discover(r,{**r.shape(),'controller':'0x0','cell_key':layer})
            self.assertFalse(item['morph']);self.assertTrue(item['colors']);self.assertTrue(item['uvs'])
            prepared=AttributeCapture([item]);r.coordinate=8;r.uv=.125;r.color=bytes([5,10,20,60])*3
            first=capture(r,prepared)[0x40000]
            r.coordinate=9;r.uv=.75;r.color=bytes([5,10,20,120])*3
            second=capture(r,prepared)[0x40000]
            self.assertEqual(first[0][0,0],8);self.assertEqual(second[0][0,0],9)
            self.assertEqual(first[2][0,0],.125);self.assertEqual(second[2][0,0],.75)
            self.assertAlmostEqual(float(second[1][0,3]),120/255)
            self.assertAlmostEqual(float(first[1][0,3]),60/255) # independent owned snapshots
        self.assertIsNone(discover(r,{**r.shape(),'controller':'0x0','cell_key':'interior:1'}))

    def test_prepared_water_capture_batches_and_rejects_replaced_buffers(self):
        class Batched(AttributeMemory):
            calls=0;replace=False
            def read_many(self,plan):
                self.calls+=1
                blocks={p:self.read(p,n)for p,n in plan}
                if self.replace and self.calls%2==0:
                    raw=bytearray(blocks[0x50000]);struct.pack_into('<I',raw,0x28,0xa0000);blocks[0x50000]=bytes(raw)
                return blocks
        r=Batched();item=discover(r,{**r.shape(),'controller':'0x0','cell_key':'aux:water'});prepared=AttributeCapture([item])
        capture(r,prepared);self.assertEqual(r.calls,2)
        r.replace=True
        with self.assertRaises(SceneReadChanged):capture(r,prepared)

    def test_resolved_vertices_and_bgra_colors_follow_original_buffers(self):
        r=AttributeMemory();item=discover(r,r.shape());r.coordinate=4;r.revision=19
        vertices,colors,uvs=capture(r,[item])[0x40000]
        self.assertEqual(vertices[0,0],4)
        np.testing.assert_allclose(colors[0],[30/255,20/255,10/255,40/255])
        r.coordinate=-3;self.assertEqual(capture(r,[item])[0x40000][0][0,0],-3)

    def test_static_worlds_use_shared_meshes_and_morph_targets_are_guarded(self):
        r=AttributeMemory();s={**r.shape(),'controller':'0x0','cell_key':'interior:1'};self.assertIsNone(discover(r,s))
        r.colors=False;self.assertTrue(discover(r,{**s,'controller':'0xc0000'})['morph'])
        r.target+=4
        with self.assertRaisesRegex(SceneReadChanged,'target'):discover(r,r.shape())

    def test_mutable_identity_and_resource_budget_fail_closed(self):
        r=AttributeMemory();item=discover(r,r.shape());r.colors=False
        with self.assertRaisesRegex(SceneReadChanged,'identity'):capture(r,[item])
        with self.assertRaisesRegex(ValueError,'budget'):capture(r,[dict(count=65537)])

    def test_real_catalog_stays_fixed_while_binary_pose_vertices_and_colors_change(self):
        r=AttributeMemory()
        class G(Graph):
            def collect(self):
                scene=super().collect();scene['shapes'][0].update(r.shape());return scene
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            out=Path(folder);(out/'meshes').mkdir();(out/'textures').mkdir()
            a=Assets.__new__(Assets);a.r=r;a.out=out;a.meshes={};a.textures={};a.missing=[];a.archives=[]
            with patch('geometry_stream.SceneReader',return_value=G(r)),patch('geometry_stream.Assets',return_value=a):g=Geometry(r)
            base=dict(world='0x10000',data='0x20000',cell_ptr=hex(r.cell),camera=dict(position=[0,0,0],forward=[0,1,0],up=[0,0,1],frustum=[-1,1,1,-1,1,100],fov=90))
            g.refresh(base);catalog=g.catalog;asset=g.shapes[0]['asset'];definition=json.loads((out/catalog).read_text())['meshes'][asset]
            mesh=(out/definition['file']).read_bytes();self.assertEqual(mesh[12:48],bytes(36))
            raw=bytearray(0xac);struct.pack_into('<4f',raw,0x1c,0,10,0,5);struct.pack_into('<2I',raw,0x98,0x50000,0)
            struct.pack_into('<13f',raw,0x40,1,0,0,0,1,0,0,0,1,0,10,0,1)
            g.capture_pose=lambda b:(base,{0x40000:raw},{},capture(r,list(g.native_attributes.values())),{})
            for i in range(5):
                r.coordinate=float(i);r.revision=i;r.color=bytes([10,20,30,40+i])*3
                g.refresh(base);self.assertEqual(g.catalog,catalog);self.assertEqual(g.shapes[0]['asset'],asset)
                sample=g.snapshot(base,prepared=True)
                packet={**sample,'session':'11112222-3333-4444-5555-666677778888','sequence':i,'sample_unix_ns':1.8e18,'pid':42}
                rows=decode(encode(packet),packet)['instance_states']
                self.assertEqual(rows[0][2]['points'][:3],[float(i),10.,0.]);self.assertAlmostEqual(rows[0][2]['colors'][3],(40+i)/255)
            self.assertEqual((out/definition['file']).read_bytes(),mesh);self.assertEqual(len(a.meshes),1)
            r.uv=.5;g.refresh(base);self.assertEqual(g.catalog,catalog)
            self.assertAlmostEqual(g.snapshot(base,prepared=True)['instance_states'][0][2]['uvs'][0],.5)
            r.indices=(2,1,0);g.refresh(base);self.assertNotEqual(g.catalog,catalog) # actual topology edits remain distinct

    def test_native_morph_vertices_preserve_all_skin_influences(self):
        skin=Skin.__new__(Skin);skin.shape=1;skin.root=2;skin.bones=(3,);skin.skin_transform=np.eye(4)
        skin.vertices=np.zeros((2,3));skin.binds=[np.eye(4)];skin.weight_sets=[(np.array([0,0]),np.array([.3,.4]))];skin.sums=np.array([.7,0.])
        worlds={k:np.eye(4)for k in (1,2,3)};worlds[3][0,3]=10;worlds[1][1,3]=2
        local=np.array([[1,0,0],[2,3,4]])
        result=skin.deform(worlds,strict=True,vertices=local)
        np.testing.assert_allclose(result,[[7.7,1.4,0],[2,5,4]])
        np.testing.assert_array_equal(skin.vertices,np.zeros((2,3)))


if __name__=='__main__':unittest.main()
