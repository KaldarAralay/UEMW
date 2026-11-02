"""Original per-geometry dynamic-effect membership, not spatial inference.

Steam 1.6.1820: NiGeometry.effectState +0x94; effect-state head +8;
two-pointer links (next, effect). Verified against native setup at 0x6BB7BA.
The native D3D light builder at 0x6BAB00 uses the global 0x7DDA0C range,
not PointLight.specular.r's object-selection radius.
"""
import struct
from live_probe import SceneReadChanged
from native_environment import LIGHT_TYPES


def capture(reader,state,cache):
    if not state:return None
    if state in cache:return cache[state]
    header=reader.read(state,12)
    if struct.unpack_from('<I',header)[0]!=0x7469b4:raise SceneReadChanged('Native light-state identity changed')
    node=struct.unpack_from('<I',header,8)[0];seen=set();lights=[]
    while node:
        if node in seen or len(seen)>=128:raise SceneReadChanged('Invalid native per-object light list')
        seen.add(node);node,effect=struct.unpack('<2I',reader.read(node,8))
        if effect and reader.u32(effect)in LIGHT_TYPES:lights.append(hex(effect))
    after=reader.read(state,12)
    if after[:4]!=header[:4]or after[8:12]!=header[8:12]:raise SceneReadChanged('Native light state changed during capture')
    result=tuple(dict.fromkeys(lights));cache[state]=result;return result
