"""Small, fresh near-pass capture; no animation prediction or retained poses."""
import math
import struct
import time
from read_batch import ReadPlan,RangeCapture
from live_probe import SceneReadChanged


class ViewPoseCapture:
    def __init__(self,records,view_pointers,plan,camera):
        self.camera=camera;nodes=set()
        for ptr,identity,parents,skin,owner in records:
            if ptr not in view_pointers:continue
            nodes.update((*parents,ptr))
            if skin is not None:nodes.update((skin.root,*skin.bones))
        self.nodes=tuple(sorted(nodes))
        self.plan=ReadPlan([(p,plan.offsets[p][1])for p in self.nodes]+[(camera,0x128)])

    def capture(self,reader,raw,world):
        started=time.perf_counter()
        for attempt in range(2):
            before=reader.u32(world+0x24);stamp=time.time_ns()
            latest=reader.capture_many(self.plan)if hasattr(reader,'capture_many')else reader.read_many(self.plan)
            after=reader.u32(world+0x24)
            if before==after or attempt:break
        block=latest[self.camera]
        transform=struct.unpack_from('<13f',block,0x40)
        forward=struct.unpack_from('<3f',block,0xdc);up=struct.unpack_from('<3f',block,0xe8);frustum=struct.unpack_from('<6f',block,0x100)
        if not all(math.isfinite(v)and abs(v)<1e8 for v in(*transform,*forward,*up,*frustum)):raise SceneReadChanged('Invalid native arms camera')
        if sum(v*v for v in forward)<.5 or sum(v*v for v in up)<.5 or not 0<frustum[4]<frustum[5]:raise SceneReadChanged('Degenerate native arms camera')
        # Retain the flat/vectorized classification path. Only these owned
        # near-pass bytes are replaced; no previous-frame bytes are accepted.
        if isinstance(raw,RangeCapture):
            data=bytearray(raw.data)
            for ptr in self.nodes:
                offset,count=raw.plan.offsets[ptr];data[offset:offset+count]=latest[ptr][:count]
            result=RangeCapture(raw.plan,data)
        else:
            result=dict(raw);result.update((p,latest[p])for p in self.nodes)
        camera=dict(position=transform[9:12],forward=forward,up=up,frustum=frustum)
        return result,camera,stamp,dict(nodes=len(self.nodes),attempts=attempt+1,read_ms=(time.perf_counter()-started)*1000)
