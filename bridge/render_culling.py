"""Conservative render-only rejection using captured original world spheres.

No occlusion, physics, animation clocks or gameplay visibility is evaluated.
Invalid/unsupported camera or bounds fail open. Retain all scene members and
sample all original nodes; only omit visual work outside this camera's frustum.
"""
import math
import numpy as np

def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def unit(a):
    size=math.sqrt(dot(a,a))
    if not math.isfinite(size) or size<1e-8:raise ValueError('Degenerate camera basis')
    return tuple(v/size for v in a)

class View:
    def __init__(self,camera):
        self.planes=[]
        try:
            self.origin=tuple(camera['position'])
            f=unit(camera['forward']);u=unit(camera['up']);r=unit(cross(f,u));u=unit(cross(r,f))
            left,right,top,bottom,near,far=camera['frustum']
            if not all(math.isfinite(v) for v in (*self.origin,left,right,top,bottom,near,far)) or not (left<0<right and bottom<0<top and 0<near<far):return
            left/=near;right/=near;top/=near;bottom/=near
            self.planes=[(unit(tuple(r[i]-left*f[i] for i in range(3))),0),
                (unit(tuple(right*f[i]-r[i] for i in range(3))),0),
                (unit(tuple(u[i]-bottom*f[i] for i in range(3))),0),
                (unit(tuple(top*f[i]-u[i] for i in range(3))),0),(f,-near),
                (tuple(-v for v in f),far)]
        except (KeyError,TypeError,ValueError,ZeroDivisionError):self.planes=[]

    def includes(self,bound):
        if not self.planes or len(bound)!=4 or not all(math.isfinite(v) and abs(v)<1e8 for v in bound) or bound[3]<=0:return True
        offset=tuple(bound[i]-self.origin[i] for i in range(3))
        # Extra margin covers small inaccuracies in original skin bounds and
        # read-only frame tearing. Never shrink a source bounding sphere.
        radius=bound[3]*1.1+32
        return all(dot(normal,offset)+distance>=-radius for normal,distance in self.planes)

    def includes_many(self,bounds):
        """Same conservative test, evaluated in one bounded numerical pass."""
        bounds=np.asarray(bounds,dtype=np.float64).reshape(-1,4)
        result=np.ones(len(bounds),dtype=bool)
        if not self.planes:return result
        valid=np.isfinite(bounds).all(axis=1)&(np.abs(bounds)<1e8).all(axis=1)&(bounds[:,3]>0)
        normals=np.asarray([p[0]for p in self.planes]);distances=np.asarray([p[1]for p in self.planes])
        offset=bounds[valid,:3]-np.asarray(self.origin)
        # einsum's direct small contraction avoids launching BLAS worker pools.
        planes=np.einsum('ij,kj->ik',offset,normals,optimize=False)+distances
        radius=bounds[valid,3]*1.1+32
        result[valid]=(planes>=-radius[:,None]-1e-7).all(axis=1)
        return result
