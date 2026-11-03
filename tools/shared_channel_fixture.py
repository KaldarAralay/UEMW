"""Owned IPC fixtures for the packaged NullRHI test; no game/installed assets."""
import ctypes as C
import hashlib
import json
import os
import shutil
from pathlib import Path
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'bridge'))
from shared_channel import Writer,HEADER,SLOT,MAX_JSON,STRIDE,K

folder=Path(sys.argv[2])if len(sys.argv)>2 else ROOT/'local/test-temp/client-fixture';token=sys.argv[1]
stop=folder/'shared-exit.request';stop.unlink(missing_ok=True)
template=json.loads((folder/'manifest-state-packed.json').read_text());body=(folder/template['frame_ref']['file']).read_bytes();writers=[];busy_writer=None
try:
    for label in('good','torn','oversize','digest','source','busy'):
        w=Writer(template['pid'],template['session']);writers.append(w);m,_=w.publish(template,body);base=w.view+HEADER.size
        if label=='torn':C.memmove(base+6,b'\0\0',2)
        if label=='oversize':C.memmove(base+16,struct.pack('<I',MAX_JSON+1),4)
        if label=='digest':C.memmove(base+SLOT.size,b'!',1)
        if label=='source':
            text=json.dumps({**m,'pid':43 if m['pid']!=43 else 44},separators=(',',':')).encode();old=json.dumps(m,separators=(',',':')).encode();assert len(text)==len(old)
            C.memmove(base+SLOT.size,text,len(text));C.memmove(base+24,hashlib.md5(text).digest(),16)
        if label=='busy':w.lock();busy_writer=w
        (folder/f'shared-{label}.json').write_text(json.dumps(w.d))
    ui_root=folder/'ui-good';ui=json.loads((ui_root/'local/bridge/ui.json').read_text());ui_body=(ui_root/'local/bridge'/ui['frame_ref']['file']).read_bytes()
    for label in('good','nonce','identity','inline'):
        target=folder/('ui-shared-'+label);shutil.copytree(ui_root,target,dirs_exist_ok=True)
        if label=='inline':
            (target/'local/bridge/ui.json').write_text(json.dumps({**ui,'version':2}));continue
        w=Writer(ui['pid'],ui['session']);writers.append(w);payload=ui_body
        if label=='identity':payload=payload[:40]+struct.pack('<I',ui['pid']+1)+payload[44:]
        m,_=w.publish_ui(ui,payload)
        if label=='nonce':
            import uuid
            m['frame_ref']['channel_nonce']=str(uuid.uuid4());text=json.dumps(m,separators=(',',':')).encode();base=w.view+HEADER.size
            C.memmove(base+SLOT.size,text,len(text));C.memmove(base+24,hashlib.md5(text).digest(),16)
        (target/'local/bridge/ui.json').write_text(json.dumps(w.d))
    (folder/'shared-ready.json').write_text(json.dumps(dict(token=token,pid=os.getpid())))
    until=time.monotonic()+90
    while time.monotonic()<until and not stop.exists():time.sleep(.05)
finally:
    if busy_writer:K.ReleaseMutex(busy_writer.mutex)
    for w in writers:w.close()
