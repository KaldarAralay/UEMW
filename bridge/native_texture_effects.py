"""Observed native environment texture effects, including enchantment frames.

Pinned 1.6.1820: effect-state environment +0x14 (dispatch 0x6F9490),
NiTextureEffect source +0x108, filter/clamp/type/coordinates +0x10C..118.
World enchantment palette +0x370 has 32 original pointers (0x410D2A).
Sphere mapping uses native reflection coordinates (0x6B6090: 0x30000).
"""
import hashlib,math,struct
from live_probe import SceneReadChanged
from native_materials import SOURCE_TEXTURE
from read_batch import ReadPlan

EFFECT=0x7507c0
STATE=0x7469b4

def discover(reader,state,generation=''):
    if not state:return None
    owner=reader.read(state,0x1c)
    if struct.unpack_from('<I',owner)[0]!=STATE:raise SceneReadChanged('Native texture effect owner changed')
    pointer=struct.unpack_from('<I',owner,0x14)[0]
    if not pointer:return None
    raw=reader.read(pointer,0x148)
    if struct.unpack_from('<I',raw)[0]!=EFFECT:raise SceneReadChanged('Native environment effect type changed')
    source=struct.unpack_from('<I',raw,0x108)[0]
    filter,clamp,kind,coordinates=struct.unpack_from('<4I',raw,0x10c)
    if filter>5 or clamp>3 or kind!=2 or coordinates>4:raise ValueError('Invalid native environment mapping policy')
    world=reader.u32(0x7c67dc);enchant,palette=struct.unpack('<2I',reader.read(world+0x36c,8))
    if pointer==enchant and palette:
        if reader.u32(palette-4)!=32:raise SceneReadChanged('Native enchantment palette size changed')
        palette_bytes=reader.read(palette,128);textures=struct.unpack('<32I',palette_bytes)
    else:palette=0;palette_bytes=struct.pack('<I',source);textures=(source,)
    names=[];name_pointers=[]
    for texture in textures:
        if not texture or reader.u32(texture)!=SOURCE_TEXTURE:raise ValueError('Unsupported native environment texture source')
        name_pointer=reader.u32(texture+0x2c);name=reader.string(name_pointer,512)
        if not name:raise ValueError('Native environment texture has no filename')
        names.append(name);name_pointers.append(name_pointer)
    if source not in textures:raise SceneReadChanged('Native environment texture outside original palette')
    if reader.u32(state+0x14)!=pointer:raise SceneReadChanged('Native environment membership changed')
    identity=hashlib.sha256(palette_bytes+'|'.join(names).encode('utf-8')).hexdigest()[:12]
    return dict(id=generation+':env:'+hex(pointer)+':'+identity,pointer=pointer,world=world,palette=palette,palette_bytes=palette_bytes,
                textures=textures,names=tuple(names),name_pointers=tuple(name_pointers),coordinates=coordinates)

def convert(assets,item):
    if not item:return None
    files=[assets.texture(name)for name in item['names']];assets.used_textures.update(item['names'])
    if any(not path for path in files):raise ValueError('Missing original environment-map palette texture')
    supported=item['coordinates']==2
    return dict(version=1,id=item['id'],texture=files[0],animation=dict(id=item['id'],frames=files),coordinates=item['coordinates'],supported=supported,
                **({}if supported else dict(unsupported='Only native sphere reflection coordinates are currently translated')))

class EffectCapture:
    def __init__(self,items):
        self.items=dict(items)
        if len(self.items)>256:raise ValueError('Native texture effect budget exceeded')
        requests=[]
        for item in self.items.values():
            requests.extend(((item['pointer'],0x148),(0x7c67dc,4)))
            for texture in item['textures']:requests.append((texture,0x30))
            if item['palette']:requests.extend(((item['world']+0x36c,8),(item['palette']-4,132)))
        self.plan=ReadPlan(requests)

def capture(reader,items):
    prepared=items if isinstance(items,EffectCapture)else EffectCapture(items)
    if not prepared.items:return dict(version=1,values={}),{}
    blocks=reader.read_many(prepared.plan)if hasattr(reader,'read_many')else{p:reader.read(p,n)for p,n in prepared.plan}
    def read(p,n):
        raw=blocks.get(p)
        if raw is None or len(raw)<n:raise SceneReadChanged('Incomplete native texture effect capture')
        return raw[:n]
    values={};frames={}
    for key,item in prepared.items.items():
        raw=read(item['pointer'],0x148)
        if struct.unpack_from('<I',raw)[0]!=EFFECT or struct.unpack('<I',read(0x7c67dc,4))[0]!=item['world']:raise SceneReadChanged('Native texture effect lifetime changed')
        source=struct.unpack_from('<I',raw,0x108)[0];filter,clamp,kind,coordinates=struct.unpack_from('<4I',raw,0x10c)
        if raw[0x90]>1 or filter>5 or clamp>3 or kind!=2 or coordinates!=item['coordinates']:raise SceneReadChanged('Native texture effect mapping changed')
        if item['palette']:
            if struct.unpack('<2I',read(item['world']+0x36c,8))!=(item['pointer'],item['palette']) or read(item['palette']-4,132)!=struct.pack('<I',32)+item['palette_bytes']:raise SceneReadChanged('Native enchantment palette replaced')
        for texture,name_pointer in zip(item['textures'],item['name_pointers']):
            header=read(texture,0x30)
            if struct.unpack_from('<I',header)[0]!=SOURCE_TEXTURE or struct.unpack_from('<I',header,0x2c)[0]!=name_pointer:raise SceneReadChanged('Native environment texture identity changed')
        try:frames[key]=item['textures'].index(source)
        except ValueError:raise SceneReadChanged('Resolved original environment texture outside palette')from None
        matrix=struct.unpack_from('<12f',raw,0xd8)
        if not all(math.isfinite(v)and abs(v)<=1e8 for v in matrix):raise ValueError('Invalid native environment mapping matrix')
        values[key]=[int(raw[0x90]),filter,clamp,coordinates,*matrix]
    return dict(version=1,values=values),frames
