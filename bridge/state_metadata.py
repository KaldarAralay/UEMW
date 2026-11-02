"""UMP1/v1 native render metadata, carried by uemw.live v4/UFB3.

Complete observed snapshots, little-endian float32. There are no clocks,
interpolation, previous-frame dependencies or gameplay decisions here.
"""
import math
import numbers
import struct

FIELDS=('environment','material_frames','material_values')
HEADER=struct.Struct('<4sHH')
ENV=struct.Struct('<16fI2i8f3I')
LIGHT=struct.Struct('<BB19f')


def scalar(value,limit=1e8,low=None,high=None):
    if (type(value)not in(float,int)and(not isinstance(value,numbers.Real)or isinstance(value,bool)))or not math.isfinite(value)or abs(value)>limit or (low is not None and value<low)or(high is not None and value>high):
        raise ValueError('Invalid packed metadata number')
    return float(value)


def integer(value,low,high):
    value=scalar(value,high if high>0 else 1e8,low,high)
    if value!=math.floor(value):raise ValueError('Invalid packed metadata integer')
    return int(value)


def vector(value,count,limit=1e8,low=None,high=None):
    if not isinstance(value,(list,tuple))or len(value)!=count:raise ValueError('Invalid packed metadata vector')
    return [scalar(v,limit,low,high)for v in value]


def key(value,limit=96):
    if not isinstance(value,str)or not 1<=len(value)<=limit or any(not 32<=ord(c)<=126 for c in value):raise ValueError('Invalid packed metadata ID')
    raw=value.encode('ascii');return bytes([len(raw)])+raw


def flag(value):
    if type(value)is not bool:raise ValueError('Invalid packed metadata flag')
    return int(value)


def version(value):
    if not isinstance(value,dict)or type(value.get('version'))is not int or value['version']!=1:raise ValueError('Unsupported packed metadata section')


def _encode(packet):
    env,frames,values=(packet[name]for name in FIELDS)
    for section in(env,frames,values):version(section)
    weather=env['weather'];lights=env['lights']
    if not isinstance(lights,list)or len(lights)>32:raise ValueError('Invalid packed native light count')
    candidates=integer(env['light_candidates'],0,4096);omitted=integer(env['omitted_lights'],0,4096)
    if candidates!=len(lights)+omitted:raise ValueError('Mixed packed native light counts')
    ambient=vector(env['ambient'],3,1024);sun=vector(env['sun_color'],3,1024);direction=vector(env['sun_direction'],3)
    fog=vector(env['fog_color'],3,1);clip=vector(env['clip'],2,low=0)
    if clip[1]<=clip[0]:raise ValueError('Invalid packed native clip range')
    globals_=ambient+sun+direction+fog+clip+[scalar(env['fog_density'],low=0),scalar(env['water_level'])]
    flags=flag(env['fog_enabled'])|flag(env['has_water'])<<1|flag(weather['underwater'])<<2
    current=integer(weather['current'],-1,9);next_=integer(weather['next'],-1,9)
    weather_values=[scalar(weather['transition'],32),scalar(weather['thunder'],32)]+vector(weather['sky'],3,32)+vector(weather['wind'],3)
    chunks=[HEADER.pack(b'UMP1',1,0),ENV.pack(*globals_,flags,current,next_,*weather_values,candidates,omitted,len(lights))]
    ids=set()
    for light in lights:
        name=light['id'];encoded=key(name,64)
        if name in ids:raise ValueError('Duplicate packed native light ID')
        ids.add(name)
        numbers_=[scalar(light['dimmer'],32),scalar(light['radius'],4294967296.,low=0),scalar(light['spot_angle'],180,0,180),scalar(light['spot_exponent'],low=0)]
        numbers_+=vector(light['position'],3)+vector(light['ambient'],3,32)+vector(light['diffuse'],3,32)+vector(light['direction'],3)+vector(light['attenuation'],3,low=0)
        chunks.extend((encoded,LIGHT.pack(integer(light['kind'],1,3),flag(light['enabled']),*numbers_)))
    table=frames['frames']
    if not isinstance(table,dict)or len(table)>256:raise ValueError('Invalid packed native frame table')
    chunks.append(struct.pack('<H',len(table)))
    for name,index in table.items():chunks.extend((key(name),struct.pack('<B',integer(index,0,255))))
    table=values['values']
    if not isinstance(table,dict)or len(table)>2048:raise ValueError('Invalid packed native material table')
    chunks.append(struct.pack('<H',len(table)))
    for name,row in table.items():
        row=vector(row,8,32)
        if any(not 0<=v<=1 for v in row[:4])or row[7]not in(0,1):raise ValueError('Invalid packed native material value')
        chunks.extend((key(name),struct.pack('<8f',*row)))
    return b''.join(chunks)


def encode(packet):
    try:return _encode(packet)
    except(KeyError,TypeError,AttributeError,OverflowError,struct.error)as error:raise ValueError('Malformed packed native metadata')from error


def decode(take):
    magic,revision,reserved=HEADER.unpack(take(HEADER.size))
    if(magic,revision,reserved)!=(b'UMP1',1,0):raise ValueError('Invalid packed metadata header')
    def read_key(limit=96):
        count=take(1)[0]
        if not 1<=count<=limit:raise ValueError('Invalid packed metadata ID size')
        raw=take(count)
        if any(not 32<=b<=126 for b in raw):raise ValueError('Invalid packed metadata ID bytes')
        return raw.decode('ascii')
    raw=ENV.unpack(take(ENV.size));g=raw[:16];flags,current,next_=raw[16:19];w=raw[19:27];candidates,omitted,count=raw[27:]
    if flags&~7 or count>32:raise ValueError('Invalid packed native environment flags/count')
    env=dict(version=1,ambient=list(g[:3]),sun_color=list(g[3:6]),sun_direction=list(g[6:9]),fog_color=list(g[9:12]),clip=list(g[12:14]),fog_density=g[14],water_level=g[15],
        fog_enabled=bool(flags&1),has_water=bool(flags&2),light_candidates=candidates,omitted_lights=omitted,
        weather=dict(current=current,next=next_,transition=w[0],thunder=w[1],sky=list(w[2:5]),wind=list(w[5:8]),underwater=bool(flags&4)),lights=[])
    for _ in range(count):
        name=read_key(64);kind,enabled,*n=LIGHT.unpack(take(LIGHT.size))
        if enabled>1:raise ValueError('Invalid packed native light flag')
        env['lights'].append(dict(id=name,kind=kind,enabled=bool(enabled),dimmer=n[0],radius=n[1],spot_angle=n[2],spot_exponent=n[3],position=n[4:7],ambient=n[7:10],diffuse=n[10:13],direction=n[13:16],attenuation=n[16:19]))
    frames={};count=struct.unpack('<H',take(2))[0]
    if count>256:raise ValueError('Packed native frame budget exceeded')
    for _ in range(count):
        name=read_key()
        if name in frames:raise ValueError('Duplicate packed native frame ID')
        frames[name]=take(1)[0]
    values={};count=struct.unpack('<H',take(2))[0]
    if count>2048:raise ValueError('Packed native material budget exceeded')
    for _ in range(count):
        name=read_key()
        if name in values:raise ValueError('Duplicate packed native material ID')
        values[name]=list(struct.unpack('<8f',take(32)))
    result=dict(environment=env,material_frames=dict(version=1,frames=frames),material_values=dict(version=1,values=values))
    # Same semantic bounds as the encoder, applied after float32 decoding.
    encode(result)
    return result
