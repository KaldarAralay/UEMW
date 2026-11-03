"""Owned complete native transforms, with sparse current deformation payloads.

The dense float32 block avoids converting thousands of native matrices to
Python numbers and back on every publication. Only immutable bytes own the
transforms/visibility. There is no previous-frame dependency or pose clock.
"""
from collections.abc import Sequence
import numpy as np


class CapturedStates(Sequence):
    def __init__(self,transforms,visible,payloads):
        if not isinstance(transforms,np.ndarray)or transforms.dtype!=np.dtype('<f4')or transforms.ndim!=2 or transforms.shape[1]!=13:
            raise ValueError('Invalid captured transform layout')
        count=len(transforms)
        if not 0<count<=16384 or not isinstance(visible,np.ndarray)or visible.dtype!=np.dtype(bool)or visible.shape!=(count,):
            raise ValueError('Invalid captured visibility layout')
        if any(type(i)not in(int,np.int32,np.int64)or not 0<=i<count or not visible[i]or not isinstance(v,tuple)or not 1<=len(v)<=2 for i,v in payloads.items()):
            raise ValueError('Invalid captured deformation rows')
        self._transforms=np.frombuffer(transforms.tobytes(),dtype='<f4').reshape(count,13)
        self._visible=np.frombuffer(visible.tobytes(),dtype=bool)
        self._payloads=dict(payloads)

    def __len__(self):return len(self._visible)

    def __iter__(self):
        for i,visible in enumerate(self._visible):
            yield (True,self._transforms[i],*self._payloads.get(i,()))if visible else (False,)

    def __getitem__(self,index):
        if isinstance(index,slice):return [self[i]for i in range(*index.indices(len(self))) ]
        if index<0:index+=len(self)
        if not 0<=index<len(self):raise IndexError(index)
        if not self._visible[index]:return (False,)
        return (True,self._transforms[index],*self._payloads.get(index,()))

    def packed_transforms(self):
        current=self._transforms[self._visible]
        if not np.isfinite(current).all()or np.any(current>1e8)or np.any(current< -1e8):
            raise ValueError('Invalid captured transform values')
        return current.tobytes()

    def remap(self,count,indices):
        indices=np.asarray(indices)
        if indices.shape!=(len(self),)or indices.dtype.kind not in 'iu'or np.any(indices>=count)or np.any(indices<0)or len(np.unique(indices))!=len(indices):
            raise ValueError('Invalid captured state remap')
        transforms=np.zeros((count,13),dtype='<f4');visible=np.zeros(count,dtype=bool)
        transforms[indices]=self._transforms;visible[indices]=self._visible
        return CapturedStates(transforms,visible,{int(indices[i]):extra for i,extra in self._payloads.items()})

    def pack_records(self,encode_payload,limit):
        """Pack rigid/hidden rows in one scatter; validate sparse payloads normally."""
        current=self._transforms[self._visible]
        if not np.isfinite(current).all()or np.any(current>1e8)or np.any(current< -1e8):
            raise ValueError('Invalid captured transform values')
        kinds=self._visible.astype(np.uint8);sizes=np.where(self._visible,53,1)
        payloads={}
        for index,extra in self._payloads.items():
            kind,data=encode_payload(extra)
            kinds[index]=kind;sizes[index]+=len(data);payloads[index]=data
        total=int(sizes.sum())
        if total>limit:raise ValueError('Binary frame exceeds 4 MiB')
        offsets=np.cumsum(sizes)-sizes;output=np.empty(total,dtype=np.uint8)
        output[offsets]=kinds
        positions=offsets[self._visible,None]+1+np.arange(52)
        output[positions]=current.view(np.uint8).reshape(-1,52)
        for index,data in payloads.items():
            offset=int(offsets[index])+53
            output[offset:offset+len(data)]=np.frombuffer(data,dtype=np.uint8)
        return output.tobytes()
