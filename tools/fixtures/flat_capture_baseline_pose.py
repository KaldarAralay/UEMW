"""Prepared render-only queries over one owned original-engine node capture.

No process reads, animation clock, culling simulation or gameplay decisions.
All model/skin identities are checked, including hidden/off-camera shapes.
"""
from collections.abc import Mapping
import numpy as np
from live_probe import SceneReadChanged
from render_culling import View

NODE=np.dtype({'names':['flags','bound','transform'],'formats':['<u2',('<f4',4),('<f4',13)],'offsets':[0x14,0x1c,0x40],'itemsize':0x74})

class PoseLayout:
    def __init__(self,records,view_pointers=()):
        self.records=records
        pointers=set()
        for ptr,identity,parents,skin,owner in records:
            pointers.update(parents);pointers.add(ptr)
            if skin is not None:pointers.update((skin.shape,skin.root,*skin.bones))
        if len(records)>16384 or len(pointers)>32768:raise ValueError('Prepared pose exceeds node/binding budget')
        self.pointers=tuple(sorted(pointers));self.index={p:i for i,p in enumerate(self.pointers)}
        self.shape_indices=np.asarray([self.index[r[0]]for r in records],dtype=np.int32)
        self.shape_index={r[0]:i for i,r in enumerate(records)}
        self.expected=np.asarray([r[1]for r in records],dtype='<u4').reshape(-1,2)
        owners=[];nodes=[]
        for i,row in enumerate(records):
            for p in (*row[2],row[0]):owners.append(i);nodes.append(self.index[p])
        self.edge_shapes=np.asarray(owners,dtype=np.int32);self.edge_nodes=np.asarray(nodes,dtype=np.int32)
        self.first_person=np.asarray([r[0]in view_pointers for r in records],dtype=bool)
        for array in(self.shape_indices,self.expected,self.edge_shapes,self.edge_nodes,self.first_person):array.flags.writeable=False

class PoseFrame(Mapping):
    def __init__(self,raw,layout,camera,first_person=True):
        self.raw=raw;self.layout=layout
        try:
            # One compact strided buffer avoids thousands of Python unpack
            # calls. Immutable joined bytes keep all numerical views owned.
            basic=b''.join(raw[p][:0x74]for p in layout.pointers)
            if len(basic)!=len(layout.pointers)*0x74:raise ValueError('Short native node header')
            self.nodes=np.frombuffer(basic,dtype=NODE)
            identities=b''.join(raw[r[0]][0x98:0xa0]for r in layout.records)
            if len(identities)!=len(layout.records)*8:raise ValueError('Short native shape identity')
            observed=np.frombuffer(identities,dtype='<u4').reshape(-1,2)
            if not np.array_equal(observed,layout.expected):raise SceneReadChanged('Geometry identity changed; refreshing before reuse')
        except(KeyError,ValueError)as error:raise SceneReadChanged('Incomplete captured pose layout: '+str(error))from error
        hidden=(self.nodes['flags']&1)!=0
        blocked=np.zeros(len(layout.records),dtype=bool)
        blocked[layout.edge_shapes[hidden[layout.edge_nodes]]]=True
        self.unhidden=~blocked
        if not first_person:self.unhidden&=~layout.first_person
        self.bounds=self.nodes['bound'][layout.shape_indices]
        self.inside=View(camera).includes_many(self.bounds)
        self.visible=self.unhidden&self.inside
        self.visible_indices=np.flatnonzero(self.visible)
    def __getitem__(self,key):return self.raw[key]
    def __iter__(self):return iter(self.raw)
    def __len__(self):return len(self.raw)
    def shape_visible(self,pointer):return bool(self.visible[self.layout.shape_index[pointer]])
    def worlds(self,pointers):
        keys=tuple(sorted(set(pointers)))
        if not keys:return {}
        indices=[self.layout.index[p]for p in keys]
        values=self.nodes['transform'][indices].astype(np.float64)
        matrices=np.zeros((len(keys),4,4),dtype=np.float64)
        matrices[:,:3,:3]=values[:,:9].reshape(-1,3,3)*values[:,12,None,None]
        matrices[:,:3,3]=values[:,9:12];matrices[:,3,3]=1
        return {p:m for p,m in zip(keys,matrices)}
