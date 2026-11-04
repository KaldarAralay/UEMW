"""Independent original near-pass poses, fenced to the committed world catalog.

Only copies resolved native nodes/bones. No animation clock or prediction.
"""
import hashlib
import json
import re
import struct
import time
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from asset_files import publish
from read_batch import ReadPlan
from pose_frame import PoseFrame,PoseLayout
from native_switches import SwitchLayout
from skin_math import Skin
from live_probe import ROOT,SceneReadChanged

NAME=re.compile(r'view-[0-9a-f]{64}\.json\Z')


def surface_key(definition,weights=None):
    shading=dict(definition['shading']);shading.pop('first_person',None)
    # Foreground geometry cannot cast world shadows. Full catalogs carry this
    # ownership annotation, but independent raw conversion does not; it must
    # not invalidate reuse of otherwise identical native geometry/materials.
    shading.pop('native_actor',None)
    return json.dumps([definition['asset'],definition['texture'],definition.get('alpha_mode','opaque'),definition.get('blend_native_opacity',True),definition.get('alpha_test'),shading,weights,definition.get('texture_stages'),definition.get('environment_map')],sort_keys=True,separators=(',',':'))


def publish_layout(value,folder):
    data=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
    if len(data)>256*1024:raise ValueError('Near-pass layout exceeds budget')
    name='view-'+hashlib.sha256(data).hexdigest()+'.json';publish(folder/name,data);return name


class DefinitionCache:
    """Rebind only byte-verified, previously converted immutable near assets."""
    def __init__(self,reader):self.reader=reader;self.assets=None;self.entries={};self.scope=None
    def ingest(self,definition,epoch):
        scope=(epoch,definition['root'],definition.get('item_root'))
        if scope!=self.scope:self.entries={};self.scope=scope
        for row in definition['rows']:
            if row.get('reuse')and len(self.entries)<128:self.entries[row['reuse']]=row['asset']
    def prepare(self,graph,definition,base):
        if not self.entries:return None
        from game_assets import Assets
        from native_attributes import discover
        from material_values import discover as material
        from native_materials import discover as flip
        r=self.reader;world=int(base['world'],16);visual=r.player_render_state(world)
        if not visual['first_person']or not visual.get('items_active')or visual.get('reference')!=base['player_ref']or visual.get('item_root')!=definition.get('item_root'):return None
        if hex(r.u32(world+0x158))!=definition['root']:return None
        model=int(visual['item_root'],16);shapes=[s for s in graph['shapes']if model in s['parents']]
        if not shapes or len(shapes)>128 or any(s.get('particles')or s.get('alpha_mode','opaque')!='opaque'for s in shapes):return None
        if self.assets is None:self.assets=Assets(r)
        # Native allocators reuse model addresses between draws. Verify actual
        # geometry/material bytes again rather than trusting an address cache.
        self.assets.meshes.clear();self.assets.begin_refresh();rows=[];nodes=set()
        prefix=definition['rows'][0]['id'].rsplit(':',1)[0]+':'if':'in definition['rows'][0]['id']else''
        for shape in shapes:
            shape=dict(shape,generation=prefix[:-1],cell_key='view:first-person')
            if shape.get('native_environment_effect'):return None
            if discover(r,shape)or material(r,shape)or flip(r,int(shape.get('texture_property','0x0'),16),shape['generation']):return None
            converted=self.assets.mesh(shape);skin=Skin(r,shape)if shape['skin']!='0x0'else None
            from native_texture_stages import read as read_stages,convert as convert_stages
            if not hasattr(self.assets,'used_textures'):self.assets.used_textures=set()
            stages,flips=convert_stages(self.assets,shape,read_stages(r,int(shape.get('texture_property','0x0'),16),shape['generation']))
            if flips:return None
            if stages:converted={**converted,'texture_stages':stages}
            from native_blend import alpha_test
            test=alpha_test(shape.get('alpha_flags',0),shape.get('alpha_ref',0))
            if test:converted={**converted,'alpha_test':test}
            key=surface_key(converted,skin.export_weights(self.assets.out)if skin else None);asset=self.entries.get(key)
            if asset is None:return None
            p=int(shape['id'],16);parents=(*shape['parents'],p);nodes.update(parents)
            row=dict(id=prefix+shape['id'],asset=asset,ptr=p,identity=[int(shape['model'],16),int(shape['skin'],16)],parents=parents,reuse=key)
            if skin:
                nodes.update((skin.root,*skin.bones));row['skin']=dict(root=skin.root,bones=skin.bones,skin_transform=skin.skin_transform.tolist(),binds=[v.tolist()for v in skin.binds])
            rows.append(row)
        identities={}
        for p in nodes:
            header=r.read(p,0x1c);identities[str(p)]=(struct.unpack_from('<I',header)[0],struct.unpack_from('<I',header,0x18)[0])
        if r.player_render_state(world)!=visual:return None
        switches=SwitchLayout(shapes,graph.get('switches',{}))
        value=dict(protocol='uemw.view.layout',version=1,catalog=definition['catalog'],root=definition['root'],item_root=definition['item_root'],rows=rows,
            node_identities=identities,switches=list(switches.definitions),shape_gates=[s.get('switch_gates',())for s in shapes])
        rebound=NearPass(publish_layout(value,self.assets.out));rebound.rebound=True;return rebound
    def close(self):
        if self.assets:self.assets.close()


def discovery_matches(value,pid,session,epoch,now):
    return isinstance(value,dict)and value.get('protocol')=='uemw.view.discovery'and value.get('version')==1 and value.get('pid')==pid and value.get('session')==session and value.get('scene_epoch')==epoch and isinstance(value.get('signature'),str)and NAME.fullmatch('view-'+value['signature']+'.json')is not None and isinstance(value.get('unix_ns'),int)and 0<=now-value['unix_ns']<400_000_000


class Discovery:
    def __init__(self,reader):
        from scene_reader import SceneReader
        self.reader=reader;self.scene=SceneReader(reader);self.last=0.;self.reported=None
    def poll(self,base,definition):
        if time.perf_counter()-self.last<.1:return None
        self.last=time.perf_counter();r=self.reader;world=int(base['world'],16);visual=r.player_render_state(world)
        if visual.get('reference')!=base['player_ref']or not visual['first_person']or not visual.get('items_active'):
            self.reported=None;return None
        model=int(visual.get('item_root')or'0x0',16);root=r.u32(world+0x158)
        if not model or not root:return None
        graph=self.scene.collect(roots=[],view_roots=[hex(root)]);self.graph=graph
        observed=sorted((int(s['id'],16),int(s['model'],16),int(s['skin'],16))for s in graph['shapes']if model in s['parents']and not s.get('particles')and s.get('alpha_mode','opaque')=='opaque')
        expected=sorted((s['ptr'],*s['identity'])for s in definition['rows'])if definition else[]
        if definition and observed==expected and definition.get('item_root')==visual.get('item_root'):
            self.reported=None;return None
        after=r.player_render_state(world)
        if after!=visual:return None
        signature=hashlib.sha256(json.dumps((visual['item_root'],observed),separators=(',',':')).encode()).hexdigest()
        if signature==self.reported:return None
        self.reported=signature;return signature


def export(geometry,base):
    rows=[];nodes=set();shapes=[]
    for shape,record in zip(geometry.shapes,geometry.records):
        p,identity,parents,skin,owner=record
        if p not in geometry.view_pointers or p in geometry.native_attributes or shape.get('particles'):continue
        definition=shape['prepared'][0]
        if definition.get('alpha_mode','opaque')!='opaque':continue
        row=dict(id=shape['render_id'],asset=shape['asset'],ptr=p,identity=identity,parents=parents)
        if not any(shape['prepared'][1:]):row['reuse']=surface_key(definition,definition.get('skin_file'))
        nodes.update((*parents,p));shapes.append(shape)
        if skin is not None:
            nodes.update((skin.root,*skin.bones))
            row['skin']=dict(root=skin.root,bones=skin.bones,skin_transform=skin.skin_transform.tolist(),binds=[v.tolist()for v in skin.binds])
        rows.append(row)
    if not rows:return None
    switches=SwitchLayout(shapes,geometry.native_switches)
    value=dict(protocol='uemw.view.layout',version=1,catalog=geometry.catalog,root=base['view_roots'][0],item_root=base.get('first_person_model_root'),
        rows=rows,node_identities={str(p):geometry.node_identities[p]for p in nodes if p in geometry.node_identities},
        switches=list(switches.definitions),shape_gates=[s.get('switch_gates',())for s in shapes])
    return publish_layout(value,geometry.assets.out)


class NearPass:
    def __init__(self,name):
        if not NAME.fullmatch(name):raise ValueError('Invalid near-pass layout name')
        path=ROOT/'local/assets'/name
        if not 0<path.stat().st_size<=256*1024:raise ValueError('Invalid near-pass layout size')
        data=path.read_bytes()
        if 'view-'+hashlib.sha256(data).hexdigest()+'.json'!=name:raise ValueError('Near-pass layout digest mismatch')
        d=json.loads(data)
        if d.get('protocol')!='uemw.view.layout'or d.get('version')!=1 or not 0<len(d['rows'])<=128:raise ValueError('Invalid near-pass layout')
        self.definition=d;self.rows=d['rows'];self.records=[];self.plan=None;self.camera=None
        for row in self.rows:
            skin=None;s=row.get('skin')
            if s:
                if not 0<len(s['bones'])<=256 or len(s['binds'])!=len(s['bones']):raise ValueError('Invalid near-pass bones')
                skin=Skin.__new__(Skin);skin.shape=row['ptr'];skin.root=s['root'];skin.bones=s['bones']
                skin.skin_transform=np.asarray(s['skin_transform'],dtype=np.float64).reshape(4,4);skin.binds=np.asarray(s['binds'],dtype=np.float64).reshape(-1,4,4)
                if not np.isfinite(skin.skin_transform).all()or not np.isfinite(skin.binds).all():raise ValueError('Invalid near-pass bind values')
            self.records.append((row['ptr'],tuple(row['identity']),tuple(row['parents']),skin,None))
        self.identities={int(p):tuple(v)for p,v in d['node_identities'].items()}
        self.switches={v['node']:v for v in d['switches']}

    def prepare(self,camera):
        nodes=set();shapes=[]
        for row,record,gates in zip(self.rows,self.records,self.definition['shape_gates']):
            p,identity,parents,skin,owner=record;nodes.update((*parents,p))
            if skin:nodes.update((skin.root,*skin.bones))
            shapes.append(dict(switch_gates=gates))
        if len(nodes)>2048:raise ValueError('Near-pass node budget exceeded')
        switches=SwitchLayout(shapes,self.switches);requests={p:0xac for p in nodes}
        for p,n in switches.requests():requests[p]=max(requests.get(p,0),n)
        requests[camera]=0x128;self.plan=ReadPlan(sorted(requests.items()));self.camera=camera
        self.layout=PoseLayout(self.records,{r[0]for r in self.records},read_plan=self.plan,switches=switches,node_identities=self.identities,near_pass_camera=True)
        self.nodes=tuple(sorted(nodes))

    def capture(self,reader,base):
        started=time.perf_counter();world=int(base['world'],16);visual=reader.player_render_state(world)
        if visual.get('reference')!=base['player_ref']:raise SceneReadChanged('Near-pass player changed')
        active=visual['first_person']and visual.get('items_active',True)
        if hex(reader.u32(world+0x158))!=self.definition['root']:raise SceneReadChanged('Near-pass root changed')
        if active and visual.get('item_root')!=self.definition.get('item_root'):raise SceneReadChanged('Near-pass equipment changed')
        camera=reader.u32(world+0x160)
        if not camera:raise SceneReadChanged('Near-pass camera missing')
        if self.camera!=camera:self.prepare(camera)
        # Two matching owned samples prevent mixing nodes from an animation
        # update in progress. Retry only this small branch, never the world.
        previous=None;raw=None;stamp=0
        for attempt in range(4):
            stamp=time.time_ns();current=reader.capture_many(self.plan)
            key=tuple(current[p][:4]+current[p][0x14:0x74]+(current[p][0x98:0xa0]if p in self.layout.shape_index else b'')for p in self.nodes)+(current[camera][0x40:0x128],)
            if key==previous:raw=current;break
            previous=key;time.sleep(.0002)
        if raw is None:raise SceneReadChanged('Near-pass animation is still updating')
        block=raw[camera];t=struct.unpack_from('<13f',block,0x40)
        cam=dict(position=t[9:12],forward=struct.unpack_from('<3f',block,0xdc),up=struct.unpack_from('<3f',block,0xe8),frustum=struct.unpack_from('<6f',block,0x100))
        if not all(np.isfinite(v)and abs(v)<1e8 for v in(*t,*cam['forward'],*cam['up'],*cam['frustum'])):raise SceneReadChanged('Invalid near-pass camera')
        frame=PoseFrame(raw,self.layout,cam,visual['first_person'],True,visual.get('items_active',True))
        needed=set()
        for i in frame.visible_indices:
            p,identity,parents,skin,owner=self.records[i]
            if skin:needed.update((p,skin.root,*skin.bones))
        worlds=frame.worlds(needed);states=[]
        for i,(row,record)in enumerate(zip(self.rows,self.records)):
            p,identity,parents,skin,owner=record;value=dict(id=row['id'],asset=row['asset'],visible=bool(frame.visible[i]))
            if value['visible']:
                value['transform']=list(struct.unpack_from('<13f',raw[p],0x40))
                if skin:value.update(palette=skin.palette(worlds).reshape(-1).tolist(),bound=list(struct.unpack_from('<4f',raw[p],0x1c)))
            states.append(value)
        after=reader.player_render_state(world)
        if (after.get('reference'),after['first_person'],after.get('items_active'),after.get('item_root'))!=(visual.get('reference'),visual['first_person'],visual.get('items_active'),visual.get('item_root'))or reader.u32(world+0x160)!=camera:raise SceneReadChanged('Near-pass changed during capture')
        return dict(protocol='uemw.view',version=1,catalog=self.definition['catalog'],sample_unix_ns=stamp,camera=cam,states=states,
                    read_ms=(time.perf_counter()-started)*1000,attempts=attempt+1,verified_cached_definition=getattr(self,'rebound',False))
