"""x64 bridge-local read-only ABI v1; never loaded into the original game."""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
from pathlib import Path
import struct
import threading
from functools import lru_cache
from read_batch import MAX_TOTAL

ROOT=Path(__file__).resolve().parents[1]
class Range(C.Structure):_fields_=[('address',C.c_uint32),('bytes',C.c_uint32),('offset',C.c_uint32)]
class Result(C.Structure):_fields_=[('bytes',C.c_uint32),('error',C.c_uint32)]

@lru_cache(maxsize=1)
def helper():
    dll=ROOT/'local/bin/read-batch.dll';manifest=dll.with_suffix('.json')
    try:
        metadata=json.loads(manifest.read_text(encoding='utf-8-sig'))
        digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest().lower()
        if struct.calcsize('P')!=8 or metadata.get('abi')!=1 or metadata.get('architecture')!='x64' or digest(dll)!=metadata['dll_sha256'].lower() or digest(ROOT/'native/read_batch.cpp')!=metadata['source_sha256'].lower():return None
        api=C.WinDLL(str(dll));api.UEMWReadBatchVersion.restype=C.c_uint32
        if api.UEMWReadBatchVersion()!=1:return None
        api.UEMWReadBatch.argtypes=[W.HANDLE,C.POINTER(Range),C.c_uint32,C.c_void_p,C.c_uint32,C.POINTER(Result)]
        api.UEMWReadBatch.restype=C.c_uint32
        return api
    except(OSError,ValueError,KeyError,TypeError,AttributeError):return None

class NativeBatch:
    def __init__(self,handle):self.handle=handle;self.api=helper();self.local=threading.local()
    def _execute(self,plan):
        if not self.api:raise RuntimeError('Native read helper is not built or its manifest is stale')
        if not self.handle:raise RuntimeError('Native read handle is closed')
        if not 0<plan.total<=MAX_TOTAL or not 0<len(plan.groups)<=32768:raise ValueError('Invalid native read plan')
        # Descriptors can be cached with the immutable geometry plan. Scratch
        # output is per reader/thread, and no view into it escapes this call.
        descriptors=getattr(plan,'native_descriptors',None)
        if descriptors is None:
            offset=0;values=[]
            for address,count,_ in plan.groups:values.append(Range(address,count,offset));offset+=count
            descriptors=(Range*len(values))(*values);plan.native_descriptors=descriptors
        capacity=1<<(plan.total-1).bit_length();local=self.local
        if getattr(local,'capacity',0)<capacity:
            local.buffer=C.create_string_buffer(capacity);local.capacity=capacity
        if getattr(local,'count',0)<len(plan.groups):local.results=(Result*len(plan.groups))();local.count=len(plan.groups)
        error=self.api.UEMWReadBatch(self.handle,descriptors,len(plan.groups),local.buffer,plan.total,local.results)
        if error:raise OSError(f'Native read batch rejected descriptors: {error}')
        return descriptors,local
    def copy(self,plan):
        descriptors,local=self._execute(plan)
        blocks=[];base=C.addressof(local.buffer)
        for index,row in enumerate(descriptors):
            got=local.results[index]
            blocks.append(C.string_at(base+row.offset,row.bytes)if got.error==0 and got.bytes==row.bytes else None)
        return blocks
    def copy_flat(self,plan):
        descriptors,local=self._execute(plan)
        valid=tuple(local.results[i].error==0 and local.results[i].bytes==row.bytes for i,row in enumerate(descriptors))
        # No mutable thread scratch escapes. Failed spans are never consumed
        # as node data: capture_ranges must fill every requested byte exactly.
        return C.string_at(C.addressof(local.buffer),plan.total),valid
