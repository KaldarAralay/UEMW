"""General scene validation and translation of actual native-format values."""
import struct
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from game_assets import Assets
from live_probe import Reader
from supported_scenes import supported
from test_scene_lifecycle import Memory
from native_ui import loading_state

class GeneralTests(unittest.TestCase):
    def test_loading_visibility_advances_generation_even_with_reused_scene_addresses(self):
        class UI:
            flags=b'\0\0'
            def u32(self,p):return {0x7d1c28:0x10000,0x30008:0x40000}[p]
            def string(self,p,n):return 'MenuLoading'
            def read(self,p,n):
                if p==0x1001c:return struct.pack('<3I',0x20000,0x20004,0x20008)
                if p==0x20000:return struct.pack('<I',0x30000)
                if p==0x30075:return self.flags
                raise AssertionError((p,n))
        ui=UI();self.assertEqual(loading_state(ui),(False,0))
        ui.flags=b'\1\1';self.assertEqual(loading_state(ui),(True,1));self.assertEqual(loading_state(ui),(True,1))
        ui.flags=b'\0\0';self.assertEqual(loading_state(ui),(False,1))
        ui.flags=b'\1\1';self.assertEqual(loading_state(ui),(True,2))
    def test_effect_count_is_not_mistaken_for_the_world_effect_root(self):
        reader=Reader.__new__(Reader);header=bytearray(0x80);struct.pack_into('<I',header,0x74,0x30000)
        reader.u32=lambda p:{0x30008:1,0x3000c:0x40000}.get(p,0)
        with patch('native_projectiles.effect_roots',return_value={}):
            self.assertEqual(reader.auxiliary_roots(0x10000,0x20000,header,dict(root=None)),[dict(layer='world_effect',root='0x40000')])
    def test_disabled_native_weather_keeps_its_root_identity(self):
        reader=Reader.__new__(Reader);header=bytearray(0x80);weather=bytearray(0x80)
        struct.pack_into('<I',header,0x58,0x30000);struct.pack_into('<I',weather,0x5c,0x40000)
        reader.read=lambda p,n:bytes(weather)
        for flags,expected in ((1,[dict(layer='weather',root='0x40000')]),(0,[dict(layer='weather',root='0x40000')])):
            reader.u32=lambda p:flags if p==0x40014 else 0
            self.assertEqual(reader.auxiliary_roots(0x10000,0x20000,header,dict(root=None)),expected)

    def test_native_camera_pass_disables_arms_in_third_person_and_vanity(self):
        reader=Reader.__new__(Reader)
        links={0x1005c:0x20000,0x20024:0x30000,0x30000:0x40000,
               0x40014:0x50000,0x40244:0x60000,0x50010:0x70000,0x40660:0}
        reader.u32=lambda p:links[p]
        for third,vanity,expected in ((0,0,True),(1,0,False),(0,1,False),(1,2,False)):
            reader.read=lambda p,n:b'REFR'if p==0x50004 else bytes((1,0))if p==0x405bd else struct.pack('<BBBBi',third,0,0,0,vanity)
            visual=reader.player_render_state(0x10000)
            self.assertEqual(visual['root'],'0x70000')
            self.assertEqual(visual['first_person'],expected)

    def test_interior_names_are_data_not_an_allowlist(self):
        self.assertTrue(supported(dict(cell='Previously unvisited native interior',cell_flags=1,cell_grid=None)))
        for name in ('','bad\0name','a'*513):self.assertFalse(supported(dict(cell=name,cell_flags=1)))
        self.assertFalse(supported(dict(cell='name',cell_flags=1,cell_grid=[0,0])))

    def test_original_player_values_and_readiness_are_copied_without_simulation(self):
        reader=Reader.__new__(Reader);links={0x1005c:0x20000,0x20024:0x30000,0x30000:0x40000};raw=bytearray(0x5c0)
        struct.pack_into('<I',raw,0x14,0x50000)
        for off,base,current in ((0x2b4,35,17.5),(0x2c0,30,9),(0x2d8,120,-5)):struct.pack_into('<2f',raw,off+4,base,current)
        raw[0x5bd]=1;reader.u32=lambda p:links[p]
        reader.read=lambda p,n:bytes(raw)if p==0x40000 else b'REFR'if p==0x50004 else (_ for _ in ()).throw(AssertionError((p,n)))
        state=reader.player_state(0x10000)
        self.assertEqual(state['health'],[35,17.5]);self.assertEqual(state['fatigue'],[120,-5]);self.assertTrue(state['weapon_ready'])

    def test_vertex_bgra_and_native_material_alpha_survive_uem2_conversion(self):
        class Colored(Memory):
            def read(self,address,count):
                if address==0x50000:
                    h=bytearray(super().read(address,count));struct.pack_into('<I',h,0x24,0x80000);return bytes(h)
                if address==0x80000:return bytes((64,128,255,255))*3
                if address==0x90028:
                    b=bytearray(0x30);struct.pack_into('<3f',b,0,.25,.5,.75);struct.pack_into('<f',b,0x28,.5);return bytes(b)
                return super().read(address,count)
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(exist_ok=True,parents=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            out=Path(folder);(out/'meshes').mkdir();(out/'textures').mkdir()
            assets=Assets.__new__(Assets);assets.r=Colored();assets.out=out;assets.meshes={};assets.textures={};assets.missing=[];assets.material_values={};assets.archives=[]
            shape=dict(model='0x50000',texture='',vertex_count=3,triangle_count=1,material='0x90000',color_mode=2)
            assets.begin_refresh();definition=assets.mesh(shape);data=(out/definition['file']).read_bytes()
            self.assertEqual(data[:4],b'UEM2');self.assertEqual(data[12+3*20:12+3*24],bytes((255,128,64,128))*3)

    def test_native_model_normals_survive_uem3_conversion(self):
        normals=struct.pack('<9f',0,0,1,0,1,0,1,0,0)
        class WithNormals(Memory):
            def read(self,address,count):
                if address==0x50000:
                    h=bytearray(super().read(address,count));struct.pack_into('<I',h,0x20,0x83000);return bytes(h)
                if address==0x83000:return normals
                return super().read(address,count)
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(exist_ok=True,parents=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            out=Path(folder);(out/'meshes').mkdir();(out/'textures').mkdir()
            assets=Assets.__new__(Assets);assets.r=WithNormals();assets.out=out;assets.meshes={};assets.textures={};assets.missing=[];assets.archives=[]
            assets.begin_refresh();definition=assets.mesh(dict(model='0x50000',texture='',vertex_count=3,triangle_count=1))
            data=(out/definition['file']).read_bytes();self.assertEqual(data[:4],b'UEM3');self.assertEqual(data[48:84],normals)

    def test_nonfinite_native_normals_keep_real_geometry_with_declared_fallback(self):
        class InvalidNormals(Memory):
            normal=float('nan')
            def read(self,address,count):
                if address==0x50000:
                    h=bytearray(super().read(address,count));struct.pack_into('<I',h,0x20,0x83000);return bytes(h)
                if address==0x83000:return struct.pack('<9f',self.normal,0,1,0,1,0,1,0,0)
                return super().read(address,count)
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(exist_ok=True,parents=True)
        for invalid in(float('nan'),1.7014117e38):
            with self.subTest(normal=invalid),tempfile.TemporaryDirectory(dir=scratch)as folder:
                InvalidNormals.normal=invalid
                out=Path(folder);(out/'meshes').mkdir();(out/'textures').mkdir()
                assets=Assets.__new__(Assets);assets.r=InvalidNormals();assets.out=out;assets.meshes={};assets.textures={};assets.missing=[];assets.archives=[]
                assets.begin_refresh();definition=assets.mesh(dict(model='0x50000',texture='',vertex_count=3,triangle_count=1))
                data=(out/definition['file']).read_bytes()
                self.assertEqual(data[:4],b'UEM2');self.assertEqual(data[12:48],assets.r.read(0x60000,36))
                self.assertEqual(data[-6:],struct.pack('<3H',0,1,2));self.assertEqual(definition['normal_source'],'generated_invalid_native')

if __name__=='__main__':unittest.main()
