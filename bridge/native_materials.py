"""Read native resolved base-map flip frames; never advance an animation clock."""
import struct
import hashlib
from live_probe import SceneReadChanged
from read_batch import ReadPlan

FLIP=0x751520
SOURCE_TEXTURE=0x75062c
TEXTURING=0x750778


def discover(reader,prop,generation='',map_index=0):
    if not 0<=map_index<14:raise ValueError('Invalid native texture flip slot')
    if not prop:return None
    if reader.u32(prop)!=TEXTURING:return None
    controller=reader.u32(prop+0x10);seen=set();found=None
    while controller:
        if controller in seen or len(seen)>=32:raise ValueError('Invalid native material controller chain')
        seen.add(controller);raw=reader.read(controller,0x34)
        if struct.unpack_from('<I',raw)[0]==FLIP:
            full=reader.read(controller,0x54)
            target=struct.unpack_from('<I',full,0x28)[0];affected=struct.unpack_from('<I',full,0x50)[0]
            if target!=prop:raise SceneReadChanged('Native texture flip target changed')
            if affected==map_index:
                if found:raise ValueError('Multiple native base-map flip controllers')
                # NI::TArray has a vtable at +0, then storage/capacity/end.
                storage,capacity,count=struct.unpack_from('<3I',full,0x38)
                if not storage or not 1<=count<=capacity<=256:raise ValueError('Invalid native texture flip palette')
                pointers=reader.read(storage,count*4);textures=struct.unpack('<'+'I'*count,pointers);names=[]
                for texture in textures:
                    if not texture or reader.u32(texture)!=SOURCE_TEXTURE:raise ValueError('Unsupported native flip texture type')
                    name=reader.string(reader.u32(texture+0x2c),512)
                    if not name:raise ValueError('Native flip texture has no source filename')
                    names.append(name)
                maps=reader.u32(prop+0x20);end=reader.u32(prop+0x28)
                if not maps or not map_index<end<=16:raise SceneReadChanged('Native flip map changed')
                mapping=reader.u32(maps+map_index*4)
                if not mapping:raise SceneReadChanged('Native flip base map missing')
                identity=hashlib.sha256(struct.pack('<I',storage)+pointers).hexdigest()[:12]
                found=dict(id=generation+':'+hex(controller)+':'+identity,controller=controller,property=prop,storage=storage,
                           capacity=capacity,count=count,pointers=pointers,textures=textures,names=tuple(names),maps=maps,mapping=mapping,map_index=map_index)
        controller=struct.unpack_from('<I',raw,0x2c)[0]
    return found


class FlipCapture:
    """Prepared addresses and immutable identity fences, never cached frames.

    Rebuilt with each adopted original topology. A single read-many operation
    samples every controller/palette/map before any resolved index is returned.
    The existing read plan handles inaccessible unrequested gaps exactly.
    """
    def __init__(self,flips):
        if len(flips)>256:raise ValueError('Native material group budget exceeded')
        self.items=dict(flips)
        records=[];requests=[]
        for key,item in flips.items():
            controller,prop,storage,maps,mapping=(item[k]for k in ('controller','property','storage','maps','mapping'))
            count,capacity=item['count'],item['capacity']
            pointers=bytes(item['pointers']);textures=tuple(item['textures'])
            slot=item.get('map_index',0)
            if not 0<=slot<14:raise ValueError('Invalid prepared native texture slot')
            if not 1<=count<=capacity<=256 or len(pointers)!=count*4 or len(textures)!=count:
                raise ValueError('Invalid prepared native flip palette')
            records.append((key,controller,prop,storage,capacity,count,pointers,textures,maps,mapping,slot))
            requests.extend(((controller,0x54),(storage,count*4),(prop,0x24),(maps+slot*4,4),(mapping+4,4)))
        self.records=tuple(records);self.plan=ReadPlan(requests)

    def subset(self,properties):
        return FlipCapture({key:item for key,item in self.items.items()if item['property']in properties})


def capture(reader,flips):
    prepared=flips if isinstance(flips,FlipCapture)else FlipCapture(flips)
    if not prepared.records:return dict(version=1,frames={})
    blocks=reader.read_many(prepared.plan)if hasattr(reader,'read_many')else{p:reader.read(p,n)for p,n in prepared.plan}
    def read(address,count):
        value=blocks.get(address)
        if value is None or len(value)<count:raise SceneReadChanged('Native flip batch was incomplete')
        return value[:count]
    frames={}
    for key,controller,prop,storage,capacity,count,pointers,textures,maps,mapping,slot in prepared.records:
        raw=read(controller,0x54)
        if struct.unpack_from('<I',raw)[0]!=FLIP or struct.unpack_from('<I',raw,0x28)[0]!=prop or struct.unpack_from('<I',raw,0x50)[0]!=slot:
            raise SceneReadChanged('Native flip controller was replaced')
        if struct.unpack_from('<3I',raw,0x38)!=(storage,capacity,count)or read(storage,count*4)!=pointers:
            raise SceneReadChanged('Native flip palette was replaced')
        prop_raw=read(prop,0x24)
        if struct.unpack_from('<I',prop_raw)[0]!=TEXTURING or struct.unpack_from('<I',prop_raw,0x20)[0]!=maps or struct.unpack('<I',read(maps+slot*4,4))[0]!=mapping:
            raise SceneReadChanged('Native texture mapping was replaced')
        current=struct.unpack('<I',read(mapping+4,4))[0]
        # Read the resolved map, avoiding assumptions about whether the
        # controller's currentIndex denotes the current or next image.
        try:frames[key]=textures.index(current)
        except ValueError:raise SceneReadChanged('Resolved native texture is outside its prepared palette')from None
    return dict(version=1,frames=frames)
