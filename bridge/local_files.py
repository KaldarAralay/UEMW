"""Bounded shared-delete reads for atomically replaced local control files."""
import ctypes as C
from ctypes import wintypes as W
import json
import time

K=C.WinDLL('kernel32',use_last_error=True)
K.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE];K.CreateFileW.restype=W.HANDLE
K.GetFileSizeEx.argtypes=[W.HANDLE,C.POINTER(C.c_longlong)]
K.ReadFile.argtypes=[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p]
K.CloseHandle.argtypes=[W.HANDLE]

_channels={}

def read_json(path,max_bytes=1024*1024):
    key=str(path)
    channel=_channels.get(key)
    if channel is not None:
        if channel.alive():
            try:return channel.read(max_json=max_bytes)[0]
            except BlockingIOError:raise
            except(OSError,ValueError):
                channel.close();del _channels[key];raise
        channel.close();del _channels[key]
    value=read_file_json(path,max_bytes)
    if value.get('protocol')=='uemw.channel':
        from shared_channel import Reader
        channel=Reader(value);_channels[key]=channel
        return channel.read(max_json=max_bytes)[0]
    return value

def read_file_json(path,max_bytes=1024*1024):
    for attempt in range(3):
        handle=K.CreateFileW(str(path),0x80000000,7,None,3,0,None)
        if handle!=C.c_void_p(-1).value:break
        error=C.get_last_error()
        if error not in (2,5,32) or attempt==2:raise C.WinError(error)
        time.sleep(.002)
    try:
        size=C.c_longlong()
        if not K.GetFileSizeEx(handle,C.byref(size)):raise C.WinError(C.get_last_error())
        if not 0<size.value<=max_bytes:raise ValueError('Local JSON exceeds the bounded file limit')
        buf=C.create_string_buffer(size.value);got=W.DWORD()
        if not K.ReadFile(handle,buf,size.value,C.byref(got),None) or got.value!=size.value:raise OSError('Short local control-file read')
        copied=buf.raw
    finally:K.CloseHandle(handle)
    # Release the Windows handle BEFORE parsing. Even shared-delete handles can
    # make replacement defer on some Windows filesystems; parsing needs only
    # our immutable copied bytes, never a live file handle.
    value=json.loads(copied.decode('utf-8-sig'))
    if not isinstance(value,dict):raise ValueError('Local control file must be an object')
    return value
