"""Owned batched UI memory snapshot; no writes, hooks or native calls.

The previous traversal supplies addresses, never values. Every sample recopies
those pages. New allocations use exact reads and enter the next bounded plan;
capture's final identity/visibility/layout fences still use the real reader.
"""
import struct
from live_probe import Reader


class UIReader:
    def __init__(self,native):self.native=native;self.pages=set();self.blocks={}
    def check_alive(self):self.native.check_alive()
    def begin(self):
        previous=self.pages;self.pages=set();self.blocks={}
        if len(previous)>4096:raise ValueError('Native UI read plan exceeds 16 MiB')
        if previous:
            try:self.blocks=self.native.read_many((p,4096)for p in previous)
            except OSError:pass # A destroyed menu can retire previous allocations.
    def read(self,address,count):
        if not 0x10000<=address<0xfff00000 or not 0<count<=4*1024*1024:raise ValueError('Invalid native UI read')
        page=address&~4095;offset=address-page
        if offset+count<=4096:
            self.pages.add(page)
            if len(self.pages)>4096:raise ValueError('Native UI read plan exceeds 16 MiB')
            block=self.blocks.get(page)
            return block[offset:offset+count]if block is not None else self.native.read(address,count)
        pages=range(address&~4095,(address+count+4095)&~4095,4096);self.pages.update(pages)
        if len(self.pages)>4096:raise ValueError('Native UI read plan exceeds 16 MiB')
        if all(p in self.blocks for p in pages):
            return b''.join(self.blocks[p][max(address-p,0):min(address+count-p,4096)]for p in pages)
        return self.native.read(address,count)
    def u32(self,address):return struct.unpack('<I',self.read(address,4))[0]
    def string(self,address,limit=256):return Reader.string(self,address,limit)

