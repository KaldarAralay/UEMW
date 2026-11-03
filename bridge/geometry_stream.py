"""Version 1 live state producer with an additive render-geometry extension."""
import argparse
import base64
import copy
import hashlib
import json
import os
import struct
import sys
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from live_probe import ROOT, Reader, snapshot_lease,SceneReadChanged
from scene_reader import SceneReader,scene_roots
from game_assets import Assets
from skin_math import Skin, matrix
from supported_scenes import supported
from frame_transport import FrameStore
from render_culling import View
from pose_frame import PoseLayout,PoseFrame
from loaded_cells import render_cells,desired_grids
from render_sample import RenderSample
from native_particles import capture as capture_particles,expand as particle_quads
from native_environment import capture as capture_environment,roles as environment_roles
from native_materials import discover as discover_flip,capture as capture_materials,FlipCapture
from material_values import discover as discover_material,capture as capture_values
from native_attributes import discover as discover_attributes,capture as capture_attributes,AttributeCapture

MAX_PACKET_BYTES=1024*1024


def effect_membership(reader,base):
    result=[]
    for item in base.get('aux_roots',[]):
        if item['layer']not in ('world_effect','projectile'):continue
        ptr=int(item['root'],16);header=reader.read(ptr+0x94,12);storage,capacity,end=struct.unpack('<3I',header)
        if end>capacity or capacity>4096:raise SceneReadChanged('Invalid native effect child array')
        result.append((item['layer'],item['root'],item.get('target_ref'),header,reader.read(storage,end*4)if storage and end else b''))
    return tuple(result)


def changed_effect_layers(before,after):
    roles={row[0]for row in(*before,*after)}
    return {'aux:'+role for role in roles if tuple(r for r in before if r[0]==role)!=tuple(r for r in after if r[0]==role)}


class Geometry:
    def __init__(self,reader):
        self.r=reader
        self.scene=SceneReader(reader)
        self.assets=Assets(reader)
        self.shapes=[]
        self.light_pointers=[]
        self.skins={}
        self.skin_sources={}
        self.cell=None
        self.catalog='';self.catalog_digest=''
        self.signature=None
        self.last_refresh=0
        self.last_world_refresh=0
        self.inventory={}
        self.scene_key=None
        self.epoch=''
        self.catalog_history=deque()
        self.transform_cache={}
        self.stream_cells=[]
        self.pose_requests=None
        self.membership_hash=''
        self.cell_definitions=[]
        self.records=[];self.terrain_count=0;self.view_pointers=set()
        self.refresh_future=None;self.refresh_key=None;self.executor=None
        self.scope=None;self.cell_generations={};self.generation_counter=0
        self.extra_generations={};self.effect_signature=();self.weapon_state=None
        self.material_flips=FlipCapture({})
        self.material_values={}
        self.native_attributes={};self.attribute_captures={}
        self.node_identities={};self.native_switches={};self.light_owners={};self.continuity_views={};self.topology_dirty=False
        self.cell_root_owners={}
        self.prepared_definitions={};self.definitions_reused=0

    def close(self):
        if self.executor:self.executor.shutdown(wait=True,cancel_futures=True)
        self.assets.close()

    def invalidate_scene(self):
        self.shapes=[];self.skins={};self.skin_sources={};self.cell=None;self.signature=None
        self.light_pointers=[]
        self.scene_key=None;self.epoch='';self.catalog='';self.catalog_digest='';self.last_refresh=0
        self.inventory={};self.assets.reset_scene()
        self.transform_cache={}
        self.stream_cells=[]
        self.pose_requests=None
        self.membership_hash=''
        self.cell_definitions=[]
        self.records=[];self.terrain_count=0;self.view_pointers=set()
        self.scope=None;self.cell_generations={}
        self.cell_root_owners={}
        self.extra_generations={};self.effect_signature=();self.weapon_state=None
        self.material_flips=FlipCapture({})
        self.material_values={}
        self.native_attributes={};self.attribute_captures={}
        self.node_identities={};self.native_switches={};self.light_owners={};self.continuity_views={};self.topology_dirty=False
        self.prepared_definitions={};self.definitions_reused=0

    def extra_groups(self,base):
        groups={}
        if base.get('view_roots'):groups['view:first-person']=tuple(base['view_roots'])
        for item in base.get('aux_roots',[]):groups.setdefault('aux:'+item['layer'],[]).append(item['root'])
        return tuple((key,tuple(value))for key,value in groups.items())

    def effects_state(self,base):
        return effect_membership(self.r,base)

    def key(self,base,cells=None):
        if not base.get('cell_flags',1)&1:
            if cells is None:cells=render_cells(self.r,base)
            return (base['world'],base['data'],'exterior-stream',tuple((c['grid'],c['cell_ptr'],tuple(c['roots'])) for c in cells),self.extra_groups(base),base.get('player_ref'),base.get('load_serial'))
        cell=int(base['cell_ptr'],16)
        return (base['world'],base['data'],base['cell_ptr'],*(hex(p)for p in scene_roots(self.r,cell)),*(ptr for _,roots in self.extra_groups(base)for ptr in roots),base.get('player_ref'),base.get('load_serial'))

    def refresh(self,base,prepared_scene=None,prepared_cells=None):
        cells=prepared_cells if prepared_cells is not None else render_cells(self.r,base) if not base.get('cell_flags',1)&1 else []
        if prepared_cells is not None and cells:
            from loaded_cells import loaded_exteriors
            resident={(c['cell_ptr'],tuple(c['roots']))for c in loaded_exteriors(self.r,int(base['data'],16))}
            if not all((c['cell_ptr'],tuple(c['roots']))in resident for c in cells):raise SceneReadChanged('Retained native world roots retired before effect preparation')
        views=list(base.get('view_roots',()))
        aux=list(base.get('aux_roots',[]));extra=self.extra_groups(base);effects=self.effects_state(base)
        scene=prepared_scene if prepared_scene is not None else self.scene.collect(cells=cells or None,view_roots=views,aux_roots=aux) if views or aux else self.scene.collect(cells=cells) if cells else self.scene.collect()
        if prepared_scene is not None and cells and scene['roots']!=[p for c in cells for p in c['roots']]+[ptr for _,roots in extra for ptr in roots]:
            raise SceneReadChanged('Prepared topology belongs to retired roots')
        if not scene['shapes']:raise RuntimeError('Original scene geometry is still loading')
        if len(scene['shapes'])>16384:raise ValueError('Native scene exceeds the 16384-mesh resource budget')
        key=((base['world'],base['data'],'exterior-stream',tuple((c['grid'],c['cell_ptr'],tuple(c['roots'])) for c in cells),extra) if cells else (base['world'],base['data'],scene['cell_ptr'],*scene['roots']))+(base.get('player_ref'),base.get('load_serial'))
        scope=((base['world'],base['data'],'exterior-stream') if cells else (base['world'],base['data'],scene['cell_ptr'],*scene['roots'][:2]))+(base.get('player_ref'),base.get('load_serial'))
        if scene['cell_ptr']!=base['cell_ptr']:
            if prepared_scene is not None and cells and any(c['cell_ptr']==scene['cell_ptr']for c in cells):
                scene={**scene,'cell_ptr':base['cell_ptr'],'cell':base['cell']}
            else:raise SceneReadChanged('Active cell changed during topology discovery')
        if key!=self.key(base,cells=cells if prepared_cells is not None else None):raise SceneReadChanged('Scene roots changed during traversal')
        if self.scope!=scope:
            self.invalidate_scene();self.scope=scope;self.epoch=str(uuid.uuid4())
        self.scene_key=key
        generations=self.assign_cells(cells)
        extra_generations={}
        for layer,roots in extra:
            identity=(roots,tuple(e for e in effects if 'aux:'+e[0]==layer)if layer in ('aux:world_effect','aux:projectile')else ())
            old=self.extra_generations.get(layer)
            if old and old[0]==identity:extra_generations[layer]=old
            else:
                self.generation_counter+=1;extra_generations[layer]=(identity,f'a{self.generation_counter:08x}')
        self.extra_generations=extra_generations;self.effect_signature=effects
        self.weapon_state=weapon_signature(base)
        effect_targets={int(v['root'],16):v['target_ref']for v in aux if v.get('target_ref')}
        for shape in scene['shapes']:
            shape.pop('effect_target',None)
            for node in(*shape.get('parents',()),int(shape['id'],16)):
                if node in effect_targets:shape['effect_target']=effect_targets[node]
            layer=shape.get('cell_key');gen=extra_generations[layer][1]if layer in extra_generations else generations[layer][1] if cells else ''
            shape['generation']=gen;shape['render_id']=gen+':'+shape['id'] if gen else shape['id']
        self.assets.begin_refresh()
        definitions={}
        flips={};properties={};values={};value_properties={};attributes={}
        reused=[s for s in scene['shapes']if scene.get('world_reused')and s.get('prepared')and s.get('cell_key')in scene.get('reused_roles',())]
        bases={(s['prepared'][0]['file'],s['prepared'][0]['texture'],s['prepared'][0].get('alpha_mode','opaque'))for s in reused}
        if bases:
            self.assets.used_meshes.update(k for k,v in self.assets.meshes.items()if(v['file'],v['texture'],v.get('alpha_mode','opaque'))in bases)
            for s in reused:
                self.assets.used_textures.add(s['texture'])
                if s['prepared'][1]:self.assets.used_textures.update(s['prepared'][1]['names'])
        source_roles=environment_roles(self.r,base)
        cancellation=getattr(self.r,'cancel',None)
        previous_definitions=self.prepared_definitions;next_definitions={};definition_bytes=0;self.definitions_reused=0
        recorder=self.r if hasattr(self.r,'begin_definition')else None
        for shape in scene['shapes']:
            if cancellation is not None and cancellation.is_set():raise SceneReadChanged('Scene preparation cancelled during asset conversion')
            if scene.get('world_reused')and shape.get('prepared')and shape.get('cell_key')in scene.get('reused_roles',()):
                definition,flip,material,mutable=shape['prepared'];definitions[shape['asset']]=definition
                if flip:flips[flip['id']]=flip
                if material:values[material['id']]=material
                if mutable:attributes[mutable['shape']]=mutable
                if shape['render_id']in previous_definitions:next_definitions[shape['render_id']]=previous_definitions[shape['render_id']]
                continue
            # Only rigid world definitions qualify. Native poses, mutable sky,
            # water, particles, skins and first-person animation keep live lanes.
            eligible=recorder and not shape.get('particles')and shape.get('skin')=='0x0'and shape.get('controller','0x0')=='0x0'and not shape.get('cell_key','').startswith(('aux:','view:'))
            descriptor=tuple(shape.get(k)for k in('model','skin','controller','texture','texture_property','material','color_mode','lighting_mode','alpha_mode','blend_native_opacity','vertex_count','triangle_count','generation','cell_key','terrain','native_lights','native_sun'))+(tuple(shape['transform']['position'])if shape.get('terrain')else None,)
            cached=previous_definitions.get(shape['render_id'])if eligible else None
            if cached and cached[0]==descriptor and recorder.matches(cached[3]):
                _,tag,prepared,dependencies=cached;definition,flip,material,mutable=prepared
                definitions[tag]=definition;shape['asset']=tag;shape['prepared']=prepared
                if flip:flips[flip['id']]=flip;self.assets.used_textures.update(flip['names'])
                if material:values[material['id']]=material
                if mutable:attributes[mutable['shape']]=mutable
                bases.add((definition['file'],definition['texture'],definition.get('alpha_mode','opaque')));self.assets.used_textures.add(shape['texture'])
                next_definitions[shape['render_id']]=cached;self.definitions_reused+=1;definition_bytes+=sum(n for _,n,_ in dependencies)
                continue
            if eligible:
                recorder.begin_definition()
                # Assets caches shared static material colours within a job.
                # Every reusable shape still fences the source colour bytes.
                if int(shape.get('material','0x0'),16):recorder.read(int(shape['material'],16)+0x28,0x30)
            prop=int(shape.get('texture_property','0x0'),16)
            group=(prop,shape['generation'])
            # A reusable definition must record its own complete property
            # dependencies, even when another shape uses the same property.
            if eligible or group not in properties:properties[group]=discover_flip(self.r,prop,shape['generation'])
            flip=properties[group]
            source={**shape,'texture':flip['names'][0]}if flip else dict(shape)
            material_key=(shape.get('material'),shape['generation'],shape.get('cell_key',''),shape.get('color_mode',2),shape['model'])
            if eligible or material_key not in value_properties:value_properties[material_key]=discover_material(self.r,shape)
            material=value_properties[material_key]
            if material:source['material_state']=material['id'];values[material['id']]=material
            mutable=discover_attributes(self.r,shape)
            if mutable:
                attributes[mutable['shape']]=mutable
                source['dynamic_attributes']=dict(positions=True,colors=mutable['colors'],uvs=mutable['uvs'],morph=mutable['morph'])
            definition=self.assets.mesh(source)
            if material:definition={**definition,'material_state':material['id']}
            if mutable:definition={**definition,'dynamic_attributes':source['dynamic_attributes']}
            if flip:
                flips[flip['id']]=flip;files=[]
                for name in flip['names']:
                    self.assets.used_textures.add(name);files.append(self.assets.texture(name))
                if any(not name for name in files):raise ValueError('Native flip palette texture is missing')
                definition={**definition,'texture_animation':dict(id=flip['id'],frames=files)}
            shading={**definition.get('shading',dict(lit=False,emissive=[0.,0.,0.],fog=True,sky=False))}
            layer=shape.get('cell_key','')
            if shape.get('particles') or layer in ('aux:sky','aux:weather','aux:world_effect'):shading['lit']=False
            if layer=='aux:sky':shading.update(fog=False,background=True)
            if layer=='aux:water':shading['water']=True
            if layer=='view:first-person':shading['first_person']=True
            if layer=='aux:weather'and shape.get('texture','').replace('\\','/').rsplit('/',1)[-1].lower()=='tx_raindrop_01.tga':shading['rain']=True
            if shape.get('particles'):shading['native_particle']=True
            if 'native_lights'in shape:shading.update(native_lights=sorted(set(shape['native_lights'])),native_sun=shape['native_sun'])
            if source_roles.get(int(shape['id'],16))=='atmosphere':shading['sky']=True
            definition={**definition,'shading':shading}
            if shape['skin']!='0x0':
                source_key=(shape['id'],shape['model'],shape['skin'],shape['generation'])
                skin=self.skin_sources.get(source_key)
                if skin is None:skin=Skin(self.r,shape);self.skin_sources[source_key]=skin
                shape['skin_source']=skin
                if not mutable:definition={**definition,'skin_file':skin.export_weights(self.assets.out),'skin_bones':len(skin.bones)+1}
            digest=hashlib.sha256((definition['asset']+'|'+definition['texture']+'|'+definition.get('alpha_mode','opaque')+'|'+str(definition.get('blend_native_opacity',True))+'|'+definition.get('skin_file','')+'|'+json.dumps(shading,sort_keys=True,separators=(',',':'))+'|'+json.dumps(definition.get('texture_animation'),sort_keys=True,separators=(',',':'))+'|'+definition.get('material_state','')+'|'+json.dumps(definition.get('dynamic_attributes'),sort_keys=True,separators=(',',':'))+'|'+json.dumps(definition.get('terrain_tile'),separators=(',',':'))).encode('ascii')).digest()
            tag=base64.b32encode(digest).rstrip(b'=').decode('ascii').lower()
            definitions[tag]=definition
            shape['asset']=tag
            shape['prepared']=(definition,flip,material,mutable)
            if eligible:
                dependencies=recorder.end_definition()
                size=sum(n for _,n,_ in dependencies)if dependencies else 0
                if dependencies and definition_bytes+size<=16*1024*1024:
                    next_definitions[shape['render_id']]=(descriptor,tag,shape['prepared'],dependencies);definition_bytes+=size
        self.prepared_definitions=next_definitions
        if bases:self.assets.used_meshes.update(k for k,v in self.assets.meshes.items()if(v['file'],v['texture'],v.get('alpha_mode','opaque'))in bases)
        self.assets.trim_cache()
        if cancellation is not None and cancellation.is_set():raise SceneReadChanged('Scene preparation cancelled before catalog conversion')
        signature=(key,tuple((s['render_id'],s['model'],s['skin'],s['asset'],s.get('cell_key')if cells else None) for s in scene['shapes']))
        if signature!=self.signature:
            filename='catalog-'+uuid.uuid4().hex+'.json'
            catalog={'format':'uemw.assets','version':1,'cell':scene['cell'],'meshes':definitions,
                     'cells':[{k:c[k]for k in ('key','grid')}for c in cells],
                     'bindings':[dict(id=s['render_id'],source_id=s['id'],asset=s['asset'],**({'effect_target':s['effect_target']}if s.get('effect_target')else{}),**({'cell_key':s['cell_key']}if s.get('cell_key')in generations else {}),**({'layer':s['cell_key'].split(':',1)[1]}if s.get('cell_key')in extra_generations else {}))for s in scene['shapes']],
                     'unsupported':{'particles':sum(count for kind,count in scene['counts'].items()if 'Particles'in kind)-scene['counts'].get('rendered_particle_systems',0),
                                    'particle_limitations':'billboard quads; quaternion rotation, animated atlas UVs and blend factors outside the documented common RGB policies are deferred',
                                    'blend_approximations':[dict(node=s['id'],**s['blend_fallback'])for s in scene['shapes']if s.get('blend_fallback')],
                                    'alpha_test_limitations':'masked cutoff is approximate; combined alpha testing/blending is not yet mirrored',
                                    'unhandled_geometry_types':{kind:count for kind,count in scene['counts'].items()if kind in ('NiTriStrips','NiLines')},
                                    'traversal_errors':scene['errors'],'missing_textures':self.assets.missing,
                                    'invalid_native_normals':[dict(asset=tag,source_texture=value['source_texture'])for tag,value in definitions.items()if value.get('normal_source')=='generated_invalid_native'],
                                    'lighting':'native resolved sun/ambient/fog and bounded local lights; per-object light selection/specular/shadows are approximate'}}
            catalog_bytes=json.dumps(catalog,separators=(',',':')).encode('utf-8')
            (self.assets.out/filename).write_bytes(catalog_bytes)
            self.catalog_digest=hashlib.md5(catalog_bytes).hexdigest()
            self.catalog=filename
            self.signature=signature
            self.catalog_history.append(filename)
            while len(self.catalog_history)>8:
                (self.assets.out/self.catalog_history.popleft()).unlink(missing_ok=True)
        valid=set()
        for shape in scene['shapes']:
            if shape['skin']!='0x0':
                key=(shape['id'],shape['model'],shape['skin'],shape['asset'],shape['generation'])
                valid.add(key)
                if key not in self.skins:
                    self.skins[key]=shape['skin_source']
        self.skins={k:v for k,v in self.skins.items() if k in valid}
        self.skin_sources={(s['id'],s['model'],s['skin'],s['generation']):s['skin_source']for s in scene['shapes']if 'skin_source'in s}
        self.shapes=scene['shapes']
        self.view_pose_capture=None
        self.shadow_caster_pointers=set()
        for shape in self.shapes:
            definition=shape['prepared'][0];shading=definition.get('shading',{})
            if shading.get('lit') and not any(shading.get(k)for k in('sky','background','water','first_person','native_particle')) and definition.get('alpha_mode','opaque')in('opaque','masked','translucent'):
                self.shadow_caster_pointers.add(int(shape['id'],16))
        self.shadow_distance=8192 if not base.get('cell_flags',1)&1 else 4096
        light_membership={}
        for index,shape in enumerate(self.shapes):
            for light in shape.get('native_lights',()):light_membership.setdefault(int(light,16),[]).append(index)
        self.native_light_membership={p:np.asarray(rows,dtype=np.int32)for p,rows in light_membership.items()}
        self.light_pointers=scene.get('lights',[])
        self.light_owners=scene.get('light_owners',{});self.node_identities=scene.get('node_identities',{})
        self.native_switches=scene.get('switches',{});self.actor_owners=scene.get('actor_owners',{});self.topology_dirty=False;self.continuity_views={}
        self.cell_root_owners=scene.get('cell_root_owners',{})
        self.material_flips=FlipCapture(flips)
        self.material_values=values
        self.native_attributes=attributes
        self.attribute_captures={}
        self.membership_hash=hashlib.md5('|'.join(sorted(s['render_id']+':'+s['asset'] for s in self.shapes)).encode('ascii')).hexdigest()
        if cancellation is not None and cancellation.is_set():raise SceneReadChanged('Scene preparation cancelled before pose layout')
        nodes=set();shape_nodes={int(s['id'],16) for s in self.shapes}
        for shape in self.shapes:
            shape['visibility_nodes']=(*shape.get('parents',()),int(shape['id'],16))
            nodes.update(shape['visibility_nodes'])
        for skin in self.skins.values():nodes.update((skin.root,*skin.bones))
        from read_batch import ReadPlan
        from native_switches import SwitchLayout
        switches=SwitchLayout(self.shapes,scene.get('switches',{}))
        requests={ptr:0xAC if ptr in shape_nodes else 0x74 for ptr in nodes}
        for ptr,size in switches.requests():requests[ptr]=max(requests.get(ptr,0),size)
        for owner in self.actor_owners.values():requests[owner['reference']]=0x50
        for checks in self.cell_root_owners.values():
            for address,pointer in checks:requests[address]=max(4,requests.get(address,0))
        self.pose_requests=ReadPlan(sorted(requests.items()))
        owners={c['key']:index for index,c in enumerate(cells)}
        self.records=[(int(s['id'],16),(int(s['model'],16),int(s['skin'],16)),s['visibility_nodes'],
            self.skins.get((s['id'],s['model'],s['skin'],s['asset'],s['generation'])),owners.get(s.get('cell_key')))for s in self.shapes]
        self.terrain_count=sum(bool(s.get('terrain'))for s in self.shapes)
        # The native near pass can retain detached weapon/body branches after
        # sheathing. Gate the entire pass rather than only the current item root.
        self.view_pointers={int(s['id'],16)for s in self.shapes if s.get('cell_key')=='view:first-person'}
        self.water_pointers={int(s['id'],16)for s in self.shapes if s.get('cell_key')in('aux:water','aux:ripple')}
        self.water_visibility_roots={int(a['root'],16)for a in aux if a['layer']in('water','ripple')}
        self.player_pointers={int(s['id'],16)for s in self.shapes if s.get('cell_key')=='aux:player'and not s.get('effect_target')}
        self.pose_layout=PoseLayout(self.records,self.view_pointers,read_plan=self.pose_requests,switches=switches,water_pointers=self.water_pointers,node_identities=self.node_identities,player_pointers=self.player_pointers,water_visibility_roots=self.water_visibility_roots,actor_owners=self.actor_owners,native_light_states={int(s['id'],16):s['native_light_state']for s in self.shapes if'native_light_state'in s},shadow_casters=self.shadow_caster_pointers,shadow_distance=self.shadow_distance,near_pass_camera=bool(int(base.get('first_person_camera_ptr','0x0'),16)),cell_root_owners=self.cell_root_owners)
        self.cell_definitions=[]
        for c in cells:
            members=[s for s in self.shapes if s['cell_key']==c['key']]
            self.cell_definitions.append(dict(key=c['key'],grid=c['grid'],cell_ptr=c['cell_ptr'],roots=c['roots'],
                instances=len(members),terrain_instances=sum(bool(s.get('terrain'))for s in members),
                generation=generations[c['key']][1],membership_md5=hashlib.md5('|'.join(sorted(s['render_id']+':'+s['asset']for s in members)).encode('ascii')).hexdigest()))
        current_ids={int(s['id'],16) for s in self.shapes}
        self.transform_cache={ptr:v for ptr,v in self.transform_cache.items() if ptr in current_ids}
        self.cell=scene['cell_ptr']
        self.stream_cells=cells
        self.inventory={k:v for k,v in scene.items() if k not in ('shapes','errors')}
        self.last_refresh=time.perf_counter()
        if not scene.get('world_reused'):self.last_world_refresh=self.last_refresh
        from native_first_person import export
        self.view_layout=export(self,base)

    def assign_cells(self,cells):
        """Keep IDs for retained roots; never reuse a retired cell generation."""
        generations={}
        for c in cells:
            identity=(c['cell_ptr'],tuple(c['roots']));old=self.cell_generations.get(c['key'])
            if old and old[0]==identity:generations[c['key']]=old
            else:
                self.generation_counter+=1;generations[c['key']]=(identity,f'c{self.generation_counter:08x}')
        self.cell_generations=generations
        return generations

    def snapshot_retained(self,base,excluded):
        """Fresh native poses for unaffected bindings; no old pose is reused."""
        key=tuple(sorted(excluded));view=self.continuity_views.get(key)
        if view is None:
            view=copy.copy(self)
            selected=[i for i,s in enumerate(self.shapes)if s.get('cell_key')not in excluded]
            if not selected:raise SceneReadChanged('No unaffected native bindings remain')
            view.shapes=[self.shapes[i]for i in selected];view.records=[self.records[i]for i in selected]
            view.view_pose_capture=None
            # A retained view has its own pose row numbering. Never index its
            # smaller visibility vector using the full catalog's light rows.
            membership={}
            for index,shape in enumerate(view.shapes):
                for light in shape.get('native_lights',()):membership.setdefault(int(light,16),[]).append(index)
            view.native_light_membership={p:np.asarray(rows,dtype=np.int32)for p,rows in membership.items()}
            pointers={r[0]for r in view.records};properties={int(s.get('texture_property','0x0'),16)for s in view.shapes}
            materials={int(s.get('material','0x0'),16)for s in view.shapes}
            view.material_flips=self.material_flips.subset(properties)
            view.material_values={k:v for k,v in self.material_values.items()if v['property']in materials}
            view.native_attributes={p:v for p,v in self.native_attributes.items()if p in pointers};view.attribute_captures={}
            view.skins={k:v for k,v in self.skins.items()if int(k[0],16)in pointers}
            view.light_pointers=[p for p in self.light_pointers if not self.light_owners.get(p)or not set(self.light_owners[p]).issubset(excluded)]
            from read_batch import ReadPlan
            from native_switches import SwitchLayout
            nodes=set();shape_nodes={r[0]for r in view.records}
            for ptr,identity,parents,skin,owner in view.records:
                nodes.update((*parents,ptr))
                if skin is not None:nodes.update((skin.root,*skin.bones))
            switches=SwitchLayout(view.shapes,self.native_switches)
            requests={p:0xac if p in shape_nodes else 0x74 for p in nodes}
            for p,n in switches.requests():requests[p]=max(n,requests.get(p,0))
            for p,owner in getattr(self,'actor_owners',{}).items():
                if p in nodes:requests[owner['reference']]=0x50
            for p,checks in getattr(self,'cell_root_owners',{}).items():
                if p in nodes:
                    for address,pointer in checks:requests[address]=max(4,requests.get(address,0))
            view.pose_requests=ReadPlan(sorted(requests.items()));view.view_pointers=self.view_pointers&pointers;view.water_pointers=self.water_pointers&pointers
            view.player_pointers=getattr(self,'player_pointers',set())&pointers
            view.pose_layout=PoseLayout(view.records,view.view_pointers,read_plan=view.pose_requests,switches=switches,water_pointers=view.water_pointers,node_identities=self.node_identities,player_pointers=view.player_pointers,water_visibility_roots=getattr(self,'water_visibility_roots',()),actor_owners=getattr(self,'actor_owners',{}),native_light_states=getattr(getattr(self,'pose_layout',None),'native_light_states',{}),shadow_casters=getattr(self,'shadow_caster_pointers',set())&pointers,shadow_distance=getattr(self,'shadow_distance',0),near_pass_camera=getattr(getattr(self,'pose_layout',None),'near_pass_camera',False),cell_root_owners=getattr(self,'cell_root_owners',{}))
            view.continuity_indices=selected
            if len(self.continuity_views)>=8:self.continuity_views.clear()
            self.continuity_views[key]=view
        view.cell=base['cell_ptr'];view.topology_dirty=False
        view.continuity_excluded=frozenset(excluded)
        packet=view.snapshot(base,prepared=True)
        if view.topology_dirty:self.topology_dirty=True
        states=[(False,)]*len(self.records)
        for i,state in zip(view.continuity_indices,packet['instance_states']):states[i]=state
        packet['instance_states']=states;packet['geometry_stats']['instances']=len(states)
        packet['geometry_stats']['masked_layers']=list(key)
        return packet

    def prepare(self,base):
        cells,safe=render_cells(self.r,base,retained=self.stream_cells) if not base.get('cell_flags',1)&1 else (None,True)
        key=self.key(base,cells)
        scope=((base['world'],base['data'],'exterior-stream') if not base.get('cell_flags',1)&1 else key[:5])+(base.get('player_ref'),base.get('load_serial'))
        weapon=weapon_signature(base)
        extra=self.extra_groups(base);old_extra=tuple((layer,value[0][0])for layer,value in self.extra_generations.items())
        if self.scope!=scope or not safe or extra!=old_extra or self.effects_state(base)!=self.effect_signature or weapon!=self.weapon_state:
            self.refresh(base)
        elif self.refresh_future is not None and self.refresh_future.done():
            future=self.refresh_future;self.refresh_future=None
            try:scene=future.result()
            except (OSError,ValueError,RuntimeError):scene=None
            if scene is not None and self.refresh_key==key:self.refresh(base,prepared_scene=scene)
        if (self.scene_key!=key or time.perf_counter()-self.last_refresh>=1) and self.refresh_future is None:
            if self.executor is None:self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='original-topology')
            self.refresh_key=key
            # Separate reader traversal state; only a completed, revalidated
            # graph is adopted by the foreground pose/asset owner.
            views=list(base.get('view_roots',()))
            aux=list(base.get('aux_roots',[]))
            self.refresh_future=self.executor.submit(lambda:SceneReader(self.r).collect(cells=cells,view_roots=views,aux_roots=aux))
        if cells and not desired_grids(base,preload=False).issubset({tuple(c['grid'])for c in self.stream_cells}):
            raise SceneReadChanged('New exterior view is awaiting original topology')
        if self.stream_cells:self.cell=base['cell_ptr']
        if self.cell!=base['cell_ptr']:
            raise RuntimeError('Geometry/current cell mismatch')

    def capture_pose(self,base):
        """Read each shared node once, before any deformation or JSON work.

        Retry once if a frame fence advances. This reduces tearing without
        stopping the game; a stable fence still does not prove atomicity.
        """
        requests=getattr(self,'pose_requests',None)
        if requests is None:
            nodes=set();shape_nodes={int(s['id'],16) for s in self.shapes}
            for shape in self.shapes:nodes.add(int(shape['id'],16));nodes.update(shape['parents'])
            for skin in self.skins.values():nodes.update((skin.root,*skin.bones))
            requests=[(ptr,0xAC if ptr in shape_nodes else 0x74) for ptr in sorted(nodes)]
        for attempt in range(2):
            started=time.perf_counter()
            capture_ns=time.time_ns()
            anchor=self.r.camera_sample()
            if any(anchor.get(k)!=base.get(k) for k in ('world','data','cell_ptr','player_ref','load_serial')):
                raise SceneReadChanged('Scene changed before pose capture')
            excluded=getattr(self,'continuity_excluded',frozenset())
            if 'view:first-person'not in excluded and anchor.get('view_roots',[])!=base.get('view_roots',[]):raise SceneReadChanged('First-person root changed before pose capture')
            def retained_aux(packet):return [v for v in packet.get('aux_roots',[])if 'aux:'+v['layer']not in excluded]
            if retained_aux(anchor)!=retained_aux(base):raise SceneReadChanged('Auxiliary roots changed before pose capture')
            nodes_started=time.perf_counter()
            try:
                if hasattr(self.r,'capture_many'):raw=self.r.capture_many(requests)
                else:raw=self.r.read_many(requests) if hasattr(self.r,'read_many') else {ptr:self.r.read(ptr,count) for ptr,count in sorted(requests)}
            except OSError as error:
                self.last_refresh=0
                raise SceneReadChanged('Native node retired during pose capture')from error
            nodes_ms=(time.perf_counter()-nodes_started)*1000
            pose_batch=getattr(self.r,'last_batch_stats',{}).copy()
            view_metrics={}
            # The independent native camera process now owns the compact arms
            # capture. Do not recopy the entire world buffer for 79 near nodes.
            classify_started=time.perf_counter()
            try:raw=PoseFrame(raw,self.pose_layout,anchor.get('camera',{}),anchor.get('first_person_active',True),all(item.get('visible',True)for item in anchor.get('aux_roots',[])if item['layer']in('water','ripple')),anchor.get('first_person_items_active',True))
            except SceneReadChanged:
                self.last_refresh=0;raise
            if raw.invalid_count or raw.light_membership_changed:self.topology_dirty=True;self.last_refresh=0
            classify_ms=(time.perf_counter()-classify_started)*1000
            # Retain every native particle binding in the immutable catalog,
            # but only copy buffers that can be drawn in this captured view.
            # Dormant/off-camera capacity must not crowd out visible effects.
            candidates=[s for s in self.shapes if s.get('particles')]
            if candidates:
                candidates=[s for s in candidates if raw.shape_visible(int(s['id'],16))]
            part_started=time.perf_counter()
            particles=capture_particles(self.r,candidates,tolerate=True)
            parts={'particles':(time.perf_counter()-part_started)*1000,'classification':classify_ms,'view_pose':view_metrics.get('read_ms',0)}
            attribute_items=list(self.native_attributes.values())
            if attribute_items:
                attribute_items=[item for item in attribute_items if raw.shape_visible(item['shape'])]
            part_started=time.perf_counter()
            try:
                if not attribute_items:attributes={}
                else:
                    capture_key=tuple(item['shape']for item in attribute_items)
                    prepared=self.attribute_captures.get(capture_key)
                    if prepared is None:
                        prepared=AttributeCapture(attribute_items)
                        if len(self.attribute_captures)>=8:self.attribute_captures.clear()
                        self.attribute_captures[capture_key]=prepared
                    attributes=capture_attributes(self.r,prepared)
            except(OSError,ValueError,RuntimeError)as error:
                self.last_refresh=0
                raise SceneReadChanged('Native mutable attributes changed during capture: '+str(error))from error
            parts['attributes']=(time.perf_counter()-part_started)*1000
            part_started=time.perf_counter()
            preferred={p for p,indices in getattr(self,'native_light_membership',{}).items()if raw.unhidden[indices].any()}
            try:environment=capture_environment(self.r,anchor,self.light_pointers,self.light_owners,preferred)
            except(OSError,ValueError)as error:
                self.last_refresh=0
                raise SceneReadChanged('Native environment changed during capture: '+str(error))from error
            try:
                parts['environment']=(time.perf_counter()-part_started)*1000
                part_started=time.perf_counter()
                materials=capture_materials(self.r,self.material_flips)
                parts['texture_frames']=(time.perf_counter()-part_started)*1000
                texture_batch=getattr(self.r,'last_batch_stats',{}).copy()if isinstance(self.material_flips,FlipCapture)and self.material_flips.records else{}
                part_started=time.perf_counter()
                values=capture_values(self.r,self.material_values)
                parts['material_values']=(time.perf_counter()-part_started)*1000
            except(OSError,ValueError,RuntimeError)as error:
                self.last_refresh=0
                raise SceneReadChanged('Native material changed during capture: '+str(error))from error
            anchor={**anchor,'environment':environment,'material_frames':materials,'material_values':values}
            end=self.r.u32(int(anchor['world'],16)+0x24)
            if self.r.u32(0x7C67DC)!=int(anchor['world'],16) or self.r.u32(int(anchor['data'],16)+0xB540)!=int(self.cell,16):
                raise SceneReadChanged('Scene changed during pose capture')
            if anchor.get('view_roots') and self.r.u32(int(anchor['world'],16)+0x158)!=int(anchor['view_roots'][0],16):raise SceneReadChanged('First-person root changed during pose capture')
            elapsed=(time.perf_counter()-started)*1000
            # A slow pass already spans an original frame; repeating the same
            # full read cannot make it atomic and doubles camera/pose latency.
            # Retry only a short pass that happened to straddle a boundary.
            skipped=end!=anchor['frame_ms']and attempt==0 and elapsed>=8
            if end==anchor['frame_ms'] or attempt==1 or skipped:
                return anchor,raw,particles,attributes,{'pose_read_ms':elapsed,'pose_parts_ms':parts,'texture_frame_batch':texture_batch,'pose_attempts':attempt+1,
                    'pose_nodes_ms':nodes_ms,
                    'pose_batch':pose_batch,
                    'pose_sample_unix_ns':capture_ns,'source_frame_ms_end':end,
                    'sample_spanned_frames':end!=anchor['frame_ms'],'retry_skipped_for_budget':skipped}

    def snapshot(self,base,*,prepared=False):
        if not prepared:self.prepare(base)
        anchor,raw,particles,attributes,metrics=self.capture_pose(base)
        translate_started=time.perf_counter()
        if anchor.get('native_loading'):raise SceneReadChanged('Native loading began before publication')
        if not isinstance(raw,PoseFrame):raw=PoseFrame(raw,getattr(self,'pose_layout',None)or PoseLayout(self.records,getattr(self,'view_pointers',set())),anchor['camera'],anchor.get('first_person_active',True))
        # Every bone and node used below comes from this one bounded read pass.
        # Skin.deform must never fall back to a new process read mid-calculation.
        needed=set()
        for i in raw.visible_indices:
            skin=self.records[i][3]
            if skin is not None:needed.update((skin.shape,skin.root,*skin.bones))
        worlds=raw.worlds(needed)
        states=[(False,)]*len(self.records);visible_counts=[0]*len(self.cell_definitions);visible_count=0;view_visible=0;view_pointers=getattr(self,'view_pointers',set())
        culled=int(np.count_nonzero(raw.unhidden&~raw.visible));deformed_count=0
        particle_shapes={int(s['id'],16)for s in self.shapes if s.get('particles')}
        for index in raw.visible_indices:
            ptr,identity,visibility_nodes,skin,owner=self.records[index]
            if ptr in particle_shapes and ptr not in particles:continue
            data=raw[ptr]
            visible_count+=1
            if ptr in view_pointers:view_visible+=1
            if owner is not None:visible_counts[owner]+=1
            transform_bytes=data[0x40:0x74]
            previous=self.transform_cache.get(ptr)
            if previous and previous[0]==transform_bytes:transform=previous[1]
            else:
                transform=[round(value,6) for value in struct.unpack('<13f',transform_bytes)]
                self.transform_cache[ptr]=(transform_bytes,transform)
            state=[True,transform]
            if ptr in particles:
                points,colors=particle_quads(particles[ptr],transform,anchor['camera'])
                state.extend((points,colors))
                deformed_count+=1
            elif ptr in attributes:
                local,colors,uvs=attributes[ptr]
                if skin is not None:
                    points=skin.deform(worlds,strict=True,vertices=local)
                else:
                    placement=matrix(transform);points=local@placement[:3,:3].T+placement[:3,3]
                if uvs is not None:
                    state.append(dict(points=points.reshape(-1),uvs=uvs.reshape(-1),**({'colors':colors.reshape(-1)}if colors is not None else{})))
                else:
                    state.append(points.reshape(-1))
                    if colors is not None:state.append(colors.reshape(-1))
                deformed_count+=1
            elif ptr in self.native_attributes:
                raise SceneReadChanged('Visible mutable native attributes were not captured')
            elif skin is not None:
                state.append(dict(palette=skin.palette(worlds),bound=struct.unpack_from('<4f',data,0x1C)))
                deformed_count+=1
            states[index]=state
        if self.r.u32(self.r.u32(0x7C67E0)+0xB540)!=int(self.cell,16):
            raise SceneReadChanged('Cell changed while reading render poses')
        cell_stats=[{**cell,'visible':count}for cell,count in zip(self.cell_definitions,visible_counts)]
        trace=os.environ.get('UEMW_VISIBILITY_TRACE')
        focus=base.get('focus')or{}
        if trace in ('before','after','hitch') and (trace=='hitch' or raw.invalid_count or focus.get('name')=='Indrele Rathryon'):
            # Opt-in diagnosis of the captured visibility decision. This writes
            # local data only; no gameplay flags or process memory are changed.
            try:
                root=self.r.u32(int(focus['id'],16)+0x10)if focus.get('name')=='Indrele Rathryon' else None;rows=[]
                for i,s in enumerate(self.shapes):
                    if root is not None and root not in s.get('parents',()):continue
                    if s['skin']=='0x0':continue
                    hidden=[];invalid=[]
                    for p in (*s.get('parents',()),int(s['id'],16)):
                        n=raw.layout.index[p]
                        if raw.nodes['flags'][n]&1:hidden.append(hex(p))
                        if raw.layout.node_known[n] and tuple((int(raw.nodes['table'][n]),int(raw.nodes['parent'][n])))!=tuple(raw.layout.node_identities[n]):invalid.append(dict(node=hex(p),expected=[hex(int(v))for v in raw.layout.node_identities[n]],observed=[hex(int(raw.nodes[k][n]))for k in ('table','parent')]))
                    if trace!='hitch' and root is None and not invalid:continue
                    rows.append(dict(id=s.get('render_id',s.get('generation','')+':'+s['id']),visible=bool(raw.visible[i]),unhidden=bool(raw.unhidden[i]),inside=bool(raw.inside[i]),bound=raw.bounds[i].tolist(),hidden=hidden,invalid=invalid))
                    if trace!='hitch' and root is None and len(rows)>=16:break
                signature=tuple((v['id'],v['visible'],v['unhidden'],tuple(v['hidden']),str(v['invalid']))for v in rows)
                if trace!='hitch' or signature!=getattr(self,'visibility_trace_signature',None):
                    with (ROOT/f'logs/npc-visibility-source-{trace}.jsonl').open('a',encoding='utf-8')as log:
                        log.write(json.dumps(dict(stamp=metrics['pose_sample_unix_ns'],camera=anchor['camera'],rows=rows))+'\n')
                    self.visibility_trace_signature=signature
            except(OSError,ValueError,KeyError)as error:
                if trace=='hitch' and str(error)!=getattr(self,'visibility_trace_error',None):
                    print(json.dumps(dict(diagnostic='visibility_trace_error',error=str(error))),file=sys.stderr,flush=True)
                    self.visibility_trace_error=str(error)
        metrics['pose_translate_ms']=(time.perf_counter()-translate_started)*1000
        return {**anchor,**metrics,'geometry_version':6 if any(item['uvs']for item in self.native_attributes.values())else 5,'scene_epoch':self.epoch,'stream_cells':cell_stats,
                'scene_catalog':self.catalog,'instance_states':states,
                **({'view_layout':self.view_layout}if getattr(self,'view_layout',None)else{}),
                **({'scene_bindings_version':1,'scene_catalog_md5':self.catalog_digest}if getattr(self,'catalog_digest','')else{}),
                'geometry_stats':{'instances':len(states),'skinned_shapes':len(self.skins),
                                  'visible':visible_count,
                                  'frustum_culled':culled,'deformed_shapes':deformed_count,
                                  'offscreen_shadow_casters':int(np.count_nonzero(raw.offscreen_casters)),
                                  'terrain_instances':self.terrain_count,
                                  'first_person_instances':len(view_pointers),'first_person_visible':view_visible,
                                  'particle_systems':sum(bool(s.get('particles'))for s in self.shapes),
                                  'particle_sampled_systems':len(particles),'particle_active':sum(p[1]for p in particles.values()),
                                  'particle_capture_dropped':sum(bool(s.get('particles'))and raw.shape_visible(int(s['id'],16))and int(s['id'],16)not in particles for s in self.shapes),
                                  'mutable_shapes':len(self.native_attributes),'mutable_sampled_shapes':len(attributes),
                                  'membership_md5':self.membership_hash,
                                  'mesh_cache_entries':len(self.assets.meshes),
                                  'texture_cache_entries':len(self.assets.textures),
                                  'catalog_history_entries':len(self.catalog_history)}}


def write_latest(packet,encoded=None):
    target=ROOT/'local/bridge/latest.json'
    temporary=target.with_suffix(f'.{os.getpid()}.tmp')
    encoded=json.dumps(packet,separators=(',',':'),allow_nan=False).encode('utf-8') if encoded is None else encoded
    if len(encoded)>MAX_PACKET_BYTES:
        raise ValueError('Geometry packet exceeds the protocol 1 MiB limit')
    temporary.write_bytes(encoded)
    for _ in range(20):
        try:
            os.replace(temporary,target)
            return len(encoded)
        except PermissionError:
            time.sleep(.002)
    # Diagnostic tools and editors may briefly deny DELETE sharing. Keep the
    # last complete snapshot and try a fresh sample next tick; UE's age limit
    # will clear it if the lock lasts too long. Never kill the producer here.
    return 0


def publish(packet,frames=None,channel=None):
    """An oversized or nonfinite sample is a dropped frame, never a dead bridge."""
    try:
        if channel is not None:
            body=b''
            if packet.get('status')=='live'and packet.get('geometry_version')in(5,6):
                from live_binary import encode
                body=encode(packet,packed_metadata=True)
            manifest,size=channel.publish(packet,body)
            if not getattr(channel,'advertised',False):
                if not write_latest(channel.d):return 0
                channel.advertised=True
            packet.clear();packet.update(manifest)
            return size
        if frames is not None and packet.get('status')=='live' and packet.get('geometry_version')in(5,6):
            from live_binary import encode
            body=encode(packet,packed_metadata=all(key in packet for key in('environment','material_frames','material_values')))
            manifest,name=frames.prepare(packet,body,binary=True)
            size=0
            try:
                size=write_latest(manifest)
                if size:frames.commit(name);packet.clear();packet.update(manifest)
            finally:
                if not size:frames.remove(name)
            return size
        body=json.dumps(packet,separators=(',',':'),allow_nan=False).encode('utf-8')
        # The presentation watchdog and diagnostics poll this commit at high
        # frequency. Keep their work small even when the full frame fits v1.
        if frames is not None and packet.get('status')=='live' and packet.get('geometry_version') in (1,2,3,4) and len(body)>64*1024:
            manifest,name=frames.prepare(packet,body)
            size=0
            try:
                size=write_latest(manifest)
                if size:
                    frames.commit(name);packet.clear();packet.update(manifest)
            finally:
                if not size:frames.remove(name)
            return size
        return write_latest(packet,body)
    except ValueError as error:
        fallback={k:packet[k] for k in ('protocol','version','session','sequence','sample_unix_ns','pid')}
        fallback.update(status='unavailable',error=str(error),read_ms=packet.get('read_ms',0))
        packet.clear();packet.update(fallback)
        if channel is not None:
            manifest,size=channel.publish(packet)
            if not getattr(channel,'advertised',False):
                if not write_latest(channel.d):return 0
                channel.advertised=True
            packet.clear();packet.update(manifest)
            return size
        return write_latest(packet)


def weapon_signature(base):
    player=base.get('player')or{}
    if base.get('first_person_active')and 'view_revision'in base:
        # Readiness changes before the native weapon nodes exist. Discovery
        # supplies the actual topology revision; do not enqueue/cancel a full
        # preparation twice for a single original draw animation.
        return (None,player.get('magic_ready'),base['view_revision'])
    return (player.get('weapon_ready'),player.get('magic_ready'),*((base['view_revision'],)if'view_revision'in base else()))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--seconds',type=float,default=-1)
    parser.add_argument('--hz',type=float,default=60)
    parser.add_argument('--file-transport',action='store_true',help='Explicit legacy file-frame diagnostics; ordinary play uses shared channel v1')
    parser.add_argument('--trace-stalls',action='store_true',help='Opt-in bounded Python thread stacks every three seconds; no game attachment or capture')
    args=parser.parse_args()
    if os.environ.get('UEMW_TRACE_GC')=='1':
        import gc
        gc_started={}
        def trace_gc(phase,info):
            generation=info['generation']
            if phase=='start':gc_started[generation]=time.perf_counter()
            elif generation in gc_started:
                elapsed=(time.perf_counter()-gc_started.pop(generation))*1000
                if elapsed>2:print(json.dumps(dict(diagnostic='python_gc_pause',generation=generation,pause_ms=elapsed,unix_ns=time.time_ns())),file=sys.stderr,flush=True)
        gc.callbacks.append(trace_gc)
    if args.trace_stalls and not 0<args.seconds<=180:parser.error('Thread-stack diagnostics require a 1..180 second test')
    trace_file=None
    trace_stop=None;trace_thread=None
    if args.trace_stalls:
        import threading,traceback
        trace_file=(ROOT/'logs/bridge-stalls.log').open('w')
        trace_stop=threading.Event()
        def trace_threads():
            # Capture owning Python frame references under the GIL. The
            # installed 3.12.10 faulthandler's native thread walker crashed
            # during the diagnostic run; never use it in the play process.
            while not trace_stop.wait(3):
                trace_file.write(f'Python thread sample {time.time_ns()}\n')
                for identity,frame in sys._current_frames().items():
                    trace_file.write(f'Thread {identity}\n');traceback.print_stack(frame,file=trace_file)
                trace_file.flush()
        trace_thread=threading.Thread(target=trace_threads,name='bridge-diagnostics',daemon=True);trace_thread.start()
    # The topology worker performs many short ctypes reads. Bound how long it
    # can hold the GIL while the fresh-pose owner is returning from its reads.
    sys.setswitchinterval(.001)
    if not 1<=args.hz<=60:
        parser.error('Sample rate must be between 1 and 60 Hz')
    reader=Reader(args.pid)
    print(json.dumps(dict(read_batch_backend='native-v1'if reader._native_batch.api else'python-fallback',pid=args.pid)),flush=True)
    sampler=RenderSample(reader)
    from async_geometry import AsyncGeometry
    geometry=AsyncGeometry(reader)
    frames=FrameStore(ROOT/'local/bridge')
    session=str(uuid.uuid4())
    from shared_channel import Writer
    channel=None
    from camera_lane import CameraLane
    camera_lane=None
    started=time.perf_counter()
    sequence=0
    last_log=0
    last_stop_poll=0
    transient_drops=0;last_transient='';last_status=None;last_retry_log=0.;view_revision=''
    try:
        channel=None if args.file_transport else Writer(args.pid,session)
        camera_lane=CameraLane(args.pid,session)
        with (ROOT/'logs/geometry-bridge.jsonl').open('a',encoding='utf-8') as log:
            while True:
                tick=time.perf_counter()
                geometry.prioritize_pose(True)
                reader.check_alive()
                if tick-last_stop_poll>=.1:
                    from local_files import read_json
                    from renderer_guard import source_stop_matches
                    try:stop=read_json(ROOT/'local/bridge/source-stop.json',8192)
                    except (OSError,ValueError):stop={}
                    if source_stop_matches(stop,session,args.pid):
                        print(json.dumps(dict(bridge_stopped=True,reason=stop.get('reason'),session=session)),flush=True)
                        break
                    from native_first_person import discovery_matches
                    try:request=read_json(ROOT/'local/bridge/view-refresh.json',8192)
                    except(OSError,ValueError):request={}
                    if geometry.state is not None and discovery_matches(request,args.pid,session,geometry.state.epoch,time.time_ns()):view_revision=request['signature']+':'+str(request['unix_ns'])
                    last_stop_poll=tick
                capture_ns=time.time_ns()
                try:
                    sample=sampler.snapshot();sample['view_revision']=view_revision
                    if sample['status']=='live':
                        if not supported(sample):
                            sample={'status':'unsupported_scene','pid':args.pid,'cell':sample['cell'],
                                    'error':'Invalid native cell identity or coordinates.'}
                            if geometry.scene_key is not None:geometry.invalidate_scene()
                        else:
                            sample.update(geometry.snapshot(sample))
                    elif sample['status']=='no_scene' and geometry.scene_key is not None:
                        geometry.invalidate_scene()
                except SceneReadChanged as error:
                    # Never publish a partial/inconsistent pose or an artificial
                    # unavailable scene for a normal retained-cell read race.
                    # The last committed frame is still age-bounded by UE and
                    # the independent presentation watchdog, including hangs.
                    transient_drops+=1;last_transient=str(error)
                    if time.perf_counter()-last_retry_log>=1:
                        print(json.dumps(dict(pid=args.pid,diagnostic='native_read_retry',unix_ns=time.time_ns(),drops=transient_drops,error=last_transient)),file=sys.stderr,flush=True)
                        last_retry_log=time.perf_counter()
                    if args.seconds>=0 and time.perf_counter()-started>=args.seconds:break
                    geometry.prioritize_pose(False)
                    time.sleep(max(0,1/args.hz-(time.perf_counter()-tick)))
                    continue
                except (OSError,ValueError,RuntimeError,np.linalg.LinAlgError) as error:
                    sample={'status':'unavailable','pid':args.pid,'error':str(error)}
                packet={'protocol':'uemw.live','version':1,'session':session,'sequence':sequence,
                        'sample_unix_ns':sample.get('pose_sample_unix_ns',capture_ns),
                        'reference_sample_unix_ns':sample.get('reference_sample_unix_ns',capture_ns),**sample,'read_ms':(time.perf_counter()-tick)*1000}
                if packet.get('geometry_version')in(3,4,5,6):
                    packet['object_count']=packet.get('object_count',len(packet.get('objects',[])));packet['objects']=[]
                packet.update(transient_read_drops=transient_drops,last_transient_read_error=last_transient)
                publish_started=time.perf_counter()
                try:size=publish(packet,frames,channel)
                except BlockingIOError:
                    # A reader copying a complete frame cannot stall capture.
                    size=0
                publish_ms=(time.perf_counter()-publish_started)*1000
                if tick-last_log>=1 or packet.get('status')!=last_status:
                    summary={k:v for k,v in packet.items() if k not in ('objects','instances','instance_states')}
                    summary['bytes']=size
                    summary['published']=size>0
                    summary['publish_ms']=publish_ms
                    summary['frame_work_ms']=(time.perf_counter()-tick)*1000
                    summary['object_count']=packet.get('object_count',len(packet.get('objects',[])))
                    summary['frame_history_entries']=min(channel.generation,8)if channel else len(frames.history)
                    summary['actors']=[o for o in packet.get('objects',[]) if o['type'].startswith(('NPC','CREA','CREC'))]
                    encoded=json.dumps(summary,separators=(',',':'))
                    log.write(encoded+'\n');log.flush();print(encoded,flush=True)
                    last_log=tick
                last_status=packet.get('status')
                sequence+=1
                if args.seconds==0 or (args.seconds>0 and tick-started>=args.seconds):
                    break
                geometry.prioritize_pose(False)
                time.sleep(max(0,1/args.hz-(time.perf_counter()-tick)))
    finally:
        geometry.prioritize_pose(False)
        if camera_lane:camera_lane.close()
        geometry.close();reader.close()
        if channel:channel.close()
        if trace_file:
            trace_stop.set();trace_thread.join();trace_file.close()


if __name__=='__main__':
    with snapshot_lease():main()
