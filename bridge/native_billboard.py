"""Resolve the original rigid-camera sun billboard at its captured camera.

NiBillboardNode mode 2 rotates only during the native draw and can be copied
before/after that temporary rotation. Keep source model vertices, placement,
scale, UVs, colours and alpha; resolve only its native visual facing rule.
"""
import struct
import numpy as np
from live_probe import SceneReadChanged


def glare_owners(reader,aux_roots):
    roots=[int(v['root'],16)for v in aux_roots or()if v['layer']=='sun_glare']
    if not roots:return {}
    if len(roots)!=1:raise SceneReadChanged('Ambiguous native sunglare root')
    world=reader.u32(0x7c67dc);weather=reader.u32(world+0x58)
    if not weather or reader.u32(weather+8)!=roots[0]:raise SceneReadChanged('Native weather sunglare owner changed')
    return {roots[0]:((world+0x58,weather),(weather+8,roots[0]))}


def rigid_points(local,transform,camera,header):
    if len(header)<0x74 or struct.unpack_from('<H',header,0x14)[0]&0x60!=0x40:
        raise SceneReadChanged('Native rigid billboard mode changed')
    forward=np.asarray(camera['forward'],dtype=np.float64)
    up=np.asarray(camera['up'],dtype=np.float64)
    right=np.cross(forward,up)
    lengths=np.asarray([np.linalg.norm(right),np.linalg.norm(up),np.linalg.norm(forward)])
    if not np.isfinite(lengths).all()or np.any(lengths<1e-8):raise SceneReadChanged('Invalid original billboard camera')
    basis=np.stack((right/lengths[0],up/lengths[1],forward/lengths[2]),axis=1)
    m=np.asarray(transform,dtype=np.float64)
    return np.asarray(local)@(basis*m[12]).T+m[9:12]
