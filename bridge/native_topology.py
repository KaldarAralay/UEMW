"""Translate original topology buffers, without calling the x86 engine.

Steam 1.6.1820 NiTriStripsData vtable 0x7509b0, getTriangleIndices
0x741e40: alternating first/second indices; strip lengths at +0x3c and
contiguous points at +0x40. A strip restart resets parity. Keep degenerates.
"""
import struct
import numpy as np
from live_probe import SceneReadChanged

STRIPS_DATA=0x7509b0
LINES_DATA=0x7501e0


def strip_indices(reader,model,header,vertices,triangles):
    if len(header)<0x44 or struct.unpack_from('<I',header)[0]!=STRIPS_DATA:
        raise SceneReadChanged('Native triangle-strip data type changed')
    if struct.unpack_from('<H',header,8)[0]!=vertices or struct.unpack_from('<H',header,0x34)[0]!=triangles:
        raise SceneReadChanged('Native triangle-strip counts changed')
    strips=struct.unpack_from('<H',header,0x38)[0]
    lengths_ptr,points_ptr=struct.unpack_from('<2I',header,0x3c)
    if not 1<=strips<=32768 or not lengths_ptr or not points_ptr:
        raise ValueError('Invalid native triangle-strip storage')
    lengths=np.frombuffer(reader.read(lengths_ptr,strips*2),dtype='<u2')
    if len(lengths)!=strips or (lengths<3).any() or sum(int(n)-2 for n in lengths)!=triangles:
        raise ValueError('Native strip lengths do not match triangle count')
    count=sum(int(n)for n in lengths)
    if count>196605:raise ValueError('Native triangle-strip point budget exceeded')
    points=np.frombuffer(reader.read(points_ptr,count*2),dtype='<u2')
    if len(points)!=count or not 0<vertices<=65535 or (points>=vertices).any():
        raise ValueError('Native triangle-strip index exceeds vertex count')
    output=np.empty((triangles,3),dtype='<u2');at=0;start=0
    for length in lengths:
        length=int(length);n=length-2;p=points[start:start+length]
        output[at:at+n,0]=p[:-2];output[at:at+n,1]=p[1:-1];output[at:at+n,2]=p[2:]
        output[at+1:at+n:2,:2]=output[at+1:at+n:2,1::-1].copy()
        at+=n;start+=length
    return output.tobytes()


def triangle_indices(reader,shape,header):
    if shape.get('topology')=='strips':
        return strip_indices(reader,int(shape['model'],16),header,shape['vertex_count'],shape['triangle_count'])
    if shape.get('topology')=='lines':
        pairs=line_pairs(reader,header,shape['vertex_count'])
        if len(pairs)!=shape['triangle_count']:raise SceneReadChanged('Native line connectivity changed')
        # Carrier triples share the existing bounded mesh/pose ABI. The line
        # component interprets only the first two indices as PT_LineList;
        # these degenerate triples are never submitted as scene triangles.
        return np.asarray([(a,b,b)for a,b in pairs],dtype='<u2').tobytes()
    return reader.read(struct.unpack_from('<I',header,0x3c)[0],shape['triangle_count']*6)


def line_pairs(reader,header,vertices):
    # DX8 index builder 0x6bd190, closure 0x6bd2b3. Last flag joins N-1 to 0.
    if len(header)<0x38 or struct.unpack_from('<I',header)[0]!=LINES_DATA:
        raise SceneReadChanged('Native line data type changed')
    if not 1<=vertices<=65535 or struct.unpack_from('<H',header,8)[0]!=vertices:
        raise SceneReadChanged('Native line vertex count changed')
    pointer=struct.unpack_from('<I',header,0x34)[0]
    if not pointer:return [] # Original DX8 index builder also draws nothing.
    flags=reader.read(pointer,vertices)
    if len(flags)!=vertices or any(v>1 for v in flags):raise ValueError('Invalid native line flags')
    return [(i,(i+1)%vertices)for i,v in enumerate(flags)if v]
