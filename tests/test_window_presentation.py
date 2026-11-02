"""Ordinary separate presentation never depends on layered-window alpha."""
import unittest
from unittest.mock import patch
import presentation
from presentation_policy import window_style


class WindowTests(unittest.TestCase):
    def test_separate_style_removes_overlay_flags_but_keeps_no_activate(self):
        style=window_style(0x80000|0x20|0x40000,True)
        self.assertFalse(style&0x80000);self.assertFalse(style&0x20);self.assertFalse(style&0x40000)
        self.assertTrue(style&0x08000000);self.assertTrue(style&0x80)
        overlay=window_style(style,False);self.assertTrue(overlay&0x80000);self.assertTrue(overlay&0x20)

    def test_separate_visibility_uses_no_activate_show_instead_of_alpha(self):
        class Api:
            visible=False
            def GetWindowLongPtrW(self,*args):return 0x08000080
            def ShowWindow(self,window,command):self.command=command;self.visible=bool(command)
            def IsWindowVisible(self,window):return self.visible
            def SetLayeredWindowAttributes(self,*args):raise AssertionError('Ordinary swapchain cannot use layered alpha')
        api=Api()
        with patch.object(presentation,'U',api):
            presentation.set_visible(123,True);self.assertEqual(api.command,4);self.assertEqual(presentation.opacity(123),255)
            presentation.set_visible(123,False);self.assertEqual(api.command,0);self.assertEqual(presentation.opacity(123),0)


if __name__=='__main__':unittest.main()
