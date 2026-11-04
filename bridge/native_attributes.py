"""Bounded current vertices/colors for native morphs and sky gradients.

Static world meshes and ordinary bone palettes keep their shared/GPU paths.
Only these small mutable shapes use versioned vertex records (v6 includes resolved UV coordinates).
"""
import struct
import numpy as np
from live_probe import SceneReadChanged
from read_batch import ReadPlan

MORPH=0x7515a0
UV_CONTROLLER=0x751a00 # NiUVController RTTI getter 0x722950; update 0x7220E0.


def identity(raw,topology='triangles'):
    base=(struct.unpack_from('<H',raw,8)[0],struct.unpack_from('<I',raw,0x2c)[0],*struct.unpack_from('<4I',raw,0x1c))
    if topology=='lines':return (*base,0,struct.unpack_from('<I',raw,0x34)[0],topology,struct.unpack_from('<I',raw)[0])
    result=(*base,struct.unpack_from('<H',raw,0x34)[0],struct.unpack_from('<I',raw,0x3c)[0])
    if topology=='strips':result+=('strips',struct.unpack_from('<H',raw,0x38)[0],struct.unpack_from('<I',raw,0x40)[0],struct.unpack_from('<I',raw)[0])
    return result


def discover(reader,shape):
    if shape.get('particles'):return None
    ptr=int(shape['id'],16);controller=int(shape.get('controller','0x0'),16);seen=set();morph=False;uv_controller=None
    while controller:
        if controller in seen or len(seen)>=32:raise ValueError('Invalid native geometry controller chain')
        seen.add(controller);raw=reader.read(controller,0x30)
        if struct.unpack_from('<I',raw)[0]==MORPH:
            if struct.unpack_from('<I',raw,0x28)[0]!=ptr:raise SceneReadChanged('Native morpher target changed')
            morph=True
        if struct.unpack_from('<I',raw)[0]==UV_CONTROLLER:
            full=reader.read(controller,0x46);target=struct.unpack_from('<I',full,0x28)[0];selected=struct.unpack_from('<H',full,0x44)[0]
            if target!=ptr:raise SceneReadChanged('Native UV controller target changed')
            if selected==0:uv_controller=(controller,target,selected)
            else:shape['unsupported_uv_animation']=selected
        controller=struct.unpack_from('<I',raw,0x2c)[0]
    water=shape.get('cell_key')in('aux:water','aux:ripple')
    sky=shape.get('cell_key')=='aux:sky'and shape.get('color_mode',2)!=0
    name=shape.get('texture','').replace('\\','/').rsplit('/',1)[-1].lower()
    flare=shape.get('cell_key')in('view:first-person','aux:sky','aux:sun_glare')and name.startswith('tx_sun_flash')
    if not morph and not sky and not water and not flare and not uv_controller:return None
    topology=shape.get('topology','triangles');header_size=0x38 if topology=='lines' else 0x48
    model=int(shape['model'],16);raw=reader.read(model,header_size);color=struct.unpack_from('<I',raw,0x24)[0]
    colors=bool((sky or water or flare)and color and shape.get('color_mode',2)!=0)
    if not morph and not colors and not water and not flare and not uv_controller:return None
    key=identity(raw,topology)
    if key[0]!=shape['vertex_count']or (topology!='lines' and key[6]!=shape['triangle_count'])or not key[2]or not key[7]:raise SceneReadChanged('Native mutable geometry layout changed')
    if uv_controller and not key[5]:raise SceneReadChanged('Native UV controller lost its resolved UV buffer')
    return dict(shape=ptr,model=model,identity=key,colors=colors,uvs=bool(key[5]),morph=morph,count=key[0],topology=topology,header_size=header_size,**(dict(billboard=shape['rigid_billboard'])if shape.get('rigid_billboard')else{}),**(dict(uv_controller=uv_controller,uv_sets=struct.unpack_from('<H',raw,0xa)[0])if uv_controller else{}))


class AttributeCapture:
    """Prepared bounded buffer addresses; captured bytes never survive a pose."""
    def __init__(self,items):
        self.items=tuple(items)
        if sum(item['count']for item in self.items)>65536:raise ValueError('Native mutable vertex budget exceeded')
        requests=[];headers=[]
        for item in self.items:
            count=item['count'];key=item['identity'];model=item['model']
            size=item.get('header_size',0x48);headers.append((model,size));requests.extend(((model,size),(key[2],count*12)))
            if item['colors']:requests.append((key[4],count*4))
            if item['uvs']:requests.append((key[5],count*8))
            if item.get('uv_controller'):requests.append((item['uv_controller'][0],0x46))
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
        model=item['model'];raw=read(model,item.get('header_size',0x48))
        if identity(raw,item.get('topology','triangles'))!=item['identity']:raise SceneReadChanged('Native mutable geometry identity changed')
        if item.get('uv_controller'):
            controller,target,selected=item['uv_controller'];control=read(controller,0x46)
            if struct.unpack_from('<I',control)[0]!=UV_CONTROLLER or struct.unpack_from('<I',control,0x28)[0]!=target or struct.unpack_from('<H',control,0x44)[0]!=selected or struct.unpack_from('<H',raw,0xa)[0]!=item['uv_sets']:raise SceneReadChanged('Native UV controller identity or selection changed')
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
        if identity(after[item['model']],item.get('topology','triangles'))!=item['identity']:raise SceneReadChanged('Native mutable geometry changed during capture')
    return result
