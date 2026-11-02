"""Owned IPC fixtures for the packaged NullRHI test; no game/installed assets."""
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'bridge'))
from shared_channel import Writer,HEADER,SLOT,MAX_JSON,STRIDE,K

folder=ROOT/'local/test-temp/client-fixture';token=sys.argv[1]
stop=folder/'shared-exit.request';stop.unlink(missing_ok=True)
template=json.loads((folder/'manifest-state-packed.json').read_text());body=(folder/template['frame_ref']['file']).read_bytes();writers=[]
try:
    for label in('good','torn','oversize','digest','source','busy'):
        w=Writer(template['pid'],template['session']);writers.append(w);m,_=w.publish(template,body);base=w.view+HEADER.size
        if label=='torn':C.memmove(base+6,b'\0\0',2)
        if label=='oversize':C.memmove(base+16,struct.pack('<I',MAX_JSON+1),4)
        if label=='digest':C.memmove(base+SLOT.size,b'!',1)
        if label=='source':
            text=json.dumps({**m,'pid':43 if m['pid']!=43 else 44},separators=(',',':')).encode();old=json.dumps(m,separators=(',',':')).encode();assert len(text)==len(old)
            C.memmove(base+SLOT.size,text,len(text));C.memmove(base+24,hashlib.md5(text).digest(),16)
        if label=='busy':w.lock()
        (folder/f'shared-{label}.json').write_text(json.dumps(w.d))
    (folder/'shared-ready.json').write_text(json.dumps(dict(token=token,pid=os.getpid())))
    until=time.monotonic()+60
    while time.monotonic()<until and not stop.exists():time.sleep(.05)
finally:
    if writers:K.ReleaseMutex(writers[-1].mutex)
    for w in writers:w.close()
