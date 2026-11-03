"""Bounded read-only native static overrides, including unloaded-cell refs.

Vanilla materializes persistent/modified references in the all-cell list.
Never call game functions or force it to load an exterior cell for rendering.
"""
import math,struct
from live_probe import SceneReadChanged


def rotation(angles):
    x,y,z=(-a for a in angles);cx,sx=math.cos(x),math.sin(x);cy,sy=math.cos(y),math.sin(y);cz,sz=math.cos(z),math.sin(z)
    return [cy*cz,-cy*sz,sy,cx*sz+sx*sy*cz,cx*cz-sx*sy*sz,-sx*cy,sx*sz-cx*sy*cz,sx*cz+cx*sy*sz,cx*cy]


class NativeStatics:
    def __init__(self,reader):self.r=reader;self.cells={};self.cell_identity=None

    def discover(self):
        r=self.r;data=r.u32(0x7c67e0);nd=r.u32(data);head=r.u32(nd+0xb264);header=r.read(head,12)
        key=(data,nd,head,header)
        if key==self.cell_identity:return self.cells
        count,current,tail=struct.unpack('<3I',header)
        if not 0<count<=16384:raise ValueError('Native scenery cell-list budget exceeded')
        cells={};seen=set()
        for _ in range(count):
            if not current or current in seen:raise SceneReadChanged('Native scenery cell list cycled')
            seen.add(current);cell,previous,nxt=struct.unpack('<3I',r.read(current,12));raw=r.read(cell,0x30)
            if raw[4:8]!=b'CELL':raise SceneReadChanged('Native scenery cell type changed')
            if not struct.unpack_from('<I',raw,0x18)[0]&1:
                grid=struct.unpack_from('<2i',raw,0x24)
                if grid in cells:raise SceneReadChanged('Ambiguous native scenery cell grid')
                cells[grid]=cell
            current=nxt
        if current not in(0,head+4)or r.read(head,12)!=header or r.u32(data)!=nd:raise SceneReadChanged('Native scenery cell list changed')
        self.cells=cells;self.cell_identity=key;return cells

    def overrides(self,grids):
        r=self.r;cells=self.discover();result={};kinds={};total=0
        for grid in grids:
            cell=cells.get(tuple(grid))
            if cell is None:continue
            identity=r.read(cell,0x30)
            if identity[4:8]!=b'CELL'or struct.unpack_from('<2i',identity,0x24)!=tuple(grid):raise SceneReadChanged('Native distant-cell identity changed')
            for offset in(0x30,0x40,0x58):
                header=r.read(cell+offset,12);count,current,tail=struct.unpack('<3I',header)
                total+=count
                if count>16384 or total>65536:raise ValueError('Native distant-reference budget exceeded')
                seen=set()
                for _ in range(count):
                    if not current or current in seen:raise SceneReadChanged('Native distant-reference list changed')
                    seen.add(current);raw=r.read(current,0x50)
                    if raw[4:8]!=b'REFR':raise SceneReadChanged('Native distant reference retired')
                    if struct.unpack_from('<I',raw,0x14)[0]!=cell+offset:raise SceneReadChanged('Native distant reference changed owning cell list')
                    physical=struct.unpack_from('<I',raw,0x28)[0]
                    if physical not in kinds:kinds[physical]=r.read(physical+4,4)
                    if kinds[physical]==b'STAT':
                        source,target=struct.unpack_from('<2I',raw,0x48);flags=struct.unpack_from('<I',raw,8)[0]
                        position=struct.unpack_from('<3f',raw,0x38);angles=struct.unpack_from('<3f',raw,0x2c)
                        if any(not math.isfinite(x)or abs(x)>1e8 for x in(*position,*angles)):raise SceneReadChanged('Invalid native distant transform')
                        if source:
                            result[source]=dict(id=source,target=target,reference=hex(current),base=r.string(r.u32(physical+0x2c)).lower(),disabled=bool(flags&0x800),deleted=bool(flags&0x20),position=position,orientation=angles,scale=((flags>>16)or 1000)*.001,native_grid=tuple(grid))
                    current=struct.unpack_from('<I',raw,0x20)[0]
                if current or r.read(cell+offset,12)!=header:raise SceneReadChanged('Native distant-reference list changed during read')
            if r.read(cell,0x30)!=identity:raise SceneReadChanged('Native distant-cell changed during read')
        return result

    def moved(self):
        """Resolve moved STAT refs even when their origin is outside the view.

        Unresolved original move entries suppress their origin's static layer;
        guessing its old master-file placement could resurrect a moved object.
        """
        r=self.r;result={};suppressed=set();cells=self.discover();total=0
        for grid,cell in cells.items():
            pointers=r.read(cell+0x50,8)
            for number,pointer in enumerate(struct.unpack('<2I',pointers)):
                if not pointer:continue
                header=r.read(pointer,16);table,count,current,tail=struct.unpack('<4I',header)
                total+=count
                if not 0x740000<=table<0x780000 or count>16384 or total>65536:raise SceneReadChanged('Invalid native moved-reference list')
                previous=0;seen=set()
                for _ in range(count):
                    if not current or current in seen:raise SceneReadChanged('Native moved-reference list cycled')
                    seen.add(current);before,nxt,data=struct.unpack('<3I',r.read(current,12))
                    if before!=previous:raise SceneReadChanged('Native moved-reference links changed')
                    if not data:raise SceneReadChanged('Native moved-reference data missing')
                    if number==1:suppressed.add(grid) # Source-ID-only entry lacks a current pose.
                    else:
                        flags,reference,source,destination=struct.unpack('<4I',r.read(data,16))
                        if not reference:suppressed.add(grid)
                        else:
                            raw=r.read(reference,0x50)
                            if raw[4:8]!=b'REFR':raise SceneReadChanged('Moved original reference retired')
                            physical=struct.unpack_from('<I',raw,0x28)[0]
                            if r.read(physical+4,4)==b'STAT':
                                source,target=struct.unpack_from('<2I',raw,0x48);value=struct.unpack_from('<I',raw,8)[0];owner=struct.unpack_from('<I',raw,0x14)[0]
                                owner_cell=r.u32(owner+0xc)if owner else 0
                                h=r.read(owner_cell,0x30)if owner_cell else b''
                                if not source or len(h)!=0x30 or h[4:8]!=b'CELL':suppressed.add(grid)
                                else:
                                    position=struct.unpack_from('<3f',raw,0x38);angles=struct.unpack_from('<3f',raw,0x2c)
                                    if any(not math.isfinite(x)or abs(x)>1e8 for x in(*position,*angles)):raise SceneReadChanged('Invalid moved static pose')
                                    inside=bool(struct.unpack_from('<I',h,0x18)[0]&1)
                                    result[source]=dict(id=source,target=target,reference=hex(reference),base=r.string(r.u32(physical+0x2c)).lower(),disabled=bool(value&0x800),deleted=bool(value&0x20),position=position,orientation=angles,scale=((value>>16)or 1000)*.001,native_grid=None if inside else struct.unpack_from('<2i',h,0x24),interior=inside)
                    previous=current;current=nxt
                if current or previous!=tail or r.read(pointer,16)!=header:raise SceneReadChanged('Native move list changed during read')
            if r.read(cell+0x50,8)!=pointers:raise SceneReadChanged('Native move lists changed')
        return result,suppressed
