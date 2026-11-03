import struct,unittest
from types import SimpleNamespace
from native_texture_effects import discover,capture,convert,EffectCapture,EFFECT,STATE
from native_materials import SOURCE_TEXTURE
from live_probe import SceneReadChanged

class EffectMemory:
    def __init__(self):
        self.blocks={0x7c67dc:bytearray(struct.pack('<I',0x90000)),0x90000:bytearray(0x374),0x70000:bytearray(28),0x80000:bytearray(0x148),0xa0000:bytearray(132)}
        struct.pack_into('<I',self.blocks[0x70000],0,STATE);struct.pack_into('<I',self.blocks[0x70000],0x14,0x80000)
        struct.pack_into('<2I',self.blocks[0x90000],0x36c,0x80000,0xa0004)
        struct.pack_into('<I',self.blocks[0x80000],0,EFFECT);self.blocks[0x80000][0x90]=1
        struct.pack_into('<5I',self.blocks[0x80000],0x108,0x100000,1,3,2,2)
        struct.pack_into('<12f',self.blocks[0x80000],0xd8,.5,0,0,0,-.5,0,0,0,0,.5,.5,0)
        struct.pack_into('<I',self.blocks[0xa0000],0,32);self.names={}
        for i in range(32):
            texture=0x100000+i*0x100;raw=bytearray(0x30);struct.pack_into('<I',raw,0,SOURCE_TEXTURE);struct.pack_into('<I',raw,0x2c,0x200000+i*0x100)
            self.blocks[texture]=raw;self.names[0x200000+i*0x100]=f'owned/frame{i:02}.dds';struct.pack_into('<I',self.blocks[0xa0000],4+i*4,texture)
    def read(self,p,n):
        for base,raw in self.blocks.items():
            if base<=p and p+n<=base+len(raw):return bytes(raw[p-base:p-base+n])
        raise OSError('Unmapped owned fixture')
    def u32(self,p):return struct.unpack('<I',self.read(p,4))[0]
    def string(self,p,limit):return self.names[p]
    def read_many(self,plan):self.batches=getattr(self,'batches',0)+1;return {p:self.read(p,n)for p,n in plan}

class TextureEffectTests(unittest.TestCase):
    def test_enchantment_uses_owned_original_palette_and_resolved_frame(self):
        r=EffectMemory();item=discover(r,0x70000,'native');plan=EffectCapture({item['id']:item})
        values,frames=capture(r,plan);self.assertEqual(frames[item['id']],0);self.assertEqual(values['values'][item['id']][:4],[1,1,3,2]);self.assertEqual(r.batches,1)
        struct.pack_into('<I',r.blocks[0x80000],0x108,item['textures'][19]);values,frames=capture(r,plan)
        self.assertEqual(frames[item['id']],19);self.assertEqual(r.batches,2)
        a=SimpleNamespace(used_textures=set(),texture=lambda name:'textures/'+name+'.png');recipe=convert(a,item)
        self.assertEqual(len(recipe['animation']['frames']),32);self.assertTrue(recipe['supported']);self.assertEqual(len(a.used_textures),32)
    def test_palette_source_world_and_effect_replacements_reject(self):
        changes=((0x7c67dc,0,0x91000),(0x80000,0,0),(0x80000,0x108,0x300000),(0x90000,0x370,0xa0104),(0xa0000,4,0),(0x100000,0,SOURCE_TEXTURE+4),(0x100000,0x2c,0x300000))
        for address,offset,value in changes:
            r=EffectMemory();item=discover(r,0x70000);plan=EffectCapture({item['id']:item});struct.pack_into('<I',r.blocks[address],offset,value)
            with self.subTest(change=(address,offset)),self.assertRaises(SceneReadChanged):capture(r,plan)
    def test_live_matrix_enable_and_sampler_are_not_recreated(self):
        r=EffectMemory();item=discover(r,0x70000);plan=EffectCapture({item['id']:item});r.blocks[0x80000][0x90]=0
        struct.pack_into('<f',r.blocks[0x80000],0xfc,.875);struct.pack_into('<I',r.blocks[0x80000],0x10c,5)
        values,_=capture(r,plan);self.assertEqual(values['values'][item['id']][0],0);self.assertEqual(values['values'][item['id']][1],5);self.assertEqual(values['values'][item['id']][13],.875)
        struct.pack_into('<f',r.blocks[0x80000],0xd8,float('nan'))
        with self.assertRaisesRegex(ValueError,'matrix'):capture(r,plan)
    def test_non_sphere_coordinates_remain_explicitly_unsupported(self):
        r=EffectMemory();struct.pack_into('<I',r.blocks[0x80000],0x118,3);item=discover(r,0x70000)
        a=SimpleNamespace(used_textures=set(),texture=lambda name:'textures/'+name+'.png');recipe=convert(a,item)
        self.assertFalse(recipe['supported']);self.assertIn('unsupported',recipe)
