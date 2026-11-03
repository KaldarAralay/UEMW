import ctypes as C
from ctypes import wintypes as W
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from contextlib import redirect_stdout
from unittest.mock import patch

import ui_stream
from shared_channel import Writer,Reader
from ui_scene import HEADER


class UIStreamTests(unittest.TestCase):
    def test_busy_publication_never_reuses_an_immutable_body_identity(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'local/test-temp')as tmp:
            root=Path(tmp);session=str(uuid.uuid4());attempts=[];commits=[]
            class Owner:
                calls=0
                def OpenProcess(self,*args):return 1
                def GetExitCodeProcess(self,handle,code):
                    self.calls+=1;C.cast(code,C.POINTER(W.DWORD))[0]=259 if self.calls<=2 else 0;return True
                def CloseHandle(self,handle):pass
            class Native:
                def __init__(self,pid):pass
                def close(self):pass
            class Capture:
                def __init__(self,r):
                    self.folder=root/'local/ui-assets';self.folder.mkdir(parents=True);self.files={};self.pixel_cache={}
                def sample(self):return dict(width=320,height=200,draws=[],textures=[],native_regions=[],ui=dict(native_ui=False,active_menus=[]),root='0x1',vertices=0,indices=0,texture_bytes=0)
                def close(self):pass
            class BusyOnce:
                def __init__(self,pid,session):self.actual=Writer(pid,session);self.d=self.actual.d
                def publish_ui(self,value,body=b''):
                    attempts.append(value['sequence'])
                    if len(attempts)==1:raise BlockingIOError('owned busy-copy test')
                    result=self.actual.publish_ui(value,body)
                    with Reader(self.d)as r:commits.append(r.read(body=True))
                    return result
                def close(self):self.actual.close()
            with patch.object(ui_stream,'ROOT',root),patch.object(ui_stream,'K',Owner()),patch.object(ui_stream,'Reader',Native),patch.object(ui_stream,'UICapture',Capture),patch.object(ui_stream,'ChannelWriter',BusyOnce),patch.object(ui_stream,'read_file_json',return_value={}),patch.object(ui_stream,'source_identity',return_value=True),patch.object(ui_stream,'wait_period'),patch.dict(os.environ,{'UEMW_UI_SHARED_CHANNEL':'1'}),patch('sys.argv',['ui_stream','--pid','42','--owner','99','--session',session]),redirect_stdout(io.StringIO()):
                ui_stream.main()
            self.assertEqual(attempts,[0,1]);self.assertEqual(len(commits),1)
            packet,body=commits[0];file_body=(root/'local/bridge'/packet['frame_ref']['file']).read_bytes()
            self.assertEqual(body,file_body);self.assertEqual(hashlib.md5(file_body).hexdigest(),packet['frame_ref']['md5'])
            self.assertEqual(HEADER.unpack_from(file_body)[4],packet['sequence'])
            descriptor=json.loads((root/'local/bridge/ui.json').read_text());self.assertEqual(descriptor['protocol'],'uemw.channel')


if __name__=='__main__':unittest.main()
