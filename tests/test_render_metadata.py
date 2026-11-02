import struct
import unittest
from live_probe import Reader,SceneReadChanged


class MetadataTests(unittest.TestCase):
    def reader(self):
        r=Reader.__new__(Reader);r.pid=42;r.moved=False;r.calls=[]
        values={0x7c67dc:0x10000,0x7c67e0:0x20000,0x7c6cdc:0x50000,0x500e8:0,0x30018:1,0x30010:0x60000}
        def u32(p):return (0x31000 if r.moved else 0x30000)if p==0x2b540 else values[p]
        def read(p,n):
            r.calls.append((p,n))
            if p in(0x30030,0x30040,0x30058):return struct.pack('<3I',{0x30030:123,0x30040:45,0x30058:9}[p],0xdead000,0xbeef000)
            if p==0x10014:return struct.pack('<f',60)
            raise AssertionError('Normal render metadata followed a reference-list link')
        r.u32=u32;r.read=read;r.string=lambda p:'Native Room'if p==0x60000 else''
        r.player_state=lambda w:dict(reference='0x40000',health=[100,100],magicka=[50,50],fatigue=[100,100])
        return r
    def anchor(self):return dict(world='0x10000',data='0x20000',cell_ptr='0x30000',player_ref='0x40000',native_loading=False,camera={'position':[1,2,3]})

    def test_normal_metadata_reads_native_counts_without_traversing_reference_objects(self):
        r=self.reader();s=r.render_metadata(self.anchor())
        self.assertEqual(s['object_count'],177);self.assertEqual(s['objects'],[]);self.assertEqual(s['cell'],'Native Room')
        self.assertEqual(s['camera'],self.anchor()['camera']);self.assertEqual(s['player']['health'],[100,100]);self.assertEqual(s['game_fps'],60)
        self.assertEqual(len(r.calls),4)

    def test_changed_cell_and_player_identity_fail_closed(self):
        r=self.reader();r.moved=True
        with self.assertRaises(SceneReadChanged):r.render_metadata(self.anchor())
        r=self.reader();anchor={**self.anchor(),'player_ref':'0x41000'}
        with self.assertRaises(SceneReadChanged):r.render_metadata(anchor)

    def test_focus_uses_original_instance_and_base_name_fields(self):
        r=Reader.__new__(Reader);ref=bytearray(0x50);ref[4:8]=b'REFR';struct.pack_into('<I',ref,0x28,0x70000)
        r.read=lambda p,n:bytes(ref)if p==0x40000 else b'NPC_'if p==0x70004 else b''
        r.u32=lambda p:{0x7002c:0xa0000,0x70034:0,0x7006c:0x80000,0x80070:0x90000}[p]
        r.string=lambda p:{0xa0000:'native_npc_id',0x90000:'Native NPC'}[p]
        self.assertEqual(r.focus_metadata(0x40000),dict(id='0x40000',base_id='native_npc_id',name='Native NPC'))
        ref[4:8]=b'XXXX'
        with self.assertRaises(SceneReadChanged):r.focus_metadata(0x40000)


if __name__=='__main__':unittest.main()
