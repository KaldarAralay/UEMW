"""Render-only CPU skinning from original-engine bone matrices and bind data.

Column-vector form of the documented classic NiGeometry skin equation:
geometryWorld * skinTransform * inverse(skeletonWorld) * boneWorld * boneBind.
See https://pyffi.readthedocs.io/en/develop/_modules/pyffi/formats/nif.html
No animation clock, animation events, interpolation or physics are evaluated.
"""
import argparse
import json
import struct
import numpy as np
from live_probe import Reader
from scene_reader import SceneReader
from asset_files import publish as publish_asset


def matrix(values):
    values=np.asarray(values,dtype=np.float64)
    result=np.eye(4,dtype=np.float64)
    result[:3,:3]=values[:9].reshape(3,3)*values[12]
    result[:3,3]=values[9:12]
    return result

def world_matrix(reader,node):
    return matrix(struct.unpack('<13f',reader.read(node+0x40,52)))

class Skin:
    def __init__(self,reader,shape):
        self.r=reader
        self.shape=int(shape['id'],16)
        model=int(shape['model'],16)
        skin=int(shape['skin'],16)
        self.root=reader.u32(skin+0xC)
        data=reader.u32(skin+8)
        self.skin_transform=matrix(struct.unpack('<13f',reader.read(data+0xC,52)))
        count=reader.u32(data+0x40)
        if not 0<count<=256:
            raise ValueError('Unsupported skin bone count')
        bones=reader.u32(skin+0x10)
        bone_data=reader.u32(data+0x44)
        self.bones=struct.unpack(f'<{count}I',reader.read(bones,4*count))
        self.vertex_count=shape['vertex_count']
        self.vertices=np.frombuffer(reader.read(reader.u32(model+0x1C),12*self.vertex_count),dtype='<f4').reshape(-1,3).astype(np.float64)
        self.binds=[]
        self.weight_sets=[]
        self.sums=np.zeros(self.vertex_count)
        dtype=np.dtype([('index','<u2'),('padding','<u2'),('weight','<f4')])
        for i in range(count):
            raw=reader.read(bone_data+0x4C*i,0x4C)
            self.binds.append(matrix(struct.unpack_from('<13f',raw,0)))
            pointer=struct.unpack_from('<I',raw,0x44)[0]
            size=struct.unpack_from('<H',raw,0x48)[0]
            if size>self.vertex_count:
                raise ValueError('Invalid bone weight count')
            weights=np.frombuffer(reader.read(pointer,size*8),dtype=dtype) if size else np.zeros(0,dtype=dtype)
            ids=weights['index'].astype(np.int32)
            values=weights['weight'].astype(np.float64)
            if np.any(ids>=self.vertex_count) or not np.isfinite(values).all() or np.any(values<0):
                raise ValueError('Invalid skin weights')
            self.weight_sets.append((ids,values))
            np.add.at(self.sums,ids,values)

    def palette(self,worlds):
        geometry=worlds[self.shape]
        left=geometry @ self.skin_transform @ np.linalg.inv(worlds[self.root])
        result=np.asarray([geometry[:3],*( (left @ worlds[bone] @ bind)[:3] for bone,bind in zip(self.bones,self.binds))],dtype='<f4')
        if not np.isfinite(result).all() or np.any(np.abs(result)>1e8):raise ValueError('Invalid native bone palette')
        return result

    def export_weights(self,folder):
        """Keep every native influence, including duplicate entries and sums != 1."""
        import hashlib
        cached=getattr(self,'_weight_file',None)
        if cached and cached[0]==folder and(folder/cached[1]).is_file():return cached[1]
        records=[[] for _ in range(self.vertex_count)]
        for bone,(ids,weights) in enumerate(self.weight_sets,1):
            for index,value in zip(ids,weights):records[index].append((bone,float(value)))
        ranges=[];entries=[]
        for i,row in enumerate(records):
            if self.sums[i]<1e-5:row=[(0,1.)]
            ranges.append((len(entries),len(row)));entries.extend(row)
        if len(entries)>524288:raise ValueError('Native skin exceeds sparse influence budget')
        payload=struct.pack('<4sIII',b'USK1',self.vertex_count,len(entries),len(self.bones)+1)+np.asarray(ranges,dtype='<u4').tobytes()+np.asarray(entries,dtype='<f4').tobytes()
        digest=hashlib.sha256(payload).hexdigest();target=folder/'meshes'/f'{digest}.uskin'
        publish_asset(target,payload)
        result='meshes/'+target.name;self._weight_file=(folder,result)
        return result

    def deform(self,worlds=None,strict=False,vertices=None):
        worlds={} if worlds is None else worlds
        def get(node):
            if node not in worlds:
                if strict:
                    raise ValueError(f'Missing captured bone/node {node:#x}')
                worlds[node]=world_matrix(self.r,node)
            return worlds[node]
        geometry=get(self.shape)
        left=geometry @ self.skin_transform @ np.linalg.inv(get(self.root))
        vertices=self.vertices if vertices is None else np.asarray(vertices,dtype=np.float64)
        if vertices.shape!=self.vertices.shape or not np.isfinite(vertices).all():raise ValueError('Invalid resolved skin morph vertices')
        result=np.zeros_like(vertices)
        for bone,bind,(ids,weights) in zip(self.bones,self.binds,self.weight_sets):
            if not len(ids):
                continue
            transform=left @ get(bone) @ bind
            positions=vertices[ids] @ transform[:3,:3].T + transform[:3,3]
            np.add.at(result,ids,positions*weights[:,None])
        unused=self.sums<1e-5
        if unused.any():
            result[unused]=vertices[unused] @ geometry[:3,:3].T+geometry[:3,3]
        if not np.isfinite(result).all() or np.abs(result).max()>1e8:
            raise ValueError('Invalid skinned vertex positions')
        return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--output')
    args=parser.parse_args()
    reader=Reader(args.pid)
    try:
        shapes=SceneReader(reader).collect()['shapes']
        rows=[]
        for shape in shapes:
            if shape['skin']=='0x0':
                continue
            skin=Skin(reader,shape)
            points=skin.deform()
            bound=struct.unpack('<4f',reader.read(int(shape['id'],16)+0x1C,16))
            distances=np.linalg.norm(points-np.array(bound[:3]),axis=1)
            rows.append({'name':shape['name'],'id':shape['id'],'vertices':len(points),'bones':len(skin.bones),
                         'engine_bound':bound,'max_distance_from_engine_center':float(distances.max()),
                         'min_weight_sum':float(skin.sums.min()),'max_weight_sum':float(skin.sums.max()),
                         'within_engine_bound':bool(distances.max()<=bound[3]*1.1+2)})
        if args.output:
            from pathlib import Path
            Path(args.output).write_text(json.dumps(rows,indent=2),encoding='utf-8')
        print(json.dumps({'shapes':len(rows),'within_engine_bounds':sum(row['within_engine_bound'] for row in rows),'examples':rows[:3]},indent=2))
    finally:
        reader.close()

if __name__=='__main__':
    main()
