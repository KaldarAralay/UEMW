import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from native_materials import discover,capture,FlipCapture,FLIP,TEXTURING,SOURCE_TEXTURE
from read_batch import copy_ranges
from live_probe import SceneReadChanged
from geometry_stream import Geometry
from game_assets import Assets
from test_scene_lifecycle import Memory,Graph


class MaterialMemory:
    def __init__(self):
        self.blocks={0x10000:bytearray(0x34),0x20000:bytearray(0x60),0x30000:bytearray(4),0x32000:bytearray(20),0x40000:bytearray(8),0x50000:bytearray(0x40),0x51000:bytearray(0x40)}
        for p,offset,value in ((0x10000,0,TEXTURING),(0x10000,0x10,0x20000),(0x10000,0x20,0x30000),(0x10000,0x24,1),(0x10000,0x28,1),
            (0x20000,0,FLIP),(0x20000,0x28,0x10000),(0x20000,0x38,0x40000),(0x20000,0x3c,2),(0x20000,0x40,2),
            (0x30000,0,0x32000),(0x32000,4,0x50000),(0x40000,0,0x50000),(0x40000,4,0x51000),
            (0x50000,0,SOURCE_TEXTURE),(0x50000,0x2c,0x60000),(0x51000,0,SOURCE_TEXTURE),(0x51000,0x2c,0x61000)):
            struct.pack_into('<I',self.blocks[p],offset,value)
    def read(self,p,n):
        for start,block in self.blocks.items():
            if start<=p and p+n<=start+len(block):return bytes(block[p-start:p-start+n])
        raise AssertionError((hex(p),n))
    def u32(self,p):return struct.unpack('<I',self.read(p,4))[0]
    def string(self,p,n):return {0x60000:'water0.dds',0x61000:'water1.dds'}[p]


class NativeMaterialTests(unittest.TestCase):
    def test_prepared_batch_samples_fresh_resolved_frames_and_reuses_only_addresses(self):
        class Batch(MaterialMemory):
            def read_many(self,plan):
                self.calls=getattr(self,'calls',0)+1;self.last_plan=plan
                return {p:self.read(p,n)for p,n in plan}
        r=Batch();item=discover(r,0x10000,'batch');prepared=FlipCapture({item['id']:item})
        self.assertEqual(capture(r,prepared)['frames'][item['id']],0)
        plan=r.last_plan
        struct.pack_into('<I',r.blocks[0x32000],4,0x51000)
        self.assertEqual(capture(r,prepared)['frames'][item['id']],1)
        self.assertEqual(r.calls,2);self.assertIs(r.last_plan,plan)
        item['mapping']=0x70000 # compiled identity/address records are independent
        self.assertEqual(capture(r,prepared)['frames'][item['id']],1)

    def test_batched_and_fallback_identity_fences_both_reject_source_replacements(self):
        class Batch(MaterialMemory):
            def read_many(self,plan):return {p:self.read(p,n)for p,n in plan}
        mutations=((0x20000,0,0),(0x20000,0x28,0x11000),(0x20000,0x50,1),
            (0x20000,0x38,0x41000),(0x20000,0x3c,3),(0x20000,0x40,1),
            (0x40000,4,0x50000),(0x10000,0,0),(0x10000,0x20,0x31000),
            (0x30000,0,0x33000),(0x32000,4,0x52000))
        for factory in (MaterialMemory,Batch):
            for block,offset,value in mutations:
                r=factory();item=discover(r,0x10000);prepared=FlipCapture({item['id']:item})
                struct.pack_into('<I',r.blocks[block],offset,value)
                with self.subTest(batch=factory.__name__,change=(block,offset)),self.assertRaises(SceneReadChanged):capture(r,prepared)

    def test_unreadable_unrequested_gaps_fall_back_but_short_requested_blocks_fail(self):
        class Batch(MaterialMemory):
            def read_many(self,plan):
                def read(p,n):
                    try:return self.read(p,n)
                    except AssertionError:raise OSError('Unmapped fixture gap')from None
                self.stats={};return copy_ranges(read,plan,self.stats)
        r=Batch();r.blocks[0x30200]=r.blocks.pop(0x32000);struct.pack_into('<I',r.blocks[0x30000],0,0x30200)
        item=discover(r,0x10000);prepared=FlipCapture({item['id']:item})
        self.assertEqual(capture(r,prepared)['frames'][item['id']],0)
        self.assertGreater(r.stats['gap_fallbacks'],0)
        for bad in ({}, {p:r.read(p,n)[:-1]for p,n in prepared.plan}):
            with patch.object(r,'read_many',return_value=bad),self.assertRaises(SceneReadChanged):capture(r,prepared)

    def test_prepared_palettes_and_group_budgets_fail_before_sampling(self):
        r=MaterialMemory();item=discover(r,0x10000)
        with self.assertRaisesRegex(ValueError,'budget'):FlipCapture({str(i):item for i in range(257)})
        for changes in ({'count':0},{'capacity':257},{'pointers':b''},{'textures':()}):
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'palette'):FlipCapture({'bad':{**item,**changes}})

    def test_empty_material_capture_never_reads_the_source(self):
        class NoRead:
            def read_many(self,plan):raise AssertionError('Empty material table must not sample')
        self.assertEqual(capture(NoRead(),FlipCapture({})),dict(version=1,frames={}))

    def test_palette_and_resolved_frame_are_read_without_an_animation_clock(self):
        r=MaterialMemory();item=discover(r,0x10000,'a1');self.assertEqual(item['names'],('water0.dds','water1.dds'))
        flips={item['id']:item};self.assertEqual(capture(r,flips)['frames'],{item['id']:0})
        # The actual source map is authoritative even if a controller field
        # denotes its next frame. No duration/time/frame-rate is evaluated.
        struct.pack_into('<I',r.blocks[0x20000],0x4c,17)
        self.assertEqual(capture(r,flips)['frames'][item['id']],0)
        struct.pack_into('<I',r.blocks[0x32000],4,0x51000)
        self.assertEqual(capture(r,flips)['frames'][item['id']],1)

    def test_replaced_palette_mapping_or_controller_fails_closed(self):
        for block,offset,value in ((0x20000,0,0),(0x20000,0x28,0x11000),(0x40000,4,0x50000),(0x32000,4,0x52000),(0x10000,0,TEXTURING+4)):
            r=MaterialMemory();item=discover(r,0x10000);struct.pack_into('<I',r.blocks[block],offset,value)
            with self.subTest(change=(block,offset)),self.assertRaises(SceneReadChanged):capture(r,{item['id']:item})

    def test_unsupported_maps_and_unbounded_palettes_are_not_synthesized(self):
        r=MaterialMemory();struct.pack_into('<I',r.blocks[0x20000],0x50,1);self.assertIsNone(discover(r,0x10000))
        r=MaterialMemory();struct.pack_into('<2I',r.blocks[0x20000],0x3c,257,257)
        with self.assertRaisesRegex(ValueError,'palette'):discover(r,0x10000)

    def test_texture_flip_does_not_change_real_mesh_or_scene_catalog(self):
        material=MaterialMemory();native=Memory()
        class R:
            def read(self,p,n):
                try:return material.read(p,n)
                except AssertionError:return native.read(p,n)
            def u32(self,p):return struct.unpack('<I',self.read(p,4))[0]
            def string(self,p,n):return material.string(p,n)
        class G(Graph):
            def collect(self):
                scene=super().collect();scene['shapes'][0].update(texture='water1.dds'if material.u32(0x32004)==0x51000 else'water0.dds',texture_property='0x10000')
                return scene
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            out=Path(folder);(out/'meshes').mkdir();(out/'textures').mkdir()
            a=Assets.__new__(Assets);a.r=R();a.out=out;a.meshes={};a.textures={};a.missing=[];a.archives=[]
            def texture(name):a.textures[name]='textures/'+name+'.png';return a.textures[name]
            a.texture=texture
            with patch('geometry_stream.SceneReader',return_value=G(native)),patch('geometry_stream.Assets',return_value=a):geometry=Geometry(a.r)
            base=dict(world='0x10000',data='0x20000',cell_ptr=hex(native.cell))
            geometry.refresh(base);first=geometry.catalog;asset=geometry.shapes[0]['asset']
            struct.pack_into('<I',material.blocks[0x32000],4,0x51000)
            geometry.refresh(base)
            self.assertEqual(geometry.catalog,first);self.assertEqual(geometry.shapes[0]['asset'],asset)
            self.assertEqual(len(a.meshes),1);self.assertEqual(next(iter(capture(a.r,geometry.material_flips)['frames'].values())),1)
            catalog=json.loads((out/first).read_text());definition=next(iter(catalog['meshes'].values()))
            self.assertEqual(definition['texture_animation']['frames'],['textures/water0.dds.png','textures/water1.dds.png'])


if __name__=='__main__':unittest.main()
