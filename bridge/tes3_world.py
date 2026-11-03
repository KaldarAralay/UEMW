"""Read-only installed TES3 scenery records. No scripts, AI, saves or collision.

Only the original three masters are supported. Reference source IDs resolve
their master-file byte into the same one-based file identity used by vanilla.
Generated data remains in ignored local storage.
"""
import math,struct
from pathlib import Path
import numpy as np

MASTERS=('Morrowind.esm','Tribunal.esm','Bloodmoon.esm')


def text(raw):
    return bytes(raw).split(b'\0',1)[0].decode('cp1252')


def fields(payload):
    at=0
    while at<len(payload):
        if at+8>len(payload):raise ValueError('Truncated TES3 scenery subrecord')
        kind,size=struct.unpack_from('<4sI',payload,at);at+=8
        if size>len(payload)-at:raise ValueError('TES3 scenery subrecord exceeds record')
        yield kind,payload[at:at+size];at+=size


def records(path):
    with Path(path).open('rb')as f:
        while header:=f.read(16):
            if len(header)!=16:raise ValueError('Truncated TES3 scenery record')
            kind,size,unused,flags=struct.unpack('<4sIII',header)
            if size>32*1024*1024:raise ValueError('TES3 scenery record exceeds budget')
            offset=f.tell();data=f.read(size)
            if len(data)!=size:raise ValueError('Truncated TES3 scenery payload')
            yield kind,data,(offset,size,flags)


def heights(raw):
    if len(raw)!=4232:raise ValueError('Invalid installed LAND height size')
    origin=struct.unpack_from('<f',raw)[0]
    if not math.isfinite(origin)or abs(origin)>1e6:raise ValueError('Invalid installed LAND origin')
    delta=np.frombuffer(raw,dtype=np.int8,count=4225,offset=4).reshape(65,65).astype(np.float32)
    delta[:,0]=origin+np.cumsum(delta[:,0]);return np.cumsum(delta,axis=1)*8


def source_id(value,current,masters):
    index=value>>24
    if index>len(masters):raise ValueError('Scenery reference has an invalid master index')
    owner=masters[index-1]if index else current
    return (owner<<24)|(value&0xffffff)


def references(payload,current,masters):
    item=None
    for kind,raw in fields(payload):
        if kind==b'FRMR':
            if item is not None:yield item
            if len(raw)!=4:raise ValueError('Invalid scenery reference ID')
            item=dict(id=source_id(struct.unpack('<I',raw)[0],current,masters))
        elif kind==b'MVRF':
            if item is not None:yield item
            item=None # Moved references are resolved by native reference state.
        elif item is not None:
            if kind==b'NAME':item['base']=text(raw).lower()
            elif kind==b'DATA':
                if len(raw)!=24:raise ValueError('Invalid scenery reference transform')
                values=struct.unpack('<6f',raw)
                if any(not math.isfinite(x)or abs(x)>1e8 for x in values):raise ValueError('Invalid scenery transform number')
                item.update(position=values[:3],orientation=values[3:])
            elif kind==b'XSCL':
                if len(raw)!=4:raise ValueError('Invalid scenery scale')
                scale=struct.unpack('<f',raw)[0]
                if not math.isfinite(scale)or not 0<scale<=65.535:raise ValueError('Invalid scenery scale range')
                item['scale']=scale
            elif kind==b'DELE':item['deleted']=True
            elif kind==b'ZNAM':item['disabled']=True
    if item is not None:yield item


class WorldIndex:
    def __init__(self,data):
        self.data=Path(data);self.files=[];self.models={};self.textures={};self.land={};self.cells={}
        known={name.lower():i+1 for i,name in enumerate(MASTERS)}
        for number,name in enumerate(MASTERS,1):
            path=self.data/name;info=path.stat();entry=dict(path=path,size=info.st_size,mtime_ns=info.st_mtime_ns,masters=());self.files.append(entry)
            for kind,payload,where in records(path):
                if kind==b'TES3':
                    names=[text(v).lower()for k,v in fields(payload)if k==b'MAST']
                    if any(n not in known or known[n]>=number for n in names):raise ValueError('Unsupported scenery master load order')
                    entry['masters']=tuple(known[n]for n in names)
                elif kind==b'STAT':
                    f=dict(fields(payload))
                    if b'NAME'in f and b'MODL'in f:self.models[text(f[b'NAME']).lower()]=text(f[b'MODL'])
                elif kind==b'LTEX':
                    f=dict(fields(payload))
                    if b'INTV'in f and b'DATA'in f:self.textures[number,struct.unpack('<I',f[b'INTV'])[0]]=text(f[b'DATA'])
                elif kind in(b'CELL',b'LAND'):
                    grid=None
                    for k,v in fields(payload):
                        if kind==b'LAND'and k==b'INTV':
                            if len(v)!=8:raise ValueError('Invalid LAND grid')
                            grid=struct.unpack('<2i',v);break
                        if kind==b'CELL'and k==b'DATA':
                            if len(v)!=12:raise ValueError('Invalid CELL grid')
                            flags,x,y=struct.unpack('<I2i',v)
                            if not flags&1:grid=(x,y)
                            break
                    if grid is not None:
                        record=(number,*where)
                        if kind==b'LAND':self.land.setdefault(grid,[]).append(record)
                        else:self.cells.setdefault(grid,[]).append(record)

    def read(self,record):
        number,offset,size,flags=record;entry=self.files[number-1];info=entry['path'].stat()
        if info.st_size!=entry['size']or info.st_mtime_ns!=entry['mtime_ns']:raise RuntimeError('Installed scenery source changed during use')
        with entry['path'].open('rb')as f:f.seek(offset);raw=f.read(size)
        if len(raw)!=size:raise ValueError('Installed scenery record disappeared')
        return raw

    def statics(self,grid):
        result={}
        for record in self.cells.get(tuple(grid),()):
            number=record[0]
            for ref in references(self.read(record),number,self.files[number-1]['masters']):
                ref={**result.get(ref['id'],{}),**ref};result[ref['id']]=ref
        return {key:{**v,'model':self.models[v['base']],'scale':v.get('scale',1.)}for key,v in result.items()if v.get('base')in self.models and 'position'in v and not v.get('deleted')}

    def terrain(self,grid):
        records=self.land.get(tuple(grid))
        if records is None:return None
        f={};sources={}
        for record in records:
            values=dict(fields(self.read(record)));f.update(values);sources.update({k:record[0]for k in values})
        if b'VHGT'not in f:return None
        result=dict(grid=tuple(grid),heights=heights(f[b'VHGT']),source=sources[b'VHGT'],texture_source=sources.get(b'VTEX',sources[b'VHGT']))
        for key,shape,dtype in((b'VNML',(65,65,3),np.int8),(b'VCLR',(65,65,3),np.uint8),(b'VTEX',(16,16),'<u2')):
            if key in f:
                expected=int(np.prod(shape))*np.dtype(dtype).itemsize
                if len(f[key])!=expected:raise ValueError('Invalid installed terrain array')
                result[key.decode()]=np.frombuffer(f[key],dtype=dtype).reshape(shape).copy()
        return result
