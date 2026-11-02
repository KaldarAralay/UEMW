"""Sample resolved native material values; never evaluate its controllers."""
import math
import struct
from live_probe import SceneReadChanged

MATERIAL=0x75036c


def discover(reader,shape):
    prop=int(shape.get('material','0x0'),16)
    if not prop or shape.get('particles'):return None
    raw=reader.read(prop,0x14)
    if struct.unpack_from('<I',raw)[0]!=MATERIAL:raise SceneReadChanged('Native material property was replaced')
    controller=struct.unpack_from('<I',raw,0x10)[0]
    # Sky/weather/water also receive resolved values directly from the engine.
    # Static world/player materials keep their baked path and cost no pose reads.
    # Draw/sheath can retire the hidden third-person weapon's material before
    # the auxiliary catalog catches up. Sampling its unused static values would
    # unnecessarily reject the entire live world during that transition.
    layer=shape.get('cell_key','')
    if not controller and (not layer.startswith('aux:')or layer=='aux:player'):return None
    model=int(shape['model'],16)
    vertex_color=bool(reader.u32(model+0x24) and shape.get('color_mode',2)!=0)
    emissive_only=shape.get('lighting_mode',1)==0
    return dict(id=shape.get('generation','')+':mat:'+hex(prop)+(':vertex'if vertex_color else':material')+(':emissive-only'if emissive_only else''),
                property=prop,controller=controller,vertex_color=vertex_color,emissive_only=emissive_only)


def capture(reader,groups):
    if len(groups)>2048:raise ValueError('Native material value budget exceeded')
    values={};cache={}
    for key,item in groups.items():
        prop=item['property']
        if prop not in cache:cache[prop]=reader.read(prop,0x54)
        raw=cache[prop]
        if struct.unpack_from('<I',raw)[0]!=MATERIAL or struct.unpack_from('<I',raw,0x10)[0]!=item['controller']:
            raise SceneReadChanged(f'Native material identity/controller changed: {hex(prop)} table={hex(struct.unpack_from("<I",raw)[0])} controller={hex(struct.unpack_from("<I",raw,0x10)[0])} expected={hex(item["controller"])}')
        diffuse=struct.unpack_from('<3f',raw,0x28);emissive=struct.unpack_from('<3f',raw,0x40);alpha=struct.unpack_from('<f',raw,0x50)[0]
        if not all(math.isfinite(v)and abs(v)<=32 for v in (*diffuse,*emissive,alpha)):raise ValueError('Invalid resolved native material values')
        # NI::VertexColorProperty::LIGHTING_E ignores material diffuse even
        # when it is white. Native rain uses exactly this resolved mode.
        unlit=item.get('emissive_only',False)or(max(emissive)>.001 and max(diffuse)<.001)
        rgb=(1.,1.,1.)if item['vertex_color']else emissive if unlit else diffuse
        tint=[max(0.,min(1.,v))for v in (*rgb,alpha)]
        values[key]=[*tint,*( (0.,0.,0.)if unlit else emissive),0 if unlit else 1]
    return dict(version=1,values=values)
