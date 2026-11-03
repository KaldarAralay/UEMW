"""Compiled checks of exactly the consumed native UI bytes, including overlaps.

Only addresses/expected structural bytes are cached. Each validation reads a
new owned snapshot; gaps in merged spans never become required identity bytes.
"""
import numpy as np
from read_batch import ReadPlan,capture_ranges


class UIFence:
    def __init__(self,fences):
        self.fences=tuple(fences)
        self.layout=tuple((p,len(value))for p,value in self.fences)
        requests={}
        for p,value in self.fences:requests[p]=max(requests.get(p,0),len(value))
        self.plan=ReadPlan(requests.items())
        size=sum(len(value)for _,value in self.fences)
        if size>16*1024*1024:raise ValueError('Native UI identity fence exceeds 16 MiB')
        self.indices=np.empty(size,dtype=np.uint32);at=0
        for p,value in self.fences:
            offset,_=self.plan.offsets[p];n=len(value)
            self.indices[at:at+n]=np.arange(offset,offset+n,dtype=np.uint32);at+=n
        self.expected=np.frombuffer(b''.join(value for _,value in self.fences),dtype=np.uint8)

    def update_expected(self,fences):
        fences=tuple(fences)
        if tuple((p,len(value))for p,value in fences)!=self.layout:return False
        # Only the address/index plan is reused. Expected values come from
        # THIS capture, including every revision/count/visibility change.
        self.fences=fences;self.expected=np.frombuffer(b''.join(value for _,value in fences),dtype=np.uint8);return True

    def matches(self,capture):
        if capture.plan is not self.plan:raise ValueError('Native UI fence/capture plan mismatch')
        return np.array_equal(np.frombuffer(capture.data,dtype=np.uint8)[self.indices],self.expected)

    def check(self,read):
        return self.matches(capture_ranges(read,self.plan,{}))
