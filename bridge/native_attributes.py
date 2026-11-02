"""Bounded current vertices/colors for native morphs and sky gradients.

Static world meshes and ordinary bone palettes keep their shared/GPU paths.
Only these small mutable shapes use versioned vertex records (v6 includes resolved UV coordinates).
"""
import struct
import numpy as np
from live_probe import SceneReadChanged
from read_batch import ReadPlan

MORPH=0x7515a0


def identity(raw):
    return (struct.unpack_from('<H',raw,8)[0],struct.unpack_from('<I',raw,0x2c)[0],
            *struct.unpack_from('<4I',raw,0x1c),struct.unpack_from('<H',raw,0x34)[0],struct.unpack_from('<I',raw,0x3c)[0])


def discover(reader,shape):
    if shape.get('particles'):return None
    ptr=int(shape['id'],16);controller=int(shape.get('controller','0x0'),16);seen=set();morph=False
    while controller:
        if controller in seen or len(seen)>=32:raise ValueError('Invalid native geometry controller chain')
        seen.add(controller);raw=reader.read(controller,0x30)
        if struct.unpack_from('<I',raw)[0]==MORPH:
            if struct.unpack_from('<I',raw,0x28)[0]!=ptr:raise SceneReadChanged('Native morpher target changed')
            morph=True
        controller=struct.unpack_from('<I',raw,0x2c)[0]
    water=shape.get('cell_key')in('aux:water','aux:ripple')
    sky=shape.get('cell_key')=='aux:sky'and shape.get('color_mode',2)!=0
    name=shape.get('texture','').replace('\\','/').rsplit('/',1)[-1].lower()
    flare=shape.get('cell_key')in('view:first-person','aux:sky')and name.startswith('tx_sun_flash')
    if not morph and not sky and not water and not flare:return None
    model=int(shape['model'],16);raw=reader.read(model,0x48);color=struct.unpack_from('<I',raw,0x24)[0]
    colors=bool((sky or water or flare)and color and shape.get('color_mode',2)!=0)
    if not morph and not colors and not water and not flare:return None
    key=identity(raw)
    if key[0]!=shape['vertex_count']or key[-2]!=shape['triangle_count']or not key[2]or not key[-1]:raise SceneReadChanged('Native mutable geometry layout changed')
    return dict(shape=ptr,model=model,identity=key,colors=colors,uvs=bool(key[5]),morph=morph,count=key[0])


class AttributeCapture:
    """Prepared bounded buffer addresses; captured bytes never survive a pose."""
    def __init__(self,items):
        self.items=tuple(items)
        if sum(item['count']for item in self.items)>65536:raise ValueError('Native mutable vertex budget exceeded')
        requests=[];headers=[]
        for item in self.items:
            count=item['count'];key=item['identity'];model=item['model']
            headers.append((model,0x48));requests.extend(((model,0x48),(key[2],count*12)))
            if item['colors']:requests.append((key[4],count*4))
            if item['uvs']:requests.append((key[5],count*8))
        self.plan=ReadPlan(requests);self.headers=ReadPlan(headers)


def capture(reader,items):
    prepared=items if isinstance(items,AttributeCapture)else AttributeCapture(items)
    if not prepared.items:return {}
    def read_many(plan):
        return reader.read_many(plan)if hasattr(reader,'read_many')else{p:reader.read(p,n)for p,n in plan}
    blocks=read_many(prepared.plan)
    def read(address,count):
        data=blocks.get(address)
        if data is None or len(data)<count:raise SceneReadChanged('Incomplete native mutable buffer capture')
        return data[:count]
    result={}
    for item in prepared.items:
        model=item['model'];raw=read(model,0x48)
        if identity(raw)!=item['identity']:raise SceneReadChanged('Native mutable geometry identity changed')
        count=item['count'];points=np.frombuffer(read(item['identity'][2],count*12),dtype='<f4').reshape(-1,3).copy()
        if not np.isfinite(points).all()or np.any(np.abs(points)>1e8):raise ValueError('Invalid resolved native morph vertices')
        colors=None
        if item['colors']:
            colors=np.frombuffer(read(item['identity'][4],count*4),dtype=np.uint8).reshape(-1,4)[:,[2,1,0,3]].astype(np.float32)/255
        uvs=None
        if item['uvs']:
            uvs=np.frombuffer(read(item['identity'][5],count*8),dtype='<f4').reshape(-1,2).copy()
            if not np.isfinite(uvs).all()or np.any(np.abs(uvs)>1e8):raise ValueError('Invalid resolved native UV coordinates')
        result[item['shape']]=(points,colors,uvs)
    after=read_many(prepared.headers)
    for item in prepared.items:
        if identity(after[item['model']])!=item['identity']:raise SceneReadChanged('Native mutable geometry changed during capture')
    return result
