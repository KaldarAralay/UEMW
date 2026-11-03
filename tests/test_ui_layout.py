import struct,unittest
from ui_layout import LayoutCache,structural,Recorder


class UILayoutTests(unittest.TestCase):
    def test_transient_branch_preserves_exact_baseline_variant_of_same_menu(self):
        class Native:
            value=b'a'
            def read(self,p,n):return self.value*n
        native=Native();cache=LayoutCache('graph');built=[]
        def build(r):built.append(native.value);return r.read(0x10000,1),set(),set()
        self.assertEqual(cache.read(native,'inventory',build),b'a');native.value=b'b';self.assertEqual(cache.read(native,'inventory',build),b'b')
        for value in (b'a',b'b',b'a'):
            native.value=value;self.assertEqual(cache.read(native,'inventory',build),value);self.assertTrue(cache.reused)
        self.assertEqual(built,[b'a',b'b'])
        for i in range(12):native.value=bytes([i]);cache.read(native,'inventory',build)
        self.assertEqual(len(cache.variants),8)
    def test_returning_menu_variant_still_validates_its_current_source_identity(self):
        class Native:
            value=b'a'
            def read(self,p,n):return self.value*n
        native=Native();cache=LayoutCache('graph');built=[]
        def build(r):built.append(1);return r.read(0x10000,1),set(),set()
        self.assertEqual(cache.read(native,'inventory',build),b'a');native.value=b'b';cache.read(native,'hud',build)
        native.value=b'a';self.assertEqual(cache.read(native,'inventory',build),b'a');self.assertTrue(cache.reused);self.assertEqual(len(built),2)
        native.value=b'c';self.assertEqual(cache.read(native,'inventory',build),b'c');self.assertFalse(cache.reused);self.assertEqual(len(built),3)
    def test_string_fences_end_at_nul_not_at_mutable_neighbouring_heap_data(self):
        class Native:
            raw=b'caf\xe9\0'+bytes(251)
            def read(self,p,n):return self.raw[p-0x10000:p-0x10000+n]
        r=Native();cache=LayoutCache('graph');builds=[]
        def build(rec):builds.append(1);return rec.string(0x10000),set(),set()
        self.assertEqual(cache.read(r,'same',build),'café');r.raw=b'caf\xe9\0'+bytes([1])*251
        self.assertEqual(cache.read(r,'same',build),'café');self.assertTrue(cache.reused);self.assertEqual(len(builds),1)
        r.raw=b'cafX\0'+bytes(251);self.assertEqual(cache.read(r,'same',build),'cafX');self.assertEqual(len(builds),2)
    def test_motion_and_refcounts_are_values_visibility_hierarchy_are_identity(self):
        a=bytearray(0x90);struct.pack_into('<I',a,0,0x700000);b=bytearray(a);b[4]=3;b[0x40]=12
        self.assertEqual(structural('graph',0x10000,a,{0x10000},set()),structural('graph',0x10000,b,{0x10000},set()))
        b[0x14]=1;self.assertNotEqual(structural('graph',0x10000,a,{0x10000},set()),structural('graph',0x10000,b,{0x10000},set()))
        b=bytearray(a);b[0x88]=12;self.assertNotEqual(structural('graph',0x10000,a,{0x10000},set()),structural('graph',0x10000,b,{0x10000},set()))
        b=bytearray(a);b[0x18]=12;self.assertNotEqual(structural('graph',0x10000,a,{0x10000},set()),structural('graph',0x10000,b,{0x10000},set()))
    def test_layout_cache_retains_no_colour_timestamp_but_checks_hidden_element_visibility(self):
        class Reader:
            raw=bytes(0x15c)
            def read(self,p,n):return self.raw[p-0x10000:p-0x10000+n]
        reader=Reader();cache=LayoutCache('layout');builds=[]
        def build(r):builds.append(1);return r.read(0x10000,0x15c),{0x10000},set()
        cache.read(reader,'root',build);a=bytearray(reader.raw);a[0x70]=1;a[0x14c]=255;reader.raw=bytes(a);cache.read(reader,'root',build);self.assertTrue(cache.reused);self.assertEqual(len(builds),1)
        a[0x75]=1;reader.raw=bytes(a);cache.read(reader,'root',build);self.assertFalse(cache.reused);self.assertEqual(len(builds),2)
        a[0x128]=10;reader.raw=bytes(a);cache.read(reader,'root',build);self.assertEqual(len(builds),3)
    def test_property_links_model_counts_and_pointer_replacement_rebuild(self):
        class Reader:
            memory={0x10000:bytes(0x90),0x20000:bytes(0x36),0x30000:bytes(8)}
            def read(self,p,n):
                for start,raw in self.memory.items():
                    if start<=p and p+n<=start+len(raw):return raw[p-start:p-start+n]
                raise OSError('retired')
        r=Reader();cache=LayoutCache('graph');builds=[]
        def build(rec):builds.append(1);return tuple(rec.read(p,n)for p,n in((0x10000,0x90),(0x20000,0x36),(0x30000,8))),{0x10000},{0x20000}
        cache.read(r,'source',build)
        for p,offset in((0x30000,0),(0x20000,8),(0x10000,0x88)):
            raw=bytearray(r.memory[p]);raw[offset]=1;r.memory[p]=bytes(raw);cache.read(r,'source',build);self.assertFalse(cache.reused)
        self.assertEqual(len(builds),4);cache.read(r,'new-root',build);self.assertEqual(len(builds),5)
