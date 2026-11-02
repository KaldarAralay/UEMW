"""Bounded read-only traversal of the original game's loaded Ni scene graph.

This reads actual geometry/poses used by Morrowind.exe. It does not parse saves,
construct a substitute world, call engine functions, or execute game code.
Layout references are pinned in live_probe.py; cached RTTI is immutable code.
"""
from collections import Counter
import argparse
import json
import math
import struct
from native_environment import LIGHT_TYPES
from live_probe import Reader,SceneReadChanged
from native_particles import header as particle_header
from native_blend import classify as classify_blend

def scene_roots(reader,cell):
    raw=reader.read(cell+0x14,0x1C)
    roots=[struct.unpack_from('<I',raw,0)[0],struct.unpack_from('<I',raw,0x18)[0]]
    if not struct.unpack_from('<I',raw,4)[0]&1:
        land=struct.unpack_from('<I',raw,0xC)[0]
        roots.append(reader.u32(land+0x10) if land else 0)
    return roots

class SceneReader:
    def __init__(self,reader):
        self.r=reader
        self.types={}

    def ancestry(self,ptr,table=None):
        if table is None:table=self.r.u32(ptr)
        if table in self.types:
            return self.types[table]
        code=self.r.read(self.r.u32(table+4),6)
        if code[0]!=0xB8 or code[5]!=0xC3:
            raise ValueError('Unsupported Ni RTTI getter instruction pattern')
        rtti=struct.unpack_from('<I',code,1)[0]
        names=[]
        seen=set()
        while rtti and rtti not in seen and len(names)<20:
            seen.add(rtti)
            name,parent=struct.unpack('<2I',self.r.read(rtti,8))
            names.append(self.r.string(name,96))
            rtti=parent
        self.types[table]=names
        return names

    def texture_property(self,ptr,inherited,header=None):
        return self.render_properties(ptr,(inherited,0,0,2),header)[0]

    def render_properties(self,ptr,inherited,header=None):
        texture,alpha,material,color_mode,*extra=inherited
        lighting_mode=extra[0]if extra else 1
        link=ptr+0x88
        seen=set()
        for _ in range(32):
            if not link or link in seen:
                break
            seen.add(link)
            raw=header[0x88:0x90] if header is not None and link==ptr+0x88 else self.r.read(link,8)
            prop,link=struct.unpack('<2I',raw)
            if prop:
                types=self.ancestry(prop)
                if 'NiTexturingProperty'in types:texture=prop
                elif 'NiAlphaProperty'in types:alpha=struct.unpack('<H',self.r.read(prop+0x14,2))[0]
                elif 'NiMaterialProperty'in types:material=prop
                elif 'NiVertexColorProperty'in types:
                    color_mode,lighting_mode=struct.unpack('<2I',self.r.read(prop+0x18,8))
                    if color_mode>2 or lighting_mode>1:raise ValueError('Invalid native vertex-colour lighting mode')
        return texture,alpha,material,color_mode,lighting_mode

    def texture_name(self,prop):
        if not prop:
            return ''
        storage=self.r.u32(prop+0x20)
        end=self.r.u32(prop+0x28)
        if not storage or not 1<=end<=16:
            return ''
        map_ptr=self.r.u32(storage)
        if not map_ptr:
            return ''
        texture=self.r.u32(map_ptr+4)
        if not texture or 'NiSourceTexture' not in self.ancestry(texture):
            return ''
        return self.r.string(self.r.u32(texture+0x2C),512)

    def collect(self,roots=None,cells=None,view_roots=None,aux_roots=None):
        owned_scene=roots is None or cells is not None
        data=self.r.u32(0x7C67E0)
        cell=self.r.u32(data+0xB540)
        if not cell:
            raise RuntimeError('No active cell')
        cell_name=self.r.string(self.r.u32(cell+0x10))
        if cells is None:
            if roots is None:roots=scene_roots(self.r,cell)
            pending=[(p,False,(0,0,0,2),0,(),index>=2,'interior:'+hex(cell)) for index,p in enumerate(roots) if p]
        else:
            roots=[int(p,16) for c in cells for p in c['roots']]
            pending=[(int(p,16),False,(0,0,0,2),0,(),index==2,c['key']) for c in cells for index,p in enumerate(c['roots']) if int(p,16)]
        if view_roots:
            roots=list(roots)+[int(p,16)for p in view_roots]
            pending.extend((int(p,16),False,(0,0,0,2),0,(),False,'view:first-person')for p in view_roots if int(p,16))
        if aux_roots:
            roots=list(roots)+[int(p['root'],16)for p in aux_roots]
            pending.extend((int(p['root'],16),False,(0,0,0,2),0,(),False,'aux:'+p['layer'])for p in aux_roots)
        actor_owners={}
        if owned_scene:
            from node_ownership import discover
            ownership_cells=[(int(c['cell_ptr'],16),int(c['roots'][0],16),c['key'])for c in cells]if cells is not None else [(cell,scene_roots(self.r,cell)[0],'interior:'+hex(cell))]
            excluded=[int(a['root'],16)for a in aux_roots or [] if a['layer']=='player']
            actor_owners=discover(self.r,ownership_cells,excluded)
            # Actor roots can be borrowed by native auxiliary render passes.
            # Visit reference-owned actors explicitly so that such a pass
            # cannot remove them from a periodic cell traversal/catalog.
            pending.extend((node,False,(0,0,0,2),0,(),False,owner['role'])for node,owner in actor_owners.items())
        for item in aux_roots or ():
            if item['layer']=='player' and item.get('owner_ref'):
                from node_ownership import player_owner
                node=int(item['root'],16)
                # Keep the player's auxiliary layer, but use reference-owned
                # cell ancestry just like NPCs. A pass-local parent must never
                # become a retirement/visibility dependency of the whole body.
                actor_owners[node]=player_owner(self.r,int(item['owner_ref'],16),node,scene_roots(self.r,cell)[0])
        switches={};node_identities={};light_owners={};light_sets={}
        from native_light_sets import capture as light_set
        native_sun=self.r.u32(data+0x98)if owned_scene else None
        def remember_switch(node,types=None,header=None):
            if node in switches:return switches[node]
            if types is None:types=self.ancestry(node)
            if 'NiSwitchNode'not in types:return None
            raw=self.r.read(node+0x94,12);storage,capacity,end=struct.unpack('<3I',raw)
            if end>capacity or capacity>32768 or(end and not storage):raise SceneReadChanged('Invalid native switch child array')
            children=struct.unpack('<'+'I'*end,self.r.read(storage,end*4))if end else()
            table=struct.unpack_from('<I',header)[0]if header is not None else self.r.u32(node)
            switches[node]=dict(node=node,vtable=table,storage=storage,capacity=capacity,children=children)
            return switches[node]
        initial=[]
        for ptr,hidden,props,depth,parents,terrain,layer in pending:
            chain=[];gates=[];child=ptr;parent=actor_owners[ptr]['cell_root']if ptr in actor_owners else self.r.u32(ptr+0x18)
            while parent:
                if parent in chain or len(chain)>=96:raise SceneReadChanged('Original parent chain changed or cycled')
                if remember_switch(parent):gates.append((parent,child))
                native=self.r.read(parent,0x1c);node_identities[parent]=(struct.unpack_from('<I',native)[0],struct.unpack_from('<I',native,0x18)[0])
                chain.append(parent);child=parent;parent=self.r.u32(parent+0x18)
            initial.append((ptr,hidden,props,depth,tuple(chain),terrain,layer,tuple(gates)))
        pending=initial
        visited=set()
        counts=Counter()
        shapes=[]
        errors=[]
        textures={}
        lights=set();effect_nodes=set()
        def effects(first,owner=None):
            if first in effect_nodes:return
            effect_nodes.add(first)
            seen=set();link=first
            for _ in range(32):
                if not link or link in seen:break
                seen.add(link);effect,link=struct.unpack('<2I',self.r.read(link,8))
                if effect and self.r.u32(effect)in LIGHT_TYPES:
                    lights.add(effect);light_owners.setdefault(effect,set()).add(owner)
            if link:raise ValueError('Invalid or oversized native effect list')
        for _,_,_,_,parents,_,owner,_ in initial:
            for parent in parents:effects(parent+0xa8,owner)
        while pending:
            ptr,hidden,texture_prop,depth,parents,terrain,cell_key,gates=pending.pop()
            if ptr in visited:
                continue
            if len(visited)>=32768 or depth>96:
                raise ValueError('Scene graph exceeds bounded traversal limits')
            visited.add(ptr)
            try:
                header=self.r.read(ptr,0x90)
                node_identities[ptr]=(struct.unpack_from('<I',header)[0],struct.unpack_from('<I',header,0x18)[0])
                types=self.ancestry(ptr,struct.unpack_from('<I',header,0)[0])
                kind=types[0]
                counts[kind]+=1
                name=self.r.string(struct.unpack_from('<I',header,8)[0],256)
                # The collision graph must never become visible geometry or
                # participate in an Unreal collision/physics system.
                if kind=='RootCollisionNode' or name.lower()=='rootcollisionnode':
                    counts['excluded_collision_subtrees']+=1
                    continue
                flags=struct.unpack_from('<H',header,0x14)[0]
                hidden=hidden or bool(flags&1)
                texture_prop=self.render_properties(ptr,texture_prop,header)
                if 'NiNode' in types:
                    switch=remember_switch(ptr,types,header)
                    node_data=self.r.read(ptr+0x94,0x1c)
                    storage,capacity,end=struct.unpack_from('<3I',node_data)
                    if end>capacity or capacity>32768:
                        raise ValueError('Invalid child array bounds')
                    if storage and end:
                        children=struct.unpack(f'<{end}I',self.r.read(storage,end*4))
                        pending.extend((child,hidden,texture_prop,depth+1,parents+(ptr,),terrain,cell_key,
                            gates+((ptr,child),)if switch else gates)for child in children if child)
                    if any(node_data[0x14:0x1c]):effects(ptr+0xa8,cell_key)
                elif 'NiLight' in types:
                    if struct.unpack_from('<I',header)[0]in LIGHT_TYPES:
                        lights.add(ptr);light_owners.setdefault(ptr,set()).add(cell_key)
                elif 'NiTriShape' in types or 'NiParticles'in types:
                    effect_state,model,skin=struct.unpack('<3I',self.r.read(ptr+0x94,12))
                    if not model:
                        continue
                    particle='NiParticles'in types
                    model_header=self.r.read(model,0x44 if particle else 0x36)
                    vertex_count=struct.unpack_from('<H',model_header,8)[0]
                    if particle:
                        capacity,_,_,_=particle_header(model_header)
                        if skin:raise ValueError('Skinned native particle geometry is unsupported')
                        vertex_count=capacity*4;triangle_count=capacity*2
                        skin=0
                    else:triangle_count=struct.unpack_from('<H',model_header,0x34)[0]
                    if not vertex_count or not triangle_count:
                        continue
                    texture,alpha,material,color_mode,lighting_mode=texture_prop
                    blend=classify_blend(alpha)
                    if texture not in textures:textures[texture]=self.texture_name(texture)
                    values=struct.unpack_from('<13f',header,0x40)
                    if not all(math.isfinite(v) and abs(v)<1e8 for v in values):raise ValueError('Invalid NiAVObject world transform')
                    shapes.append({'id':hex(ptr),'name':name,'type':kind,'model':hex(model),'controller':hex(struct.unpack_from('<I',header,0x10)[0]),
                                   'skin':hex(skin),'visible':not hidden,'cell_key':cell_key,
                                   'vertex_count':vertex_count,'triangle_count':triangle_count,
                                   'texture':textures[texture],'texture_property':hex(texture),'alpha_flags':alpha,'alpha_mode':blend['mode'],
                                   'blend_native_opacity':blend['native_opacity'],'blend_fallback':blend['fallback'],
                                   'material':hex(material),'color_mode':color_mode,'lighting_mode':lighting_mode,
                                   'transform':{'rotation':values[:9],'position':values[9:12],'scale':values[12]},'parents':parents,'terrain':terrain,
                                   'switch_gates':gates})
                    if owned_scene and cell_key!='view:first-person':
                        # The near pass uses the existing global-light path in UE;
                        # unused per-object effect lists must not churn its assets.
                        membership=light_set(self.r,effect_state,light_sets)
                        if membership is not None:shapes[-1].update(native_light_state=effect_state,native_lights=membership,native_sun=hex(native_sun)in membership)
                    if particle:
                        shapes[-1].update(particles=True,particle_capacity=capacity)
                        counts['rendered_particle_systems']+=1;counts['particle_capacity']+=capacity
                    if terrain:
                        counts['terrain_shapes']+=1;counts['terrain_triangles']+=triangle_count
                    counts['vertices']+=vertex_count
                    counts['triangles']+=triangle_count
                    if skin:
                        counts['skinned_shapes']+=1
            except (OSError,ValueError) as e:
                if len(errors)<50:
                    errors.append({'node':hex(ptr),'error':str(e)})
        if cell!=self.r.u32(data+0xB540):
            raise SceneReadChanged('Cell changed during graph traversal; dropped')
        return {'cell':cell_name,'cell_ptr':hex(cell),'roots':[hex(p) for p in roots],
                'stream_cells':cells or [],
                'nodes':len(visited),'counts':dict(counts),'shapes':shapes,'errors':errors,'lights':sorted(lights),'switches':switches,
                'node_identities':node_identities,'actor_owners':actor_owners,'light_owners':{p:tuple(owners)for p,owners in light_owners.items()}}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--output')
    args=parser.parse_args()
    reader=Reader(args.pid)
    try:
        result=SceneReader(reader).collect()
        if args.output:
            from pathlib import Path
            Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in result.items() if k!='shapes'},indent=2))
        print('texture_examples:',[s['texture'] for s in result['shapes'] if s['texture']][:8])
    finally:
        reader.close()


if __name__=='__main__':
    main()
