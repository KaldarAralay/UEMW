"""Batch the existing native skin equation over one owned PoseFrame.

Only immutable bind data/indices are prepared. Each result uses the current
captured original matrices; no animation clock, interpolation or pose reuse.
"""
import numpy as np


class PalettePlan:
    def __init__(self,layout):
        self.layout=layout
        rows=[];shapes=[];roots=[];owners=[];bones=[];transforms=[];binds=[];counts=[]
        for row,(ptr,identity,parents,skin,cell)in enumerate(layout.records):
            if skin is None:continue
            count=len(skin.bones)
            if not 0<count<=256 or len(skin.binds)!=count:raise ValueError('Invalid prepared native skin')
            owner=len(rows);rows.append(row);shapes.append(layout.index[skin.shape]);roots.append(layout.index[skin.root]);counts.append(count)
            transforms.append(skin.skin_transform)
            for bone,bind in zip(skin.bones,skin.binds):owners.append(owner);bones.append(layout.index[bone]);binds.append(bind)
        self.rows=np.asarray(rows,dtype=np.int32);self.shapes=np.asarray(shapes,dtype=np.int32);self.roots=np.asarray(roots,dtype=np.int32)
        self.owners=np.asarray(owners,dtype=np.int32);self.bones=np.asarray(bones,dtype=np.int32);self.counts=np.asarray(counts,dtype=np.int32)
        self.transforms=np.asarray(transforms,dtype=np.float64).reshape(-1,4,4)
        self.binds=np.asarray(binds,dtype=np.float64).reshape(-1,4,4)

    def capture(self,frame,excluded=()):
        if frame.layout is not self.layout:raise ValueError('Native palette plan belongs to another capture layout')
        active=frame.visible[self.rows].copy()
        if excluded:
            for i,row in enumerate(self.rows):
                if self.layout.records[row][0]in excluded:active[i]=False
        selected=np.flatnonzero(active)
        if not len(selected):return {}
        bone_mask=active[self.owners];bone_owners=np.cumsum(active,dtype=np.int32)[self.owners[bone_mask]]-1
        root_nodes,root_rows=np.unique(self.roots[selected],return_inverse=True)
        geometry=frame.world_matrices(self.shapes[selected])
        left=(geometry@self.transforms[selected])@np.linalg.inv(frame.world_matrices(root_nodes))[root_rows]
        bone_world=frame.world_matrices(self.bones[bone_mask])
        final=(left[bone_owners]@bone_world)@self.binds[bone_mask]
        # Preserve the scalar path's float64 arithmetic and float32 output.
        counts=self.counts[selected];starts=np.cumsum(counts+1,dtype=np.int32)-(counts+1)
        result=np.empty((len(selected)+len(final),3,4),dtype='<f4')
        result[starts]=geometry[:,:3]
        result[np.arange(len(final))+bone_owners+1]=final[:,:3]
        if not np.isfinite(result).all()or np.any(np.abs(result)>1e8):raise ValueError('Invalid native bone palette')
        return {int(self.rows[i]):result[start:start+count+1]for i,start,count in zip(selected,starts,counts)}
