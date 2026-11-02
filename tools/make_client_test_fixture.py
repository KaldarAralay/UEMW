"""Own synthetic triangle/skin/transport fixture for headless runtime tests."""
import hashlib
import copy
import json
from pathlib import Path
import struct
import sys
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bridge'))
from live_binary import encode,HEADER
from frame_transport import filename

folder=ROOT/'local/test-temp/client-fixture'
for part in ('meshes','textures','frames'):(folder/part).mkdir(parents=True,exist_ok=True)
payload=struct.pack('<4sII',b'UEM3',3,3)+np.asarray([[0,0,0],[3,0,0],[0,4,0]],dtype='<f4').tobytes()+np.asarray([[0,0,1]]*3,dtype='<f4').tobytes()+np.asarray([[0,0],[1,0],[0,1]],dtype='<f4').tobytes()+bytes([255])*12+struct.pack('<3H',0,1,2)
(folder/'meshes/triangle.umesh').write_bytes(payload)
Image.new('RGBA',(2,2),(255,255,255,255)).save(folder/'textures/white.png')
Image.new('RGBA',(2,2),(0,64,255,255)).save(folder/'textures/blue.png')
skin=struct.pack('<4sIII',b'USK1',3,3,2)+struct.pack('<6I',0,1,1,1,2,1)+struct.pack('<6f',1,.7,1,1,0,1)
(folder/'meshes/triangle.uskin').write_bytes(skin)
mesh=dict(file='meshes/triangle.umesh',texture='textures/white.png',alpha_mode='opaque',texture_animation=dict(id='native:flip',frames=['textures/white.png','textures/blue.png']))
catalog=dict(format='uemw.assets',version=1,cells=[],meshes={'rigid':mesh,'skin':{**mesh,'skin_file':'meshes/triangle.uskin','skin_bones':2}},bindings=[dict(id='rigid-instance',asset='rigid'),dict(id='skin-instance',asset='skin')])
(folder/'catalog-fixture.json').write_text(json.dumps(catalog,separators=(',',':')),encoding='utf-8')

# Own image/index fixtures exercise optional-upgrade validation and native fallback.
upgrade_source='textures/'+('a'*64)+'.png'
(folder/upgrade_source).write_bytes((folder/'textures/white.png').read_bytes())
for case in ('good','bad-path','bad-budget','bad-hash','missing'):
    root=folder/('upgrade-'+case);(root/'textures').mkdir(parents=True,exist_ok=True)
    target='textures/'+('a'*64)+'-2x.png';Image.new('RGBA',(4,4),(180,160,140,255)).save(root/target)
    item=dict(file=target,source_md5=hashlib.md5((folder/upgrade_source).read_bytes()).hexdigest(),md5=hashlib.md5((root/target).read_bytes()).hexdigest(),source_width=2,source_height=2,width=4,height=4)
    if case=='bad-path':item['file']='../outside.png'
    if case=='bad-hash':item['md5']='0'*32
    if case=='missing':(root/target).unlink()
    index=dict(protocol='uemw.texture-upgrades',version=1,budget_bytes=1 if case=='bad-budget'else 192*1024*1024,planned_mip_bytes=168,entries={upgrade_source:item})
    (root/'index.json').write_text(json.dumps(index),encoding='utf-8')
variant=copy.deepcopy(catalog);variant['meshes']={key:{**value,'texture':upgrade_source,'source_texture':'tx_wall_stone_01.dds'}for key,value in variant['meshes'].items()}
for invalid in (False,True):
    root=folder/('upgrade-v2-bad-resident'if invalid else'upgrade-v2');(root/'textures').mkdir(parents=True,exist_ok=True)
    entries={}
    for letter,priority in (('a',0),('b',20)):
        source='textures/'+letter*64+'.png';target='textures/'+letter*64+'-2x.png'
        (folder/source).write_bytes((folder/'textures/white.png').read_bytes());Image.new('RGBA',(4,4),(180,160,140,255)).save(root/target)
        entries[source]=dict(file=target,source_md5=hashlib.md5((folder/source).read_bytes()).hexdigest(),md5=hashlib.md5((root/target).read_bytes()).hexdigest(),source_width=2,source_height=2,width=4,height=4,priority=priority)
    index=dict(protocol='uemw.texture-upgrades',version=2,budget_bytes=8*1024**3,planned_mip_bytes=336,resident_budget_bytes=256*1024**2+1 if invalid else 168,entries=entries)
    (root/'index.json').write_text(json.dumps(index),encoding='utf-8')
for value in variant['meshes'].values():value.pop('texture_animation',None)
(folder/'catalog-upgrade.json').write_text(json.dumps(variant),encoding='utf-8')
hair=copy.deepcopy(catalog)
for value in hair['meshes'].values():
    value.pop('texture_animation',None);value.update(source_texture='Textures\\TX_B_N_Dark Elf_F_Hair01.dds',alpha_mode='translucent')
(folder/'catalog-hair.json').write_text(json.dumps(hair),encoding='utf-8')
for excluded in (False,True):
    leaves=copy.deepcopy(hair)
    for value in leaves['meshes'].values():value.update(source_texture='Textures\\Tx_BC_leaves_02.dds',shading=dict(lit=True,fog=True,sky=False,emissive=[0,0,0],native_particle=excluded))
    (folder/('catalog-foliage-particle.json'if excluded else'catalog-foliage.json')).write_text(json.dumps(leaves),encoding='utf-8')
glass=copy.deepcopy(catalog)
sky=copy.deepcopy(catalog);sky['meshes']={};sky['bindings']=[]
for name,texture,atmosphere in (('stars','Tx_Stars_Mage.tga',False),('moon','tx_masser_half_wan.dds',False),('moon-mask','tx_mooncircle_full_M.dds',False),('sun','tx_sun_05.dds',False),('cloud','tx_sky_clear.dds',False),('atmosphere','',True)):
    value=copy.deepcopy(mesh);value.pop('texture_animation',None);value.update(source_texture=texture,alpha_mode='additive'if name=='moon'else'translucent',shading=dict(lit=False,fog=False,sky=atmosphere,background=True,emissive=[0,0,0]));sky['meshes'][name]=value;sky['bindings'].append(dict(id='sky-'+name,asset=name))
(folder/'catalog-celestial.json').write_text(json.dumps(sky),encoding='utf-8')
for value in glass['meshes'].values():
    value.pop('texture_animation',None);value.update(source_texture='Textures\\Tx_glass_bottle_blue.tga',alpha_mode='translucent',shading=dict(lit=True,fog=True,sky=False,emissive=[0,0,0]))
(folder/'catalog-glass.json').write_text(json.dumps(glass),encoding='utf-8')
for first_person in (False,True):
    smoke=copy.deepcopy(glass);smoke['meshes']={'rigid':smoke['meshes']['rigid']};smoke['bindings']=[smoke['bindings'][0]]
    smoke['meshes']['rigid'].update(source_texture='tx_smokealpha00.tga',shading=dict(lit=False,fog=True,sky=False,emissive=[0,0,0],native_particle=True,first_person=first_person))
    (folder/f'catalog-smoke-{int(first_person)}.json').write_text(json.dumps(smoke),encoding='utf-8')

for mode in('opaque','masked','translucent','additive','premultiplied','modulate'):
    for opacity in(True,False):
        variant={**catalog,'meshes':{key:{**value,'alpha_mode':mode,'blend_native_opacity':opacity}for key,value in catalog['meshes'].items()}}
        (folder/f'catalog-blend-{mode}-{int(opacity)}.json').write_text(json.dumps(variant,separators=(',',':')),encoding='utf-8')
for label,value in(('unknown','unknown'),('bad-opacity',False)):
    variant={**catalog,'meshes':{key:{**v,'alpha_mode':value if label=='unknown'else'additive','blend_native_opacity':'bad'if label=='bad-opacity'else True}for key,v in catalog['meshes'].items()}}
    (folder/f'catalog-blend-{label}.json').write_text(json.dumps(variant,separators=(',',':')),encoding='utf-8')
material_catalog={**catalog,'meshes':{key:{**value,'material_state':'native:material'}for key,value in catalog['meshes'].items()}}
(folder/'catalog-material-values.json').write_text(json.dumps(material_catalog,separators=(',',':')),encoding='utf-8')
mutable_catalog=dict(format='uemw.assets',version=1,cells=[],meshes={'mutable':{**mesh,'dynamic_attributes':dict(positions=True,colors=True,uvs=True,morph=True)}},bindings=[dict(id='mutable-instance',asset='mutable')])
(folder/'catalog-native-attributes.json').write_text(json.dumps(mutable_catalog,separators=(',',':')),encoding='utf-8')
(folder/'catalog-rigid-modes.json').write_text(json.dumps(dict(format='uemw.assets',version=1,cells=[],meshes={'rigid':mesh},bindings=[dict(id='rigid-mode',asset='rigid')]),separators=(',',':')),encoding='utf-8')
resource_meshes={**catalog['meshes'],'mutable':mutable_catalog['meshes']['mutable']}
for phase in (0,1):
    bindings=[dict(id=f'resource-{i if phase==0 or i<48 else i+96}',asset=('rigid','skin','mutable')[(i+(1 if phase and i<12 else 0))%3])for i in range(96)]
    (folder/f'catalog-resources-{phase}.json').write_text(json.dumps(dict(format='uemw.assets',version=1,cells=[],meshes=resource_meshes,bindings=bindings),separators=(',',':')),encoding='utf-8')
(folder/'catalog-resources-pending.json').write_bytes((folder/'catalog-resources-0.json').read_bytes())
reuse_bindings=[dict(id=f'reuse-{i}',asset='skin'if i==1 else'mutable'if i==2 else'rigid')for i in range(6144)]
(folder/'catalog-native-reuse.json').write_text(json.dumps(dict(format='uemw.assets',version=1,cells=[],meshes=resource_meshes,bindings=reuse_bindings),separators=(',',':')),encoding='utf-8')
(folder/'catalog-native-reuse-pending.json').write_text(json.dumps(dict(format='uemw.assets',version=1,cells=[],meshes=resource_meshes,bindings=[{**b,'id':'replacement-4'}if i==4 else b for i,b in enumerate(reuse_bindings)]),separators=(',',':')),encoding='utf-8')
packet=dict(protocol='uemw.live',version=3,status='live',session='11112222-3333-4444-5555-666677778888',scene_epoch='99990000-aaaa-bbbb-cccc-ddddeeeeffff',pid=42,sequence=123,sample_unix_ns=1793497851123456789,geometry_version=5,
    scene_catalog='catalog-fixture.json',
    instance_states=[[False],[True,[1,0,0,0,1,0,0,0,1,2,3,4,1],dict(palette=np.asarray([np.eye(4)[:3],np.eye(4)[:3]],dtype='<f4'),bound=[1,2,3,4])]])
body=encode(packet);name='frames/'+filename(packet,True)
(folder/name).write_bytes(body)
packet.pop('instance_states');packet['frame_ref']=dict(file=name,bytes=len(body),md5=hashlib.md5(body).hexdigest())
(folder/'manifest.json').write_text(json.dumps(packet,separators=(',',':')),encoding='utf-8')
uv_packet={**packet,'geometry_version':6,'sequence':124,'scene_catalog':'catalog-native-attributes.json',
    'instance_states':[[True,[1,0,0,0,1,0,0,0,1,0,0,0,1],dict(points=[1,2,3,4,2,3,1,6,3],colors=[1,0,0,.5,0,1,0,.5,0,0,1,.5],uvs=[.25,0,1,0,0,1])]]}
for invalid in (False,True):
    current={**uv_packet,'sequence':125 if invalid else 124};body=bytearray(encode(current))
    if invalid:struct.pack_into('<I',body,HEADER.size+1+52+4,4)
    name='frames/'+filename(current,True);(folder/name).write_bytes(body)
    current.pop('instance_states');current['frame_ref']=dict(file=name,bytes=len(body),md5=hashlib.md5(body).hexdigest())
    (folder/('manifest-uv-invalid.json'if invalid else'manifest-uv.json')).write_text(json.dumps(current,separators=(',',':')),encoding='utf-8')
environment=dict(version=1,ambient=[.1,.2,.3],sun_color=[.4,.5,.6],sun_direction=[1,2,3],fog_color=[.2,.3,.4],fog_density=.8,fog_enabled=True,clip=[1,7168],water_level=123,has_water=True,
    weather=dict(current=4,next=5,transition=.25,sky=[.3,.4,.5],wind=[2,4,6],thunder=.75,underwater=True),light_candidates=1,omitted_lights=0,
    lights=[dict(id='0x1234',kind=2,enabled=True,dimmer=.5,position=[10,20,30],ambient=[.1,.2,.3],diffuse=[.6,.5,.4],direction=[0,0,-1],attenuation=[1,.01,.0001],radius=500,spot_angle=0,spot_exponent=0)])
(folder/'environment.json').write_text(json.dumps(environment,separators=(',',':')),encoding='utf-8')
metadata_env=copy.deepcopy(environment);metadata_env.update(light_candidates=36,omitted_lights=4,lights=[])
for i in range(32):
    light=copy.deepcopy(environment['lights'][0]);light.update(id=f'native:light{i:03}',position=[i*10,20,30],spot_angle=30,spot_exponent=2,radius=258922080. if i==0 else 500.)
    metadata_env['lights'].append(light)
state_packet=dict(protocol='uemw.live',version=1,status='live',session='11112222-3333-4444-5555-666677778888',scene_epoch='99990000-aaaa-bbbb-cccc-ddddeeeeffff',pid=42,sample_unix_ns=1793497851123456789,geometry_version=6,
    scene_catalog='catalog-fixture.json',cell='Owned codec fixture',menu=False,window=123,
    camera=dict(position=[0,0,0],forward=[0,1,0],up=[0,0,1],fov=75),objects=[],
    environment=metadata_env,material_frames=dict(version=1,frames={f'native:flip{i:03}':i%2 for i in range(76)}),
    material_values=dict(version=1,values={f'native:material{i:03}':[.1,.2,.3,.4,.5,.6,.7,1]for i in range(128)}),
    instance_states=[[True,[1,0,0,0,1,0,0,0,1,i,0,0,1]]if i<800 else[False]for i in range(6144)])
def store_metadata_fixture(label,sequence,packed,mutate=None):
    current={**state_packet,'sequence':sequence};body=bytearray(encode(current,packed_metadata=packed))
    if mutate:mutate(body)
    name='frames/'+filename(current,True);(folder/name).write_bytes(body)
    manifest={k:v for k,v in current.items()if k not in ('instance_states','objects')}
    if packed:
        for key in('environment','material_frames','material_values'):manifest.pop(key)
        manifest['state_metadata_version']=1
    manifest.update(version=4 if packed else 3,frame_ref=dict(file=name,bytes=len(body),md5=hashlib.md5(body).hexdigest()))
    (folder/f'manifest-state-{label}.json').write_text(json.dumps(manifest,separators=(',',':')),encoding='utf-8')
store_metadata_fixture('legacy',200,False)
store_metadata_fixture('packed',201,True)
store_metadata_fixture('reserved',202,True,lambda b:struct.pack_into('<H',b,b.index(b'UMP1')+6,1))
store_metadata_fixture('light-count',203,True,lambda b:struct.pack_into('<I',b,b.index(b'UMP1')+8+116,33))
store_metadata_fixture('material',204,True,lambda b:struct.pack_into('<f',b,len(b)-4,.5))
store_metadata_fixture('truncated',205,True,lambda b:b.__delitem__(slice(-5,None)))
store_metadata_fixture('trailing',206,True,lambda b:b.append(0))
print('Synthetic test fixture:',folder)
