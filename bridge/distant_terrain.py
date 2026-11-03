"""Terrain LOD from actual LAND samples, with exact full-resolution borders."""
import numpy as np


def texture_grid(raw):
    a=np.asarray(raw,dtype='<u2')
    if a.shape!=(16,16):raise ValueError('Invalid installed terrain texture grid')
    # Vanilla VTEX stores sixteen 4x4 blocks, not a flat row-major image.
    return a.reshape(4,4,4,4).transpose(0,2,1,3).reshape(16,16).copy()


def mesh(land,step=4):
    if step not in(1,2,4,8):raise ValueError('Unsupported distant terrain LOD')
    h=np.asarray(land['heights']);gx,gy=land['grid']
    if h.shape!=(65,65)or not np.isfinite(h).all():raise ValueError('Invalid distant terrain heights')
    positions=[];samples=[];indices=[];known={}
    def vertex(x,y):
        if (x,y)not in known:
            known[x,y]=len(positions);samples.append((x,y));positions.append((gx*8192+x*128,gy*8192+y*128,float(h[y,x])))
        return known[x,y]
    for y in range(0,64,step):
        for x in range(0,64,step):
            ring=[(x,y)]
            if y==0:ring.extend((x+i,y)for i in range(1,step))
            ring.append((x+step,y))
            if x+step==64:ring.extend((x+step,y+i)for i in range(1,step))
            ring.append((x+step,y+step))
            if y+step==64:ring.extend((x+step-i,y+step)for i in range(1,step))
            ring.append((x,y+step))
            if x==0:ring.extend((x,y+step-i)for i in range(1,step))
            corners=[vertex(*p)for p in ring]
            if len(ring)==4:indices.extend(((corners[0],corners[1],corners[2]),(corners[0],corners[2],corners[3])))
            else:
                center=vertex(x+step//2,y+step//2)
                indices.extend((center,corners[i],corners[(i+1)%len(corners)])for i in range(len(corners)))
    p=np.asarray(positions,dtype='<f4');sample=np.asarray(samples);result=dict(points=p,indices=np.asarray(indices,dtype='<u2'),uvs=(p[:,:2]/512).astype('<f4'),samples=sample)
    if 'VNML'in land:result['normals']=land['VNML'][sample[:,1],sample[:,0]].astype('<f4')/127
    if 'VCLR'in land:result['colours']=np.c_[land['VCLR'][sample[:,1],sample[:,0]],np.full(len(p),255,dtype=np.uint8)]
    return result
