"""Bounded original actor statistics for acceptance evidence; no game writes."""
import math
import struct


def actor_state(reader,reference):
    reference=int(reference,16)if isinstance(reference,str)else reference
    if reader.read(reference+4,4)!=b'REFR':raise ValueError('Expected native reference')
    link=reader.u32(reference+0x44);seen=set()
    for _ in range(64):
        if not link:return None
        if link in seen:raise ValueError('Cyclic native actor attachment list')
        seen.add(link)
        kind,next_link=struct.unpack('<2I',reader.read(link,8))
        if kind==8:
            data=reader.u32(link+8)
            if not data or reader.u32(data+0x14)!=reference:return None
            stats={name:list(struct.unpack('<2f',reader.read(data+offset+4,8)))for name,offset in (('health',0x2b4),('fatigue',0x2d8))}
            if not all(math.isfinite(v)and abs(v)<1e8 for values in stats.values()for v in values):raise ValueError('Invalid original actor statistic')
            return dict(reference=hex(reference),mobile=hex(data),**stats)
        link=next_link
    raise ValueError('Unbounded native actor attachment list')
