"""Read the original x86 DataHandler's nine committed exterior entries.

Slot order is deliberately ignored: identify cells by captured grid coordinates.
MWSE headers are layout references only; no MWSE code is loaded or called.
"""
import struct
import math
from live_probe import SceneReadChanged
from scene_reader import scene_roots

def retain_prepared_cells(desired,retained,resident,counts,budget=12000):
    """Keep bounded prepared coverage while its actual native roots reside.

    Turning the camera must not retire/recreate an otherwise resident cell.
    Newly required cells always take precedence over optional retained cells.
    """
    result={c['key']:c for c in desired};live={(c['cell_ptr'],tuple(c['roots']))for c in resident}
    estimate=sum(counts.get(c['key'],3000)for c in desired)
    for c in retained:
        n=counts.get(c['key'],3000)
        if c['key']not in result and (c['cell_ptr'],tuple(c['roots']))in live and estimate+n<=budget:
            result[c['key']]=c;estimate+=n
    return sorted(result.values(),key=lambda c:tuple(c['grid']))

def loaded_exteriors(reader,data):
    table=reader.read(data+4,36)
    result=[];grids=set();cells=set()
    for entry in struct.unpack('<9I',table):
        if not entry:continue
        raw=reader.read(entry,12)
        state,cell=struct.unpack_from('<B3xI',raw)
        if state>5:raise ValueError('Unsupported exterior loading state')
        if state!=1 or not cell:continue
        header=reader.read(cell,0x30)
        if header[4:8]!=b'CELL':raise ValueError('Unexpected exterior cell record')
        flags=struct.unpack_from('<I',header,0x18)[0]
        if flags&1:raise ValueError('Interior appeared in exterior residency table')
        grid=struct.unpack_from('<2i',header,0x24)
        if grid in grids or cell in cells:raise SceneReadChanged('Exterior table changed during capture')
        grids.add(grid);cells.add(cell)
        roots=scene_roots(reader,cell)
        result.append(dict(cell_ptr=hex(cell),grid=grid,flags=flags,
            name=reader.string(struct.unpack_from('<I',header,0x10)[0]),
            roots=[hex(p)for p in roots],key=f'exterior:{grid[0]},{grid[1]}'))
        if reader.read(entry,12)!=raw:raise SceneReadChanged('Exterior loading entry changed during capture')
    if reader.read(data+4,36)!=table:raise SceneReadChanged('Exterior residency table changed during capture')
    return sorted(result,key=lambda c:c['grid'])

def desired_grids(base,preload=True):
    """Conservative XY envelope of the captured original view, with preload margin."""
    camera=base.get('camera')
    if not camera:return {tuple(base['cell_grid'])}
    origin=camera['position'];f=camera['forward'];u=camera['up']
    right=(f[1]*u[2]-f[2]*u[1],f[2]*u[0]-f[0]*u[2],f[0]*u[1]-f[1]*u[0])
    left,r,top,bottom,near,far=camera['frustum']
    values=(*origin,*f,*u,left,r,top,bottom,near,far)
    if not all(math.isfinite(v)for v in values) or not 0<near<far<=20000:raise ValueError('Unsupported streaming frustum')
    points=[origin]
    for depth in (near,far):
        for x in (left,r):
            for y in (bottom,top):points.append(tuple(origin[i]+f[i]*depth+right[i]*x*depth/near+u[i]*y*depth/near for i in range(3)))
    lo=[min(p[i]for p in points)for i in range(2)];hi=[max(p[i]for p in points)for i in range(2)]
    margin=384 if preload else 0
    cx,cy=base['cell_grid']
    # Original Morrowind itself has a nine-cell resident neighborhood. Geometry
    # outside that neighborhood is neither synthesized nor requested from UE.
    xs=range(max(cx-1,math.floor((lo[0]-margin)/8192)),min(cx+1,math.floor((hi[0]+margin)/8192))+1)
    ys=range(max(cy-1,math.floor((lo[1]-margin)/8192)),min(cy+1,math.floor((hi[1]+margin)/8192))+1)
    grids={(x,y)for x in xs for y in ys};grids.add(tuple(base['cell_grid']))
    return grids

def render_cells(reader,base,retained=None):
    resident=loaded_exteriors(reader,int(base['data'],16));wanted=desired_grids(base)
    cells=[c for c in resident if c['grid']in wanted]
    # A prefetch envelope can include cells the original engine has not yet
    # committed. Render only its committed cells; a pending neighbor must not
    # freeze the camera/actors in every already-resident cell.
    if any(len(c['roots'])!=3 for c in cells):
        raise SceneReadChanged('Committed exterior cell has invalid root slots')
    if not any(c['cell_ptr']==base['cell_ptr'] and c['grid']==tuple(base['cell_grid'])for c in cells):raise SceneReadChanged('Active cell is not committed')
    if retained is not None:
        live={(c['cell_ptr'],tuple(c['roots']))for c in resident}
        return cells,all((c['cell_ptr'],tuple(c['roots']))in live for c in retained)
    return cells
