"""Native actor-reference ownership, independent of temporary render parents."""
import struct
from live_probe import SceneReadChanged


def identity(raw):
    if len(raw)<0x50 or raw[4:8]!=b'REFR':raise SceneReadChanged('Actor reference was retired')
    return (struct.unpack_from('<2I',raw),struct.unpack_from('<I',raw,0x10)[0],struct.unpack_from('<I',raw,0x28)[0],*struct.unpack_from('<2I',raw,0x48))


def matches(raw,expected):
    try:return identity(raw)==expected and not struct.unpack_from('<I',raw,8)[0]&((1<<5)|(1<<11))
    except (SceneReadChanged,struct.error):return False

def cell_roots(reader,cells):
    """Bind render roots to live TES cell slots, independent of render passes."""
    result={}
    for cell,expected in cells:
        raw=reader.read(cell+0x14,0x1c)
        first,flags=struct.unpack_from('<2I',raw)
        second=struct.unpack_from('<I',raw,0x18)[0]
        roots=[first,second];rows=[(first,((cell+0x14,first),)),(second,((cell+0x2c,second),))]
        if not flags&1:
            land=struct.unpack_from('<I',raw,0xc)[0];root=reader.u32(land+0x10)if land else 0
            roots.append(root)
            if land:rows.append((root,((cell+0x20,land),(land+0x10,root))))
        if expected is not None and roots!=list(expected):raise SceneReadChanged('Cell render roots changed during ownership discovery')
        for root,checks in rows:
            if root:
                if root in result:raise SceneReadChanged('Cell render root has ambiguous ownership')
                result[root]=checks
    return result

def cell_root_matches(raw,checks):
    try:return all(struct.unpack_from('<I',raw[address])[0]==pointer for address,pointer in checks)
    except(KeyError,struct.error):return False

def player_owner(reader,reference,node,cell_root):
    raw=reader.read(reference,0x50);key=identity(raw)
    if key[1]!=node or not matches(raw,key):raise SceneReadChanged('Player render reference changed')
    if reader.read(key[2]+4,4)not in(b'NPC_',b'CREA'):raise SceneReadChanged('Player reference is not an actor')
    return dict(reference=reference,identity=key,cell_root=cell_root,role='aux:player')


def discover(reader,cells,excluded=()):
    result={};kinds={};excluded=set(excluded)
    for cell,root,role in cells:
        for offset in (0x30,0x40,0x58):
            header=reader.read(cell+offset,12);count,current,tail=struct.unpack('<3I',header)
            if count>10000:raise SceneReadChanged('Actor ownership list exceeds reference budget')
            seen=set()
            for _ in range(count+1):
                if not current:break
                if current in seen:raise SceneReadChanged('Actor ownership list cycled')
                seen.add(current);raw=reader.read(current,0x50);key=identity(raw);node=key[1];physical=key[2]
                if node and node not in excluded:
                    if physical not in kinds:kinds[physical]=reader.read(physical+4,4)
                    if kinds[physical]in (b'NPC_',b'CREA'):
                        result[node]=dict(reference=current,identity=key,cell_root=root,role=role)
                current=struct.unpack_from('<I',raw,0x20)[0]
            if current or reader.read(cell+offset,12)!=header:raise SceneReadChanged('Actor ownership list changed during discovery')
    return result
