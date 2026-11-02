import struct
import unittest
import numpy as np
from read_batch import ReadPlan,RangeCapture,capture_ranges,copy_ranges
from pose_frame import PoseFrame,PoseLayout
from live_probe import SceneReadChanged
from test_pose_frame import header,CAMERA


class FlatCaptureTests(unittest.TestCase):
    def test_flat_and_dictionary_paths_match_requested_overlapping_bytes_and_ownership(self):
        plan=ReadPlan([(0x10000,172),(0x10020,116),(0x13000,116),(0x30000,172)])
        memory=bytearray(i%251 for i in range(0x30000))
        read=lambda address,count:bytes(memory[address-0x10000:address-0x10000+count])
        expected=copy_ranges(read,plan,{})
        stats={};flat=capture_ranges(read,plan,stats)
        self.assertEqual(dict(flat),expected)
        with self.assertRaises(KeyError):flat[0x10001]
        with self.assertRaises(TypeError):plan.offsets[0x10000]=(0,4)
        memory[:]=b'z'*len(memory)
        self.assertEqual(dict(flat),expected)
        self.assertEqual(stats['read_calls'],len(plan.groups))

    def test_failed_bulk_gap_is_replaced_only_by_complete_exact_requested_reads(self):
        plan=ReadPlan([(0x10000,116),(0x11000,172)])
        values={0x10000:b'a'*116,0x11000:b'b'*172}
        stats={};flat=capture_ranges(lambda p,n:values[p],plan,stats,lambda p:(b'X'*p.total,(False,)))
        self.assertEqual(dict(flat),values)
        self.assertEqual(stats['gap_fallbacks'],1);self.assertEqual(stats['read_calls'],3)
        for missing in (0x10000,0x11000):
            def read(p,n):
                if p==missing:raise OSError('Requested node retired')
                return values[p]
            with self.assertRaises(OSError):capture_ranges(read,plan,{},lambda p:(b'X'*p.total,(False,)))
        with self.assertRaisesRegex(OSError,'Incomplete'):capture_ranges(lambda p,n:b'a',plan,{},lambda p:(b'X'*p.total,(False,)))

    def test_malformed_flat_bulk_table_cannot_be_accepted(self):
        plan=ReadPlan([(0x10000,116)])
        for data,valid in ((b'x',()),(b'x'*116,(1,)),(bytearray(116),(True,)),(b'x'*116,())):
            with self.subTest(valid=valid),self.assertRaises(OSError):capture_ranges(None,plan,{},lambda p:(data,valid))

    def test_prepared_gather_matches_legacy_pose_and_hidden_identity_fence(self):
        rng=np.random.default_rng(73);raw={0x10000:header(flags=1)};records=[]
        for i in range(120):
            p=0x20000+i*256;identity=(i+1,0)
            raw[p]=header(identity,flags=int(i%11==0),bound=(*rng.uniform(-300,300,3),5.),transform=rng.uniform(-2,2,13).tolist())
            records.append((p,identity,(0x10000,p)if i%2 else(p,),None,None))
        plan=ReadPlan([(p,0x74 if p==0x10000 else 0xac)for p in raw])
        def capture():
            data=bytearray(plan.total)
            for p,(offset,size)in plan.offsets.items():data[offset:offset+size]=raw[p][:size]
            return RangeCapture(plan,data)
        layout=PoseLayout(records,read_plan=plan)
        saved=PoseFrame(capture(),layout,CAMERA)
        legacy=PoseFrame(raw,PoseLayout(records),CAMERA)
        np.testing.assert_array_equal(saved.nodes,legacy.nodes)
        np.testing.assert_array_equal(saved.visible,legacy.visible)
        for p,matrix in saved.worlds(raw).items():np.testing.assert_array_equal(matrix,legacy.worlds(raw)[p])
        p=records[1][0];raw[p]=header((9999,0),flags=1)
        with self.assertRaisesRegex(SceneReadChanged,'identity'):PoseFrame(capture(),layout,CAMERA)
        self.assertEqual(struct.unpack('<2I',saved[p][0x98:0xa0]),records[1][1])
        other=ReadPlan(list(plan))
        with self.assertRaisesRegex(SceneReadChanged,'read plan'):PoseFrame(RangeCapture(other,saved.raw.data),layout,CAMERA)

    def test_missing_or_short_prepared_ranges_reject_before_gather(self):
        records=[(0x20000,(1,0),(0x10000,0x20000),None,None)]
        for requests in ([(0x20000,0xac)],[(0x10000,0x73),(0x20000,0xac)],[(0x10000,0x74),(0x20000,0x99)]):
            with self.assertRaises((KeyError,ValueError)):PoseLayout(records,read_plan=ReadPlan(requests))


if __name__=='__main__':unittest.main()
