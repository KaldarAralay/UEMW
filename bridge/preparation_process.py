"""Private process-pool preparation protocol v1; no public IPC endpoint.

Only this parent's spawned worker produces these messages. Pickle is confined
to inherited Python multiprocessing pipes; files/network input are not loaded.
Native handles, archive cursors and preparation caches never cross the pipe.
"""
import copy,hashlib,io,json,multiprocessing as mp,os,pickle,threading,time
from pathlib import Path
from types import MappingProxyType

PROTOCOL='uemw.preparation';VERSION=1;MAX_PAYLOAD=64*1024*1024
_engine=_reader=_cancel=_local_cancel=None
_last_parts={}
_last_digest=''
_accepted_history={}

class CountCache:
    def __init__(self,count):self.count=count
    def __len__(self):return self.count
class AssetSnapshot:
    def __init__(self,out,meshes,textures,missing):
        self.out=Path(out);self.meshes=CountCache(meshes);self.textures=CountCache(textures);self.missing=missing
    def close(self):pass
def restore_plan(groups,source_requests):
    from read_batch import ReadPlan,MAX_TOTAL
    p=ReadPlan.__new__(ReadPlan);p.groups=groups;p.requests=sum(len(g)for _,_,g in groups);p.total=sum(n for _,n,_ in groups)
    if p.requests>32768 or p.total>MAX_TOTAL:raise ValueError('Transferred read plan exceeds budget')
    offset=0;locations={}
    for start,count,rows in groups:
        for address,size in rows:locations[address]=(offset+address-start,size)
        offset+=count
    p.offsets=MappingProxyType(locations)
    if source_requests is not None:p.source_requests=source_requests
    return p
def restore_geometry(state):
    from geometry_stream import Geometry
    transfer=state.pop('_pose_transfer',None)
    g=Geometry.__new__(Geometry);g.__dict__.update(state)
    if transfer is not None:
        from pose_frame import PoseLayout
        g.pose_layout=PoseLayout.__new__(PoseLayout);g.pose_layout.__dict__.update(transfer)
        g.pose_layout.records=g.records;g.pose_layout.read_plan=g.pose_requests
    return g
class PreparationPickler(pickle.Pickler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from live_probe import Reader
        from scene_read_ahead import SceneReadAhead
        self.reader_types=(Reader,SceneReadAhead)
    def persistent_id(self,obj):
        return ('native_reader',)if isinstance(obj,self.reader_types)else None
    def reducer_override(self,obj):
        from geometry_stream import Geometry
        from game_assets import Assets
        from read_batch import ReadPlan
        if isinstance(obj,ReadPlan):return restore_plan,(obj.groups,None)
        if isinstance(obj,Assets):return AssetSnapshot,(str(obj.out),len(obj.meshes),len(obj.textures),obj.missing)
        if isinstance(obj,Geometry):
            state={k:v for k,v in obj.__dict__.items()if k not in('scene_read_plan','prepared_definitions','pose_layout','_particle_metadata','_palette_plan')}
            if getattr(obj,'pose_layout',None) is not None:
                layout=obj.pose_layout
                state['_pose_transfer']={k:v for k,v in layout.__dict__.items()if k not in('records','read_plan')}
            # Pose publication needs full particle descriptors and the binding
            # identities/roles, not thousands of conversion-only dictionaries.
            keys=('id','cell_key','asset','model','skin','generation','parents','effect_target','texture_property','material','switch_gates','native_lights','texture_effect','native_environment_effect')
            state['shapes']=[s if s.get('particles')else{k:s[k]for k in keys if k in s}for s in obj.shapes]
            state['prepared_definitions']={}
            return restore_geometry,(state,)
        return NotImplemented
class PreparationUnpickler(pickle.Unpickler):
    def __init__(self,stream,reader):super().__init__(stream);self.reader=reader
    def persistent_load(self,token):
        if token!=('native_reader',):raise pickle.UnpicklingError('Unknown private preparation token')
        return self.reader
def dumps(obj):
    b=io.BytesIO();PreparationPickler(b,protocol=5).dump(obj);data=b.getvalue()
    if len(data)>MAX_PAYLOAD:raise ValueError('Prepared scene exceeds 64 MiB transfer budget')
    return data
def loads(data,reader):
    if type(data)is not bytes or len(data)>MAX_PAYLOAD:raise ValueError('Invalid prepared scene payload')
    return PreparationUnpickler(io.BytesIO(data),reader).load()
def fingerprint_values(g):
    keys=('scope','signature','records','node_identities','native_switches','actor_owners','cell_root_owners','light_pointers','light_owners','native_attributes','material_values','view_pointers','water_pointers','water_visibility_roots','player_pointers','extra_generations','effect_signature','weapon_state','cell_definitions','shadow_caster_pointers','shadow_distance')
    state={k:getattr(g,k,None)for k in keys};state['flips']=g.material_flips.items
    state['texture_effects']=getattr(getattr(g,'texture_effects',None),'items',{})
    state['native_light_states']=getattr(getattr(g,'pose_layout',None),'native_light_states',{})
    skin_keys={id(v):k for k,v in getattr(g,'skins',{}).items()}
    state['records']=[(p,identity,parents,skin_keys.get(id(skin))if skin is not None else None,owner)for p,identity,parents,skin,owner in(getattr(g,'records',None)or())]
    # Pickle memoization reflects incidental object sharing. Fingerprints must
    # compare native definition values, so unchanged jobs stay small messages.
    memo={}
    scalar_types=(int,float,str,bool,type(None))
    def canonical(value):
        if type(value)in scalar_types:return value
        key=id(value)
        if key in memo:return memo[key]
        result=convert(value);memo[key]=result;return result
    def convert(value):
        if isinstance(value,dict):return [[str(k),canonical(v)]for k,v in sorted(value.items(),key=lambda x:str(x[0]))]
        if isinstance(value,(set,frozenset)):return sorted(canonical(v)for v in value)
        if isinstance(value,(list,tuple)):return [canonical(v)for v in value]
        if isinstance(value,bytes):return value.hex()
        return value
    return canonical(state)
def fingerprint(g):
    return hashlib.sha256(json.dumps(fingerprint_values(g),separators=(',',':'),allow_nan=False).encode()).hexdigest()
def layout_patch(g):
    skin_keys={id(v):k for k,v in g.skins.items()}
    return dict(records=[(p,identity,parents,skin_keys[id(skin)]if skin is not None else None,owner)for p,identity,parents,skin,owner in g.records],
                node_identities=g.node_identities,read_plan=g.pose_requests,switches=g.pose_layout.switches,
                shape_gates={s['id']:s.get('switch_gates',())for s in g.shapes},native_light_states=g.pose_layout.native_light_states,
                shadow_casters=getattr(g,'shadow_caster_pointers',set()),shadow_distance=getattr(g,'shadow_distance',0),view_layout=getattr(g,'view_layout',None),
                prepared_layout={k:v for k,v in g.pose_layout.__dict__.items()if k not in('records','read_plan')})
def apply_layout_patch(g,patch):
    from pose_frame import PoseLayout
    import numpy as np
    rows=patch['records']
    if [(r[0],r[1])for r in rows]!=[(r[0],r[1])for r in g.records]:raise ValueError('Layout patch changed geometry identities')
    old_switches=getattr(getattr(g,'pose_layout',None),'switches',None);new_switches=patch['switches']
    same_switches=old_switches is new_switches or(old_switches is not None and new_switches is not None and old_switches.definitions==new_switches.definitions and all(np.array_equal(getattr(old_switches,k),getattr(new_switches,k))for k in('owners','switches','children')))
    same_shadows=patch.get('shadow_casters',getattr(g,'shadow_caster_pointers',set()))==getattr(g,'shadow_caster_pointers',set())and patch.get('shadow_distance',getattr(g,'shadow_distance',0))==getattr(g,'shadow_distance',0)
    if getattr(g,'pose_layout',None)and same_switches and same_shadows and all(tuple(row[2])==tuple(old[2])and row[4]==old[4]for row,old in zip(rows,g.records))and set(patch.get('native_light_states',{}))==set(g.pose_layout.native_light_states)and patch['read_plan'].groups==g.pose_requests.groups:
        # Native effect-state allocation/parent identity churn does not alter
        # the prepared incidence arrays. Update only expected identities rather
        # than rebuilding hundreds of thousands of edges on the pose thread.
        layout=g.pose_layout
        for p,value in patch['node_identities'].items():
            if g.node_identities.get(p)!=value and p in layout.index:
                index=layout.index[p];layout.node_identities[index]=value;layout.node_known[index]=True
        layout.native_light_states={p:patch['native_light_states'][p]for p in layout.native_light_states}
        layout.expected_light_states=np.asarray(list(layout.native_light_states.values()),dtype='<u4')
        g.node_identities=patch['node_identities'];g.continuity_views={};g.view_layout=patch.get('view_layout')
        for shape in g.shapes:
            p=int(shape['id'],16)
            if p in layout.native_light_states:shape['native_light_state']=layout.native_light_states[p]
        return
    records=[(p,identity,parents,g.skins[key]if key is not None else None,owner)for p,identity,parents,key,owner in rows]
    casters=patch.get('shadow_casters',getattr(g,'shadow_caster_pointers',set()));distance=patch.get('shadow_distance',getattr(g,'shadow_distance',0))
    if 'prepared_layout'in patch:
        # The spawned preparation process already built these incidence and
        # gather arrays. Reconstructing them here can consume several native
        # frames. This follows the existing full/auxiliary transfer ownership
        # rule: only inherited private worker pipes may carry these objects.
        layout=PoseLayout.__new__(PoseLayout);layout.__dict__.update(patch['prepared_layout'])
        layout.records=records;layout.read_plan=patch['read_plan']
        expected=np.asarray([r[1]for r in records],dtype='<u4').reshape(-1,2)
        if layout.shape_indices.shape!=(len(records),)or not np.array_equal(layout.expected,expected)or tuple(layout.pointers[i]for i in layout.shape_indices)!=tuple(r[0]for r in records):
            raise ValueError('Prepared layout does not match geometry identities')
    else:
        layout=PoseLayout(records,g.view_pointers,read_plan=patch['read_plan'],switches=patch['switches'],water_pointers=g.water_pointers,node_identities=patch['node_identities'],player_pointers=g.player_pointers,water_visibility_roots=g.water_visibility_roots,actor_owners=g.actor_owners,native_light_states=patch.get('native_light_states',{}),shadow_casters=casters,shadow_distance=distance,near_pass_camera=getattr(getattr(g,'pose_layout',None),'near_pass_camera',False),cell_root_owners=getattr(g,'cell_root_owners',{}))
    # Commit only after the entire replacement layout has validated.
    g.records=records;g.pose_requests=patch['read_plan'];g.pose_layout=layout;g.node_identities=patch['node_identities'];g.continuity_views={}
    g.shadow_caster_pointers=casters;g.shadow_distance=distance
    g.view_pose_capture=None
    g.view_layout=patch.get('view_layout')
    for shape,row in zip(g.shapes,records):
        shape['parents']=row[2][:-1];shape['switch_gates']=patch['shape_gates'].get(shape['id'],())
        if row[0]in layout.native_light_states:shape['native_light_state']=layout.native_light_states[row[0]]
def identity_patch(old,ready):
    if old is None or set(old.pose_layout.native_light_states)!=set(ready.pose_layout.native_light_states):return None
    return dict(nodes={p:v for p,v in ready.node_identities.items()if old.node_identities.get(p)!=v},
                lights={p:v for p,v in ready.pose_layout.native_light_states.items()if old.pose_layout.native_light_states.get(p)!=v},view_layout=getattr(ready,'view_layout',None))

def apply_identity_patch(g,patch):
    import numpy as np
    if any(p not in g.pose_layout.native_light_states for p in patch['lights']):raise ValueError('Identity patch changed light membership')
    if any(type(v)is not int or not 0<=v<=0xffffffff for v in patch['lights'].values()):raise ValueError('Invalid native light-state address')
    for p,value in patch['nodes'].items():
        if len(value)!=2 or any(type(v)is not int or not 0<=v<=0xffffffff for v in value):raise ValueError('Invalid native node identity patch')
    for p,value in patch['nodes'].items():
        g.node_identities[p]=value
        if p in g.pose_layout.index:
            i=g.pose_layout.index[p];g.pose_layout.node_identities[i]=value;g.pose_layout.node_known[i]=True
    for p,value in patch['lights'].items():
        g.pose_layout.native_light_states[p]=value;g.shapes[g.pose_layout.shape_index[p]]['native_light_state']=value
    g.pose_layout.expected_light_states=np.asarray(list(g.pose_layout.native_light_states.values()),dtype='<u4')
    g.continuity_views={};g.view_layout=patch.get('view_layout')

def lighting_catalog_patch(old,ready):
    """A light-list edit is metadata, not a replacement of every pose array."""
    if not old or old.scene_key!=ready.scene_key or len(old.shapes)!=len(ready.shapes):return None
    def surface(definition):
        result=dict(definition);shading=dict(result.get('shading',{}))
        shading.pop('native_lights',None);shading.pop('native_sun',None);result['shading']=shading;return result
    updates=[]
    for i,(before,after)in enumerate(zip(old.shapes,ready.shapes)):
        if any(before.get(k)!=after.get(k)for k in('id','render_id','model','skin','generation','cell_key')):return None
        if surface(before['prepared'][0])!=surface(after['prepared'][0]):return None
        if before['asset']!=after['asset']or before.get('native_lights')!=after.get('native_lights'):
            updates.append((i,after['asset'],after.get('native_lights')))
    same_records=all((a[0],a[1],a[2],a[4])==(b[0],b[1],b[2],b[4])and ((a[3]is None and b[3]is None)or(a[3]is not None and b[3]is not None and a[3].root==b[3].root and tuple(a[3].bones)==tuple(b[3].bones)))for a,b in zip(old.records,ready.records))
    same_switches=old.pose_layout.switches.definitions==ready.pose_layout.switches.definitions and all(__import__('numpy').array_equal(getattr(old.pose_layout.switches,k),getattr(ready.pose_layout.switches,k))for k in('owners','switches','children'))
    fast=identity_patch(old,ready)if same_records and same_switches else None
    return dict(layout=None if fast is not None else layout_patch(ready),identity=fast,updates=updates,catalog=ready.catalog,catalog_digest=ready.catalog_digest,binding_index=getattr(ready,'binding_index',None),
        signature=None if fast is not None and isinstance(getattr(old,'signature',None),tuple)else ready.signature,membership_hash=ready.membership_hash,cell_definitions=ready.cell_definitions)

def apply_lighting_catalog_patch(g,patch):
    import numpy as np
    # Work against copied metadata and tiny expected-identity arrays. The large
    # immutable incidence/index buffers remain shared until a successful commit.
    target=copy.copy(g);target.shapes=list(g.shapes);target.skins=dict(g.skins);target.node_identities=dict(g.node_identities)
    target.pose_layout=copy.copy(g.pose_layout)
    target.pose_layout.node_identities=g.pose_layout.node_identities.copy();target.pose_layout.node_known=g.pose_layout.node_known.copy()
    target.pose_layout.native_light_states=dict(g.pose_layout.native_light_states)
    changed={i for i,asset,lights in patch['updates']}
    if patch.get('identity')is not None:changed.update(g.pose_layout.shape_index[p]for p in patch['identity']['lights'])
    else:changed.update(range(len(g.shapes)))
    for i in changed:target.shapes[i]=dict(g.shapes[i])
    for i,asset,lights in patch['updates']:
        if not 0<=i<len(target.shapes)or not isinstance(asset,str):raise ValueError('Invalid lighting binding update')
        target.shapes[i]['asset']=asset
        if lights is None:target.shapes[i].pop('native_lights',None)
        else:target.shapes[i]['native_lights']=lights
    assets={target.shapes[i]['id']:asset for i,asset,lights in patch['updates']}
    target.skins={(k[0],k[1],k[2],assets.get(k[0],k[3]),k[4]):skin for k,skin in g.skins.items()}
    if patch.get('identity')is not None:apply_identity_patch(target,patch['identity'])
    else:apply_layout_patch(target,patch['layout'])
    membership={}
    for i,shape in enumerate(target.shapes):
        for light in shape.get('native_lights',()):membership.setdefault(int(light,16),[]).append(i)
    target.native_light_membership={p:np.asarray(v,dtype=np.int32)for p,v in membership.items()}
    for key in('catalog','catalog_digest','membership_hash','cell_definitions'):setattr(target,key,patch[key])
    target.binding_index=patch.get('binding_index')
    if patch['signature']is None:
        entries=list(g.signature[1])
        for i,asset,lights in patch['updates']:
            entry=list(entries[i]);entry[3]=asset;entries[i]=tuple(entry)
        target.signature=(g.signature[0],tuple(entries))
    else:target.signature=patch['signature']
    g.__dict__.update(target.__dict__)


def auxiliary_patch(old,ready,roles):
    """Reuse validated, unchanged resident bindings across an auxiliary edit."""
    if old is None or old.scope!=ready.scope or old.epoch!=ready.epoch:return None
    indices={s['id']:i for i,s in enumerate(old.shapes)};order=[]
    keys=('id','cell_key','asset','model','skin','generation','parents','effect_target','texture_property','material','switch_gates','native_lights','texture_effect','native_environment_effect')
    for shape,row in zip(ready.shapes,ready.records):
        if shape.get('cell_key')in roles:
            i=indices.get(shape['id'])
            if i is None:return None
            before=old.shapes[i];record=old.records[i]
            if any(before.get(k)!=shape.get(k)for k in keys):return None
            if row[:3]!=record[:3]or row[3]is not record[3]or row[4]!=record[4]:return None
            order.append(i)
        else:
            order.append((shape if shape.get('particles')else{k:shape[k]for k in keys if k in shape},row))
    fields=('cell','catalog','catalog_digest','binding_index','last_refresh','last_world_refresh','scene_key','epoch','stream_cells','membership_hash','cell_definitions',
            'terrain_count','scope','cell_generations','generation_counter','extra_generations','effect_signature','weapon_state','material_flips','material_values','texture_effects',
            'native_attributes','native_switches','light_pointers','light_owners','shadow_caster_pointers','shadow_distance','actor_owners','cell_root_owners','water_pointers',
            'water_visibility_roots','player_pointers','view_pointers','view_layout')
    return dict(order=order,state={k:getattr(ready,k)for k in fields},nodes={p:v for p,v in ready.node_identities.items()if old.node_identities.get(p)!=v},
                plan=ready.pose_requests,layout={k:v for k,v in ready.pose_layout.__dict__.items()if k not in('records','read_plan')})


def apply_auxiliary_patch(g,patch):
    from pose_frame import PoseLayout
    import numpy as np
    target=copy.copy(g);target.__dict__.update(patch['state']);target.shapes=[];target.records=[]
    for row in patch['order']:
        if type(row)is int:
            if not 0<=row<len(g.shapes):raise ValueError('Auxiliary patch references a retired binding')
            target.shapes.append(g.shapes[row]);target.records.append(g.records[row])
        else:
            shape,record=row
            if int(shape['id'],16)!=record[0]or tuple(record[1])!=(int(shape['model'],16),int(shape['skin'],16)):raise ValueError('Auxiliary binding identity mismatch')
            target.shapes.append(shape);target.records.append(record)
    target.node_identities={**g.node_identities,**patch['nodes']};target.pose_requests=patch['plan']
    target.pose_layout=PoseLayout.__new__(PoseLayout);target.pose_layout.__dict__.update(patch['layout'])
    target.pose_layout.records=target.records;target.pose_layout.read_plan=target.pose_requests
    target.skins={(s['id'],s['model'],s['skin'],s['asset'],s['generation']):r[3]for s,r in zip(target.shapes,target.records)if r[3]is not None}
    target.signature=(target.scene_key,tuple(((s['generation']+':')if s['generation']else'')+s['id']for s in target.shapes))
    # Match Geometry.refresh's exact signature for later lighting-only deltas.
    target.signature=(target.scene_key,tuple((target.signature[1][i],s['model'],s['skin'],s['asset'],s.get('cell_key')if target.stream_cells else None)for i,s in enumerate(target.shapes)))
    membership={}
    for i,shape in enumerate(target.shapes):
        for light in shape.get('native_lights',()):membership.setdefault(int(light,16),[]).append(i)
    target.native_light_membership={p:np.asarray(v,dtype=np.int32)for p,v in membership.items()}
    target.attribute_captures={};target.continuity_views={};target.view_pose_capture=None;target.topology_dirty=False
    g.__dict__.update(target.__dict__)

def initialize(pid,cancel):
    global _engine,_reader,_cancel,_local_cancel
    from live_probe import Reader
    from async_geometry import AsyncGeometry
    _reader=Reader(pid);_engine=AsyncGeometry(_reader,process_preparation=False);_cancel=cancel;_local_cancel=threading.Event()
    parent=mp.parent_process()
    def watch():
        while True:
            if parent is not None and not parent.is_alive():os._exit(0)
            if _cancel.is_set():_local_cancel.set()
            time.sleep(.005)
    threading.Thread(target=watch,name='preparation-parent-watch',daemon=True).start()
def prepare(base,accepted_fingerprint,force_payload):
    global _last_parts,_last_digest
    _local_cancel.clear()
    if _cancel.is_set():_local_cancel.set()
    if accepted_fingerprint!=_last_digest and accepted_fingerprint in _accepted_history:
        _engine.state,_last_parts=_accepted_history[accepted_fingerprint];_last_digest=accepted_fingerprint
    started=time.perf_counter();old=_engine.state
    context=_engine.context(base)
    seed=_engine.preparation_seed(base,context)
    reuse=bool(seed and seed.get('world_scene'))
    roles=seed['world_scene']['reused_roles']if reuse else set()
    if not(seed and seed.get('world_scene')) and old and old.stream_cells and not base.get('cell_flags',1)&1:
        from loaded_cells import render_cells,loaded_exteriors,retain_prepared_cells
        counts={c['key']:c['instances']for c in old.cell_definitions}
        seed['coverage_cells']=retain_prepared_cells(render_cells(_reader,base),old.stream_cells,loaded_exteriors(_reader,int(base['data'],16)),counts)
    had_coverage=bool(seed and 'coverage_cells'in seed)
    profile=None
    if reuse and os.environ.get('UEMW_PROFILE_PREPARATION','')=='1':
        import cProfile
        profile=cProfile.Profile();profile.enable()
    work_started=time.perf_counter()
    try:ready=_engine.work(base,seed,_local_cancel)
    except ValueError as error:
        if had_coverage and ('budget'in str(error)or'traversal limits'in str(error)):
            seed=_engine.seed();ready=_engine.work(base,seed,_local_cancel)
        else:raise
    work_ms=(time.perf_counter()-work_started)*1000
    if _local_cancel.is_set():ready.close();raise RuntimeError('Prepared process scene was cancelled')
    auxiliary=auxiliary_patch(old,ready,roles)if reuse and not force_payload and accepted_fingerprint==_last_digest else None
    values=[]if auxiliary is not None else fingerprint_values(ready)
    digest=hashlib.sha256(json.dumps(values,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    parts={k:hashlib.sha256(json.dumps(v,separators=(',',':'),allow_nan=False).encode()).hexdigest()for k,v in values}
    changed=[k for k,v in parts.items()if _last_parts.get(k)!=v]
    kind='unchanged'
    catalog_patch=None
    identities=None
    if force_payload or digest!=accepted_fingerprint:
        kind='layout'if not force_payload and accepted_fingerprint==_last_digest and set(changed)<=set(('node_identities','records','native_light_states'))else'full'
        if kind=='layout'and set(changed)<=set(('node_identities','native_light_states')):
            identities=identity_patch(old,ready)
            if identities is not None:kind='identity'
        if kind=='full'and not force_payload and accepted_fingerprint==_last_digest and set(changed)<=set(('signature','cell_definitions','node_identities','records','native_light_states')):
            catalog_patch=lighting_catalog_patch(old,ready)
            if catalog_patch is not None:kind='lighting-layout'
    if auxiliary is not None:
        kind='auxiliary';changed=['auxiliary_topology'];payload=dumps(auxiliary)
        digest=hashlib.sha256(accepted_fingerprint.encode()+payload).hexdigest()
    else:payload=dumps(identities if kind=='identity'else catalog_patch if kind=='lighting-layout'else layout_patch(ready)if kind=='layout'else ready)if kind!='unchanged'else None
    if profile:
        profile.disable()
        os.environ.pop('UEMW_PROFILE_PREPARATION',None)
        from live_probe import ROOT
        profile.dump_stats(str(ROOT/'logs/weapon57-preparation.prof'))
        (ROOT/'logs/weapon57-preparation-sizes.json').write_text(json.dumps({k:len(dumps(v))for k,v in ready.__dict__.items()if k not in('r','scene','assets')},indent=2))
    _last_parts=parts;_last_digest=digest
    _engine.state=ready
    _accepted_history[digest]=(ready,parts)
    while len(_accepted_history)>3:_accepted_history.pop(next(iter(_accepted_history)))
    if old:old.close()
    return dict(protocol=PROTOCOL,version=VERSION,pid=_reader.pid,fingerprint=digest,payload=payload,
                last_refresh=ready.last_refresh,last_world_refresh=ready.last_world_refresh,
                reads=getattr(ready,'preparation_reads',{}),worker_ms=(time.perf_counter()-started)*1000,
                payload_bytes=len(payload)if payload else 0,changed_fields=changed,kind=kind,base_fingerprint=accepted_fingerprint,urgent_world_reuse=reuse,work_ms=work_ms)
