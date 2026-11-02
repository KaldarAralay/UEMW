"""Exercise actual Windows reads on owned low-address pages, never game data."""
import ctypes as C
from ctypes import wintypes as W
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest
from native_read_batch import NativeBatch,Range,Result,helper
from read_batch import ReadPlan,copy_ranges,capture_ranges,MAX_TOTAL
from live_probe import Reader,K
from native_materials import FlipCapture,capture,FLIP,TEXTURING
import struct

K.VirtualAlloc.argtypes=[C.c_void_p,C.c_size_t,W.DWORD,W.DWORD];K.VirtualAlloc.restype=C.c_void_p
K.VirtualFree.argtypes=[C.c_void_p,C.c_size_t,W.DWORD];K.VirtualFree.restype=W.BOOL
K.VirtualProtect.argtypes=[C.c_void_p,C.c_size_t,W.DWORD,C.POINTER(W.DWORD)];K.VirtualProtect.restype=W.BOOL
K.GetCurrentProcess.argtypes=[];K.GetCurrentProcess.restype=W.HANDLE

@unittest.skipUnless(helper(),'Build tools/build-read-batch.ps1 to exercise the native ABI')
class NativeBatchTests(unittest.TestCase):
    def setUp(self):
        self.address=0
        for candidate in range(0x20000000,0x60000000,0x1000000):
            value=K.VirtualAlloc(candidate,65536,0x3000,4)
            if value:self.address=value;break
        if not self.address:raise RuntimeError('Could not reserve owned low-address test pages')
        self.bytes=bytes(i%251 for i in range(65536));C.memmove(self.address,self.bytes,len(self.bytes))
        self.reader=Reader.__new__(Reader);self.reader.handle=K.GetCurrentProcess();self.reader._scratch=threading.local()
        self.bulk=NativeBatch(self.reader.handle)
    def tearDown(self):K.VirtualFree(self.address,0,0x8000)
    def test_prepared_material_capture_uses_one_real_native_batch_and_fresh_map_values(self):
        definitions={};mappings=[]
        for i in range(16):
            a=self.address+i*512;controller=a+64;maps=a+160;mapping=a+176;storage=a+192;textures=(a+224,a+256)
            for p,value in ((a,TEXTURING),(a+0x20,maps),(controller,FLIP),(controller+0x28,a),(controller+0x38,storage),
                (controller+0x3c,2),(controller+0x40,2),(controller+0x50,0),(maps,mapping),(mapping+4,textures[0]),
                (storage,textures[0]),(storage+4,textures[1])):C.memmove(p,struct.pack('<I',value),4)
            definitions[str(i)]=dict(controller=controller,property=a,storage=storage,capacity=2,count=2,
                pointers=struct.pack('<2I',*textures),textures=textures,maps=maps,mapping=mapping)
            mappings.append((mapping,textures))
        self.reader._native_batch=self.bulk;prepared=FlipCapture(definitions)
        first=capture(self.reader,prepared)
        self.assertEqual(first['frames'],{str(i):0 for i in range(16)})
        self.assertEqual(self.reader.last_batch_stats['native_batches'],1)
        self.assertEqual(self.reader.last_batch_stats['read_calls'],1)
        for mapping,textures in mappings:C.memmove(mapping+4,struct.pack('<I',textures[1]),4)
        self.assertEqual(capture(self.reader,prepared)['frames'],{str(i):1 for i in range(16)})
        self.assertEqual(first['frames'],{str(i):0 for i in range(16)})
    def test_real_batch_preserves_overlaps_exact_lengths_and_independent_ownership(self):
        a=self.address;plan=ReadPlan([(a+17,172),(a+31,116),(a+4011,172),(a+17,116)])
        stats={};first=copy_ranges(self.reader.read,plan,stats,self.bulk.copy)
        self.assertEqual(first,{address:self.bytes[address-a:address-a+count]for address,count in plan})
        self.assertEqual(stats['native_batches'],1);self.assertEqual(stats['read_calls'],1)
        C.memmove(a+17,b'z'*172,172)
        second=copy_ranges(self.reader.read,plan,{},self.bulk.copy)
        self.assertNotEqual(first[a+17],second[a+17]);self.assertEqual(first[a+17],self.bytes[17:189])
    def test_unrequested_guard_gap_falls_back_but_guarded_requested_bytes_fail(self):
        a=self.address;old=W.DWORD()
        self.assertTrue(K.VirtualProtect(a+4096,4096,1,C.byref(old)))
        try:
            stats={};plan=ReadPlan([(a+4080,16),(a+8192,116)])
            copied=copy_ranges(self.reader.read,plan,stats,self.bulk.copy)
            self.assertEqual(copied[a+8192],self.bytes[8192:8308]);self.assertEqual(stats['gap_fallbacks'],1)
            self.assertEqual(stats['read_calls'],3)
            with self.assertRaises(OSError):copy_ranges(self.reader.read,ReadPlan([(a+4080,16),(a+4096,116)]),{},self.bulk.copy)
        finally:K.VirtualProtect(a+4096,4096,old.value,C.byref(old))
    def test_native_descriptor_bounds_reject_before_touching_destination(self):
        a=self.address;out=C.create_string_buffer(b'untouched',32);result=(Result*1)()
        for row,capacity in [(Range(1,4,0),32),(Range(a,4,31),32),(Range(a,0,0),32),(Range(0xffefffff,2,0),32),(Range(a,4,0),MAX_TOTAL+1)]:
            with self.subTest(row=(row.address,row.bytes,row.offset),capacity=capacity):
                self.assertEqual(self.bulk.api.UEMWReadBatch(self.reader.handle,C.byref(row),1,out,capacity,result),87)
                self.assertEqual(out.value,b'untouched')
    def test_concurrent_batches_reuse_only_their_own_thread_scratch(self):
        a=self.address;plan=ReadPlan([(a+17,172),(a+9000,172)]);gate=threading.Barrier(2)
        def run():
            first=copy_ranges(self.reader.read,plan,{},self.bulk.copy);address=C.addressof(self.bulk.local.buffer)
            gate.wait(timeout=2);second=copy_ranges(self.reader.read,plan,{},self.bulk.copy)
            self.assertEqual(first,second);return address
        with ThreadPoolExecutor(max_workers=2)as pool:
            x=pool.submit(run);y=pool.submit(run);self.assertNotEqual(x.result(timeout=3),y.result(timeout=3))
    def test_closed_handle_refuses_the_copy(self):
        self.bulk.handle=None
        with self.assertRaisesRegex(RuntimeError,'closed'):self.bulk.copy(ReadPlan([(self.address,4)]))
    def test_real_flat_buffer_matches_legacy_and_survives_scratch_reuse_and_guard_gap(self):
        a=self.address;plan=ReadPlan([(a+17,172),(a+31,116),(a+9000,172)])
        self.reader._native_batch=self.bulk
        first=self.reader.capture_many(plan)
        expected=copy_ranges(self.reader.read,plan,{},self.bulk.copy)
        self.assertEqual(dict(first),expected);self.assertEqual(self.reader.last_batch_stats['native_batches'],1)
        C.memmove(a+17,b'z'*172,172)
        second=self.reader.capture_many(plan)
        self.assertNotEqual(second[a+17],first[a+17]);self.assertEqual(dict(first),expected)
        old=W.DWORD();self.assertTrue(K.VirtualProtect(a+4096,4096,1,C.byref(old)))
        try:
            stats={};guard_plan=ReadPlan([(a+4080,16),(a+8192,116)])
            flat=capture_ranges(self.reader.read,guard_plan,stats,self.bulk.copy_flat)
            self.assertEqual(flat[a+8192],self.bytes[8192:8308]);self.assertEqual(stats['gap_fallbacks'],1)
            with self.assertRaises(OSError):capture_ranges(self.reader.read,ReadPlan([(a+4080,16),(a+4096,116)]),{},self.bulk.copy_flat)
        finally:K.VirtualProtect(a+4096,4096,old.value,C.byref(old))

class PlanTests(unittest.TestCase):
    def test_prepared_plan_matches_fallback_and_aggregate_limit_precedes_reads(self):
        plan=ReadPlan([(0x10000,116),(0x10010,172),(0x20000,4)])
        read=lambda address,count:bytes([address%251])*count
        self.assertEqual(copy_ranges(read,plan,{}),copy_ranges(read,list(plan),{}))
        with self.assertRaisesRegex(ValueError,'32 MiB'):ReadPlan((0x10000+i*0x800000,4*1024*1024)for i in range(9))

if __name__=='__main__':unittest.main()
