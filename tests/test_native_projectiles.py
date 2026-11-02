import struct
import unittest
from unittest.mock import patch
from live_probe import Reader,SceneReadChanged
from native_projectiles import roots,effect_roots

class Memory:
    def __init__(self):
        self.blocks={0x10000:struct.pack('<5I',1,1,0x20000,0x20000,0),0x20000:struct.pack('<3I',0x1000c,0x1000c,0x30000),
            0x30014:struct.pack('<I',0x40000),0x60000:struct.pack('<3I',0,0x70000,2),0x70000:struct.pack('<I',0x71000),
            0x71000:struct.pack('<3I',0x72000,0x70000,0x80000),0x72000:struct.pack('<3I',0x70000,0x71000,0x81000)}
        ref=bytearray(0x14);ref[4:8]=b'REFR';struct.pack_into('<I',ref,0x10,0x50000);self.blocks[0x40000]=bytes(ref)
        for p,target,node in((0x80000,0x40000,0xa0000),(0x81000,0x99900,0xb0000)):
            v=bytearray(0x24);struct.pack_into('<I',v,0,target);struct.pack_into('<I',v,0x1c,node);self.blocks[p]=bytes(v)
    def read(self,p,n):
        for base,data in self.blocks.items():
            if base<=p and p+n<=base+len(data):return data[p-base:p-base+n]
        raise AssertionError((p,n))
    def u32(self,p):return struct.unpack('<I',self.read(p,4))[0]

class ProjectileTests(unittest.TestCase):
    def test_actor_attached_effects_are_discovered_and_expired_effects_are_hidden(self):
        r=Memory();self.assertEqual(effect_roots(r,0x60000),[0xa0000,0xb0000])
        self.assertEqual(effect_roots(r,0x60000,include_targets=True),{0xa0000:0x40000,0xb0000:0x99900})
        item=bytearray(r.blocks[0x81000]);item[0x20]=1;r.blocks[0x81000]=bytes(item)
        self.assertEqual(effect_roots(r,0x60000),[0xa0000])
        r.blocks[0x60000]=bytes(12)
        self.assertEqual(effect_roots(r,0x60000),[])

    def test_owned_projectile_roots_keep_the_catalog_layer_order(self):
        class Sample:
            def u32(self,p):return {0x20028:0x30000,0x30014:0x40000}.get(p,0)
        h=bytearray(0x80);struct.pack_into('<I',h,0x5c,0x20000)
        with patch('native_projectiles.roots',return_value=[0x50000]):
            rows=Reader.auxiliary_roots(Sample(),0x10000,0x70000,h,dict(root='0x60000',reference='0x61000'))
        self.assertEqual(rows[-1]['owner_ref'],'0x61000')
        self.assertEqual(rows,[dict(layer='projectile',root='0x40000'),dict(layer='projectile',root='0x50000'),dict(layer='player',root='0x60000',owner_ref='0x61000')])

    def test_native_reference_and_only_its_owned_effect_are_selected(self):
        self.assertEqual(roots(Memory(),0x10000,0x60000),[0x50000,0xa0000])
    def test_retired_reference_and_changed_native_lists_fail_closed(self):
        r=Memory();r.blocks[0x40000]=bytes(0x14)
        with self.assertRaises(SceneReadChanged):roots(r,0x10000,0x60000)
        r=Memory();r.blocks[0x71000]=struct.pack('<3I',0x71000,0x70000,0x80000)
        with self.assertRaises(SceneReadChanged):roots(r,0x10000,0x60000)

if __name__=='__main__':unittest.main()
