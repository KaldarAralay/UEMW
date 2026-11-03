"""uemw.live v3: bounded little-endian UFB1/v5 and UFB2/v6 buffers.

Metadata remains JSON; shape states are typed binary with exact identity fences.
All records are complete snapshots in immutable catalog binding order.
"""
import math
import struct
import uuid
import numpy as np
from captured_states import CapturedStates

HEADER=struct.Struct('<4sHH16s16sQdIIII')
LIMIT=4*1024*1024
TRANSFORM=struct.Struct('<13f')

def guid(value):
    h=uuid.UUID(value).hex
    return struct.pack('<4I',*(int(h[i:i+8],16) for i in range(0,32,8)))

def floats(values,count=None,color=False):
    a=np.asarray(values,dtype='<f4').reshape(-1)
    if (count is not None and len(a)!=count) or not np.isfinite(a).all() or np.any(np.abs(a)>1e8) or (color and (np.any(a<0) or np.any(a>1))):
        raise ValueError('Invalid binary numeric array')
    return a.tobytes()

def transform_bytes(values):
    # Small tuples are the common case (one per visible rigid/skin shape).
    # Avoid an ndarray plus several ufunc reductions for each 52-byte record.
    try:
        if len(values)!=13 or not all(math.isfinite(v) and abs(v)<=1e8 for v in values):
            raise ValueError('Invalid binary transform')
        return TRANSFORM.pack(*values)
    except (TypeError,OverflowError,struct.error)as error:
        raise ValueError('Invalid binary transform')from error

def packed_transforms(states):
    """Validate this complete frame in one numerical pass, before float32 cast.

    No pose is cached. Bounds are checked at source precision so rounding a
    slightly out-of-range double into a valid float32 cannot bypass validation.
    """
    if isinstance(states,CapturedStates):return states.packed_transforms()
    values=[]
    for row in states:
        if not row or type(row[0])is not bool:raise ValueError('Invalid binary visibility')
        if row[0]:
            if not 2<=len(row)<=4:raise ValueError('Invalid binary row')
            values.append(row[1])
        elif len(row)!=1:raise ValueError('Invalid hidden binary record')
    if not values:return b''
    try:
        array=np.asarray(values)
        if array.shape!=(len(values),13)or array.dtype.kind not in 'biuf' or not np.isfinite(array).all()or np.any(array>1e8)or np.any(array< -1e8):
            raise ValueError('Invalid binary transform block')
        return array.astype('<f4',copy=False).tobytes()
    except(TypeError,OverflowError)as error:raise ValueError('Invalid binary transform block')from error


def deformation_payload(extra,geometry):
    if isinstance(extra[0],dict)and 'palette'not in extra[0]:
        if geometry!=6 or len(extra)!=1:raise ValueError('Native UV records require geometry v6')
        data=extra[0];points=np.asarray(data['points'],dtype='<f4').reshape(-1)
        if not 0<len(points)<=65535*3 or len(points)%3:raise ValueError('Invalid native UV vertex count')
        count=len(points)//3;flags=3 if 'colors'in data else 2
        payload=struct.pack('<II',count,flags)+floats(points)
        if flags&1:payload+=floats(data['colors'],count*4,True)
        return 5,payload+floats(data['uvs'],count*2)
    if isinstance(extra[0],dict):
        palette=np.asarray(extra[0]['palette'],dtype='<f4').reshape(-1,12)
        if len(extra)!=1 or not 1<=len(palette)<=257:raise ValueError('Invalid native bone palette')
        if len(extra[0]['bound'])!=4 or extra[0]['bound'][3]<0:raise ValueError('Invalid native bound')
        return 4,struct.pack('<HH',len(palette),0)+floats(extra[0]['bound'],4)+floats(palette)
    points=np.asarray(extra[0],dtype='<f4').reshape(-1)
    if not 0<len(points)<=65535*3 or len(points)%3:raise ValueError('Invalid binary vertex count')
    payload=struct.pack('<I',len(points)//3)+floats(points)
    if len(extra)==2:payload+=floats(extra[1],len(points)//3*4,True)
    return 3 if len(extra)==2 else 2,payload

def encode(packet,packed_metadata=False,*,batch_transforms=True):
    states=packet['instance_states'];count=len(states)
    if not 0<count<=16384:raise ValueError('Invalid binary instance count')
    sequence=packet['sequence'];stamp=packet['sample_unix_ns'];pid=packet['pid']
    if type(sequence)is not int or not 0<=sequence<=9007199254740991 or not math.isfinite(stamp) or stamp<=0 or type(pid)is not int or not 1<=pid<=0xffffffff:
        raise ValueError('Invalid binary identity')
    geometry=packet['geometry_version']
    if geometry not in(5,6):raise ValueError('Unsupported binary geometry version')
    chunks=[HEADER.pack(b'UFB3'if packed_metadata else b'UFB2'if geometry==6 else b'UFB1',3 if packed_metadata else 2 if geometry==6 else 1,0,guid(packet['session']),guid(packet['scene_epoch']),sequence,float(stamp),pid,geometry,count,0)]
    if batch_transforms and isinstance(states,CapturedStates):
        chunks.append(states.pack_records(lambda extra:deformation_payload(extra,geometry),LIMIT-HEADER.size))
        if packed_metadata:
            from state_metadata import encode as encode_metadata
            chunks.append(encode_metadata(packet))
        if sum(map(len,chunks))>LIMIT:raise ValueError('Binary frame with metadata exceeds 4 MiB')
        return b''.join(chunks)
    transforms=packed_transforms(states)if batch_transforms and count>=64 else None
    transform_offset=0
    size=HEADER.size
    for row in states:
        if not row or type(row[0])is not bool:raise ValueError('Invalid binary visibility')
        if not row[0]:
            if len(row)!=1:raise ValueError('Invalid hidden binary record')
            record=b'\0'
        else:
            if not 2<=len(row)<=4:raise ValueError('Invalid binary row')
            if transforms is None:transform=transform_bytes(row[1])
            else:transform=transforms[transform_offset:transform_offset+52];transform_offset+=52
            if len(row)==2:record=b'\1'+transform
            else:
                kind,payload=deformation_payload(row[2:],geometry)
                record=bytes([kind])+transform+payload
        size+=len(record)
        if size>LIMIT:raise ValueError('Binary frame exceeds 4 MiB')
        chunks.append(record)
    if packed_metadata:
        from state_metadata import encode as encode_metadata
        metadata=encode_metadata(packet);size+=len(metadata)
        if size>LIMIT:raise ValueError('Binary frame with metadata exceeds 4 MiB')
        chunks.append(metadata)
    return b''.join(chunks)

def decode(body,manifest):
    if not HEADER.size<=len(body)<=LIMIT:raise ValueError('Invalid binary frame size')
    magic,version,reserved,session,epoch,sequence,stamp,pid,geometry,count,padding=HEADER.unpack_from(body)
    packed=magic==b'UFB3'and version==3 and geometry in(5,6)
    if not(packed or (magic,version,geometry)in((b'UFB1',1,5),(b'UFB2',2,6))) or reserved or padding or not 0<count<=16384:raise ValueError('Invalid binary header')
    if manifest.get('version')in(4,5) and(not packed or manifest.get('state_metadata_version')!=1):raise ValueError('Invalid packed metadata binding')
    if packed and(manifest.get('version')==3 or any(k in manifest for k in('environment','material_frames','material_values'))):raise ValueError('Mixed packed/JSON metadata authority')
    if manifest.get('geometry_version')!=geometry:raise ValueError('Binary geometry version mismatch')
    if (session,epoch,sequence,stamp,pid)!=(guid(manifest['session']),guid(manifest['scene_epoch']),manifest['sequence'],float(manifest['sample_unix_ns']),manifest['pid']):raise ValueError('Binary frame identity mismatch')
    offset=HEADER.size;states=[]
    def take(n):
        nonlocal offset
        if offset+n>len(body):raise ValueError('Truncated binary frame')
        value=body[offset:offset+n];offset+=n;return value
    def numeric(n,color=False):
        a=np.frombuffer(take(n*4),dtype='<f4')
        floats(a,n,color)
        return a.tolist()
    for _ in range(count):
        kind=take(1)[0]
        if kind==0:states.append([False]);continue
        if kind not in(1,2,3,4,5)or(kind==5 and geometry!=6):raise ValueError('Unknown binary record kind')
        row=[True,numeric(13)]
        if kind in(2,3):
            vertices=struct.unpack('<I',take(4))[0]
            if not 0<vertices<=65535:raise ValueError('Invalid binary vertex count')
            row.append(numeric(vertices*3))
            if kind==3:row.append(numeric(vertices*4,True))
        elif kind==5:
            vertices,flags=struct.unpack('<II',take(8))
            if not 0<vertices<=65535 or flags not in(2,3):raise ValueError('Invalid native UV record')
            data=dict(points=numeric(vertices*3))
            if flags&1:data['colors']=numeric(vertices*4,True)
            data['uvs']=numeric(vertices*2);row.append(data)
        elif kind==4:
            bones,reserved=struct.unpack('<HH',take(4))
            if reserved or not 1<=bones<=257:raise ValueError('Invalid palette count')
            bound=numeric(4)
            if bound[3]<0:raise ValueError('Invalid native bound')
            row.append(dict(bound=bound,palette=numeric(bones*12)))
        states.append(row)
    metadata={}
    if packed:
        from state_metadata import decode as decode_metadata
        metadata=decode_metadata(take)
    if offset!=len(body):raise ValueError('Trailing binary frame bytes')
    return {**manifest,**metadata,'version':1,'geometry_version':geometry,'instance_states':states,'objects':[]}
