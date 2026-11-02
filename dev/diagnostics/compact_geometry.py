"""Geometry v3 diagnostic expansion; the UE renderer consumes rows directly."""
from functools import lru_cache
import math
from pathlib import Path
import re
from local_files import read_json
from live_probe import ROOT

@lru_cache(maxsize=8)
def bindings(name,assets):
    if not re.fullmatch(r'catalog-[0-9a-f]{32}\.json',name):raise ValueError('Invalid compact catalog path')
    catalog=read_json(Path(assets)/name,8*1024*1024);rows=catalog.get('bindings')
    if catalog.get('format')!='uemw.assets' or catalog.get('version')!=1 or not isinstance(rows,list) or not 0<len(rows)<=16384:raise ValueError('Invalid compact bindings')
    cells=catalog.get('cells')
    owners={'exterior:-2,-9','exterior:-2,-8'} if cells is None else set()
    if cells is not None:
        if not isinstance(cells,list) or len(cells)>9:raise ValueError('Invalid compact cell budget')
        for c in cells:
            grid=c.get('grid')
            if not isinstance(grid,list) or len(grid)!=2 or any(type(v)is not int or abs(v)>32768 for v in grid) or c.get('key')!=f'exterior:{grid[0]},{grid[1]}' or c['key']in owners:raise ValueError('Invalid compact cell declaration')
            owners.add(c['key'])
    ids=set()
    for b in rows:
        if not isinstance(b,dict) or not isinstance(b.get('id'),str) or len(b['id'])>64 or b['id']in ids or b.get('asset')not in catalog['meshes']:raise ValueError('Invalid compact binding identity')
        if b.get('cell_key')is not None and b['cell_key']not in owners:raise ValueError('Invalid compact cell owner')
        ids.add(b['id'])
    return rows

def numbers(values,count):
    return isinstance(values,list) and len(values)==count and all(type(v)in(int,float) and math.isfinite(v) and abs(v)<=1e8 for v in values)

def expand(packet,assets=None):
    if packet.get('geometry_version')not in(3,4):return packet
    definitions=bindings(packet['scene_catalog'],str(assets or ROOT/'local/assets'))
    states=packet.get('instance_states')
    if not isinstance(states,list) or len(states)!=len(definitions):raise ValueError('Compact binding/state count mismatch')
    instances=[]
    for b,row in zip(definitions,states):
        if not isinstance(row,list) or not row or type(row[0])is not bool:raise ValueError('Invalid compact visibility')
        item={**b,'visible':row[0]}
        if not row[0]:
            if len(row)!=1:raise ValueError('Invalid hidden compact state')
        else:
            if len(row)not in((2,3,4)if packet['geometry_version']==4 else(2,3)) or not numbers(row[1],13):raise ValueError('Invalid compact transform')
            item['transform']=row[1]
            if len(row)>=3:
                if not isinstance(row[2],list) or not 0<len(row[2])<=65535*3 or len(row[2])%3 or not numbers(row[2],len(row[2])):raise ValueError('Invalid compact pose')
                item['deformed']=row[2]
            if len(row)==4:
                if not numbers(row[3],len(row[2])//3*4)or any(v<0 or v>1 for v in row[3]):raise ValueError('Invalid compact colors')
                item['colors']=row[3]
        instances.append(item)
    return {**packet,'instances':instances}
