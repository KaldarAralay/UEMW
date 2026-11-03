import unittest
from ui_fence import UIFence
from read_batch import capture_ranges


class UIFenceTests(unittest.TestCase):
    def test_plan_reuse_requires_exact_layout_and_recopies_expected_revision_bytes(self):
        f=UIFence(((0x10000,b'ab'),));plan=f.plan;indices=f.indices
        old=capture_ranges(lambda p,n:b'ab',f.plan,{})
        self.assertTrue(f.update_expected(((0x10000,b'ac'),)));self.assertIs(f.plan,plan);self.assertIs(f.indices,indices)
        self.assertFalse(f.matches(old));self.assertTrue(f.check(lambda p,n:b'ac'))
        self.assertFalse(f.update_expected(((0x10001,b'ac'),)));self.assertTrue(f.check(lambda p,n:b'ac'))
    def test_only_consumed_bytes_define_identity_and_every_overlap_is_checked(self):
        f=UIFence(((0x10000,b'ab'),(0x10001,b'b'),(0x10004,b'ef')))
        def check(value):return f.check(lambda p,n:value[p-0x10000:p-0x10000+n])
        self.assertTrue(check(b'abXXef'))
        self.assertFalse(check(b'acXXef'))
        self.assertFalse(UIFence(((0x10000,b'ab'),(0x10001,b'c'))).check(lambda p,n:b'ab'[p-0x10000:p-0x10000+n]))

    def test_unreadable_unconsumed_gap_uses_exact_ranges(self):
        f=UIFence(((0x10000,b'ab'),(0x10010,b'cd')))
        def read(p,n):
            if(p,n)==(0x10000,2):return b'ab'
            if(p,n)==(0x10010,2):return b'cd'
            raise OSError('gap')
        self.assertTrue(f.check(read))
        with self.assertRaises(OSError):f.check(lambda p,n:read(p,n)if p==0x10000 else b'')

    def test_a_reused_plan_always_compares_new_owned_bytes(self):
        f=UIFence(((0x10000,b'ab'),));a=capture_ranges(lambda p,n:b'ab',f.plan,{})
        b=capture_ranges(lambda p,n:b'ac',f.plan,{})
        self.assertTrue(f.matches(a));self.assertFalse(f.matches(b));self.assertTrue(f.matches(a))
        with self.assertRaises(ValueError):f.matches(capture_ranges(lambda p,n:b'ab',UIFence(f.fences).plan,{}))
