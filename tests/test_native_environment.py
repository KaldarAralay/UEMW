import struct
import unittest
from native_environment import capture,light

class Memory:
    def __init__(self):
        self.cells={};self.values={0x40018:3,0x20098:0x50000,0x10058:0x60000,0x50000:0x74FFE0,0x70000:0x749D40,0x80004:4,0x81004:5}
        self.light=bytearray(0xdc);struct.pack_into('<I',self.light,0,0x74FFE0);self.light[0x90]=1
        struct.pack_into('<f',self.light,0xa8,.5);struct.pack_into('<3f',self.light,0xac,.1,.2,.3);struct.pack_into('<3f',self.light,0xb8,1,.5,.25);struct.pack_into('<3f',self.light,0xd0,0,0,-1)
        self.point=bytearray(self.light);struct.pack_into('<I',self.point,0,0x749D40);struct.pack_into('<3f',self.point,0xd0,1,.01,0);struct.pack_into('<f',self.point,0xc4,500)
        self.weather=bytearray(0x1d0);struct.pack_into('<2I',self.weather,0x3c,0x80000,0x81000);struct.pack_into('<3f',self.weather,0x90,.4,.5,.6);struct.pack_into('<3f',self.weather,0xb8,1,2,3);struct.pack_into('<f',self.weather,0x170,.25);struct.pack_into('<f',self.weather,0x178,.75);self.weather[0x199]=1
    def u32(self,p):return self.values[p]
    def read(self,p,n):
        if p==0x20098:return struct.pack('<2I',0x50000,0x90000)
        if p==0x4001c:return bytes((10,20,30,0))+bytes(12)
        if p==0x40090:return struct.pack('<f',123)
        if p==0x90014:return struct.pack('<H2xf4B',2,.8,40,60,80,255)
        if p==0x50000:return bytes(self.light[:n])
        if p==0x70000:return bytes(self.point[:n])
        if p==0x60000:return bytes(self.weather[:n])
        raise AssertionError((p,n))

class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.memory=Memory();self.base=dict(world='0x10000',data='0x20000',cell_ptr='0x40000',camera=dict(position=[0,0,0],frustum=[-1,1,1,-1,1,7168]))
    def test_resolved_sun_fog_weather_and_native_water_are_copied(self):
        p=capture(self.memory,self.base,[0x70000]);self.assertEqual(p['version'],1)
        self.assertAlmostEqual(p['ambient'][0],.05);self.assertEqual(p['sun_color'],[.5,.25,.125]);self.assertEqual(p['sun_direction'],[0,0,-1])
        self.assertEqual(p['fog_color'],[80/255,60/255,40/255]);self.assertAlmostEqual(p['fog_density'],.8,places=6);self.assertTrue(p['fog_enabled'])
        self.assertEqual(p['weather']['current'],4);self.assertEqual(p['weather']['next'],5);self.assertEqual(p['weather']['transition'],.25);self.assertEqual(p['weather']['wind'],[1,2,3]);self.assertTrue(p['weather']['underwater']);self.assertEqual(p['water_level'],123)
        self.assertAlmostEqual(p['lights'][0]['attenuation'][1],.01,places=6)
    def test_runtime_fog_enable_uses_original_dx8_mask_not_serialized_nif_mask(self):
        original=self.memory.read
        for flags,enabled in ((0,False),(1,False),(2,True),(3,True),(0x18,False),(0x1a,True)):
            self.memory.read=lambda p,n,f=flags:struct.pack('<H2xf4B',f,.8,40,60,80,255)if p==0x90014 else original(p,n)
            with self.subTest(flags=flags):self.assertEqual(capture(self.memory,self.base)['fog_enabled'],enabled)
    def test_native_flicker_and_disable_are_not_simulated_or_cached(self):
        first=capture(self.memory,self.base,[0x70000]);struct.pack_into('<f',self.memory.point,0xa8,.125)
        second=capture(self.memory,self.base,[0x70000]);self.assertEqual(first['lights'][0]['dimmer'],.5);self.assertEqual(second['lights'][0]['dimmer'],.125)
        self.memory.point[0x90]=0;self.assertEqual(capture(self.memory,self.base,[0x70000])['lights'],[])
    def test_pass_local_app_cull_does_not_switch_off_a_native_enabled_light(self):
        struct.pack_into('<H',self.memory.point,0x14,1);struct.pack_into('<H',self.memory.light,0x14,1)
        self.assertTrue(light(self.memory,0x70000)['enabled'])
        value=capture(self.memory,self.base,[0x70000]);self.assertEqual(len(value['lights']),1);self.assertEqual(value['sun_color'],[.5,.25,.125])
        self.memory.point[0x90]=0;self.assertEqual(capture(self.memory,self.base,[0x70000])['lights'],[])
    def test_cell_configuration_is_fallback_not_a_second_resolved_ambient_light(self):
        value=capture(self.memory,self.base);self.assertAlmostEqual(value['ambient'][0],.05)
        self.memory.light[0x90]=0;value=capture(self.memory,self.base);self.assertEqual(value['ambient'],[0,0,0])
        original=self.memory.read
        self.memory.read=lambda p,n:struct.pack('<2I',0,0x90000)if p==0x20098 else original(p,n)
        self.assertEqual(capture(self.memory,self.base)['ambient'],[30/255,20/255,10/255])
    def test_sky_and_effect_ambient_do_not_brighten_world_surfaces(self):
        self.memory.values[0x70000]=0x74FB90
        struct.pack_into('<I',self.memory.point,0,0x74FB90)
        struct.pack_into('<f',self.memory.point,0xa8,1)
        struct.pack_into('<3f',self.memory.point,0xac,1,1,1)
        ignored=capture(self.memory,self.base,[0x70000],{0x70000:('aux:sky','view:first-person','aux:world_effect')})
        baseline=capture(self.memory,self.base)
        self.assertEqual(ignored['ambient'],baseline['ambient'])
        world=capture(self.memory,self.base,[0x70000],{0x70000:('exterior:0,0',)})
        self.assertAlmostEqual(world['ambient'][0],1.05)
    def test_nonfinite_and_recycled_native_lights_are_rejected(self):
        struct.pack_into('<f',self.memory.point,0xb8,float('nan'))
        with self.assertRaises(ValueError):light(self.memory,0x70000)
    def test_large_native_unsigned_radius_is_preserved_without_relaxing_coordinates(self):
        struct.pack_into('<f',self.memory.point,0xc4,258922080.)
        self.assertEqual(light(self.memory,0x70000)['radius'],258922080.)
        struct.pack_into('<f',self.memory.point,0x64,258922080.)
        with self.assertRaisesRegex(ValueError,'position'):light(self.memory,0x70000)
    def test_disabled_native_light_unused_payload_cannot_stop_scene_capture(self):
        self.memory.point[0x90]=0;struct.pack_into('<f',self.memory.point,0xc4,float('nan'));struct.pack_into('<f',self.memory.point,0xb8,float('nan'))
        self.assertEqual(capture(self.memory,self.base,[0x70000])['lights'],[])
        self.memory.point[0x90]=1
        with self.assertRaises(ValueError):capture(self.memory,self.base,[0x70000])
    def test_signed_no_weather_and_exterior_behaviour_are_preserved(self):
        self.memory.values[0x80004]=0xffffffff;self.memory.values[0x81004]=0xffffffff;self.memory.values[0x40018]=0x83
        value=capture(self.memory,self.base)
        self.assertEqual(value['weather']['current'],-1);self.assertEqual(value['weather']['next'],-1)
        self.assertEqual(value['water_level'],0);self.assertTrue(value['has_water'])
        self.memory.values[0x70000]=0x7506a8
        with self.assertRaises(ValueError):light(self.memory,0x70000)
    def test_visible_object_membership_takes_priority_in_the_real_32_light_budget(self):
        original=self.memory.read;blocks={};pointers=[]
        for i in range(33):
            p=0xa0000+i*0x1000;pointers.append(p);self.memory.values[p]=0x749d40
            raw=bytearray(self.memory.point);struct.pack_into('<3f',raw,0x64,i*500,0,0);blocks[p]=bytes(raw)
        self.memory.read=lambda p,n:blocks[p][:n]if p in blocks else original(p,n)
        before=capture(self.memory,self.base,pointers);self.assertNotIn(hex(pointers[-1]),[v['id']for v in before['lights']])
        after=capture(self.memory,self.base,pointers,preferred_lights={pointers[-1]})
        self.assertEqual(len(after['lights']),32);self.assertEqual(after['omitted_lights'],1);self.assertIn(hex(pointers[-1]),[v['id']for v in after['lights']])

    def test_camera_distance_changes_do_not_reassign_unchanged_light_slots(self):
        original=self.memory.read;self.memory.values[0x71000]=0x749d40
        def read(p,n):
            if p==0x71000:
                data=bytearray(self.memory.point);struct.pack_into('<3f',data,0x64,2000,0,0);return bytes(data[:n])
            return original(p,n)
        self.memory.read=read
        a=capture(self.memory,self.base,[0x70000,0x71000])
        moved={**self.base,'camera':{**self.base['camera'],'position':[2000,0,0]}}
        b=capture(self.memory,moved,[0x70000,0x71000])
        self.assertEqual([v['id']for v in a['lights']],[v['id']for v in b['lights']])
        self.assertEqual({v['id']:v for v in a['lights']},{v['id']:v for v in b['lights']})

if __name__=='__main__':unittest.main()
