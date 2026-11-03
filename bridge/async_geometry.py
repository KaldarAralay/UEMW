"""Transactional background preparation; the pose owner never converts assets.

One bounded worker owns its archive cursors, reader and writable preparation
state. Only completed, revalidated native scenes replace committed bindings.
An obsolete/failed preparation cannot mutate the active scene or its caches.
"""
import copy
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import re
import threading
import time
from geometry_stream import Geometry,effect_membership,changed_effect_layers,weapon_signature
from live_probe import Reader,SceneReadChanged
from loaded_cells import render_cells,loaded_exteriors,desired_grids,retain_prepared_cells
from scene_reader import scene_roots

CATALOG=re.compile(r'catalog-[0-9a-f]{32}\.json\Z')


class CancelledReader(Reader):
    def __init__(self,pid,cancel):
        self.cancel=cancel
        super().__init__(pid)
    def preparation_turn(self):
        gate=getattr(self,'preparation_gate',None)
        while gate is not None and not gate.is_set():
            if self.cancel.is_set():raise SceneReadChanged('Scene preparation cancelled')
            gate.wait(.01)
    def read(self,address,count):
        self.preparation_turn()
        if self.cancel.is_set():raise SceneReadChanged('Scene preparation cancelled')
        return super().read(address,count)
    def read_many(self,requests):
        self.preparation_turn()
        if self.cancel.is_set():raise SceneReadChanged('Scene preparation cancelled')
        return super().read_many(requests)


class AsyncGeometry:
    def __init__(self,reader,*,geometry_factory=Geometry,reader_factory=CancelledReader,interval=1.,process_preparation=None):
        self.r=reader;self.factory=geometry_factory;self.reader_factory=reader_factory;self.interval=interval
        self.state=None;self.future=None;self.cancel=None;self.request_scope=None
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='native-scene-assets')
        self.history=[];self.started=0.;self.retry_after=0.;self.error='';self.completed=0;self.rejected=0
        self.prepare_ms=0.;self.closed=False
        self.preparation_gate=threading.Event();self.preparation_gate.set()
        self.process_preparation=(isinstance(reader,Reader)and geometry_factory is Geometry and reader_factory is CancelledReader)if process_preparation is None else process_preparation
        self.preparer=None;self.process_fingerprint='';self.process_info={}
        if self.process_preparation:
            import multiprocessing as mp
            from concurrent.futures import ProcessPoolExecutor
            from preparation_process import initialize
            context=mp.get_context('spawn');self.process_cancel=context.Event()
            self.preparer=ProcessPoolExecutor(max_workers=1,mp_context=context,initializer=initialize,initargs=(reader.pid,self.process_cancel))

    def prioritize_pose(self,active):
        if active:self.preparation_gate.clear()
        else:self.preparation_gate.set()

    @property
    def scene_key(self):return self.state.scene_key if self.state else None

    @staticmethod
    def extra_groups(base):
        groups={}
        if base.get('view_roots'):groups['view:first-person']=tuple(base['view_roots'])
        for item in base.get('aux_roots',[]):groups.setdefault('aux:'+item['layer'],[]).append(item['root'])
        return tuple((key,tuple(value))for key,value in groups.items())

    def context(self,base):
        extra=self.extra_groups(base)
        if base.get('cell_flags',1)&1:
            roots=tuple(hex(p)for p in scene_roots(self.r,int(base['cell_ptr'],16)))
            scope=(base['world'],base['data'],base['cell_ptr'],*roots[:2],base.get('player_ref'),base.get('load_serial'))
            key=(base['world'],base['data'],base['cell_ptr'],*roots,*(p for _,rows in extra for p in rows),base.get('player_ref'),base.get('load_serial'))
            cells=[];safe=True
        else:
            cells,safe=render_cells(self.r,base,retained=self.state.stream_cells if self.state else [])
            if self.process_preparation and self.state and self.state.stream_cells:
                counts={c['key']:c['instances']for c in self.state.cell_definitions}
                cells=retain_prepared_cells(cells,self.state.stream_cells,loaded_exteriors(self.r,int(base['data'],16)),counts)
            scope=(base['world'],base['data'],'exterior-stream',base.get('player_ref'),base.get('load_serial'))
            key=(base['world'],base['data'],'exterior-stream',tuple((c['grid'],c['cell_ptr'],tuple(c['roots']))for c in cells),extra,base.get('player_ref'),base.get('load_serial'))
        # This cheap root/child fence also requests newly created effects.
        effects=effect_membership(self.r,base)
        return dict(scope=scope,key=key,cells=cells,safe=safe,extra=extra,effects=effects,weapon=weapon_signature(base))

    def seed(self):
        if self.state is None:return None
        old=self.state
        fields=('scope','signature','scene_key','epoch','catalog','generation_counter')
        result={key:getattr(old,key)for key in fields}
        if hasattr(old,'catalog_digest'):result['catalog_digest']=old.catalog_digest
        if hasattr(old,'binding_index'):result['binding_index']=old.binding_index
        if hasattr(old,'last_world_refresh'):result['last_world_refresh']=old.last_world_refresh
        if hasattr(old,'scene_read_plan'):result['scene_read_plan']=old.scene_read_plan
        if hasattr(old,'prepared_definitions'):result['prepared_definitions']=old.prepared_definitions
        for key in ('cell_generations','extra_generations','skin_sources'):
            result[key]=dict(getattr(old,key))
        result['meshes']=dict(old.assets.meshes);result['textures']=dict(old.assets.textures)
        result['missing']=list(old.assets.missing);result['types']=dict(old.scene.types)
        return result

    def work(self,base,seed,cancel):
        reader=None;ready=None
        try:
            reader=self.reader_factory(self.r.pid,cancel)
            if isinstance(reader,CancelledReader):reader.preparation_gate=self.preparation_gate
            anchor=reader.camera_sample()
            if anchor.get('native_loading')or any(anchor.get(k)!=base.get(k)for k in ('world','data','cell_ptr','player_ref')):
                raise SceneReadChanged('Native scene changed before asset preparation')
            ready=self.factory(reader)
            world_scene=seed.pop('world_scene',None)if seed else None
            coverage_cells=seed.pop('coverage_cells',None)if seed else None
            if seed:
                for key,value in seed.items():
                    if key in ('meshes','textures','missing'):setattr(ready.assets,key,value)
                    elif key=='types':ready.scene.types=value
                    else:setattr(ready,key,value)
            read_ahead=None
            if isinstance(reader,Reader) and isinstance(ready,Geometry):
                from scene_read_ahead import SceneReadAhead
                plan=None if world_scene else getattr(ready,'scene_read_plan',None)
                if seed:
                    current=ready.key(base)
                    scope=(*current[:3],*(current[3:5]if current[2]!='exterior-stream'else()),base.get('player_ref'),base.get('load_serial'))
                    if seed.get('scope')!=scope:plan=None
                read_ahead=SceneReadAhead(reader,plan);ready.scene.r=read_ahead;ready.r=read_ahead;ready.assets.r=read_ahead
            # The job writes at most one new catalog. History eviction belongs
            # to the publishing owner, after adoption, never to this worker.
            if world_scene:
                changed=world_scene['changed']
                auxiliary=ready.scene.collect(roots=[],view_roots=base.get('view_roots',[])if 'view:first-person'in changed else [],
                    aux_roots=[v for v in base.get('aux_roots',[])if 'aux:'+v['layer']in changed])
                prepared={**auxiliary,'shapes':world_scene['shapes']+auxiliary['shapes'],'roots':world_scene['roots']+[p for _,rows in self.extra_groups(base)for p in rows],
                    'node_identities':{**world_scene['node_identities'],**auxiliary.get('node_identities',{})},
                    'actor_owners':{**world_scene.get('actor_owners',{}),**auxiliary.get('actor_owners',{})},
                    'switches':{**world_scene['switches'],**auxiliary.get('switches',{})},
                    'lights':sorted(set(world_scene['lights'])|set(auxiliary.get('lights',[]))),
                    'light_owners':{**world_scene['light_owners'],**auxiliary.get('light_owners',{})},
                    'counts':dict(Counter(world_scene['counts'])+Counter(auxiliary['counts'])),'world_reused':True,'reused_roles':world_scene['reused_roles']}
                ready.refresh(base,prepared_scene=prepared,prepared_cells=world_scene['cells'])
            else:ready.refresh(base,prepared_cells=coverage_cells)if coverage_cells is not None else ready.refresh(base)
            if read_ahead:
                if not world_scene:ready.scene_read_plan=read_ahead.plan()
                read_ahead.stats['definitions_reused']=getattr(ready,'definitions_reused',0)
                ready.preparation_reads=read_ahead.stats;ready.scene.r=reader;ready.r=reader;ready.assets.r=reader
            if cancel.is_set():raise SceneReadChanged('Prepared scene was superseded')
            return ready
        except BaseException:
            if ready:self.discard(ready)
            raise
        finally:
            if reader:reader.close()

    def urgent(self,context):
        old=self.state
        return bool(old and (tuple((layer,value[0][0])for layer,value in old.extra_generations.items())!=context['extra']or old.effect_signature!=context['effects']or old.weapon_state!=context['weapon']))

    def preparation_seed(self,base,context):
        seed=self.seed();old=self.state
        urgent=old and (tuple((layer,value[0][0])for layer,value in old.extra_generations.items())!=context['extra']or old.effect_signature!=context['effects']or old.weapon_state!=context['weapon'])
        # Looking toward another loaded exterior cell must not put a short-lived
        # projectile behind a complete world conversion. Retain only already
        # prepared, still-resident cells for this urgent auxiliary job. Its
        # truthful smaller scene key requests the missing coverage afterwards.
        same_world=old and old.scope==context['scope']and context['safe']and bool(old.stream_cells)==bool(context['cells'])
        if urgent and same_world and isinstance(old,Geometry):
            before={layer:value[0][0]for layer,value in old.extra_generations.items()};after=dict(context['extra'])
            changed={layer for layer in set(before)|set(after)if before.get(layer)!=after.get(layer)}
            changed.update(changed_effect_layers(old.effect_signature,context['effects']))
            if old.weapon_state!=context['weapon']:changed.update(('view:first-person','aux:player'))
            shapes=[dict(s)for s in old.shapes if s.get('cell_key')not in changed]
            counts=Counter(s['type']for s in shapes)
            lights=[p for p in old.light_pointers if not old.light_owners.get(p)or not set(old.light_owners[p]).issubset(changed)]
            retained_cells=copy.deepcopy(old.stream_cells)
            roots=[p for c in retained_cells for p in c['roots']]if retained_cells else[hex(p)for p in scene_roots(self.r,int(base['cell_ptr'],16))]
            seed['world_scene']=dict(shapes=shapes,counts=dict(counts),roots=roots,cells=retained_cells,changed=changed,reused_roles={s.get('cell_key')for s in shapes},node_identities=old.node_identities,switches=old.native_switches,
                                     lights=lights,light_owners={p:old.light_owners.get(p,())for p in lights},actor_owners=getattr(old,'actor_owners',{}))
        return seed

    def start(self,base,context):
        self.cancel=threading.Event();self.request_scope=context['scope'];self.started=time.perf_counter()
        self.request_key=context['key']
        self.request_dynamic=(context['extra'],context['effects'],context['weapon'])
        self.request_urgent=self.urgent(context)
        if self.process_preparation:
            from preparation_process import prepare
            self.cancel=self.process_cancel;self.cancel.clear()
            self.future=self.preparer.submit(prepare,copy.deepcopy(base),self.process_fingerprint,self.state is None)
            return
        seed=self.preparation_seed(base,context)
        self.future=self.executor.submit(self.work,copy.deepcopy(base),seed,self.cancel)

    def discard(self,ready):
        for name in ready.catalog_history:
            if CATALOG.fullmatch(name)and(not self.state or name!=self.state.catalog):
                try:(ready.assets.out/name).unlink(missing_ok=True)
                except PermissionError:pass
                try:(ready.assets.out/('bindings-'+name[8:-5]+'.bin')).unlink(missing_ok=True)
                except PermissionError:pass
        ready.close()

    def compatible(self,ready,base,context):
        if ready.scope!=context['scope']:return False
        # Auxiliary changes are masked before native reads/publication. They
        # cannot starve valid prepared branches by repeatedly cancelling them.
        if ready.stream_cells:
            resident={(c['cell_ptr'],tuple(c['roots']))for c in loaded_exteriors(self.r,int(base['data'],16))}
            if not all((c['cell_ptr'],tuple(c['roots']))in resident for c in ready.stream_cells):return False
        return True

    def finish(self,base,context):
        if not self.future or not self.future.done():return
        future=self.future;self.future=None;cancel=self.cancel;self.cancel=None
        self.prepare_ms=(time.perf_counter()-self.started)*1000
        try:
            ready=future.result()
            if self.process_preparation:
                from preparation_process import PROTOCOL,VERSION,loads,apply_layout_patch,apply_lighting_catalog_patch,apply_identity_patch,apply_auxiliary_patch
                message=ready
                if message.get('protocol')!=PROTOCOL or message.get('version')!=VERSION or message.get('pid')!=self.r.pid:raise ValueError('Invalid preparation worker reply')
                self.process_info={k:message[k]for k in('worker_ms','payload_bytes','changed_fields','kind')}
                self.process_info['urgent_world_reuse']=message.get('urgent_world_reuse',False)
                self.process_info['work_ms']=message.get('work_ms',0)
                if message['kind']in('layout','lighting-layout','identity','auxiliary'):
                    if cancel.is_set()or self.state is None or message['base_fingerprint']!=self.process_fingerprint or not self.compatible(self.state,base,context):raise RuntimeError('Layout patch no longer matches native scope')
                    began=time.perf_counter();decoded=loads(message['payload'],self.r);self.process_info['transfer_decode_ms']=(time.perf_counter()-began)*1000
                    apply=apply_auxiliary_patch if message['kind']=='auxiliary'else apply_identity_patch if message['kind']=='identity'else apply_lighting_catalog_patch if message['kind']=='lighting-layout'else apply_layout_patch
                    began=time.perf_counter();apply(self.state,decoded);self.process_info['layout_apply_ms']=(time.perf_counter()-began)*1000
                    self.process_fingerprint=message['fingerprint']
                    self.state.last_refresh=message['last_refresh'];self.state.last_world_refresh=message['last_world_refresh'];self.state.preparation_reads=message['reads'];self.state.topology_dirty=False
                    if message['kind']in('lighting-layout','auxiliary'):self.remember_catalog(self.state)
                    self.completed+=1;self.error='';return
                if message['payload']is None:
                    if cancel.is_set()or self.state is None or message['fingerprint']!=self.process_fingerprint or not self.compatible(self.state,base,context):raise RuntimeError('Unchanged preparation reply no longer matches native scope')
                    self.state.last_refresh=message['last_refresh'];self.state.last_world_refresh=message['last_world_refresh'];self.state.preparation_reads=message['reads'];self.state.topology_dirty=False
                    self.completed+=1;self.error='';return
                ready=loads(message['payload'],self.r)
        except (OSError,ValueError,RuntimeError)as error:
            self.error=str(error);self.retry_after=0. if cancel.is_set()else time.perf_counter()+.5;return
        try:valid=not cancel.is_set()and self.compatible(ready,base,context)
        except (OSError,ValueError,RuntimeError):valid=False
        if not valid:
            self.rejected+=1
            if self.process_preparation:ready.close()
            else:self.discard(ready)
            return
        old=self.state
        ready.r=self.r;ready.scene.r=self.r
        if old and getattr(old,'epoch',None)==getattr(ready,'epoch',None):
            selection=getattr(old,'environment_light_selection',None)
            if selection is not None:ready.environment_light_selection=selection
        self.state=ready;self.completed+=1;self.error=''
        if self.process_preparation:self.process_fingerprint=message['fingerprint']
        self.remember_catalog(ready)
        if old:
            # Releasing a large retired graph is also preparation work. Keep
            # its object destruction out of the fresh-pose publishing path.
            if isinstance(old,Geometry):self.executor.submit(old.close)
            else:old.close()

    def remember_catalog(self,ready):
        if not self.history or self.history[-1]!=ready.catalog:self.history.append(ready.catalog)
        while len(self.history)>8:
            name=self.history.pop(0)
            if CATALOG.fullmatch(name):
                try:(ready.assets.out/name).unlink(missing_ok=True)
                except PermissionError:pass
    def diagnostics(self):
        return dict(pending=self.future is not None,completed=self.completed,rejected=self.rejected,
                    last_prepare_ms=round(self.prepare_ms,3),pending_ms=round((time.perf_counter()-self.started)*1000,3)if self.future else 0.,last_error=self.error,
                    read_ahead=getattr(self.state,'preparation_reads',{}),backend='process-v1'if self.process_preparation else'thread',worker=self.process_info)

    def snapshot(self,base):
        context=self.context(base)
        # A failed asset preparation only backs off that exact request. A new
        # native effect/equipment/world identity must not inherit its delay.
        if self.request_scope!=context['scope']or getattr(self,'request_key',None)!=context['key']or getattr(self,'request_dynamic',None)!=(context['extra'],context['effects'],context['weapon']):self.retry_after=0.
        weapon_changed=getattr(self,'request_dynamic',None)is not None and self.request_dynamic[2]!=context['weapon']
        if self.future and(self.request_scope!=context['scope']or weapon_changed or(not getattr(self,'request_urgent',False)and getattr(self,'request_dynamic',None)!=(context['extra'],context['effects'],context['weapon']))):self.cancel.set()
        self.finish(base,context)
        old=self.state;now=time.perf_counter()
        old_extra=tuple((layer,value[0][0])for layer,value in old.extra_generations.items())if old else ()
        needs=old is None or old.scope!=context['scope']or old.scene_key!=context['key']or not context['safe']or old_extra!=context['extra']or old.effect_signature!=context['effects']or old.weapon_state!=context['weapon']or getattr(old,'topology_dirty',False)or now-getattr(old,'last_world_refresh',old.last_refresh)>=self.interval
        if needs and self.future is None and now>=self.retry_after:self.start(base,context)
        info=self.diagnostics()
        if old is None or old.scope!=context['scope']or not context['safe']:
            info['waiting_for']='initial_scene'if old is None else'scope_changed'if old.scope!=context['scope']else'retired_cell_roots'if not context['safe']else'auxiliary_roots_changed'
            return {**base,'status':'preparing_scene','preparation':info}
        # Keep sampling native transforms for valid retained bindings while the
        # worker discovers/decodes additional cells. No old pose is relabeled.
        if old.stream_cells:old.cell=base['cell_ptr']
        excluded=set()
        if old_extra!=context['extra']:
            before=dict(old_extra);after=dict(context['extra'])
            excluded.update(layer for layer in before if before[layer]!=after.get(layer))
        excluded.update(changed_effect_layers(old.effect_signature,context['effects']))
        if base.get('first_person_active')and not base.get('first_person_items_active',True):excluded.add('view:first-person')
        if old.weapon_state!=context['weapon']:excluded.update(('view:first-person','aux:player'))
        try:packet=old.snapshot_retained(base,excluded)if excluded else old.snapshot(base,prepared=True)
        except SceneReadChanged:
            # Changed equipment/switch topology needs a new catalog immediately,
            # rather than waiting for the periodic discovery interval.
            old.last_refresh=0.;self.retry_after=0.
            if self.future is None:self.start(base,context)
            raise
        missing=desired_grids(base,preload=False)-{tuple(c['grid'])for c in old.stream_cells}if old.stream_cells else set()
        packet['preparation']={**info,'missing_visible_cells':[list(v)for v in sorted(missing)]}
        return packet

    def invalidate_scene(self):
        if self.cancel:self.cancel.set()
        if self.state:self.state.close();self.state=None

    def close(self):
        if self.closed:return
        self.closed=True
        self.preparation_gate.set()
        if self.cancel:self.cancel.set()
        self.executor.shutdown(wait=True,cancel_futures=False)
        if self.preparer:self.preparer.shutdown(wait=True,cancel_futures=False)
        if self.future:
            try:
                result=self.future.result()
                if not self.process_preparation:self.discard(result)
            except (OSError,ValueError,RuntimeError):pass
            self.future=None
        if self.state:self.state.close();self.state=None
