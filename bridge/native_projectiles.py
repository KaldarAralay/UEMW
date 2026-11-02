"""Read original projectile references and their owned visual effect roots."""
import struct
from live_probe import SceneReadChanged


def effect_roots(reader,vfx,targets=None,*,include_targets=False):
    if not vfx:return {}if include_targets else[]
    header=reader.read(vfx,12);sentinel,n=struct.unpack_from('<2I',header,4)
    if n>4096 or(n and not sentinel):raise SceneReadChanged('Native VFX list exceeds bounds')
    if not n:
        if reader.read(vfx+4,8)!=header[4:12]:raise SceneReadChanged('Native VFX ownership changed during capture')
        return {}if include_targets else[]
    link=reader.u32(sentinel);visited=set();nodes={}
    for _ in range(n):
        if not link or link==sentinel or link in visited:raise SceneReadChanged('Native VFX list changed')
        visited.add(link);following,previous,effect=struct.unpack('<3I',reader.read(link,12))
        item=reader.read(effect,0x24);target=struct.unpack_from('<I',item)[0]
        if (targets is None or target in targets)and not item[0x20]:
            node=struct.unpack_from('<I',item,0x1c)[0]
            if node:
                if node in nodes and nodes[node]!=target:raise SceneReadChanged('Native VFX owner changed')
                nodes[node]=target
        link=following
    if link!=sentinel or reader.read(vfx+4,8)!=header[4:12]:raise SceneReadChanged('Native VFX ownership changed during capture')
    return dict(sorted(nodes.items()))if include_targets else sorted(nodes)


def roots(reader,manager,vfx=0):
    if not manager:return []
    original=reader.read(manager,0x14);count,head=struct.unpack_from('<2I',original,4)
    if count>256:raise SceneReadChanged('Native projectile list exceeds bounds')
    references={};nodes=set();seen=set();link=head
    for _ in range(count):
        if not link or link==manager+0xc or link in seen:raise SceneReadChanged('Native projectile list changed')
        seen.add(link);previous,following,mobile=struct.unpack('<3I',reader.read(link,12))
        ref=reader.u32(mobile+0x14)
        if ref:
            data=reader.read(ref,0x14)
            if data[4:8]!=b'REFR':raise SceneReadChanged('Native projectile reference was replaced')
            references[ref]=mobile;node=struct.unpack_from('<I',data,0x10)[0]
            if node:nodes.add(node)
        link=following
    if count and link not in(0,manager+0xc):raise SceneReadChanged('Native projectile list count changed')
    if references and vfx:nodes.update(effect_roots(reader,vfx,references))
    after=reader.read(manager,16)
    if after!=original[:16]:raise SceneReadChanged('Native projectile membership changed during capture: '+original[:16].hex()+' -> '+after.hex())
    return sorted(nodes)
