"""Render native particle buffers as quads; no emission, ageing or simulation.

Layouts: pinned MWSE NIParticles.h / NIGeometryData.h. The original engine
owns active count, positions, sizes and colors. Billboard expansion is visual
translation only. The pinned vanilla DX8 draw path (0x6AD0A0) reads neither
RotatingParticlesData.quaternions nor GeometryData.textureCoords. It expands
camera-facing corners and fixed full-texture UVs even for rotating particles.
"""
import math
import struct
import numpy as np
from live_probe import SceneReadChanged

MAX_SYSTEM=1024
MAX_SCENE=4096


def header(raw,capacity=None):
    count=struct.unpack_from('<H',raw,8)[0]
    active=struct.unpack_from('<H',raw,0x3c)[0]
    radius=struct.unpack_from('<f',raw,0x38)[0]
    if not 0<count<=MAX_SYSTEM or active>count or not math.isfinite(radius) or not 0<=radius<=1e5:
        raise ValueError('Invalid or unsupported native particle bounds')
    if capacity is not None and count!=capacity:raise SceneReadChanged('Native particle capacity changed')
    return count,active,radius,tuple(struct.unpack_from('<I',raw,o)[0]for o in (0x1c,0x24,0x40))


def capture(reader,shapes,tolerate=False):
    """Capture all changing buffers before any quad expansion/JSON work."""
    particles=[s for s in shapes if s.get('particles')]
    if tolerate:
        result={};used=0
        for shape in particles:
            if used+shape['particle_capacity']>MAX_SCENE:continue
            try:item=capture(reader,[shape])
            except(OSError,ValueError,SceneReadChanged):continue
            result.update(item);used+=shape['particle_capacity']
        return result
    if sum(s['particle_capacity']for s in particles)>MAX_SCENE:
        raise ValueError('Native particles exceed the 4096-particle scene budget')
    result={}
    for shape in particles:
        model=int(shape['model'],16);raw=reader.read(model,0x44)
        table=struct.unpack_from('<I',raw)[0]
        if 'particle_data_vtable'in shape and table!=shape['particle_data_vtable']:raise SceneReadChanged('Native particle data type changed')
        count,active,radius,pointers=header(raw,shape['particle_capacity'])
        xyz,color,sizes=pointers
        if not xyz:raise ValueError('Missing native particle vertices')
        positions=reader.read(xyz,active*12)if active else b''
        colors=reader.read(color,active*4)if color and active else None
        scales=reader.read(sizes,active*4)if sizes and active else None
        material=int(shape.get('material','0x0'),16)
        tint=(1.,1.,1.,1.)
        if material:
            values=reader.read(material+0x28,0x2c)
            diffuse=struct.unpack_from('<3f',values);emissive=struct.unpack_from('<3f',values,0x18)
            rgb=emissive if max(emissive)>.001 and max(diffuse)<.001 else diffuse
            tint=(*rgb,struct.unpack_from('<f',values,0x28)[0])
        if shape.get('color_mode',2)==0:colors=None
        end=reader.read(model,0x44)
        # Counts/pointers changing implies buffer reuse; drop rather than read
        # retired memory into a new emitter. The outer source-frame fence also
        # records/retries updates that overlap an original engine frame.
        if end[:4]!=raw[:4] or header(end,count)[3]!=pointers or struct.unpack_from('<H',end,0x3c)[0]!=active:
            raise SceneReadChanged('Native particle storage changed during capture')
        result[int(shape['id'],16)]=(count,active,radius,positions,colors,scales,tint)
    return result


def expand(sample,transform,camera):
    count,active,radius,xyz,bgra,sizes,tint=sample
    m=np.asarray(transform,dtype=np.float64)
    points=np.repeat(m[9:12][None,:],count*4,axis=0).reshape(count,4,3)
    rgba=np.zeros((count,4),dtype=np.float64)
    if active:
        centers=np.frombuffer(xyz,dtype='<f4').reshape(active,3).astype(np.float64)
        scales=np.frombuffer(sizes,dtype='<f4').astype(np.float64)if sizes is not None else np.ones(active)
        if not np.isfinite(centers).all()or not np.isfinite(scales).all()or np.any(scales<0)or np.any(scales>1e5):
            raise ValueError('Invalid native particle position/size')
        centers=centers @ (m[:9].reshape(3,3)*m[12]).T+m[9:12]
        up=np.asarray(camera['up'],dtype=np.float64);forward=np.asarray(camera['forward'],dtype=np.float64)
        right=np.cross(forward,up);length=np.linalg.norm(right)
        if length<1e-8:raise ValueError('Invalid particle billboard basis')
        right/=length;up/=np.linalg.norm(up)
        # Native 0x6AD395..6AD532: right-down, left-down, left-up,
        # right-up, paired with UV (0,0),(1,0),(1,1),(0,1).
        corners=np.array([right-up,-right-up,-right+up,right+up])
        half=scales*radius*abs(m[12])
        points[:active]=centers[:,None,:]+half[:,None,None]*corners[None,:,:]
        if bgra is not None:rgba[:active]=np.frombuffer(bgra,dtype=np.uint8).reshape(active,4)[:,[2,1,0,3]]/255.
        else:rgba[:active]=1.
        if not np.isfinite(tint).all():raise ValueError('Invalid native particle material')
        # Native vertex RGB takes precedence, while material alpha still applies.
        rgba[:active]*=np.clip((1.,1.,1.,tint[3])if bgra is not None else tint,0,1)
    if not np.isfinite(points).all()or np.max(np.abs(points))>1e8:raise ValueError('Invalid particle world positions')
    return points.round(4).reshape(-1).tolist(),np.repeat(rgba,4,axis=0).round(4).reshape(-1).tolist()
