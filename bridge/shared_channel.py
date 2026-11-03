"""uemw.channel/v1: bounded same-user Windows IPC, never mapped into Morrowind.

A named mutex protects eight complete snapshots. Readers copy owned bytes,
then release the mutex before hashing/parsing. No gameplay decisions or clocks.
"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
import struct
import uuid

K=C.WinDLL('kernel32',use_last_error=True)
K.CreateFileMappingW.argtypes=[W.HANDLE,C.c_void_p,W.DWORD,W.DWORD,W.DWORD,W.LPCWSTR];K.CreateFileMappingW.restype=W.HANDLE
K.OpenFileMappingW.argtypes=[W.DWORD,W.BOOL,W.LPCWSTR];K.OpenFileMappingW.restype=W.HANDLE
K.MapViewOfFile.argtypes=[W.HANDLE,W.DWORD,W.DWORD,W.DWORD,C.c_size_t];K.MapViewOfFile.restype=C.c_void_p
K.UnmapViewOfFile.argtypes=[C.c_void_p]
K.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR];K.CreateMutexW.restype=W.HANDLE
K.OpenMutexW.argtypes=[W.DWORD,W.BOOL,W.LPCWSTR];K.OpenMutexW.restype=W.HANDLE
K.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];K.WaitForSingleObject.restype=W.DWORD
K.ReleaseMutex.argtypes=[W.HANDLE]
K.CloseHandle.argtypes=[W.HANDLE]
K.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];K.OpenProcess.restype=W.HANDLE

MAX_JSON=64*1024;MAX_BODY=4*1024*1024;SLOTS=8
HEADER=struct.Struct('<4sHHIIII16s16sQII24x');assert HEADER.size==96
SLOT=struct.Struct('<4sHHQII16s16s8x');assert SLOT.size==64
STRIDE=SLOT.size+MAX_JSON+MAX_BODY;CAPACITY=HEADER.size+SLOTS*STRIDE

def guid(value):
    from live_binary import guid as native_guid
    return native_guid(str(value))

def validate_descriptor(d):
    if not isinstance(d,dict)or d.get('protocol')!='uemw.channel'or type(d.get('version'))is not int or d['version']!=1:raise ValueError('Unknown shared channel descriptor')
    for key in('pid','writer_pid'):
        if type(d.get(key))is not int or not 1<=d[key]<=0xffffffff:raise ValueError('Invalid shared channel PID')
    try:session=str(uuid.UUID(d['session']));nonce=str(uuid.UUID(d['nonce']))
    except(KeyError,TypeError,AttributeError)as error:raise ValueError('Invalid shared channel UUID')from error
    expected='Local\\UEMW-v1-'+uuid.UUID(session).hex+'-'+uuid.UUID(nonce).hex
    if d.get('name')!=expected:raise ValueError('Shared channel name/identity mismatch')
    return {**d,'session':session,'nonce':nonce}

class Channel:
    def __init__(self):self.mapping=self.mutex=self.view=self.writer=None;self.d=None;self.generation=0
    def close(self):
        if self.view:K.UnmapViewOfFile(self.view);self.view=None
        for field in('writer','mutex','mapping'):
            handle=getattr(self,field)
            if handle:K.CloseHandle(handle);setattr(self,field,None)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def __del__(self):self.close()
    def alive(self):return bool(self.writer and K.WaitForSingleObject(self.writer,0)==258)
    def lock(self):
        status=K.WaitForSingleObject(self.mutex,0)
        if status==0:return
        if status==0x80:
            K.ReleaseMutex(self.mutex);raise OSError('Shared channel mutex was abandoned')
        if status==258:raise BlockingIOError('Shared channel copy busy')
        raise C.WinError(C.get_last_error())
    def header(self):
        raw=C.string_at(self.view,HEADER.size);magic,version,size,slots,stride,pid,writer,session,nonce,generation,index,reserved=HEADER.unpack(raw)
        if (magic,version,size,slots,stride,pid,writer,session,nonce,reserved)!=(b'UMSC',1,HEADER.size,SLOTS,STRIDE,self.d['pid'],self.d['writer_pid'],guid(self.d['session']),guid(self.d['nonce']),0)or any(raw[72:]):raise ValueError('Invalid shared channel header')
        if generation and index!=(generation-1)%SLOTS:raise ValueError('Invalid shared channel commit')
        return generation,index
    def read(self,*,body=False,generation=None,max_json=MAX_JSON):
        if not self.alive():raise OSError('Shared channel producer exited')
        self.lock()
        try:
            latest,index=self.header()
            wanted=latest if generation is None else generation
            if type(wanted)is not int or wanted<=0 or wanted>latest or latest-wanted>=SLOTS:raise ValueError('Shared frame no longer retained')
            base=self.view+HEADER.size+((wanted-1)%SLOTS)*STRIDE
            raw=C.string_at(base,SLOT.size);magic,version,flags,commit,nj,nb,jhash,bhash=SLOT.unpack(raw)
            if(magic,version,flags,commit)!=(b'UMSL',1,1,wanted)or not 0<nj<=min(MAX_JSON,max_json) or nb>MAX_BODY or any(raw[56:]):raise ValueError('Invalid shared slot header')
            text=C.string_at(base+SLOT.size,nj);payload=C.string_at(base+SLOT.size+nj,nb)if body else None
        finally:K.ReleaseMutex(self.mutex)
        if hashlib.md5(text).digest()!=jhash or(body and hashlib.md5(payload).digest()!=bhash):raise ValueError('Shared slot digest mismatch')
        packet=json.loads(text)
        if not isinstance(packet,dict)or packet.get('session')!=self.d['session']or packet.get('pid')!=self.d['pid']:raise ValueError('Shared snapshot source mismatch')
        if packet.get('version')==5 or(packet.get('protocol')=='uemw.ui'and packet.get('version')==2):
            ref=packet.get('frame_ref',{})
            if ref.get('storage')!='shared-v1'or ref.get('channel_nonce')!=self.d['nonce']or ref.get('commit_generation')!=wanted or ref.get('bytes')!=nb or ref.get('md5')!=bhash.hex():raise ValueError('Shared frame reference mismatch')
        elif nb:raise ValueError('Unexpected body on inline shared status')
        return packet,payload

class Writer(Channel):
    def lock(self):
        status=K.WaitForSingleObject(self.mutex,0)
        # This one writer is still alive. An abandoned previous owner was a
        # read-only peer, so a fresh complete commit can safely replace it.
        if status in(0,0x80):return
        if status==258:raise BlockingIOError('Shared channel copy busy')
        raise C.WinError(C.get_last_error())
    def close(self):
        if self.view and self.mutex and K.WaitForSingleObject(self.mutex,0)in(0,0x80):
            # Cooperative shutdown invalidates all retained frames before the
            # process exits. An interrupted copy is already uncommitted.
            try:C.memmove(self.view+68,struct.pack('<I',1),4)
            finally:K.ReleaseMutex(self.mutex)
        super().close()
    def __init__(self,pid,session):
        super().__init__();nonce=uuid.uuid4();self.d=validate_descriptor(dict(protocol='uemw.channel',version=1,pid=pid,writer_pid=os.getpid(),session=str(uuid.UUID(session)),nonce=str(nonce),name='Local\\UEMW-v1-'+uuid.UUID(session).hex+'-'+nonce.hex))
        try:
            self.mapping=K.CreateFileMappingW(C.c_void_p(-1),None,4,0,CAPACITY,self.d['name'])
            if not self.mapping:raise C.WinError(C.get_last_error())
            if C.get_last_error()==183:raise RuntimeError('Shared channel already exists')
            self.view=K.MapViewOfFile(self.mapping,2|4,0,0,CAPACITY)
            if not self.view:raise C.WinError(C.get_last_error())
            self.mutex=K.CreateMutexW(None,False,self.d['name']+'-mutex')
            if not self.mutex:raise C.WinError(C.get_last_error())
            if C.get_last_error()==183:raise RuntimeError('Shared channel mutex already exists')
            self.writer=K.OpenProcess(0x100000,False,os.getpid())
            if not self.writer:raise C.WinError(C.get_last_error())
            C.memmove(self.view,HEADER.pack(b'UMSC',1,HEADER.size,SLOTS,STRIDE,pid,os.getpid(),guid(session),guid(nonce),0,0,0),HEADER.size)
        except BaseException:self.close();raise
    def publish(self,packet,body=b''):
        return self._publish(packet,body,ui=False)
    def publish_ui(self,packet,body=b''):
        """UI/v2 metadata and owned UUI1 bytes in the unchanged channel/v1 ABI."""
        if type(packet.get('version'))is not int or packet['version']!=1 or(packet.get('status')=='live')!=bool(body)or len(body)>2*1024*1024:raise ValueError('Invalid shared UI publication')
        return self._publish(packet,body,ui=True)
    def _publish(self,packet,body,*,ui):
        if not self.view:raise OSError('Shared channel closed')
        if packet.get('protocol')!=('uemw.ui'if ui else 'uemw.live')or packet.get('session')!=self.d['session']or packet.get('pid')!=self.d['pid']:raise ValueError('Wrong source for shared publisher')
        if len(body)>MAX_BODY:raise ValueError('Shared body exceeds limit')
        generation=self.generation+1
        if generation>9007199254740991:raise ValueError('Shared commit counter exhausted')
        value=dict(packet)
        digest=hashlib.md5(body).digest()
        if body:
            if ui:
                sequence=packet.get('sequence')
                if type(sequence)is not int or not 0<=sequence<=9007199254740991:raise ValueError('Invalid shared UI sequence')
                name='ui-frames/'+uuid.UUID(self.d['session']).hex+'-'+str(sequence)+'.uui'
                if packet.get('frame_ref',{}).get('file')!=name:raise ValueError('Shared UI file identity mismatch')
                value.update(version=2,frame_ref=dict(file=name,bytes=len(body),md5=digest.hex(),storage='shared-v1',channel_nonce=self.d['nonce'],commit_generation=generation))
            else:
                from frame_transport import filename
                value={k:v for k,v in packet.items()if k not in('instances','instance_states','objects','environment','material_frames','material_values')}
                value.update(version=5,state_metadata_version=1,object_count=packet.get('object_count',len(packet.get('objects',[]))),frame_ref=dict(file='frames/'+filename(packet,True),bytes=len(body),md5=digest.hex(),storage='shared-v1',channel_nonce=self.d['nonce'],commit_generation=generation))
        text=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
        if not 0<len(text)<=MAX_JSON:raise ValueError('Shared manifest exceeds limit')
        self.lock()
        try:
            index=(generation-1)%SLOTS;base=self.view+HEADER.size+index*STRIDE
            C.memmove(base,SLOT.pack(b'UMSL',1,0,generation,len(text),len(body),hashlib.md5(text).digest(),digest),SLOT.size)
            C.memmove(base+SLOT.size,text,len(text))
            if body:C.memmove(base+SLOT.size+len(text),body,len(body))
            C.memmove(base+6,struct.pack('<H',1),2)
            C.memmove(self.view,HEADER.pack(b'UMSC',1,HEADER.size,SLOTS,STRIDE,self.d['pid'],self.d['writer_pid'],guid(self.d['session']),guid(self.d['nonce']),generation,index,0),HEADER.size)
            self.generation=generation
        finally:K.ReleaseMutex(self.mutex)
        return value,len(text)

class Reader(Channel):
    def __init__(self,descriptor):
        super().__init__();self.d=validate_descriptor(descriptor)
        try:
            self.writer=K.OpenProcess(0x100000,False,self.d['writer_pid'])
            if not self.alive():raise OSError('Shared channel producer is absent')
            self.mapping=K.OpenFileMappingW(4,False,self.d['name'])
            if not self.mapping:raise C.WinError(C.get_last_error())
            self.view=K.MapViewOfFile(self.mapping,4,0,0,CAPACITY)
            if not self.view:raise C.WinError(C.get_last_error())
            self.mutex=K.OpenMutexW(0x100000|1,False,self.d['name']+'-mutex')
            if not self.mutex:raise C.WinError(C.get_last_error())
        except BaseException:self.close();raise
