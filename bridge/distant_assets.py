"""Local-only scenery conversion from installed masters/NIFs/textures.

All positions, topology, colours and paint assignments derive from game data.
Only immutable STAT meshes and LAND are eligible; native overrides provide
enable/delete/move/scale state. No actors, collision or gameplay are created.
"""
import hashlib,json,math,struct
from collections import OrderedDict
from pathlib import Path
import numpy as np
from asset_files import publish
from game_assets import Assets,normalized
from native_blend import classify,alpha_test
from nif_static import shapes,UnsupportedNif
from tes3_world import WorldIndex
from distant_native import rotation
from distant_terrain import mesh as terrain_mesh,texture_grid

MAX_BINDINGS=4096
MAX_MESHES=1024
MAX_VERTICES=1000000


def write_mesh(folder,points,normals,uvs,colours,indices):
    points=np.asarray(points,dtype='<f4').reshape(-1,3);n=len(points);uvs=np.asarray(uvs,dtype='<f4').reshape(-1,2);indices=np.asarray(indices).reshape(-1,3)
    if not 0<n<=65535 or len(uvs)!=n or not 0<len(indices)<=65535 or not np.isfinite(indices).all()or(indices<0).any()or(indices>=n).any()or(indices!=np.floor(indices)).any():raise ValueError('Distant mesh layout exceeds budget')
    indices=indices.astype('<u2')
    normals=None if normals is None else np.asarray(normals,dtype='<f4').reshape(-1,3)
    if normals is not None and len(normals)!=n:raise ValueError('Distant normal layout changed')
    if any(not np.isfinite(a).all()or (np.abs(a)>1e8).any()for a in(points,uvs)if a is not None):raise ValueError('Invalid distant mesh number')
    if normals is not None and (not np.isfinite(normals).all()or(np.abs(normals)>1e8).any()):raise ValueError('Invalid distant normal')
    colours=np.asarray(colours,dtype=np.uint8).reshape(n,4)
    raw=struct.pack('<4sII',b'UEM3'if normals is not None else b'UEM2',n,indices.size)+points.tobytes()+(normals.tobytes()if normals is not None else b'')+uvs.tobytes()+colours.tobytes()+indices.tobytes()
    digest=hashlib.sha256(raw).hexdigest();name='meshes/'+digest+'.umesh';publish(folder/name,raw)
    return dict(asset=digest,file=name,vertices=n,triangles=len(indices))


class DistantAssets:
    def __init__(self,root):
        self.root=Path(root);self.folder=self.root/'local/distant-assets';self.folder.mkdir(parents=True,exist_ok=True)
        for p in('meshes','textures'): (self.folder/p).mkdir(exist_ok=True)
        self.assets=Assets(None);self.assets.out=self.folder;self.world=WorldIndex(self.assets.data)
        self.prototypes=OrderedDict();self.terrain_cache=OrderedDict();self.reference_cache=OrderedDict();self.unsupported={}

    def close(self):self.assets.close()

    def texture(self,name):
        result=self.assets.texture(name)
        if not result:raise UnsupportedNif('Missing installed distant texture: '+name)
        return result

    def prototype(self,model):
        key=normalized(model)
        if key in self.prototypes:
            self.prototypes.move_to_end(key);return self.prototypes[key]
        if key in self.unsupported:return ()
        filename=key if key.startswith('meshes/')else'meshes/'+key
        loose=self.assets.data/filename;blob=loose.read_bytes()if loose.is_file()else next((b for a in reversed(self.assets.archives)if(b:=a.read(filename))is not None),None)
        if blob is None:self.unsupported[key]='Missing installed NIF';return ()
        try:
            original=shapes(blob);result=[]
            bounds=np.concatenate([s['points']for s in original])if original else np.zeros((0,3))
            radius=float(np.linalg.norm(bounds.max(0)-bounds.min(0))/2)if len(bounds)else 0
            if radius<64:
                self.prototypes[key]=()
                while len(self.prototypes)>256:self.prototypes.popitem(last=False)
                return () # Explicit small-object distance policy.
            for s in original:
                n=len(s['points']);properties=s['properties'];material=properties.get('NiMaterialProperty',{});mode=properties.get('NiVertexColorProperty',{}).get('mode',2)
                diffuse=np.asarray(material.get('diffuse',[1,1,1]));emissive=np.asarray(material.get('emissive',[0,0,0]));alpha=float(material.get('alpha',1))
                unlit=float(np.max(emissive))>.001 and float(np.max(diffuse))<.001
                tint=np.r_[emissive if unlit else diffuse,alpha]
                c=s['colours']
                if c is not None and mode!=0:colour=c.copy();tint[:3]=1
                else:colour=np.ones((n,4),dtype=np.float32)
                colour=np.rint(colour*tint*255).clip(0,255).astype(np.uint8)
                uv=s['uvs'][0]if len(s['uvs'])else np.zeros((n,2),dtype=np.float32)
                definition=write_mesh(self.folder,s['points'],s['normals'],uv,colour,s['indices'])
                ap=properties.get('NiAlphaProperty',{});flags=ap.get('flags',0);blend=classify(flags)
                definition.update(texture=self.texture(s['texture'])if s['texture']else'',source_texture=s['texture'],alpha_mode=blend['mode'],blend_native_opacity=blend['native_opacity'],shading=dict(lit=not(unlit or mode==1),fog=True,sky=False,emissive=[0.,0.,0.]if unlit else emissive.tolist(),native_lights=[],native_sun=True))
                test=alpha_test(flags,ap.get('reference',0))
                if test:definition['alpha_test']=test
                maps=[]
                for m in s['maps']:
                    if m['uv']>=len(s['uvs']):raise UnsupportedNif('Distant texture references absent UV set')
                    row=dict(slot=m['slot'],source_texture=m['texture'],texture=self.texture(m['texture']),uv_set=m['uv'],clamp=m['clamp'],filter=m['filter'])
                    if 'bump'in m:row['bump']=m['bump'].tolist()
                    maps.append(row)
                if maps:
                    recipe=dict(version=1,apply=int(properties['NiTexturingProperty']['apply']),maps=maps)
                    if any(m['uv_set']for m in maps if m['slot']<=6):
                        packed=np.empty((n,3,2),dtype='<f4')
                        for i in range(3):packed[:,i]=s['uvs'][i if i<len(s['uvs'])else 0]
                        body=struct.pack('<4sII',b'UUV1',n,3)+packed.tobytes();name='meshes/'+hashlib.sha256(body).hexdigest()+'.uuv';publish(self.folder/name,body);recipe['uv_file']=name
                    definition['texture_stages']=recipe
                # Material properties/stages are part of the resource identity.
                tag=hashlib.sha256(json.dumps(definition,sort_keys=True,separators=(',',':')).encode()).hexdigest();result.append((tag,definition))
            result=tuple(result)
        except (ValueError,OSError,IndexError,np.linalg.LinAlgError)as error:
            self.unsupported[key]=str(error);result=()
        self.prototypes[key]=result
        while len(self.prototypes)>256:self.prototypes.popitem(last=False)
        return result

    def land_texture(self,land,index):
        if not index:return '_land_default.tga'
        owner=land['texture_source'];name=self.world.textures.get((owner,index-1))
        if name is None:
            for master in reversed(self.world.files[owner-1]['masters']):
                name=self.world.textures.get((master,index-1))
                if name:break
        if name is None:raise ValueError('Unresolved original distant LAND texture')
        return name

    def terrain(self,grid):
        grid=tuple(grid)
        if grid in self.terrain_cache:self.terrain_cache.move_to_end(grid);return self.terrain_cache[grid]
        land=self.world.terrain(grid)
        if land is None:return None
        data=terrain_mesh(land,4);colours=data.get('colours',np.full((len(data['points']),4),255,dtype=np.uint8));uv=data['uvs']
        d=write_mesh(self.folder,data['points'],data.get('normals'),uv,colours,data['indices']);tiles=[]
        paint=texture_grid(land.get('VTEX',np.zeros((16,16),dtype='<u2')))
        for y in range(16):
            for x in range(16):
                name=self.land_texture(land,int(paint[y,x]));tiles.append(dict(tile=[grid[0]*16+x,grid[1]*16+y],texture=self.texture(name),source_texture=name))
        first=tiles[0];d.update(texture=first['texture'],source_texture=first['source_texture'],alpha_mode='opaque',distant_terrain=True,shading=dict(lit=True,fog=True,sky=False,emissive=[0,0,0],native_lights=[],native_sun=True))
        tag='land-'+d['asset'];result=(tag,d,tiles);self.terrain_cache[grid]=result
        while len(self.terrain_cache)>64:self.terrain_cache.popitem(last=False)
        return result

    def references(self,grid):
        grid=tuple(grid)
        if grid not in self.reference_cache:self.reference_cache[grid]=self.world.statics(grid)
        self.reference_cache.move_to_end(grid)
        while len(self.reference_cache)>64:self.reference_cache.popitem(last=False)
        return self.reference_cache[grid]

    def build(self,center,excluded,overrides,moved=None,suppressed=()):
        center=tuple(center);excluded=set(map(tuple,excluded));suppressed=set(map(tuple,suppressed));overrides={**overrides,**(moved or{})}
        # Prepare a hidden resident halo too. Renderer-side union gates exclude
        # both current native cells and the source's captured resident cells;
        # a cell cannot double-render during an asynchronous boundary handoff.
        grids=[(x,y)for x in range(center[0]-3,center[0]+4)for y in range(center[1]-3,center[1]+4)]
        grids.sort(key=lambda g:((g[0]-center[0])**2+(g[1]-center[1])**2,g))
        definitions={};bindings=[];states=[];tiles=[];budget_skips=0;terrain_count=0;static_refs={}
        identity=[1,0,0,0,1,0,0,0,1,0,0,0,1]
        for grid in grids:
            terrain=self.terrain(grid)
            if terrain:
                tag,d,paint=terrain;definitions[tag]=d;bindings.append(dict(id=f'distant:land:{grid[0]},{grid[1]}',asset=tag,cell_key=f'distant:{grid[0]},{grid[1]}'));states.append((True,identity));tiles.extend(paint);terrain_count+=1
            if grid not in suppressed:static_refs.update({k:{**v,'origin':grid}for k,v in self.references(grid).items()})
        # Native moved/created static refs can enter the band from another cell.
        for key,ref in overrides.items():
            if ref.get('native_grid')in grids and ref.get('base')in self.world.models and key not in static_refs:static_refs[key]={**ref,'model':self.world.models[ref['base']],'origin':ref['native_grid']}
        statics=0
        origin=[(center[0]+.5)*8192,(center[1]+.5)*8192,0]
        order=sorted(static_refs.items(),key=lambda row:(tuple(overrides.get(row[0],{}).get('native_grid')or row[1]['origin'])in excluded,math.dist(overrides.get(row[0],row[1])['position'],origin),row[0]))
        for key,original in order:
            ref={**original,**overrides.get(key,{})}
            if ref.get('interior'):continue
            if ref['base']not in self.world.models:continue
            # A moved reference must be selected by its actual current cell.
            target=(math.floor(ref['position'][0]/8192),math.floor(ref['position'][1]/8192))
            if target not in grids:continue
            proto=self.prototype(self.world.models[ref['base']])
            additions={t:d for t,d in proto if t not in definitions}
            if len(bindings)+len(proto)>MAX_BINDINGS or len(definitions)+len(additions)>MAX_MESHES or sum(d['vertices']for d in definitions.values())+sum(d['vertices']for d in additions.values())>MAX_VERTICES:budget_skips+=1;continue
            scale=float(ref.get('scale',1));transform=[*rotation(ref['orientation']),*ref['position'],scale];visible=not(ref.get('disabled')or ref.get('deleted'))
            for part,(tag,d)in enumerate(proto):
                definitions[tag]=d;bindings.append(dict(id=f'distant:stat:{key:08x}:{part}',asset=tag,cell_key=f'distant:{target[0]},{target[1]}'));states.append((visible,transform))
            statics+=bool(proto)
        catalog=dict(format='uemw.assets',version=1,meshes=definitions,bindings=bindings,terrain_tiles=tiles,cells=[dict(key=f'distant:{g[0]},{g[1]}',grid=g)for g in grids],source_kind='installed-distant-stat-land',unsupported=dict(models=self.unsupported,budget_skips=budget_skips,small_objects_below_radius=64,controllers='omitted; native live rendering resumes when resident'))
        encoded=json.dumps(catalog,separators=(',',':')).encode();digest=hashlib.md5(encoded).hexdigest();name='catalog-'+digest+'.json';publish(self.folder/name,encoded)
        body=struct.pack('<4sI',b'UDF1',len(states))+b''.join(struct.pack('<I13f',bool(v),*m)for v,m in states);pose_digest=hashlib.md5(body).hexdigest();pose='poses-distant-'+pose_digest+'.udf';publish(self.folder/pose,body)
        return dict(catalog=name,catalog_md5=digest,poses=pose,poses_md5=pose_digest,bindings=len(bindings),terrain_cells=terrain_count,static_references=statics,meshes=len(definitions),unsupported_models=len(self.unsupported),budget_skips=budget_skips,lod_step=4,excluded_grids=[list(g)for g in sorted(excluded)],center=list(center))
