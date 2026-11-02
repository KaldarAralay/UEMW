import unittest
from live_probe import Reader

class BatchedReadTests(unittest.TestCase):
    def test_bounded_spans_preserve_exact_ranges_across_page_boundaries(self):
        reader=Reader.__new__(Reader);calls=[]
        def data(address,size):return bytes((address+i)%251 for i in range(size))
        def read(address,size):calls.append((address,size));return data(address,size)
        reader.read=read
        requests=[(0x10100,172),(0x10200,116),(0x10ff0,32),(0x11100,172),(0x11200,116)]
        result=reader.read_many(requests)
        self.assertEqual(result,{ptr:data(ptr,count) for ptr,count in requests})
        self.assertEqual(calls,[(0x10100,0x11200+116-0x10100)])

    def test_failure_drops_whole_batch(self):
        reader=Reader.__new__(Reader)
        def read(address,size):raise OSError('unloaded page')
        reader.read=read
        with self.assertRaisesRegex(OSError,'unloaded page'):reader.read_many([(0x10000,172),(0x10200,116)])

    def test_unmapped_gap_falls_back_but_valid_requested_nodes_are_preserved(self):
        r=Reader.__new__(Reader);calls=[]
        def read(address,count):
            calls.append((address,count))
            if address<0x12000 and address+count>0x11000:raise OSError('unrequested gap')
            return bytes([address&255])*count
        r.read=read
        result=r.read_many([(0x10ff0,16),(0x12000,116)])
        self.assertEqual(result,{0x10ff0:bytes([240])*16,0x12000:bytes(116)})
        self.assertEqual(len(calls),3);self.assertEqual(r.last_batch_stats['gap_fallbacks'],1)

    def test_large_node_sets_have_bounded_spans_and_duplicate_addresses_use_longest_range(self):
        r=Reader.__new__(Reader);calls=[]
        def read(address,count):calls.append(count);return bytes([17])*count
        r.read=read;requests=[(0x10000+i*1024,172)for i in range(1000)]+[(0x10000,116)]
        result=r.read_many(requests)
        self.assertEqual(len(result),1000);self.assertEqual(len(result[0x10000]),172)
        self.assertTrue(all(n<=65536 for n in calls));self.assertLess(len(calls),20)

    def test_incomplete_node_read_never_returns_a_partial_batch(self):
        r=Reader.__new__(Reader);r.read=lambda address,count:bytes(count-1)
        with self.assertRaises(OSError):r.read_many([(0x10000,172),(0x10200,116)])

    def test_invalid_ranges_are_rejected_before_remote_reads(self):
        r=Reader.__new__(Reader);calls=[];r.read=lambda *args:calls.append(args)
        for request in ((0x100,16),(0x10000,0),(0xffefffff,2),(0x10000,True),(0x10000,4*1024*1024+1)):
            with self.subTest(request=request),self.assertRaises(ValueError):r.read_many([request])
        self.assertEqual(calls,[])

if __name__=='__main__':unittest.main()
