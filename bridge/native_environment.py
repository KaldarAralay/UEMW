"""Read resolved native lighting/weather; never advance a clock or game state.

Offsets: pinned MWSE SharedSE NI{Light,PointLight,SpotLight,Property}.h,
TES3{DataHandler,WeatherController,Cell}.h; Steam 1.6.1820 hash guard in Reader.
The bounded client light list is a rendering approximation of native per-object
light selection. Source flicker, enable state, colors and transforms are copied.
"""
import math
import struct

LIGHT_TYPES={0x74FB90:0,0x74FFE0:1,0x749D40:2,0x7506A8:3}
MAX_LIGHTS=32

def numbers(values,limit=1e8,field='values'):
    result=list(values)
    for index,value in enumerate(result):
        if not math.isfinite(value)or abs(value)>limit:raise ValueError(f'Invalid native environment numbers: {field}[{index}]={value!r}, limit={limit}')
    return result

def light(reader,pointer,raw=None,table=None):
    table=reader.u32(pointer)if table is None else table;kind=LIGHT_TYPES.get(table)
    if kind is None:raise ValueError('Native light type changed')
    raw=reader.read(pointer,0xf0 if kind==3 else 0xdc if kind in(1,2)else 0xd0)if raw is None else raw
    if struct.unpack_from('<I',raw)[0]!=table:raise ValueError('Native light retired while reading')
    if raw[0x90]>1:raise ValueError('Invalid native light enable state')
    # The native light-state renderer at 0x6BB7D4 tests enabled (+0x90),
    # not the NiAVObject APP_CULLED render-pass flag (+0x14).
    enabled=bool(raw[0x90])
    label=f'light {hex(pointer)}'
    dimmer=struct.unpack_from('<f',raw,0xA8)[0];numbers((dimmer,),32,label+'.dimmer')
    ambient=numbers(struct.unpack_from('<3f',raw,0xAC),32,label+'.ambient')
    diffuse=numbers(struct.unpack_from('<3f',raw,0xB8),32,label+'.diffuse')
    position=numbers(struct.unpack_from('<3f',raw,0x64),field=label+'.position')
    radius=struct.unpack_from('<f',raw,0xC4)[0] if kind in(2,3)else 0.
    attenuation=numbers(struct.unpack_from('<3f',raw,0xD0),1e8,label+'.attenuation')if kind in(2,3)else[1.,0.,0.]
    direction=numbers(struct.unpack_from('<3f',raw,0xD0 if kind==1 else 0xDC),field=label+'.direction')if kind in(1,3)else[0.,0.,-1.]
    angle,exponent=struct.unpack_from('<2f',raw,0xE8)if kind==3 else(0.,0.)
    # SharedSE PointLight::getRadius reads the native specular.r as unsigned
    # int. Its float32 representation can exceed the coordinate safety limit.
    numbers((radius,),4294967296.,label+'.radius')
    numbers((angle,exponent),field=label+'.angle/exponent')
    if radius<0 or not 0<=angle<=180 or exponent<0 or any(v<0 for v in attenuation):raise ValueError('Invalid native light attenuation/radius')
    return dict(id=hex(pointer),kind=kind,enabled=enabled,dimmer=dimmer,ambient=ambient,diffuse=diffuse,
        position=position,direction=direction,attenuation=attenuation,radius=radius,spot_angle=angle,spot_exponent=exponent)

def roles(reader,base):
    weather=int(base.get('weather_controller','0x0'),16)
    if not weather:return {}
    pointers=struct.unpack('<5I',reader.read(weather+0x7c,20))
    return {p:role for p,role in zip(pointers,('atmosphere','cloud','cloud','sun','glare'))if p}

def capture(reader,base,pointers=(),owners=None,preferred_lights=()):
    world=int(base['world'],16);data=int(base['data'],16);cell=int(base['cell_ptr'],16)
    flags=reader.u32(cell+0x18)
    packed=reader.read(cell+0x1c,16)
    cell_ambient=[packed[i]/255 for i in(2,1,0)]
    sun,fog=struct.unpack('<2I',reader.read(data+0x98,8))
    pointers=set(pointers)|({sun}if sun else set())
    if len(pointers)>1024:raise ValueError('Native environment exceeds 1024-light capture budget')
    if pointers and hasattr(reader,'read_many'):
        headers=reader.read_many([(p,4)for p in pointers]);tables={p:struct.unpack('<I',raw)[0]for p,raw in headers.items()}
        if any(table not in LIGHT_TYPES for table in tables.values()):raise ValueError('Native light retired before capture')
        raw_lights=reader.read_many([(p,0xf0 if LIGHT_TYPES[table]==3 else 0xdc if LIGHT_TYPES[table]in(1,2)else 0xd0)for p,table in tables.items()])
        all_lights={}
        for p in pointers:
            raw=raw_lights[p]
            if struct.unpack_from('<I',raw)[0]!=tables[p]:raise ValueError('Native light retired while reading')
            if raw[0x90]>1:raise ValueError('Invalid native light enable state')
            # Native-disabled effects contribute nothing. Their unused numeric
            # payloads may be stale; do not let them invalidate a whole pose.
            if raw[0x90]:all_lights[p]=light(reader,p,raw,tables[p])
    else:
        all_lights={}
        for p in pointers:
            table=reader.u32(p);kind=LIGHT_TYPES.get(table)
            if kind is None:raise ValueError('Native light type changed')
            raw=reader.read(p,0xf0 if kind==3 else 0xdc if kind in(1,2)else 0xd0)
            if struct.unpack_from('<I',raw)[0]!=table:raise ValueError('Native light retired while reading')
            if raw[0x90]>1:raise ValueError('Invalid native light enable state')
            if raw[0x90]:all_lights[p]=light(reader,p,raw,table)
    ambient=[0.,0.,0.];have_ambient=False
    for pointer,value in all_lights.items():
        if value['kind']==0 and value['enabled']:
            # Sky/near-pass and VFX ambient lights illuminate only their native
            # branches. Adding these white lights globally washes out the world.
            branches=(owners or {}).get(pointer,())
            if branches and not any(owner is None or owner.startswith(('interior:','exterior:'))for owner in branches):continue
            have_ambient=True
            ambient=[a+b*value['dimmer']for a,b in zip(ambient,value['ambient'])]
    sunlight=all_lights.pop(sun,None)
    if sunlight and sunlight['kind']!=1:raise ValueError('Native sun light identity changed')
    if sunlight and sunlight['enabled']:
        have_ambient=True
        ambient=[a+b*sunlight['dimmer']for a,b in zip(ambient,sunlight['ambient'])]
        sun_color=[v*sunlight['dimmer']for v in sunlight['diffuse']];sun_direction=sunlight['direction']
    else:sun_color=[0.,0.,0.];sun_direction=[0.,0.,-1.]
    # Resolved native ambient already incorporates the cell configuration.
    # Adding that configuration again washed warm resolved colour to grey.
    if not have_ambient and not sun and flags&1:ambient=cell_ambient
    fog_density=0.;fog_color=[0.,0.,0.];fog_enabled=False
    if fog:
        raw=reader.read(fog+0x14,12)
        # Steam 1.6.1820's runtime fog flags differ from serialized NIF flags.
        # Its DX8 state setter at 0x6B8A26 shifts by one before testing enable,
        # then writes D3DRS_FOGENABLE (28). Bit 0 incorrectly disabled all fog.
        fog_enabled=bool(struct.unpack_from('<H',raw)[0]&2)
        fog_density=struct.unpack_from('<f',raw,4)[0]
        fog_color=[raw[8+i]/255 for i in(2,1,0)]
    numbers((fog_density,),field='fog_density')
    if fog_density<0:raise ValueError('Invalid native fog density')
    near,far=base['camera'].get('frustum',[0,0,0,0,1,7168])[4:6]
    numbers((near,far))
    if not 0<=near<far<=1e8:raise ValueError('Invalid native fog clip range')
    weather=reader.u32(world+0x58)
    state=dict(current=-1,next=-1,transition=0.,sky=[0.,0.,0.],wind=[0.,0.,0.],thunder=0.,underwater=False)
    if weather:
        raw=reader.read(weather,0x1d0)
        current,next_weather=struct.unpack_from('<2I',raw,0x3c)
        state.update(current=reader.u32(current+4)if current else -1,next=reader.u32(next_weather+4)if next_weather else -1,
            sky=numbers(struct.unpack_from('<3f',raw,0x90),32,'weather.sky'),wind=numbers(struct.unpack_from('<3f',raw,0xb8),field='weather.wind'),
            transition=struct.unpack_from('<f',raw,0x170)[0],thunder=struct.unpack_from('<f',raw,0x178)[0],underwater=bool(raw[0x199]))
        for key in ('current','next'):
            if state[key]>0x7fffffff:state[key]-=0x100000000
        numbers((state['transition'],state['thunder']),32,'weather.transition/thunder')
        if not -1<=state['current']<=9 or not -1<=state['next']<=9 or raw[0x199]>1:raise ValueError('Invalid native weather identity')
    camera=base['camera']['position']
    candidates=[v for v in all_lights.values()if v['kind']!=0 and v['enabled']]
    preferred=set(preferred_lights)
    candidates.sort(key=lambda v:(0 if v['kind']==1 else 1 if int(v['id'],16)in preferred else 2,max(0,math.dist(v['position'],camera)-v['radius']),v['id']))
    # Distance determines inclusion, not shader slot identity. Reordering the
    # same chosen lights on a camera step needlessly rebinds every material's
    # object-light mask. Keep identical selection with canonical slot order.
    selected=sorted(candidates[:MAX_LIGHTS],key=lambda v:v['id'])
    behaves_outside=not bool(flags&1) or bool(flags&0x80)
    water_level=struct.unpack('<f',reader.read(cell+0x90,4))[0]if not behaves_outside and flags&2 else 0.
    numbers((water_level,),field='water_level')
    return dict(version=1,ambient=numbers(ambient,1024),sun_color=numbers(sun_color,1024),sun_direction=sun_direction,
        fog_color=fog_color,fog_density=fog_density,fog_enabled=fog_enabled,clip=[near,far],weather=state,
        has_water=bool(flags&2 or behaves_outside),water_level=water_level,lights=selected,
        light_candidates=len(candidates),omitted_lights=max(0,len(candidates)-MAX_LIGHTS))
