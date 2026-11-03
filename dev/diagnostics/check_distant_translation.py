"""Compare installed distant-source translation with current original buffers.

Read-only, no game commands, saves, screenshots or substitute scene. Reports
float32 world-coordinate quantization separately from actual source topology.
"""
import argparse,json,math,struct
from pathlib import Path
import numpy as np
from live_probe import Reader,ROOT
from game_assets import Bsa,normalized
from scene_reader import SceneReader
from tes3_world import WorldIndex
from distant_native import rotation
from nif_static import shapes,UnsupportedNif
from terrain_layout import native_tile
from distant_terrain import texture_grid


def stem(name):return normalized(name).replace('textures/','').rsplit('.',1)[0]


def run(r):
    world=WorldIndex(ROOT/'local/Morrowind/Data Files');snapshot=r.snapshot();archives=[Bsa(ROOT/'local/Morrowind/Data Files'/name)for name in('Morrowind.bsa','Tribunal.bsa','Bloodmoon.bsa')]
    report=dict(passed=False,recording=False,save_writes=False,geometry=[],terrain=[],unsupported=[],scope='Installed data versus actual current original buffers. World transforms allow recorded float32 composition quantization; no displayed-frame claim.')
    try:
        chosen=[]
        for ref in snapshot['objects']:
            if ref['type']=='STAT'and ref['node']!='0x0'and ref['base_id']in world.models and ref['base_id']not in{v['base_id']for v in chosen}:chosen.append(ref)
            if len(chosen)>=6:break
        for ref in chosen:
            key='meshes/'+normalized(world.models[ref['base_id']]);blob=next((data for a in reversed(archives)if(data:=a.read(key))is not None),None)
            if blob is None:raise RuntimeError('Installed static model is missing: '+key)
            try:source=shapes(blob)
            except UnsupportedNif as error:report['unsupported'].append(dict(model=key,reason=str(error)));continue
            actual=SceneReader(r).collect(roots=[int(ref['node'],16)]);used=set();scale=((ref['flags']>>16)or 1000)*.001
            for shape in source:
                predicted=shape['points']@np.asarray(rotation(ref['orientation'])).reshape(3,3).T*scale+ref['position'];matches=[]
                for native in actual['shapes']:
                    if native['id']in used or native['name']!=shape['name']or native['vertex_count']!=len(predicted):continue
                    h=r.read(int(native['model'],16),0x48);p=np.frombuffer(r.read(struct.unpack_from('<I',h,0x1c)[0],native['vertex_count']*12),dtype='<f4').reshape(-1,3)
                    t=native['transform'];expected=p@np.asarray(t['rotation']).reshape(3,3).T*t['scale']+t['position'];error=float(np.abs(expected-predicted).max());matches.append((error,native,expected))
                if not matches:raise RuntimeError('Installed static shape has no original counterpart: '+shape['name'])
                error,native,expected=min(matches,key=lambda v:v[0]);used.add(native['id'])
                tolerance=max(.001,float(abs(np.spacing(np.float32(np.max(np.abs(expected))))))*2)
                report['geometry'].append(dict(model=key,name=shape['name'],vertices=len(predicted),max_world_error=error,float32_tolerance=tolerance))
                if error>tolerance:raise RuntimeError('Installed/native static transform mismatch: '+shape['name'])
        if not report['geometry']:raise RuntimeError('No supported actual static geometry was compared')
        grid=snapshot.get('cell_grid')
        if grid:
            land=world.terrain(grid);cell=int(snapshot['cell_ptr'],16);pointer=r.u32(cell+0x20);root=r.u32(pointer+0x10)if pointer else 0
            if root and land and 'VTEX'in land:
                tiles=texture_grid(land['VTEX']);graph=SceneReader(r).collect(roots=[root])
                for s in graph['shapes'][::8]:
                    if s['vertex_count']!=25 or s['triangle_count']!=32:continue
                    h=r.read(int(s['model'],16),0x48);p=np.frombuffer(r.read(struct.unpack_from('<I',h,0x1c)[0],25*12),dtype='<f4').reshape(25,3);uv=np.frombuffer(r.read(struct.unpack_from('<I',h,0x28)[0],25*8),dtype='<f4').reshape(25,2);tile=native_tile(p,uv,s['transform'])
                    if tile is None:continue
                    x,y=tile[0]-grid[0]*16,tile[1]-grid[1]*16
                    if not 0<=x<16 or not 0<=y<16:continue
                    index=int(tiles[y,x]);texture=world.textures.get((land['texture_source'],index-1))if index else'_land_default.tga'
                    t=s['transform'];points=p@np.asarray(t['rotation']).reshape(3,3).T*t['scale']+t['position'];ix=np.rint((points[:,0]-grid[0]*8192)/128).astype(int);iy=np.rint((points[:,1]-grid[1]*8192)/128).astype(int)
                    if (ix<0).any()or(ix>64).any()or(iy<0).any()or(iy>64).any():raise RuntimeError('Original LAND sample coordinate escaped its cell')
                    height_error=float(np.abs(points[:,2]-land['heights'][iy,ix]).max())
                    row=dict(tile=tile,index=index,installed=texture,native=s['texture'],vertices=25,max_height_error=height_error);report['terrain'].append(row)
                    if height_error>.001:raise RuntimeError('Installed/native terrain height differs')
                    if texture is None or stem(texture)!=stem(s['texture']):raise RuntimeError('Installed/native terrain texture assignment differs')
        report['passed']=True;return report
    finally:
        for a in archives:a.close()
        (ROOT/'logs/distant08-translation-parity.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);args=p.parse_args();r=Reader(args.pid)
    try:
        result=run(r);print(json.dumps(dict(passed=result['passed'],shapes=len(result['geometry']),vertices=sum(x['vertices']for x in result['geometry']),terrain_tiles=len(result['terrain']),unsupported=result['unsupported']),indent=2))
    finally:r.close()
