"""Reuse native UI structure only while every consumed structural read matches.

Actual vertex/material/texture/pose values are still recopied per sample.
Refcounts, transforms and bounds do not define a graph's structure. Visibility,
property links, child arrays, model storage and layout clipping do.
"""
import struct
from collections import OrderedDict
from live_probe import Reader
from ui_fence import UIFence


class Recorder:
    def __init__(self,reader):self.reader=reader;self.reads={}
    def read(self,p,n):
        value=self.reader.read(p,n);self.reads[p,n]=value;return value
    def u32(self,p):return struct.unpack('<I',self.read(p,4))[0]
    def string(self,p,limit=256):
        # Reader.string may fetch beyond the terminating NUL into a neighbour's
        # mutable heap data. Those unused bytes do not define this string.
        if not p:return ''
        out=bytearray()
        while len(out)<limit:
            current=p+len(out);raw=self.reader.read(current,min(limit-len(out),0x1000-(current&0xfff)));end=raw.find(b'\0');used=raw if end<0 else raw[:end+1];self.reads[current,len(used)]=used
            out.extend(raw if end<0 else raw[:end])
            if end>=0:break
        return out.decode('cp1252',errors='replace')
    def check_alive(self):return self.reader.check_alive()


def structural(mode,p,raw,headers,models):
    n=len(raw)
    if mode=='graph'and p in headers and n==0x90:
        return((p,raw[:4]),(p+8,raw[8:0x1c]),(p+0x84,raw[0x84:0x90]))
    if mode=='graph'and p in models and n>=0x36:
        # Scene traversal consumes type and counts. Conversion independently
        # recopies/checks the current pointers and complete native buffers.
        return((p,raw[:4]),(p+8,raw[8:10]),(p+0x34,raw[0x34:0x36]))
    if mode=='layout'and p in headers and n==0x15c:
        return tuple((p+a,raw[a:b])for a,b in((8,12),(0x1c,0x28),(0x75,0x77),(0x88,0x8c),(0x128,0x138)))
    return((p,raw),)


class LayoutCache:
    def __init__(self,mode):self.mode=mode;self.key=None;self.fences=();self.compiled=None;self.value=None;self.reused=False;self.variants=OrderedDict();self.serial=0
    def read(self,reader,key,build):
        self.reused=False
        # A native tooltip can change the structure without changing menus.
        # Retain a few exact variants of the same mode instead of discarding
        # its baseline graph whenever a transient native branch appears.
        for identity,cached in reversed(tuple(self.variants.items())):
            cached_key,fences,compiled,value=cached
            if cached_key!=key or not fences:continue
            try:valid=compiled.check(reader.read)
            except OSError:valid=False
            if valid:
                self.key=key;self.fences,self.compiled,self.value=fences,compiled,value;self.variants.move_to_end(identity);self.reused=True;return value
        recorder=Recorder(reader);value,headers,models=build(recorder)
        fences=[]
        for(p,_),raw in recorder.reads.items():fences.extend(structural(self.mode,p,raw,headers,models))
        if len(fences)>32768:raise ValueError('Native UI structure cache exceeds bounded read plan')
        self.key=key;self.fences=tuple(fences);self.compiled=UIFence(self.fences);self.value=value
        self.serial+=1;self.variants[self.serial]=(key,self.fences,self.compiled,self.value)
        while len(self.variants)>8 or sum(row[2].expected.nbytes for row in self.variants.values())>16*1024*1024:self.variants.popitem(last=False)
        return value
