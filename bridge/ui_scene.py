"""Read native menu-camera geometry and UI texture pixels, never a window feed.

Layout, glyph quads, wrapping, colours, cursor and UI state belong to Morrowind.
Only projection/clipping and transport are performed here. No UI actions.
"""
import hashlib,json,math,struct
from collections import OrderedDict
from io import BytesIO
from pathlib import Path
import numpy as np
from PIL import Image
from live_probe import ROOT,SceneReadChanged
from scene_reader import SceneReader
from native_ui import inspect_ui
from game_assets import Assets,normalized
from asset_files import publish
from native_topology import triangle_indices
from ui_read import UIReader

MAX_DRAWS=2048
MAX_VERTICES=65536
MAX_INDICES=196608
MAX_TEXTURES=128
MAX_TEXTURE_BYTES=64*1024*1024


def node_identity(pointer,header):
    """Fence destruction/visibility, not ordinary motion after a captured pose.

    UI transforms/bounds are owned values in this sample; a moving cursor must
    not invalidate all other UI. Refcounts are not object identities either.
    """
    return((pointer,header[:4]),(pointer+8,header[8:0x18]),(pointer+0x84,header[0x84:0x90]))


def project(points,camera,width,height):
    points=np.asarray(points,dtype=np.float64);relative=points-np.asarray(camera['position'])
    depth=relative@np.asarray(camera['forward']);right=relative@np.asarray(camera['right']);up=relative@np.asarray(camera['up'])
    left,r,top,bottom,near,far=camera['frustum']
    if not 0<near<far or r<=left or top<=bottom or not np.isfinite(points).all()or(depth<=near).any():raise ValueError('Unsupported native UI projection/near clipping')
    xy=np.empty((len(points),2));xy[:,0]=((right*near/depth-left)/(r-left))*width;xy[:,1]=((top-up*near/depth)/(top-bottom))*height
    if not np.isfinite(xy).all()or(np.abs(xy)>1e7).any():raise ValueError('Invalid projected UI geometry')
    return xy,depth


def clip_triangles(vertices,indices,rect):
    """Screen-space clip, interpolating original UVs/RGBA at real clip edges."""
    v=np.asarray(vertices,dtype=np.float64);indices=np.asarray(indices,dtype=np.int64).reshape(-1,3)
    left,top,right,bottom=rect;columns=v.shape[1]
    if left>=right or top>=bottom:return np.empty((0,columns)),np.empty((0,3),dtype=np.uint16)
    if v[:,0].max()<left or v[:,0].min()>right or v[:,1].max()<top or v[:,1].min()>bottom:return np.empty((0,columns)),np.empty((0,3),dtype=np.uint16)
    if ((v[:,0]>=left)&(v[:,0]<=right)&(v[:,1]>=top)&(v[:,1]<=bottom)).all():return v,indices
    output=[];triangles=[]
    for tri in indices:
        poly=[v[i]for i in tri]
        for axis,edge,minimum in((0,left,True),(0,right,False),(1,top,True),(1,bottom,False)):
            result=[]
            if not poly:break
            previous=poly[-1];inside_previous=previous[axis]>=edge if minimum else previous[axis]<=edge
            for current in poly:
                inside=current[axis]>=edge if minimum else current[axis]<=edge
                if inside!=inside_previous:
                    fraction=(edge-previous[axis])/(current[axis]-previous[axis]);result.append(previous+(current-previous)*fraction)
                if inside:result.append(current)
                previous=current;inside_previous=inside
            poly=result
        if len(poly)>=3:
            offset=len(output);output.extend(poly);triangles.extend((offset,offset+i,offset+i+1)for i in range(1,len(poly)-1))
        if len(output)>MAX_VERTICES:raise ValueError('Native UI clipping exceeds vertex budget')
    return np.asarray(output).reshape(-1,columns),np.asarray(triangles,dtype=np.uint16).reshape(-1,3)


def element_clips(reader,root,width,height):
    """Observe layout identity/owners; native mesh buffers already carry clips."""
    pending=[(root,'',0)];seen=set();result={};identities=[];owners={}
    while pending:
        p,owner,depth=pending.pop()
        if p in seen or len(seen)>=8192:raise SceneReadChanged('Native UI element list cycled/exceeded budget')
        seen.add(p);raw=reader.read(p,0x15c)
        if raw[0x75]>1 or raw[0x76]>1:raise SceneReadChanged('Native UI visibility changed')
        if p!=root and not(raw[0x75]or raw[0x76]):continue
        if depth==1:owner=reader.string(struct.unpack_from('<I',raw,8)[0],96)
        node=struct.unpack_from('<I',raw,0x88)[0]
        if node:
            owners[node]=owner
            a,b,c,d=struct.unpack_from('<4i',raw,0x128)
            result[node]=(a,b,c,d)
        first,end,capacity=struct.unpack_from('<3I',raw,0x1c)
        if not first<=end<=capacity or(end-first)%4 or end-first>8192*4:raise SceneReadChanged('Invalid native UI child vector')
        identities.append((p,raw[0x1c:0x28],raw[0x70:0x7d],raw[0x88:0x8c],raw[0x128:0x138]))
        if first!=end:pending.extend((x,owner,depth+1)for x in struct.unpack('<'+'I'*((end-first)//4),reader.read(first,end-first))if x)
    return result,identities,owners


class UICapture:
    def __init__(self,reader,folder=None):
        self.native=reader;self.r=UIReader(reader);self.scene=SceneReader(self.r);self.assets=Assets(reader);self.folder=Path(folder or ROOT/'local/ui-assets');self.folder.mkdir(parents=True,exist_ok=True)
        self.files=OrderedDict();self.used=set();self.geometry_cache={}

    def close(self):self.assets.close()

    def geometry(self,p,node,h,shape,projection,projection_key,width,height,clip):
        r=self.r;count=shape['vertex_count'];uv_pointer=struct.unpack_from('<I',h,0x28)[0];color_pointer=struct.unpack_from('<I',h,0x24)[0];material=int(shape['material'],16)
        points_raw=r.read(struct.unpack_from('<I',h,0x1c)[0],count*12);uv_raw=r.read(uv_pointer,count*8)if uv_pointer else b'';colors_raw=r.read(color_pointer,count*4)if color_pointer and shape['color_mode']!=0 else b'';material_raw=r.read(material+0x28,0x2c)if material else b'';indices_raw=triangle_indices(r,shape,h)
        key=(node,h,points_raw,uv_raw,colors_raw,material_raw,indices_raw,shape['color_mode'],projection_key,width,height,clip)
        cached=self.geometry_cache.get(p)
        if cached and cached[0]==key:return cached[1]
        points=np.frombuffer(points_raw,dtype='<f4').reshape(count,3);uv=np.frombuffer(uv_raw,dtype='<f4').reshape(count,2)if uv_raw else np.zeros((count,2));tint=np.ones(4)
        if material_raw:tint[:3]=struct.unpack_from('<3f',material_raw);tint[3]=struct.unpack_from('<f',material_raw,0x28)[0]
        colors=np.frombuffer(colors_raw,dtype=np.uint8).reshape(count,4)[:,[2,1,0,3]].astype(float)/255 if colors_raw else np.ones((count,4))
        if colors_raw:tint[:3]=1
        colors*=tint;result=None
        if(colors[:,3]>0).any():
            if not np.isfinite(uv).all()or not np.isfinite(colors).all():raise ValueError('Invalid native UI attributes')
            indices=np.frombuffer(indices_raw,dtype='<u2').reshape(-1,3)
            if indices.size and indices.max()>=count:raise SceneReadChanged('Native UI indices escaped vertex buffer')
            t=shape['transform'];world_points=points@np.asarray(t['rotation']).reshape(3,3).T*t['scale']+t['position'];xy,depth=project(world_points,projection,width,height)
            attributes=np.empty((count,8));attributes[:,:2]=xy;attributes[:,2:4]=uv;attributes[:,4:]=colors
            # The game has already clipped/generated its UI vertex buffers.
            # Journal NIF anchors then move children without updating cached
            # Element clip boxes. Applying those boxes again loses real text.
            vertices,indices=clip_triangles(attributes,indices,(0,0,width,height))
            if len(indices):result=(vertices,indices,float(((world_points-projection['position'])@np.asarray(projection['forward'])).mean()))
        if len(self.geometry_cache)>2048:self.geometry_cache.clear()
        self.geometry_cache[p]=(key,result);return result

    def texture(self,texture,world):
        r=self.r;kinds=self.scene.ancestry(texture)
        if 'NiRenderedTexture'in kinds:
            # Original UI-only offscreen targets expose an original readback
            # SourceTexture. Never read/capture the gameplay backbuffer.
            candidates=[]
            for offset in(0x1a8,0x22c):
                raw=r.read(world+offset+0x2c,8);rendered,readback=struct.unpack('<2I',raw)
                if rendered==texture and readback:candidates.append(readback)
            if len(candidates)!=1:raise ValueError('UI rendered texture has no unique native UI-only readback')
            texture=candidates[0];kinds=self.scene.ancestry(texture)
        if 'NiSourceTexture'not in kinds:raise ValueError('Unsupported native UI texture class')
        header=r.read(texture,0x3c);pixels=struct.unpack_from('<I',header,0x34)[0]
        if pixels:
            raw=r.read(pixels,0x48);fmt,*masks,bpp=struct.unpack_from('<6I',raw,8);pointer,widths,heights,offsets,levels,stride,revision=struct.unpack_from('<7I',raw,0x2c)
            width=r.u32(widths);height=r.u32(heights);offset=r.u32(offsets)
            if not 1<=width<=1024 or not 1<=height<=1024 or not 1<=levels<=16 or offset!=0 or stride not in(3,4)or bpp!=stride*8 or fmt not in(0,1,4,5):raise ValueError('Unsupported native UI pixel format/budget')
            expected=([0xff,0xff00,0xff0000,0xff000000]if stride==4 else[0xff,0xff00,0xff0000,0])
            reverse=([0xff0000,0xff00,0xff,0xff000000]if stride==4 else[0xff0000,0xff00,0xff,0])
            rgb=[*expected[:3],0];bgr=[*reverse[:3],0]
            if masks not in(expected,reverse,rgb,bgr):raise ValueError('Unsupported native UI channel masks')
            content=r.read(pointer,width*height*stride)
            if r.read(pixels,0x48)!=raw or r.read(texture,0x3c)!=header:raise SceneReadChanged('Native UI texture changed during capture')
            if hasattr(self,'texture_fences'):self.texture_fences.extend(((pixels,raw),(texture,header)))
            rgba=np.frombuffer(content,dtype=np.uint8).reshape(height,width,stride)
            if masks in(reverse,bgr):rgba=rgba[:,:,[2,1,0,3]if stride==4 else[2,1,0]]
            if stride==3:rgba=np.concatenate((rgba,np.full((height,width,1),255,dtype=np.uint8)),axis=2)
            elif masks[3]==0:rgba=rgba.copy();rgba[:,:,3]=255 # Native XRGB save thumbnails are opaque.
            body=struct.pack('<4sII',b'UTX1',width,height)+rgba.tobytes()
        else:
            name=r.string(struct.unpack_from('<I',header,0x2c)[0],512)
            if not name:raise ValueError('Native UI texture has neither pixels nor an installed filename')
            if name in self.files:
                self.files.move_to_end(name);self.used.add(self.files[name]['file']);return self.files[name]
            relative=normalized(name)
            if not relative.startswith(('textures/','icons/','fonts/','bookart/')):relative='textures/'+relative
            stem=relative.rsplit('.',1)[0];blob=None
            for candidate in dict.fromkeys((relative,stem+'.dds',stem+'.tga',stem+'.bmp')):
                loose=self.assets.data/candidate
                blob=loose.read_bytes()if loose.is_file()else next((b for a in reversed(self.assets.archives)if(b:=a.read(candidate))is not None),None)
                if blob is not None:break
            if blob is None:raise ValueError('Installed UI texture is missing: '+name)
            with Image.open(BytesIO(blob))as image:
                if not 1<=image.width<=1024 or not 1<=image.height<=1024:raise ValueError('Installed UI texture exceeds budget')
                image=image.convert('RGBA');body=struct.pack('<4sII',b'UTX1',image.width,image.height)+image.tobytes();width,height=image.size
        digest=hashlib.sha256(body).hexdigest();filename=digest+'.utx';publish(self.folder/filename,body);self.used.add(filename)
        row=dict(file=filename,sha256=digest,md5=hashlib.md5(body).hexdigest(),width=width,height=height,bytes=len(body))
        if not pixels:
            self.files[name]=row
            while len(self.files)>128:self.files.popitem(last=False)
        return row

    def sample(self):
        r=self.r;r.check_alive();r.begin();self.texture_fences=[];world=r.u32(0x7c67dc);camera=r.u32(world+0x18c);raw=r.read(camera,0x148);root=struct.unpack_from('<I',raw,0x128)[0];width,height=struct.unpack('<2I',r.read(world+0x78,8));ui=inspect_ui(r)
        if not 320<=width<=8192 or not 200<=height<=8192 or not root:raise SceneReadChanged('Native UI viewport/root unavailable')
        projection=dict(position=struct.unpack_from('<3f',raw,0x64),forward=struct.unpack_from('<3f',raw,0xdc),up=struct.unpack_from('<3f',raw,0xe8),right=struct.unpack_from('<3f',raw,0xf4),frustum=struct.unpack_from('<6f',raw,0x100))
        if struct.unpack_from('<4f',raw,0x118)!=(0.,1.,1.,0.):raise ValueError('Unsupported native UI viewport port')
        clips,identities,owners=element_clips(r,int(ui['root'],16),width,height)
        graph=self.scene.collect(roots=[root],prune_hidden=True);draws=[];textures=[];texture_indices={};native_textures={};native_regions=[];texture_bytes=0;vertices_total=0;indices_total=0;self.used=set();node_fences=[]
        if graph['errors']:raise SceneReadChanged('Native UI graph is incomplete: '+graph['errors'][0]['error'])
        for order,shape in enumerate(reversed(graph['shapes'])):
            if not shape['visible']:continue
            if shape['type']!='NiTriShape'or shape['skin']!='0x0':raise ValueError('Unsupported native UI geometry: '+shape['type'])
            p=int(shape['id'],16);node=r.read(p,0xa0);model=int(shape['model'],16);h=r.read(model,0x48);count=shape['vertex_count'];triangles=shape['triangle_count']
            if struct.unpack_from('<H',h,8)[0]!=count or struct.unpack_from('<H',h,0x34)[0]!=triangles:raise SceneReadChanged('Native UI geometry count changed')
            clip=next((clips[parent]for parent in reversed((*shape['parents'],p))if parent in clips),(0,0,width,height))
            geometry=self.geometry(p,node,h,shape,projection,raw[0x40:0x128],width,height,clip)
            if geometry is None:continue
            vertices,indices,depth=geometry
            texture_index=0xffffffff;prop=int(shape['texture_property'],16)
            if prop:
                storage=r.u32(prop+0x20);texmap=r.u32(storage)if storage else 0;texture=r.u32(texmap+4)if texmap else 0
                if texture:
                    if 'NiRenderedTexture'in self.scene.ancestry(texture):
                        owner=next((owners[parent]for parent in reversed((*shape['parents'],p))if owners.get(parent)),'')
                        target=next((label for offset,label in((0x1a8,'MenuInventory'),(0x22c,'MenuMap'))if r.u32(world+offset+0x2c)==texture),None)
                        if target and owner==target and target in ui['active_menus']:
                            # Exact original UI target only. Expose its bounded
                            # original-window region inside the passive overlay;
                            # never capture a gameplay window or synthesize it.
                            a=vertices[:,:2].min(0);b=vertices[:,:2].max(0)
                            if len(native_regions)>=16 or not(0<=a[0]<b[0]<=width and 0<=a[1]<b[1]<=height):raise ValueError('Invalid native UI target region')
                            native_regions.append(dict(id=hex(p),menu=target,rect=[*a,*b],kind='original-ui-render-target'));node_fences.append((p,node,model,h));continue
                    if texture not in native_textures:native_textures[texture]=self.texture(texture,world)
                    row=native_textures[texture];key=row['sha256']
                    if key not in texture_indices:
                        texture_indices[key]=len(textures);textures.append(row);texture_bytes+=row['bytes']
                    texture_index=texture_indices[key]
            vertices_total+=len(vertices);indices_total+=indices.size
            if len(draws)>=MAX_DRAWS or vertices_total>MAX_VERTICES or indices_total>MAX_INDICES or len(textures)>MAX_TEXTURES or texture_bytes>MAX_TEXTURE_BYTES:raise ValueError('Native UI frame exceeds bounded budgets')
            draws.append(dict(id=p,texture=texture_index,vertices=vertices,indices=indices,depth=depth,order=order))
            node_fences.append((p,node,model,h))
        # Original painter/depth order. Source camera depth wins; original
        # child order breaks ties. No menus/glyphs are laid out by this code.
        draws.sort(key=lambda d:(-round(d['depth'],3),d['order']))
        actual=self.native
        camera_after=actual.read(camera,0x148)
        if actual.u32(0x7c67dc)!=world or actual.u32(world+0x18c)!=camera or camera_after[:4]!=raw[:4]or camera_after[8:]!=raw[8:]or inspect_ui(actual)!=ui:raise SceneReadChanged('Native UI camera/menu changed during capture')
        # Keep every identity/layout fence in one owned external read batch.
        fences=[]
        for pointer,header in graph['ui_read_fences']:
            fences.extend(node_identity(pointer,header)if len(header)==0x90 else((pointer,header),))
        for pointer,header in self.texture_fences:fences.extend(((pointer,header[:4]),(pointer+8,header[8:])))
        for p,node,model,h in node_fences:fences.extend((*node_identity(p,node),(p+0x94,node[0x94:0xa0]),(model,h[:4]),(model+8,h[8:])))
        for p,children,flags,node,clip in identities:
            fences.extend(((p+0x1c,children),(p+0x75,flags[5:7]),(p+0x88,node),(p+0x128,clip)))
        requests={}
        for pointer,expected in fences:requests[pointer]=max(requests.get(pointer,0),len(expected))
        copied=actual.read_many(requests.items())
        for pointer,expected in fences:
            if copied[pointer][:len(expected)]!=expected:raise SceneReadChanged('Native UI visibility/model/layout changed during capture')
        return dict(width=width,height=height,draws=draws,textures=textures,native_regions=native_regions,ui=ui,camera=projection,root=hex(root),vertices=vertices_total,indices=indices_total,texture_bytes=texture_bytes)


HEADER=struct.Struct('<4sHH16sQdIIII')
DRAW=struct.Struct('<4I')
VERTEX=np.dtype([('values','<f4',(4,)),('colour','u1',(4,))])


def encode(sample,session,sequence,stamp,pid):
    from live_binary import guid
    data=[HEADER.pack(b'UUI1',1,0,guid(session),sequence,stamp,pid,sample['width'],sample['height'],len(sample['draws']))]
    for d in sample['draws']:
        v=d['vertices'];packed=np.empty(len(v),dtype=VERTEX);packed['values']=v[:,:4];packed['colour']=np.rint(v[:,4:].clip(0,1)*255).astype(np.uint8)
        data.extend((DRAW.pack(d['id'],d['texture'],len(v),d['indices'].size),packed.tobytes(),d['indices'].astype('<u2').tobytes()))
    body=b''.join(data)
    if len(body)>2*1024*1024:raise ValueError('Native UI body exceeds 2 MiB')
    return body
