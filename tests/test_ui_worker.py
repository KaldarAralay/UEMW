import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import ui_stream


class UIWorkerTests(unittest.TestCase):
    def test_busy_unavailable_publication_survives_and_uses_a_new_identity(self):
        capture=Mock();capture.sample.side_effect=RuntimeError('Native UI not initialized')
        channel=Mock();channel.d={'protocol':'uemw.channel'}
        calls=[]
        def publish(value,body):
            calls.append(dict(value))
            if len(calls)==1:raise BlockingIOError('Shared channel copy busy')
            return value,True
        channel.publish_ui.side_effect=publish
        iterations=iter((259,259,0));kernel=Mock()
        def alive(handle,code):code._obj.value=next(iterations);return True
        kernel.GetExitCodeProcess.side_effect=alive
        with tempfile.TemporaryDirectory()as folder:
            root=Path(folder);(root/'local/bridge').mkdir(parents=True)
            with patch.multiple(ui_stream,ROOT=root,K=kernel),patch.object(ui_stream,'Reader'),patch.object(ui_stream,'UICapture',return_value=capture),patch.object(ui_stream,'ChannelWriter',return_value=channel),patch.object(ui_stream,'read_file_json',return_value={}),patch.object(ui_stream,'source_identity',return_value=True),patch.object(ui_stream,'wait_period'),patch('sys.argv',['ui_stream.py','--pid','42','--session','owned','--owner','84']),patch('sys.stdout',io.StringIO()):
                ui_stream.main()
        self.assertEqual([v['sequence']for v in calls],[0,1])
        self.assertTrue(all(v['status']=='unavailable'and 'frame_ref'not in v for v in calls))
        self.assertEqual(capture.sample.call_count,2)
        channel.close.assert_called_once();capture.close.assert_called_once()
