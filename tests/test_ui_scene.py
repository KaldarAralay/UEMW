import hashlib
import struct
import tempfile
import unittest
from collections import OrderedDict
from pathlib import Path
import numpy as np
from ui_scene import project,clip_triangles,encode,HEADER,DRAW,UICapture,node_identity
from ui_presentation import ready,regions,Transition,LoadingTransition
from presentation_policy import decide,OverlayLatch


class NativeUIProjectionTests(unittest.TestCase):
    def test_motion_is_a_sampled_value_visibility_and_identity_are_fenced(self):
        before=bytes(range(0x90));after=bytearray(before);after[4:8]=bytes(4);after[0x40:0x74]=bytes(0x34)
        self.assertEqual(node_identity(0x10000,before),node_identity(0x10000,after))
        after[0x14]^=1;self.assertNotEqual(node_identity(0x10000,before),node_identity(0x10000,after))

    def test_batched_snapshot_never_reuses_previous_sample_values(self):
        from ui_read import UIReader
        class Native:
            value=1
            def read(self,a,n):return bytes([self.value])*n
            def read_many(self,ranges):return{a:self.read(a,n)for a,n in ranges}
        n=Native();r=UIReader(n);r.begin();self.assertEqual(r.read(0x11003,2),b'\x01\x01')
        n.value=2;r.begin();n.value=3;self.assertEqual(r.read(0x11003,2),b'\x02\x02')
        r.begin();self.assertEqual(r.read(0x11003,2),b'\x03\x03')

    def test_mode_prefetch_reuses_only_addresses_and_retired_hints_do_not_poison_neighbours(self):
        from ui_read import UIReader
        class Native:
            value=1;retired=set();reads=[]
            def read(self,p,n):
                self.reads.append((p,n))
                if any(p<=a<p+n for a in self.retired):raise OSError('retired allocation')
                return bytes([self.value])*n
        n=Native();r=UIReader(n);r.begin('inventory');r.read(0x10000,4);r.read(0x11000,4)
        r.begin('hud');r.read(0x20000,4);n.value=2;n.retired={0x10000};n.reads=[];r.begin('inventory')
        self.assertEqual(r.read(0x11000,4),b'\x02'*4);self.assertNotIn((0x11000,4),n.reads)
        with self.assertRaises(OSError):r.read(0x10000,4)
        n.value=3;r.begin('hud');self.assertEqual(r.read(0x20000,4),b'\x03'*4)

    def test_new_menu_page_is_owned_once_and_never_reused_in_a_new_sample(self):
        from ui_read import UIReader
        class Native:
            value=1
            def __init__(self):self.reads=[]
            def read(self,p,n):self.reads.append((p,n));return bytes([self.value])*n
        n=Native();r=UIReader(n);r.begin('new-menu')
        for i in range(64):self.assertEqual(r.read(0x11000+i*4,4),b'\x01'*4)
        self.assertEqual(n.reads,[(0x11000,4096)])
        n.value=2;r.begin('new-menu');self.assertEqual(r.read(0x11000,4),b'\x02'*4)

    def test_flat_ui_snapshot_owns_cross_page_bytes_and_ignores_failed_spans(self):
        from ui_read import UIReader
        class Bulk:
            api=True
            def __init__(self,native):self.native=native
            def copy_flat(self,plan):
                self.scratch=bytearray([self.native.value])*plan.total
                valid=tuple(not any(p<=a<p+n for a in self.native.retired)for p,n,_ in plan.groups)
                return self.scratch,valid
        class Native:
            value=1;retired=set()
            def __init__(self):self._native_batch=Bulk(self)
            def read(self,p,n):
                if any(p<=a<p+n for a in self.retired):raise OSError('retired page')
                return bytes([self.value])*n
        n=Native();r=UIReader(n);r.begin('inventory');self.assertEqual(r.read(0x10ffc,8),b'\x01'*8)
        n.value=2;r.begin('inventory');n._native_batch.scratch[:]=b'\x09'*len(n._native_batch.scratch);n.value=3
        self.assertEqual(r.read(0x10ffc,8),b'\x02'*8);self.assertEqual(r.read(0x11000,4),b'\x02'*4)
        n.value=4;n.retired={0x10000};r.begin('inventory')
        self.assertEqual(r.read(0x11000,4),b'\x04'*4)
        with self.assertRaises(OSError):r.read(0x10000,4)

    def test_geometry_reuse_requires_current_native_vertices_and_colour(self):
        class Reader:
            def read(self,p,n):return data[p]
        data={1:struct.pack('<9f',-2,2,2,2,2,2,0,2,-2),2:struct.pack('<6f',0,0,1,0,.5,1),3:struct.pack('<3H',0,1,2)}
        c=UICapture.__new__(UICapture);c.r=Reader();c.geometry_cache={};h=bytearray(0x48);struct.pack_into('<I',h,0x1c,1);struct.pack_into('<I',h,0x28,2);struct.pack_into('<I',h,0x3c,3)
        s=dict(vertex_count=3,triangle_count=1,material='0x0',color_mode=0,transform=dict(rotation=np.eye(3).ravel(),scale=1,position=[0,0,0]))
        camera=dict(position=[0,0,0],forward=[0,1,0],right=[1,0,0],up=[0,0,1],frustum=[-1,1,1,-1,1,100])
        node=bytearray(0xa0);struct.pack_into('<13f',node,0x40,*np.eye(3).ravel(),0,0,0,1)
        args=(0x10000,bytes(node),bytes(h),s,camera,b'camera',640,480,(0,0,640,480));first=c.geometry(*args);self.assertIs(c.geometry(*args),first)
        data[1]=struct.pack('<9f',-1,2,2,2,2,2,0,2,-2);changed=c.geometry(*args);self.assertIsNot(changed,first);self.assertNotEqual(first[0][0,0],changed[0][0,0])
        # Journal anchors move final glyphs after native layout. Cached Element
        # boxes are identity metadata, not a second clip on the resolved mesh.
        moved=c.geometry(*args[:-1],(0,0,1,1));self.assertIsNotNone(moved);np.testing.assert_array_equal(moved[0],changed[0])
        # The graph still has its older transform. Current owned header bytes
        # must move the cursor and cannot inherit a prior validation result.
        struct.pack_into('<f',node,0x64,.5);current=(args[0],bytes(node),*args[2:]);translated=c.geometry(*current)
        self.assertIsNot(translated,changed);self.assertNotEqual(translated[0][0,0],changed[0][0,0]);self.assertIs(c.geometry(*current),translated)
        struct.pack_into('<f',node,0x64,float('nan'))
        with self.assertRaisesRegex(ValueError,'transform'):c.geometry(args[0],bytes(node),*args[2:])

    def test_native_perspective_and_near_rejection(self):
        c=dict(position=[0,0,0],forward=[0,1,0],right=[1,0,0],up=[0,0,1],frustum=[-1,1,1,-1,1,100])
        xy,depth=project([[-2,2,2],[2,2,-2],[0,2,0]],c,640,480)
        np.testing.assert_allclose(xy,[[0,0],[640,480],[320,240]])
        np.testing.assert_equal(depth,[2,2,2])
        for point in ([0,1,0],[0,-2,0],[float('nan'),2,0]):
            with self.assertRaises(ValueError):project([point],c,640,480)

    def test_clip_preserves_original_uv_and_alpha_interpolation(self):
        v=np.array([[-10,0,0,0,1,0,0,0],[10,0,1,0,0,1,0,1],[10,20,1,1,0,0,1,1]])
        p,i=clip_triangles(v,[0,1,2],(0,0,20,20))
        self.assertTrue(len(i)>0);self.assertGreaterEqual(p[:,0].min(),0)
        for edge in p[p[:,0]==0]:self.assertAlmostEqual(edge[2],.5);self.assertAlmostEqual(edge[7],.5)
        p,i=clip_triangles(v,[0,1,2],(30,30,40,40));self.assertEqual(p.shape,(0,8));self.assertEqual(i.shape,(0,3))

    def test_wire_layout_retains_identity_and_real_vertex_values(self):
        v=np.array([[1,2,.25,.5,1,0,0,.5],[4,2,.75,.5,0,1,0,1],[1,6,.25,1,0,0,1,1]])
        sample=dict(width=640,height=480,draws=[dict(id=0x10000,texture=0xffffffff,vertices=v,indices=np.array([[0,1,2]],dtype=np.uint16))])
        body=encode(sample,'11112222-3333-4444-5555-666677778888',17,1700000000000000000,42)
        h=HEADER.unpack_from(body);self.assertEqual(HEADER.size,56);self.assertEqual(h[-4:],(42,640,480,1));self.assertEqual(h[4],17)
        self.assertEqual(DRAW.unpack_from(body,56),(0x10000,0xffffffff,3,3))
        self.assertEqual(struct.unpack_from('<4f4B',body,72),(1,2,.25,.5,255,0,0,128))
        self.assertEqual(struct.unpack_from('<3H',body,len(body)-6),(0,1,2))

    def test_wire_cache_requires_immutable_current_geometry_and_keeps_fresh_header(self):
        v=np.array([[1,2,0,0,1,1,1,1],[3,2,1,0,1,1,1,1],[1,4,0,1,1,1,1,1]],dtype=float)
        indices=np.array([[0,1,2]],dtype=np.uint16);v.flags.writeable=False;indices.flags.writeable=False
        draw=dict(id=0x10000,texture=0xffffffff,vertices=v,indices=indices);s=dict(width=640,height=480,draws=[draw]);cache={};session='11112222-3333-4444-5555-666677778888'
        a=encode(s,session,1,1700000000000000000,42,cache);owned=cache[draw['id']][3]
        b=encode(s,session,2,1700000000000000001,42,cache)
        self.assertIs(cache[draw['id']][3],owned);self.assertEqual(a[56:],b[56:]);self.assertEqual(HEADER.unpack_from(b)[4],2)
        self.assertEqual(b,encode(s,session,2,1700000000000000001,42))
        draw['texture']=0;changed=encode(s,session,3,1700000000000000002,42,cache);self.assertNotEqual(changed[56:],b[56:])
        v.flags.writeable=True;v[0,0]=8
        self.assertEqual(encode(s,session,4,1700000000000000003,42,cache),encode(s,session,4,1700000000000000003,42))
        encode({**s,'draws':[]},session,5,1700000000000000004,42,cache);self.assertFalse(cache)

    def test_live_pixel_masks_and_revision_fence(self):
        class Reader:
            def __init__(self,changed=False,alpha=0xff000000):self.changed=changed;self.reads=0;self.alpha=alpha
            def read(self,p,n):
                if p==0x10000:
                    h=bytearray(0x3c);struct.pack_into('<I',h,0x34,0x20000);return bytes(h)
                if p==0x20000:
                    self.reads+=1;h=bytearray(0x48);struct.pack_into('<6I',h,8,1,0xff0000,0xff00,0xff,self.alpha,32);struct.pack_into('<7I',h,0x2c,0x30000,1,2,3,1,4,self.reads if self.changed else 1);return bytes(h)
                if p==0x30000:return bytes([30,20,10,128])
                raise AssertionError(p)
            def u32(self,p):return {1:1,2:1,3:0}[p]
        with tempfile.TemporaryDirectory()as temp:
            c=UICapture.__new__(UICapture);c.r=Reader();c.scene=type('Scene',(),{'ancestry':lambda _,p:['NiSourceTexture']})();c.folder=Path(temp);c.files=OrderedDict();c.used=set()
            row=c.texture(0x10000,0);body=(c.folder/row['file']).read_bytes()
            self.assertEqual(body[12:],bytes([10,20,30,128]));self.assertEqual(row['sha256'],hashlib.sha256(body).hexdigest())
            self.assertIs(c.texture(0x10000,0),row)
            c.r=Reader(alpha=0);row=c.texture(0x10000,0);self.assertEqual((c.folder/row['file']).read_bytes()[12:],bytes([10,20,30,255]))
            from live_probe import SceneReadChanged
            c.r=Reader(True)
            with self.assertRaises(SceneReadChanged):c.texture(0x10000,0)


class NativeUIPresentationTests(unittest.TestCase):
    def test_known_native_loading_recovers_after_catalog_ready_and_has_a_bound(self):
        t=LoadingTransition();self.assertFalse(t.active(False,False,10));self.assertTrue(t.active(True,False,11))
        self.assertTrue(t.active(False,False,12));self.assertFalse(t.active(False,True,12.1));self.assertFalse(t.active(False,False,12.2))
        self.assertTrue(t.active(True,False,20));self.assertFalse(t.active(False,False,40.01))
    def base(self):
        return dict(ui_ready=True,ui_sample_unix_ns=10e9,pid=42,session='a',ui_native_menu=True,ui_menus=['MenuInventory'])

    def test_freshness_menu_and_source_ownership(self):
        r=self.base();s=dict(pid=42,session='a');u=dict(native_ui=True,active_menus=['MenuInventory'])
        self.assertTrue(ready(r,s,u,10.2))
        for patch in (dict(ui_sample_unix_ns=9e9),dict(ui_sample_unix_ns=11e9),dict(session='b'),dict(pid=43),dict(ui_menus=['MenuDialog']),dict(ui_ready=False)):
            self.assertFalse(ready({**r,**patch},s,u,10.2))

    def test_only_bounded_native_ui_regions_map_into_passive_window(self):
        r=dict(ui_width=1024,ui_height=768,ui_native_regions=[[22.5,437,113,618]])
        u=dict(active_menus=['MenuInventory'])
        self.assertEqual(regions(r,[100,100,1920,1080],u),((271,614,399,870),))
        for patch in (dict(ui_width=True),dict(ui_native_regions=[[-1,0,100,100]]),dict(ui_native_regions=[[0,0,float('nan'),100]])):
            with self.assertRaises(ValueError):regions({**r,**patch},[0,0,1024,768],u)
        with self.assertRaises(ValueError):regions(r,[0,0,1024,768],dict(active_menus=['MenuDialog']))

    def test_menu_transition_is_bounded_then_fallback_latches(self):
        t=Transition();self.assertTrue(t.hold('inventory',False,10));self.assertFalse(t.hold('inventory',False,10.151))
        self.assertFalse(t.hold('inventory',True,11));self.assertTrue(t.hold('dialog',False,12))
        cold=Transition();self.assertTrue(cold.hold('first-menu',False,20,1.25));self.assertTrue(cold.hold('first-menu',False,20.8,1.25));self.assertFalse(cold.hold('first-menu',False,21.251,1.25))
        latch=OverlayLatch();latch.apply('a','overlay',True,'ue_native_ui')
        self.assertEqual(latch.apply('a','overlay',False,'ui_unavailable'),(False,'fallback_latched_restart_overlay'))
        self.assertFalse(latch.apply('a','overlay',True,'ue_native_ui')[0])
        self.assertTrue(latch.apply('b','overlay',True,'ue_native_ui')[0])

    def test_mirrored_menu_preserves_ue_scene_loading_returns_original(self):
        args=dict(game_foreground=True,minimized=False,ui_known=True,native_ui=True,source_live=True,renderer_live=True,ui_mirrored=True)
        self.assertEqual(decide('overlay',**args),(True,'ue_native_ui'))
        self.assertEqual(decide('overlay',**{**args,'native_loading':True}),(False,'native_loading'))
        self.assertEqual(decide('overlay',**{**args,'game_foreground':False}),(False,'other_foreground'))
