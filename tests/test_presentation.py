import itertools
import struct
import unittest
from native_ui import inspect_ui
from presentation_policy import decide,OverlayLatch,separate_rect,separate_desktop_rect,preferred_size
from presentation import frame_ready

class OverlayRecoveryTests(unittest.TestCase):
    def test_full_hd_fits_another_display_without_covering_the_native_window(self):
        game=[8,32,1030,797];areas=[[0,0,1920,1040],[-1920,600,0,1680]]
        self.assertEqual(separate_desktop_rect(game,areas,(1920,1080)),[-1920,600,1920,1080])
        self.assertEqual(preferred_size({'viewport':[1920,1080]}),(1920,1080))
        for value in ([True,1080],[1920,0],['1920',1080],[1920],None):
            with self.subTest(value=value),self.assertRaises(ValueError):preferred_size({'viewport':value})
    def test_viewport_shrinks_safely_when_no_display_can_fit_the_request(self):
        game=[8,32,1030,797];areas=[[0,0,1366,1040]]
        x,y,w,h=separate_desktop_rect(game,areas,(1920,1080));self.assertLess(w,1920)
        self.assertTrue(x>=1038 or y>=829);self.assertLessEqual(x+w,1366);self.assertLessEqual(y+h,1040)
    def test_separate_view_never_covers_native_ui_on_small_desktops(self):
        for game,work in (([8,32,1030,797],[0,0,1366,1080]),([-1912,32,1030,797],[-1920,0,0,1080]),([400,50,800,600],[0,0,1920,1080])):
            view=separate_rect(game,work,4/3);self.assertIsNotNone(view)
            x,y,w,h=view;gx,gy,gw,gh=game
            self.assertTrue(x+w<=gx or gx+gw<=x or y+h<=gy or gy+gh<=y)
            self.assertTrue(work[0]<=x<x+w<=work[2] and work[1]<=y<y+h<=work[3])
            self.assertAlmostEqual(w/h,4/3,delta=.02)
        self.assertIsNone(separate_rect([0,0,1920,1080],[0,0,1920,1080],16/9))
    def test_freshness_fault_latches_until_explicit_rearm(self):
        latch=OverlayLatch()
        self.assertEqual(latch.apply('first','overlay',False,'source_unavailable'),(False,'source_unavailable'))
        self.assertEqual(latch.apply('first','overlay',True,'ue_play_view'),(True,'ue_play_view'))
        self.assertEqual(latch.apply('first','overlay',False,'renderer_unavailable'),(False,'fallback_latched_restart_overlay'))
        for _ in range(10):
            self.assertEqual(latch.apply('first','overlay',True,'ue_play_view'),(False,'fallback_latched_restart_overlay'))
        self.assertEqual(latch.apply('second','overlay',True,'ue_play_view'),(True,'ue_play_view'))
    def test_native_menus_and_focus_changes_do_not_latch(self):
        latch=OverlayLatch();latch.apply('first','overlay',True,'ue_play_view')
        for reason in ('native_ui','other_foreground','minimized'):
            latch.apply('first','overlay',False,reason)
            self.assertEqual(latch.apply('first','overlay',True,'ue_play_view'),(True,'ue_play_view'))
        latch.apply('first','overlay',False,'source_unavailable')
        self.assertEqual(latch.apply('first','side-by-side',True,'two_windows'),(True,'two_windows'))


class UIReader:
    def __init__(self, names=('MenuMulti',), menu=False):
        self.memory = {}; self.names = {}; self.changed = False
        self.put(0x7C67DC, struct.pack('<I', 0x10000))
        self.put(0x7D1C28, struct.pack('<I', 0x20000))
        world = bytearray(0xD7); world[0xD6] = menu
        struct.pack_into('<I', world, 0xCC, 123)
        self.put(0x10000, world)
        root = bytearray(0x78)
        struct.pack_into('<3I', root, 0x1C, 0x30000, 0x30000+4*len(names), 0x30400)
        self.put(0x20000, root)
        for index, name in enumerate(names):
            address = 0x40000+index*0x100; text = 0x80000+index*0x100
            self.put(0x30000+index*4, struct.pack('<I', address))
            child = bytearray(0x78); child[0x75] = 1
            struct.pack_into('<I', child, 8, text)
            self.put(address, child); self.names[text] = name
    def check_alive(self): pass
    def put(self, address, data): self.memory.update({address+i:v for i,v in enumerate(data)})
    def read(self, address, size):
        if self.changed and address == 0x2001C and size == 12:
            return bytes(12)
        return bytes(self.memory[address+i] for i in range(size))
    def u32(self, address): return struct.unpack('<I', self.read(address,4))[0]
    def string(self, address, limit): return self.names[address]


class NativeUITests(unittest.TestCase):
    def test_console_and_unknown_menu_uncover_even_without_menu_flag(self):
        for name in ('MenuConsole', 'MenuDialog', 'MenuInventory', 'UnrecognizedMenu'):
            with self.subTest(name=name):
                state = inspect_ui(UIReader(('MenuMulti', name)))
                self.assertFalse(state['menu'])
                self.assertTrue(state['native_ui'])
                self.assertEqual(state['active_menus'], [name])
        self.assertFalse(inspect_ui(UIReader())['native_ui'])
        self.assertTrue(inspect_ui(UIReader(menu=True))['native_ui'])
    def test_last_layout_visibility_also_unmasks_ui(self):
        reader = UIReader(('MenuConsole',))
        reader.put(0x40075, bytes((0,1)))
        self.assertTrue(inspect_ui(reader)['native_ui'])
    def test_unloading_and_invalid_vectors_fail_closed(self):
        for failure in ('unload', 'vector', 'flags'):
            reader = UIReader()
            if failure == 'unload': reader.changed = True
            elif failure == 'vector': reader.put(0x20020, struct.pack('<I', 0x40001))
            else: reader.put(0x40075, b'\x02')
            with self.subTest(failure=failure), self.assertRaises((RuntimeError,ValueError)):
                inspect_ui(reader)


class PresentationPolicyTests(unittest.TestCase):
    def test_all_unsafe_overlay_combinations_uncover_original(self):
        for flags in itertools.product((False,True), repeat=6):
            focused, minimized, known, ui, source, render = flags
            visible, reason = decide('overlay',game_foreground=focused,minimized=minimized,
                ui_known=known,native_ui=ui,source_live=source,renderer_live=render)
            self.assertEqual(visible, focused and not minimized and known and not ui and source and render, flags)
        safe = dict(game_foreground=True,minimized=False,ui_known=True,native_ui=False,source_live=True,renderer_live=True)
        self.assertEqual(decide('bogus',**safe), (False,'invalid_mode'))
    def test_fallback_stays_visible_for_native_ui(self):
        visible, reason = decide('side-by-side',game_foreground=True,minimized=False,ui_known=False,
            native_ui=True,source_live=False,renderer_live=False)
        self.assertTrue(visible)
        self.assertEqual(reason,'two_windows')
    def test_freshness_session_and_pid_are_required(self):
        source = dict(protocol='uemw.live',version=1,pid=123,status='live',geometry_version=1,sample_unix_ns=10e9,session='A',scene_epoch='first')
        render = dict(version=1,live=True,pid=123,renderer_pid=456,session='A',unix_ns=10e9,scene_epoch='first')
        self.assertEqual(frame_ready(source,render,123,456,10.1),(True,True))
        self.assertEqual(frame_ready({**source,'geometry_version':2,'version':2},render,123,456,10.1),(True,True))
        self.assertEqual(frame_ready({**source,'geometry_version':3},render,123,456,10.1),(True,True))
        self.assertEqual(frame_ready({**source,'geometry_version':4},render,123,456,10.1),(True,True))
        self.assertEqual(frame_ready({**source,'geometry_version':5,'version':3},render,123,456,10.1),(True,True))
        self.assertEqual(frame_ready({**source,'geometry_version':6,'version':3},render,123,456,10.1),(True,True))
        self.assertEqual(frame_ready({**source,'geometry_version':6,'version':4,'state_metadata_version':1},render,123,456,10.1),(True,True))
        self.assertEqual(frame_ready({**source,'geometry_version':6,'version':4,'state_metadata_version':2},render,123,456,10.1),(False,True))
        self.assertEqual(frame_ready({**source,'geometry_version':7},render,123,456,10.1),(False,True))
        self.assertEqual(frame_ready(source,render,123,456,10.6),(False,False))
        self.assertEqual(frame_ready(source,render,124,456,10.1),(False,False))
        self.assertEqual(frame_ready(source,render,123,789,10.1),(True,False))
        self.assertEqual(frame_ready(source,{**render,'session':'B'},123,456,10.1),(True,False))
        self.assertEqual(frame_ready(source,{**render,'scene_epoch':'departed'},123,456,10.1),(True,False))
        self.assertEqual(frame_ready({},render,123,456,10.1),(False,False))
