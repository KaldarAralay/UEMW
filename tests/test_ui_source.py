import unittest
from unittest.mock import patch
from ui_stream import source_identity
from ui_stream import retire_cached_images
from ui_stream import wait_period
from collections import OrderedDict


class UISourceIdentityTests(unittest.TestCase):
    def test_menu_wait_respects_cadence_and_wakes_for_native_mode_change(self):
        clock=[0.0];sleeps=[]
        def sleep(seconds):sleeps.append(seconds);clock[0]+=seconds
        capture=type('Capture',(),{})()
        with patch('ui_stream.time.perf_counter',side_effect=lambda:clock[0]),patch('ui_stream.time.sleep',side_effect=sleep):
            wait_period(capture,0,1/60);self.assertAlmostEqual(clock[0],1/60);self.assertTrue(all(0<=v<=.002 for v in sleeps))
            sleeps.clear();clock[0]=.025;wait_period(capture,0,1/60);self.assertEqual(sleeps,[0]);self.assertEqual(clock[0],.025)
            class Native:
                def u32(self,address):return 0x10000
                def read(self,address,count):return b'\x01'
            capture.native=Native();capture.menu_probe=(0x10000,False);clock[0]=0;sleeps.clear();wait_period(capture,0,1/30)
            self.assertLess(clock[0],.003);self.assertEqual(sleeps,[.002])
    def test_retirement_keeps_all_still_referenced_font_and_pixel_rows(self):
        capture=type('Capture',(),{})();kept={'file':'font.utx'};old={'file':'old.utx'}
        capture.files=OrderedDict(font=kept,old=old);capture.pixel_cache=OrderedDict({1:('current bytes',kept),2:('old bytes',old)})
        retire_cached_images(capture,{'old.utx'})
        self.assertEqual(list(capture.files),['font']);self.assertIs(capture.files['font'],kept);self.assertEqual(list(capture.pixel_cache),[1])
    def test_original_owner_and_session_are_required_without_reading_pose_slots(self):
        session='11112222-3333-4444-5555-666677778888';nonce='99990000-aaaa-bbbb-cccc-ddddeeeeffff'
        value=dict(protocol='uemw.channel',version=1,pid=42,writer_pid=43,session=session,nonce=nonce,name='Local\\UEMW-v1-'+session.replace('-','')+'-'+nonce.replace('-',''))
        with patch('shared_channel.Reader',side_effect=AssertionError('UI must not resolve world poses')):
            self.assertTrue(source_identity(value,42,session,43))
            self.assertFalse(source_identity(value,42,session,44))
            self.assertFalse(source_identity(value,41,session,43))
            self.assertFalse(source_identity(value,42,nonce,43))
        with self.assertRaises(ValueError):source_identity({**value,'name':'unbound'},42,session,43)
        self.assertFalse(source_identity(dict(protocol='other',version=1,pid=42,session=session),42,session,43))
