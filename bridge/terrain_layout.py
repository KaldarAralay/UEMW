"""Recognize original loaded terrain tiles without modifying their geometry."""
import numpy as np


def native_tile(points,uvs,transform):
    p=np.asarray(points,dtype=np.float64);uv=np.asarray(uvs,dtype=np.float64)
    if p.shape!=(25,3)or uv.shape!=(25,2):return None
    world=p@np.asarray(transform['rotation']).reshape(3,3).T*transform['scale']+transform['position']
    if not np.isfinite(world).all()or not np.isfinite(uv).all():return None
    minimum=world[:,:2].min(0);span=world[:,:2].max(0)-minimum
    if np.max(np.abs(span-512))>.02 or np.max(np.abs(uv-(world[:,:2]-minimum)/512))>.001:return None
    if np.max(np.abs(minimum-np.round(minimum/512)*512))>.02:return None
    return np.floor((minimum+256)/512).astype(int).tolist()
