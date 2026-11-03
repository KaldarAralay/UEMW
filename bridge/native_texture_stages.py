"""Read original NiTexturingProperty stages; no generated maps or clocks.

Steam 1.6.1820 layout independently documented by MWSE NIProperty.h. Maps
are sparse pointers, not a compact list. Unknown combinations stay explicit.
"""
import struct
import hashlib
import numpy as np
from live_probe import SceneReadChanged
from native_materials import TEXTURING,SOURCE_TEXTURE,discover

NAMES=('base','dark','detail','gloss','glow','bump',*(f'decal{i}'for i in range(8)))

def read(reader,prop,generation=''):
    if not prop:return None
    raw=reader.read(prop,0x34)
    if struct.unpack_from('<I',raw)[0]!=TEXTURING:raise SceneReadChanged('Native texturing property changed')
    apply=struct.unpack_from('<I',raw,0x18)[0]
    storage,capacity,end=struct.unpack_from('<3I',raw,0x20)
    if apply>4 or end>capacity or capacity>16 or end>14 or (end and not storage):raise ValueError('Invalid native texture stage layout')
    pointers=reader.read(storage,end*4)if end else b'';maps=[]
    for slot,mapping in enumerate(struct.unpack('<'+'I'*end,pointers)):
        if not mapping:continue
        values=struct.unpack('<5I',reader.read(mapping,20));source,clamp,filter,uv=values[1:]
        if clamp>3 or filter>5 or uv>7:raise ValueError('Invalid native texture map settings')
        if not source or reader.u32(source)!=SOURCE_TEXTURE:
            maps.append(dict(slot=slot,kind=NAMES[slot],source_texture='',uv_set=uv,clamp=clamp,filter=filter,supported=False,unsupported='Native rendered/non-source texture is not translated by this file-backed stage path'));continue
        name=reader.string(reader.u32(source+0x2c),512)
        if not name:
            maps.append(dict(slot=slot,kind=NAMES[slot],source_texture='',uv_set=uv,clamp=clamp,filter=filter,supported=False,unsupported='Native in-memory texture without a source filename retains the existing colour fallback'));continue
        row=dict(slot=slot,kind=NAMES[slot],source_texture=name,uv_set=uv,clamp=clamp,filter=filter)
        flip=discover(reader,prop,generation,map_index=slot)
        if flip:row['flip']=flip
        if slot==5:
            values=struct.unpack('<6f',reader.read(mapping+20,24))
            import math
            if not all(math.isfinite(v)and abs(v)<=1e8 for v in values):raise ValueError('Invalid native bump stage parameters')
            row['bump']=list(values)
        maps.append(row)
    after=reader.read(prop,0x34)
    if after[:4]!=raw[:4]or after[0x18:0x2c]!=raw[0x18:0x2c]or(end and reader.read(storage,end*4)!=pointers):raise SceneReadChanged('Native texture stage table changed')
    return dict(version=1,apply=apply,maps=maps)

def convert(assets,shape,stages):
    if not stages:return None,{}
    rows=[];flips={};unsupported=[]
    if stages['apply']>2:unsupported.append(dict(apply=stages['apply'],reason='Highlight apply mode is retained; PC rendering uses the existing modulate fallback'))
    for original in stages['maps']:
        row={k:v for k,v in original.items()if k!='flip'}
        if row.get('unsupported'):unsupported.append(dict(slot=row['slot'],reason=row['unsupported']))
        flip=original.get('flip')
        if flip:row['source_texture']=flip['names'][0]
        row['texture']=assets.texture(flip['names'][0]if flip else row['source_texture'])if row['source_texture']else''
        assets.used_textures.add(row['source_texture'])
        if flip:
            files=[assets.texture(name)for name in flip['names']];assets.used_textures.update(flip['names'])
            if any(not file for file in files):raise ValueError('Missing native stage flip texture')
            row['animation']=dict(id=flip['id'],frames=files);flips[flip['id']]=flip
        if row['slot']>6:unsupported.append(dict(slot=row['slot'],reason='Additional decal beyond the first is not yet translated'))
        if row['uv_set']>2:
            row['supported']=False;unsupported.append(dict(slot=row['slot'],reason='Native UV sets above two exceed the current material channel budget'))
        rows.append(row)
    result=dict(version=1,apply=stages['apply'],maps=rows,unsupported=unsupported)
    # Most original maps use native UV set zero, including mutable water/sky.
    # Original sets 0/1/2 map to UE UV0/2/3, leaving UV1 for sparse skin ranges.
    if any(row['uv_set']for row in rows if row['slot']<=6 and row.get('supported',True)):
        if shape.get('particles'):raise ValueError('Native particle secondary UV sets are unsupported')
        model=int(shape['model'],16);header=assets.r.read(model,0x34)
        count,sets=struct.unpack_from('<2H',header,8);pointer=struct.unpack_from('<I',header,0x28)[0]
        if count!=shape['vertex_count']or not 1<=sets<=8 or not pointer:raise SceneReadChanged('Native stage UV layout changed')
        data=np.frombuffer(assets.r.read(pointer,count*sets*8),dtype='<f4').reshape(sets,count,2)
        if not np.isfinite(data).all()or np.max(np.abs(data))>1e8:raise ValueError('Invalid native texture stage UVs')
        selected={row['slot']:row['uv_set']for row in rows if row['slot']<=6 and row.get('supported',True)}
        if any(index>=sets for index in selected.values()):raise ValueError('Native texture map references absent UV set')
        packed=np.empty((count,3,2),dtype='<f4')
        for index in range(3):packed[:,index]=data[index if index<sets else 0]
        if shape.get('dynamic_attributes',{}).get('uvs'):
            # Resolved set zero belongs to the current UFB6 pose, not an
            # immutable resource identity that would churn each animation tick.
            packed[:,0]=0
            for index in range(sets,3):packed[:,index]=0
        after=assets.r.read(model,0x34)
        if after[8:12]!=header[8:12]or after[0x28:0x34]!=header[0x28:0x34]:raise SceneReadChanged('Native stage UV identity changed')
        body=struct.pack('<4sII',b'UUV1',count,3)+packed.tobytes()
        name='meshes/'+hashlib.sha256(body).hexdigest()+'.uuv'
        from asset_files import publish
        publish(assets.out/name,body);result['uv_file']=name
    return result,flips
