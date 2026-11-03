"""Small strict NetImmerse 4.0.0.2 reader for installed distant STAT meshes.

This is a visual data translator, not a scene/game simulation. Controllers,
skinning, LOD/billboard/effect nodes and unknown classes reject the asset;
their original-engine live representation remains available when resident.
"""
import math,struct
import numpy as np


class UnsupportedNif(ValueError):pass


class Cursor:
    def __init__(self,data):self.data=data;self.at=0
    def take(self,n):
        if n<0 or n>len(self.data)-self.at:raise ValueError('Truncated installed NIF')
        value=self.data[self.at:self.at+n];self.at+=n;return value
    def scalar(self,fmt):return struct.unpack('<'+fmt,self.take(struct.calcsize('<'+fmt)))[0]
    def u32(self):return self.scalar('I')
    def ref(self):return self.scalar('i')
    def string(self):
        n=self.u32()
        if n>4096:raise ValueError('Installed NIF string budget exceeded')
        return self.take(n).decode('cp1252').rstrip('\0')
    def count(self,limit):
        n=self.u32()
        if n>limit:raise ValueError('Installed NIF array budget exceeded')
        return n
    def refs(self):return [self.ref()for _ in range(self.count(32768))]
    def boolean(self):
        # Legacy 4.0 files use a 32-bit zero/nonzero value. Original exporters
        # also wrote noncanonical pointer-like true values for texture maps.
        return bool(self.u32())
    def floats(self,n):
        v=np.frombuffer(self.take(n*4),dtype='<f4').copy()
        if not np.isfinite(v).all()or (np.abs(v)>1e8).any():raise ValueError('Invalid installed NIF float')
        return v


def object_net(c):
    name=c.string();extra=c.ref();controller=c.ref()
    if controller!=-1:raise UnsupportedNif('Animated distant static')
    return dict(name=name,extra=extra)


def av_object(c):
    o=object_net(c);o['flags']=c.scalar('H');position=c.floats(3);rotation=c.floats(9).reshape(3,3);scale=c.floats(1)[0];c.floats(3)
    matrix=np.eye(4);matrix[:3,:3]=rotation*scale;matrix[:3,3]=position;o['matrix']=matrix;o['properties']=c.refs()
    if c.boolean():raise UnsupportedNif('Legacy bound-volume node')
    return o


def geometry_data(c):
    n=c.scalar('H')
    if not 0<n<=65535 or not c.boolean():raise ValueError('Invalid installed NIF vertices')
    points=c.floats(n*3).reshape(n,3);normals=c.floats(n*3).reshape(n,3)if c.boolean()else None
    bound=c.floats(4);colours=c.floats(n*4).reshape(n,4)if c.boolean()else None
    sets=c.scalar('H')&63;have_uv=c.boolean()
    if sets>3:raise UnsupportedNif('Distant static UV sets above two')
    uv=c.floats(sets*n*2).reshape(sets,n,2)if have_uv and sets else np.zeros((0,n,2),dtype=np.float32)
    return dict(points=points,normals=normals,bound=bound,colours=colours,uvs=uv)


def texture_desc(c):
    source=c.ref();clamp=c.u32();filter_=c.u32();uv=c.u32();c.take(6)
    if clamp>3 or filter_>5 or uv>2:raise UnsupportedNif('Unsupported distant texture sampler')
    return dict(source=source,clamp=clamp,filter=filter_,uv=uv)


def parse(data):
    if len(data)>64*1024*1024:raise ValueError('Installed NIF byte budget exceeded')
    c=Cursor(data);line=data.find(b'\n',0,128)
    if line<0 or data[:line]!=b'NetImmerse File Format, Version 4.0.0.2':raise UnsupportedNif('Distant NIF version other than 4.0.0.2')
    c.take(line+1)
    if c.u32()!=0x04000002:raise ValueError('NIF textual/binary versions disagree')
    count=c.count(32768);objects=[]
    for _ in range(count):
        kind=c.string();c.kind=kind;o=dict(kind=kind)
        if kind in('NiNode','RootCollisionNode','NiBSAnimationNode','NiBSParticleNode'):
            o.update(av_object(c));o['children']=c.refs();o['effects']=c.refs()
            if o['effects']:raise UnsupportedNif('Distant static dynamic effects')
        elif kind=='NiTriShape':
            o.update(av_object(c));o['data']=c.ref();o['skin']=c.ref()
            if o['skin']!=-1:raise UnsupportedNif('Skinned distant static')
        elif kind=='NiTriShapeData':
            o.update(geometry_data(c));triangles=c.scalar('H');points=c.u32()
            if points!=triangles*3:raise ValueError('Invalid installed NIF triangle count')
            indices=np.frombuffer(c.take(points*2),dtype='<u2').reshape(-1,3).copy()
            if indices.size and (indices>=len(o['points'])).any():raise ValueError('Installed NIF index exceeds vertex count')
            o['indices']=indices
            for _ in range(c.scalar('H')):c.take(c.scalar('H')*2)
        elif kind=='NiTexturingProperty':
            o.update(object_net(c));o['flags']=c.scalar('H');o['apply']=c.u32();n=c.count(10);maps={}
            if n<5:raise ValueError('Invalid installed NIF texture count')
            for slot in range(n):
                if c.boolean():
                    maps[slot]=texture_desc(c)
                    if slot==5:maps[slot]['bump']=c.floats(6)
            o['maps']=maps
        elif kind=='NiSourceTexture':
            o.update(object_net(c));external=c.scalar('B')
            if external!=1:raise UnsupportedNif('Embedded distant static texture')
            o['texture']=c.string();o['preferences']=[c.u32()for _ in range(3)];o['static']=c.scalar('B')
        elif kind=='NiMaterialProperty':
            o.update(object_net(c));o['flags']=c.scalar('H');values=c.floats(14)
            o.update(ambient=values[:3],diffuse=values[3:6],specular=values[6:9],emissive=values[9:12],gloss=values[12],alpha=values[13])
        elif kind=='NiAlphaProperty':o.update(object_net(c));o['flags']=c.scalar('H');o['reference']=c.scalar('B')
        elif kind=='NiVertexColorProperty':o.update(object_net(c));o['flags']=c.scalar('H');o['mode']=c.u32();o['lighting']=c.u32()
        elif kind in('NiZBufferProperty','NiDitherProperty','NiSpecularProperty','NiWireframeProperty','NiShadeProperty'):
            o.update(object_net(c));o['flags']=c.scalar('H')
        elif kind=='NiStencilProperty':
            o.update(object_net(c));o['flags']=c.scalar('H');enabled=c.scalar('B');c.take(28)
            if enabled:raise UnsupportedNif('Stencil-enabled distant static')
        elif kind=='NiStringExtraData':o['next']=c.ref();o['bytes']=c.u32();o['text']=c.string()
        elif kind=='NiIntegerExtraData':o['next']=c.ref();o['bytes']=c.u32();o['value']=c.u32()
        else:raise UnsupportedNif('Unsupported distant NIF class: '+kind)
        objects.append(o)
    roots=c.refs()
    if c.at!=len(data):raise ValueError('Trailing installed NIF data')
    if any(i<0 or i>=len(objects)for i in roots):raise ValueError('Invalid installed NIF root')
    return objects,roots


def shapes(data):
    objects,roots=parse(data);result=[];visited=set();stack=[(i,np.eye(4),{})for i in roots]
    def get(i):
        if not 0<=i<len(objects):raise ValueError('Invalid installed NIF object reference')
        return objects[i]
    while stack:
        i,parent,inherited=stack.pop()
        if i in visited:raise ValueError('Cyclic/shared distant NIF ancestry')
        visited.add(i);o=get(i)
        if o['kind']=='RootCollisionNode'or o.get('name','').lower()=='rootcollisionnode'or o.get('flags',0)&1:continue
        matrix=parent@o.get('matrix',np.eye(4));props=dict(inherited)
        for p in o.get('properties',()):
            if p!=-1:
                prop=get(p);props[prop['kind']]=prop
        if 'children'in o:stack.extend((p,matrix,props)for p in o['children']if p!=-1)
        elif o['kind']=='NiTriShape':
            d=get(o['data'])
            if d['kind']!='NiTriShapeData':raise ValueError('Distant shape/data classes disagree')
            if not len(d['indices']):continue
            points=d['points']@matrix[:3,:3].T+matrix[:3,3]
            normals=d['normals']
            if normals is not None:
                normals=normals@np.linalg.inv(matrix[:3,:3]);length=np.linalg.norm(normals,axis=1);normals=normals/np.maximum(length[:,None],1e-12)
            texture='';tp=props.get('NiTexturingProperty',{});maps=[]
            for slot,m in tp.get('maps',{}).items():
                source=get(m['source'])
                if source['kind']!='NiSourceTexture':raise UnsupportedNif('Non-source distant texture')
                maps.append(dict(slot=slot,texture=source['texture'],**{k:v for k,v in m.items()if k!='source'}))
                if slot==0:texture=source['texture']
            result.append(dict(name=o.get('name',''),points=points,normals=normals,colours=d['colours'],uvs=d['uvs'],indices=d['indices'],texture=texture,maps=maps,properties=props))
    if sum(len(s['points'])for s in result)>131072:raise ValueError('Distant static vertex budget exceeded')
    return result
