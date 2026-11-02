"""One local test placement from installed native LAND heights; no game collision."""
import math
import struct
import numpy as np
from interior_catalog import records,fields
from live_probe import ROOT


def heights(raw):
    if len(raw)!=4232:raise ValueError('Invalid original LAND height record')
    origin=struct.unpack_from('<f',raw)[0]
    if not math.isfinite(origin)or abs(origin)>1e6:raise ValueError('Invalid original LAND height origin')
    delta=np.frombuffer(raw,dtype=np.int8,count=65*65,offset=4).reshape(65,65).astype(np.float64)
    first=origin+np.cumsum(delta[:,0]);result=delta.copy();result[:,0]=first
    return np.cumsum(result,axis=1)*8


def select_point(elevations,grid,near,water=0):
    if elevations.shape!=(65,65)or not np.isfinite(elevations).all():raise ValueError('Invalid native LAND sample grid')
    choices=[]
    for y in range(2,63):
        for x in range(2,63):
            ceiling=float(np.max(elevations[y-1:y+2,x-1:x+2]))
            if ceiling>water-512:continue
            point=[grid[0]*8192+x*128,grid[1]*8192+y*128]
            choices.append((math.dist(point,near[:2]),x,y,ceiling,point))
    if not choices:raise RuntimeError('No safely deep native terrain point in this test cell')
    _,x,y,ceiling,point=min(choices)
    return dict(grid=list(grid),sample=[x,y],position=point,terrain_neighborhood_max=ceiling,water_level=water,
                scope='Test placement over installed LAND terrain. Native collision, swimming and camera determine live results.')


def deep_water(grid,near,water=0):
    for kind,payload in records(ROOT/'local/Morrowind/Data Files/Morrowind.esm'):
        if kind!=b'LAND':continue
        data=dict(fields(payload))
        if struct.unpack('<2i',data[b'INTV'])==tuple(grid):return select_point(heights(data[b'VHGT']),grid,near,water)
    raise RuntimeError('No installed native LAND for this test cell')
