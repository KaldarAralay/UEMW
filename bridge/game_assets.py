"""Local-only conversion of installed TES3 BSA textures and live mesh buffers.

Generated Bethesda-derived files stay under ignored local/assets. Source code
contains no Bethesda mesh, texture, master-file or save data.
Mesh v1: little-endian UEM1, u32 vertex count, u32 index count, then XYZ f32,
UV f32 and triangle u16 arrays. Coordinates remain in original engine space.
"""
import argparse
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PureWindowsPath
import struct
from types import MappingProxyType
import numpy as np
from PIL import Image
from live_probe import ROOT, Reader
from scene_reader import SceneReader
from asset_files import publish as publish_asset
from terrain_layout import native_tile


def normalized(name):
    name=name.replace('\\','/').lower().strip('/')
    if ':' in name or '..' in name.split('/'):
        raise ValueError('Asset paths must remain inside the installed Data Files directory')
    return name

class Bsa:
    indices={}
    def __init__(self,path):
        self.file=path.open('rb')
        info=os.fstat(self.file.fileno());key=(str(path.resolve()),info.st_size,info.st_mtime_ns,info.st_ino)
        if key in self.indices:
            self.entries=self.indices[key];return
        version,hash_offset,count=struct.unpack('<3I',self.file.read(12))
        if version!=0x100 or count>200000 or hash_offset<12*count:
            raise ValueError('Not a supported original TES3 BSA')
        records=struct.unpack(f'<{2*count}I',self.file.read(8*count))
        offsets=struct.unpack(f'<{count}I',self.file.read(4*count))
        names=self.file.read(hash_offset-12*count)
        data_start=12+hash_offset+8*count
        self.entries={}
        for i,offset in enumerate(offsets):
            if offset>=len(names):
                raise ValueError('Invalid BSA filename offset')
            end=names.find(b'\0',offset)
            if end<0:
                raise ValueError('Unterminated BSA filename')
            name=normalized(names[offset:end].decode('cp1252'))
            size,start=records[2*i:2*i+2]
            self.entries[name]=(data_start+start,size)
        self.entries=MappingProxyType(self.entries)
        if len(self.indices)>=6:self.indices.pop(next(iter(self.indices)))
        self.indices[key]=self.entries

    def read(self,name):
        entry=self.entries.get(name)
        if entry is None:
            return None
        offset,size=entry
        if size>64*1024*1024:
            raise ValueError('BSA texture exceeds the bounded conversion size')
        self.file.seek(offset)
        data=self.file.read(size)
        if len(data)!=size:
            raise ValueError('Truncated BSA entry')
        return data

    def close(self):
        self.file.close()


class Assets:
    def __init__(self,reader):
        self.r=reader
        self.data=ROOT/'local/Morrowind/Data Files'
        self.out=ROOT/'local/assets'
        (self.out/'meshes').mkdir(parents=True,exist_ok=True)
        (self.out/'textures').mkdir(exist_ok=True)
        self.archives=[Bsa(self.data/name) for name in ('Morrowind.bsa','Tribunal.bsa','Bloodmoon.bsa')]
        self.textures={}
        self.meshes={}
        self.missing=[]
        self.material_values={}
        self.material_emissive={}

    def close(self):
        for archive in self.archives:
            archive.close()

    def begin_refresh(self):
        self.used_meshes=set()
        self.used_textures=set()
        self.material_values={}
        self.material_emissive={}

    def trim_cache(self):
        self.meshes={key:value for key,value in self.meshes.items() if key in self.used_meshes}
        self.textures={key:value for key,value in self.textures.items() if key in self.used_textures}
        self.missing=[value for value in self.missing if value['texture'] in self.used_textures]

    def reset_scene(self):
        # Memory addresses/unique IDs are scoped to an original loaded scene.
        # Re-read immutable buffers after a cell/root change, even on address reuse.
        self.meshes.clear();self.textures.clear();self.missing.clear()

    def texture(self,name):
        if name in self.textures:
            return self.textures[name]
        if not name:
            return ''
        relative=normalized(name)
        if not relative.startswith('textures/'):
            relative='textures/'+relative
        stem=str(PureWindowsPath(relative).with_suffix('')).replace('\\','/')
        choices=list(dict.fromkeys([relative,stem+'.dds',stem+'.tga',stem+'.bmp']))
        blob=None
        selected=''
        for candidate in choices:
            loose=self.data/Path(candidate)
            if loose.is_file():
                blob=loose.read_bytes();selected=candidate;break
            for archive in reversed(self.archives):
                blob=archive.read(candidate)
                if blob is not None:
                    selected=candidate;break
            if blob is not None:
                break
        if blob is None:
            self.missing.append({'texture':name,'reason':'not found in private installed assets'})
            self.textures[name]=''
            return ''
        digest=hashlib.sha256(blob).hexdigest()
        target=self.out/'textures'/f'{digest}.png'
        if not target.exists():
            with Image.open(BytesIO(blob)) as original:
                if max(original.size)>8192:
                    raise ValueError('Texture exceeds maximum supported dimensions')
                rgba=original.convert('RGBA')
                encoded=BytesIO();rgba.save(encoded,format='PNG');publish_asset(target,encoded.getvalue())
        result='textures/'+target.name
        self.textures[name]=result
        return result

    def mesh(self,shape):
        if shape.get('particles'):return self.particle_mesh(shape)
        model=int(shape['model'],16)
        header=self.r.read(model,0x48)
        unique,revision=struct.unpack_from('<IH',header,0x2C)
        color_ptr=struct.unpack_from('<I',header,0x24)[0]
        dynamic=shape.get('dynamic_attributes')
        immutable_uvs=immutable_indices=None
        if dynamic:
            uv_pointer=struct.unpack_from('<I',header,0x28)[0]
            immutable_uvs=self.r.read(uv_pointer,shape['vertex_count']*8)if uv_pointer and not dynamic.get('uvs') else bytes(shape['vertex_count']*8)
            immutable_indices=self.r.read(struct.unpack_from('<I',header,0x3c)[0],shape['triangle_count']*6)
            # Morph/gradient revisions must not create new immutable resources.
            # Resolved live UVs have their own lane. Topology edits still change
            # the immutable key rather than being frozen.
            revision=('native_attributes',hashlib.sha256(immutable_uvs+immutable_indices).digest(),bool(dynamic.get('colors')))
        emissive=(0.,0.,0.);unlit=False
        # Live material values are applied by the renderer, never baked into
        # immutable geometry or its cache key. Static materials retain v1 behavior.
        tint=(1.,1.,1.,1.);material=0 if shape.get('material_state') else int(shape.get('material','0x0'),16)
        if material:
            if material not in self.material_values:
                raw=self.r.read(material+0x28,0x30)
                diffuse=struct.unpack_from('<3f',raw,0);emissive=struct.unpack_from('<3f',raw,0x18);alpha=struct.unpack_from('<f',raw,0x28)[0]
                values=(*diffuse,*emissive,alpha)
                if not np.isfinite(values).all():raise ValueError('Invalid native material color')
                unlit=max(emissive)>.001 and max(diffuse)<.001
                self.material_emissive[material]=(tuple(emissive) if not unlit else (0.,0.,0.),unlit)
                rgb=emissive if unlit else diffuse
                self.material_values[material]=tuple(max(0.,min(1.,v))for v in (*rgb,alpha))
            tint=self.material_values[material]
            emissive,unlit=self.material_emissive[material]
        if color_ptr and shape.get('color_mode',2)!=0:tint=(1.,1.,1.,tint[3])
        key=(model,unique,revision,shape['texture'],shape.get('generation',''),shape.get('alpha_mode','opaque'),shape.get('blend_native_opacity',True),shape.get('color_mode',2),tint,emissive,unlit,tuple(shape['transform']['position'])if shape.get('terrain')else None)
        if hasattr(self,'used_meshes'):
            self.used_meshes.add(key);self.used_textures.add(shape['texture'])
        if key in self.meshes:
            return self.meshes[key]
        count=shape['vertex_count']
        triangles=shape['triangle_count']
        vertices=bytes(count*12)if dynamic else self.r.read(struct.unpack_from('<I',header,0x1C)[0],count*12)
        normal_pointer=struct.unpack_from('<I',header,0x20)[0]
        normals=self.r.read(normal_pointer,count*12)if normal_pointer and not dynamic else b''
        normal_source='native_dynamic_triangle_fallback'if dynamic else'native'if normals else'generated_missing_native'
        if normals and (not np.isfinite(np.frombuffer(normals,dtype='<f4')).all()or np.max(np.abs(np.frombuffer(normals,dtype='<f4')))>1e8):
            # Match the consumer's finite/bounded normal contract. Keep real
            # geometry when optional shading contains NaNs or finite garbage;
            # UEM2's triangle-normal path supplies approximate lighting.
            # Record the limitation instead of rebuilding the entire world
            # repeatedly because one optional shading buffer contains NaNs.
            normals=b'';normal_source='generated_invalid_native'
        uv_pointer=struct.unpack_from('<I',header,0x28)[0]
        uvs=immutable_uvs if dynamic else self.r.read(uv_pointer,count*8) if uv_pointer else bytes(count*8)
        indices=immutable_indices if dynamic else self.r.read(struct.unpack_from('<I',header,0x3C)[0],triangles*6)
        if color_ptr and shape.get('color_mode',2)!=0 and not(dynamic and dynamic.get('colors')):
            colors=np.frombuffer(self.r.read(color_ptr,count*4),dtype=np.uint8).reshape(-1,4)[:,[2,1,0,3]].astype(np.float32)
        else:colors=np.full((count,4),255.,dtype=np.float32)
        colors=np.rint(colors*np.asarray(tint,dtype=np.float32)).clip(0,255).astype(np.uint8).tobytes()
        if not np.isfinite(np.frombuffer(vertices,dtype='<f4')).all() or not np.isfinite(np.frombuffer(uvs,dtype='<f4')).all():
            raise ValueError('Non-finite mesh buffer')
        if np.frombuffer(indices,dtype='<u2').max()>=count:
            raise ValueError('Triangle index exceeds vertex count')
        payload=struct.pack('<4sII',b'UEM3'if normals else b'UEM2',count,triangles*3)+vertices+normals+uvs+colors+indices
        digest=hashlib.sha256(payload).hexdigest()
        target=self.out/'meshes'/f'{digest}.umesh'
        publish_asset(target,payload)
        result={'asset':digest,'file':'meshes/'+target.name,'texture':self.texture(shape['texture']),'alpha_mode':shape.get('alpha_mode','opaque'),'blend_native_opacity':shape.get('blend_native_opacity',True),
                'source_texture':shape['texture'],'vertices':count,'triangles':triangles,'normal_source':normal_source,
                'shading':dict(lit=not(unlit or shape.get('color_mode',2)==1),emissive=list(emissive),fog=True,sky=False)}
        if result['texture'] and shape.get('terrain') and count==25 and triangles==32 and not dynamic and shape.get('alpha_mode','opaque')=='opaque':
            tile=native_tile(np.frombuffer(vertices,dtype='<f4').reshape(-1,3),np.frombuffer(uvs,dtype='<f4').reshape(-1,2),shape['transform'])
            if tile is not None:result['terrain_tile']=tile
        self.meshes[key]=result
        return result

    def particle_mesh(self,shape):
        # Static topology only. Every current center/size/color comes from the
        # original process in geometry v4, never an Unreal particle simulation.
        count=shape['particle_capacity'];vertices=count*4
        key=('particle-quads',count,shape['texture'],shape.get('alpha_mode','translucent'),shape.get('blend_native_opacity',True))
        if hasattr(self,'used_meshes'):
            self.used_meshes.add(key);self.used_textures.add(shape['texture'])
        if key in self.meshes:return self.meshes[key]
        points=bytes(vertices*12)
        uvs=struct.pack('<8f',0,1,1,1,1,0,0,0)*count
        colors=bytes([255])*vertices*4
        indices=np.asarray([[4*i+j for j in (0,1,2,0,2,3)]for i in range(count)],dtype='<u2').tobytes()
        payload=struct.pack('<4sII',b'UEM2',vertices,count*6)+points+uvs+colors+indices
        digest=hashlib.sha256(payload).hexdigest();target=self.out/'meshes'/f'{digest}.umesh'
        publish_asset(target,payload)
        result=dict(asset=digest,file='meshes/'+target.name,texture=self.texture(shape['texture']),
                    alpha_mode=shape.get('alpha_mode','translucent'),blend_native_opacity=shape.get('blend_native_opacity',True),source_texture=shape['texture'],vertices=vertices,triangles=count*2)
        self.meshes[key]=result
        return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pid',type=int,required=True)
    args=parser.parse_args()
    reader=Reader(args.pid)
    assets=Assets(reader)
    try:
        scene=SceneReader(reader).collect()
        for shape in scene['shapes']:
            shape['mesh']=assets.mesh(shape)
        manifest={'format':'uemw.assets','version':1,'cell':scene['cell'],'instances':scene['shapes'],
                  'missing_textures':assets.missing,'unsupported':scene['errors']}
        target=assets.out/'catalog.json'
        target.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        print(json.dumps({'manifest':str(target),'instances':len(scene['shapes']),'unique_mesh_files':len(set(m['file'] for m in assets.meshes.values())),
                          'source_textures':len(assets.textures),'missing_textures':assets.missing},indent=2))
    finally:
        assets.close()
        reader.close()


if __name__=='__main__':
    main()
