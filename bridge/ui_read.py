"""Owned batched UI memory snapshot; no writes, hooks or native calls.

The previous traversal supplies addresses, never values. Every sample recopies
those pages. New allocations use exact reads and enter the next bounded plan;
capture's final identity/visibility/layout fences still use the real reader.
"""
import struct
from collections import OrderedDict
from live_probe import Reader
from read_batch import ReadPlan


class UIReader:
    def __init__(self,native):self.native=native;self.pages=set();self.blocks={};self.modes=OrderedDict();self.mode=None
    def check_alive(self):self.native.check_alive()
    def remember(self,mode,pages):
        previous=self.modes.get(mode)
        if previous is None or previous[0]!=pages:self.modes[mode]=(pages,ReadPlan(((p,4096)for p in pages),max_gap=0))
        self.modes.move_to_end(mode)
        while len(self.modes)>8:self.modes.popitem(last=False)
    def begin(self,mode=None):
        previous=self.pages
        if previous:self.remember(self.mode,previous)
        self.mode=mode;known=self.modes.get(mode)
        if known is not None:previous=known[0]
        self.pages=set();self.blocks={}
        if len(previous)>4096:raise ValueError('Native UI read plan exceeds 16 MiB')
        if previous:
            self.remember(mode,previous);plan=self.modes[mode][1]
            bulk=getattr(self.native,'_native_batch',None)
            flat=valid=blocks=None
            if bulk and bulk.api:
                if hasattr(bulk,'copy_flat'):
                    flat,valid=bulk.copy_flat(plan);flat=bytes(flat)
                    if len(flat)!=plan.total or len(valid)!=len(plan.groups):raise OSError('Incomplete owned UI snapshot')
                else:blocks=bulk.copy(plan)
            for i,(p,n,pages)in enumerate(plan.groups):
                try:
                    if flat is not None:
                        if not valid[i]:raise OSError('Retired optional UI prefetch span')
                        # Page addresses point into one immutable owned copy.
                        # No views into the helper's reusable scratch escape.
                        self.blocks.update((a,(flat,plan.offsets[a][0]))for a,_ in pages);continue
                    raw=blocks[i]if blocks is not None else self.native.read(p,n)
                    if raw is None or len(raw)!=n:raise OSError('Retired optional UI prefetch span')
                    self.blocks.update((a,(raw,a-p))for a,_ in pages)
                except OSError:
                    # These are address hints, not required current fields.
                    # Retain readable neighbours if a prior menu retired one
                    # allocation. An actual field read below still fails if
                    # its bytes are unreadable; no old values are retained.
                    for a,size in pages:
                        try:
                            raw=self.native.read(a,size)
                            if len(raw)==size:self.blocks[a]=(raw,0)
                        except OSError:pass
    def read(self,address,count):
        if not 0x10000<=address<0xfff00000 or not 0<count<=4*1024*1024:raise ValueError('Invalid native UI read')
        page=address&~4095;offset=address-page
        if offset+count<=4096:
            self.pages.add(page)
            if len(self.pages)>4096:raise ValueError('Native UI read plan exceeds 16 MiB')
            block=self.blocks.get(page)
            if block is None:
                # New menu allocations are not in the previous address plan.
                # Own their page on first use instead of issuing a native call
                # for every small field on that same page. This sample alone
                # owns the bytes; begin() always discards all prior values.
                try:
                    block=self.native.read(page,4096)
                    if len(block)!=4096:raise OSError('Short optional UI page')
                    self.blocks[page]=(block,0)
                except OSError:return self.native.read(address,count)
                return block[offset:offset+count]
            raw,base=block;return raw[base+offset:base+offset+count]
        pages=range(address&~4095,(address+count+4095)&~4095,4096);self.pages.update(pages)
        if len(self.pages)>4096:raise ValueError('Native UI read plan exceeds 16 MiB')
        for p in pages:
            if p not in self.blocks:
                try:
                    block=self.native.read(p,4096)
                    if len(block)!=4096:raise OSError('Short optional UI page')
                    self.blocks[p]=(block,0)
                except OSError:return self.native.read(address,count)
        raw,base=self.blocks[page]
        if all(self.blocks[p][0]is raw and self.blocks[p][1]==base+p-page for p in pages):return raw[base+offset:base+offset+count]
        return b''.join(raw[base+max(address-p,0):base+min(address+count-p,4096)]for p in pages for raw,base in(self.blocks[p],))
    def u32(self,address):return struct.unpack('<I',self.read(address,4))[0]
    def string(self,address,limit=256):return Reader.string(self,address,limit)

