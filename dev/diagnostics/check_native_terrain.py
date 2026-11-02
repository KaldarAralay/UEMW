"""Two real native paint boundaries, same-session shader A/B; no save/video."""
import hashlib
import json
import math
import shutil
import struct
import subprocess
import sys
import time
import numpy as np
from PIL import Image
from live_probe import ROOT
from acceptance_step import look
from input_backend import require_foreground,move
from check_native_visuals import console,wait,live,read_json,capture
from check_native_motion import witness
from check_normal_play import feet
from interior_catalog import records,fields
from water_test_fixture import heights
from scene_reader import SceneReader
from loaded_cells import render_cells

def aim(reader,target):
    """Calibrate against native camera response, including OS mouse scaling."""
    gains=[.002,.002]
    def angles():
        camera=reader.camera_sample()['camera'];f=camera['forward']
        return camera,[math.atan2(f[0],f[1]),math.asin(max(-1,min(1,f[2])))]
    for _ in range(12):
        camera,before=angles();d=[target[i]-camera['position'][i]for i in range(3)]
        yaw=math.atan2(d[0],d[1]);pitch=math.atan2(d[2],math.hypot(d[0],d[1]))
        error=[(yaw-before[0]+math.pi)%(2*math.pi)-math.pi,before[1]-pitch]
        if max(map(abs,error))<.012:return
        counts=[max(-256,min(256,round(error[i]/gains[i])))for i in range(2)]
        move(reader,*counts);time.sleep(.15);_,after=angles()
        change=[(after[0]-before[0]+math.pi)%(2*math.pi)-math.pi,before[1]-after[1]]
        for i in range(2):
            if abs(counts[i])>3 and .0002<abs(change[i]/counts[i])<.03:gains[i]=change[i]/counts[i]
    raise RuntimeError('Native camera did not settle on the terrain boundary')

def run(reader):
    require_foreground(reader);saves=ROOT/'local/Morrowind/Saves'
    original={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(version=1,passed=False,recording=False,shots=[],console_commands=[],started_unix_ns=time.time_ns())
    renderer=wait(lambda:live(reader),10)['renderer_pid']
    def ready():
        w=live(reader,renderer)
        return w if w and not w.get('partial_geometry') and w.get('terrain_layers',0)>0 else None
    try:
        console(reader,'set gamehour to 12',report);look(reader,0,-.5);wait(ready,25)
        w=witness([]);catalog=read_json(ROOT/'local/assets'/w['render_catalog'],16*1024*1024)
        tiles={tuple(v['terrain_tile']):v for v in catalog['meshes'].values()if 'terrain_tile'in v}
        if len(tiles)<256:raise RuntimeError('No complete native terrain assignments')
        terrain={}
        needed={(x//16,y//16)for x,y in tiles}
        for kind,payload in records(ROOT/'local/Morrowind/Data Files/Morrowind.esm'):
            if kind!=b'LAND':continue
            f=dict(fields(payload));grid=struct.unpack('<2i',f[b'INTV'])
            if grid in needed:terrain[grid]=heights(f[b'VHGT'])
            if len(terrain)==len(needed):break
        def elevation(x,y):
            grid=(math.floor(x/8192),math.floor(y/8192));a=terrain[grid]
            u=(x-grid[0]*8192)/128;v=(y-grid[1]*8192)/128;i=min(63,math.floor(u));j=min(63,math.floor(v));fx=u-i;fy=v-j
            return float((a[j,i]*(1-fx)+a[j,i+1]*fx)*(1-fy)+(a[j+1,i]*(1-fx)+a[j+1,i+1]*fx)*fy)
        # A valid LAND edge may be underneath a large placed rock. Avoid opaque
        # native object bounds along both the standing position and sight line.
        base=reader.snapshot();graph=SceneReader(reader).collect(cells=render_cells(reader,base),view_roots=base['view_roots'],aux_roots=base['aux_roots'])
        blockers=[]
        for shape in graph['shapes']:
            if shape.get('terrain')or shape.get('alpha_mode')!='opaque':continue
            bound=struct.unpack('<4f',reader.read(int(shape['id'],16)+0x1c,16))
            if np.isfinite(bound).all()and 30<bound[3]<1800:blockers.append(bound)
        def clear(stand,target):
            start=np.asarray(stand)+[0,0,115];delta=np.asarray(target)-start;length=float(delta@delta)
            for bound in blockers:
                center=np.asarray(bound[:3]);t=float(np.clip((center-start)@delta/length,0,1))
                if np.linalg.norm(center-(start+t*delta))<bound[3]+15:return False
            return True
        candidates=[];position=feet(reader)
        for (x,y),a in tiles.items():
            for axis in (0,1):
                other=(x+1,y)if axis==0 else(x,y+1);b=tiles.get(other)
                if not b or a['texture']==b['texture']:continue
                edge=[(x+1)*512,(y+.5)*512]if axis==0 else[(x+.5)*512,(y+1)*512]
                stand=[edge[0]-220,edge[1]]if axis==0 else[edge[0],edge[1]-220]
                try:z=elevation(*stand);target_z=elevation(*edge)
                except KeyError:continue
                if z<40 or target_z<30 or abs(z-target_z)>80 or math.dist(stand,position[:2])>9000:continue
                if not clear([*stand,z+12],[*edge,target_z]):continue
                names=(a.get('source_texture','')+' '+b.get('source_texture','')).lower()
                preferred='grass'in names and any(t in names for t in ('dirt','road','mud'))
                cross=(x//16,y//16)!=(other[0]//16,other[1]//16)
                candidates.append(dict(score=(z>180,not preferred,math.dist(stand,position[:2])),cross=cross,stand=[*stand,z+12],target=[*edge,target_z],tiles=[[x,y],list(other)],textures=[a['source_texture'],b['source_texture']]))
        if not candidates:raise RuntimeError('No dry nearby native paint boundary')
        first=min(candidates,key=lambda c:c['score']);crosses=[c for c in candidates if c['cross']]
        cases=[('near-boundary',first)]+([('cell-boundary',min(crosses,key=lambda c:c['score']))]if crosses else[])
        report['cross_cell_candidate_found']=bool(crosses);report['native_terrain_tiles']=len(tiles)
        for case,fixture in cases:
            report.setdefault('fixtures',[]).append(dict(case=case,**fixture))
            console(reader,'player->Position '+' '.join(f'{v:.3f}'for v in fixture['stand'])+' 0',report)
            # Native cell loading and the asynchronous renderer can complete at
            # different times after a teleport. Require this actual tile pair
            # in the final assignment map, then wait for its identity to settle.
            time.sleep(4);last_signature=None;stable_since=time.monotonic()
            def settled():
                nonlocal last_signature,stable_since
                w=ready()
                if not w or w['retaining_catalog']:return None
                if w['terrain_signature']!=last_signature:last_signature=w['terrain_signature'];stable_since=time.monotonic();return None
                if time.monotonic()-stable_since<2:return None
                definitions=read_json(ROOT/'local/assets'/w['render_catalog'],16*1024*1024)['meshes'].values()
                actual={tuple(v['terrain_tile']):v.get('source_texture')for v in definitions if 'terrain_tile'in v}
                return w if all(actual.get(tuple(tile))==texture for tile,texture in zip(fixture['tiles'],fixture['textures']))else None
            wait(settled,25)
            aim(reader,fixture['target'])
            for enabled in (False,True):
                w=witness([],terrain_blend=enabled);time.sleep(.3);wait(ready,10)
                label='blended'if enabled else'original'
                w=witness([]);captured=ROOT/capture(f'terrain-{case}-{label}');dest=ROOT/f'logs/terrain-{case}-{label}.png';shutil.copyfile(captured,dest)
                with Image.open(dest)as im:visible=float(np.mean(np.max(np.asarray(im.convert('RGB').crop((250,180,1670,980)).resize((128,72))),axis=2)>5))
                if visible<.05:raise RuntimeError('Terrain capture contains no visible scene')
                if w['terrain_blending']!=enabled:raise RuntimeError('Terrain comparison mode did not apply')
                if not w['terrain_materials'] or w['terrain_bound_materials']!=w['terrain_materials'] or w['terrain_active_materials']!=(w['terrain_materials']if enabled else 0):raise RuntimeError('Terrain material bindings did not match the requested comparison')
                report['shots'].append(dict(case=case,profile=label,image=str(dest.relative_to(ROOT)),witness=w,camera=reader.camera_sample()['camera']))
            a,b=[s['camera']for s in report['shots'][-2:]]
            if report['shots'][-2]['witness']['terrain_signature']!=report['shots'][-1]['witness']['terrain_signature']:raise RuntimeError('Terrain assignment changed between captures; comparison rejected')
            position_error=math.dist(a['position'],b['position']);direction_error=math.dist(a['forward'],b['forward'])
            report.setdefault('camera_comparisons',[]).append(dict(case=case,position_error=position_error,direction_error=direction_error))
            if position_error>3 or direction_error>.01:raise RuntimeError('Native camera moved during terrain comparison; captures are not comparable')
            images=[np.asarray(Image.open(ROOT/s['image']).convert('RGB'),dtype=np.int16)[240:940,360:1100]for s in report['shots'][-2:]]
            difference=np.max(np.abs(images[0]-images[1]),axis=2);changed=float(np.mean(difference>8))
            report.setdefault('pixel_comparisons',[]).append(dict(case=case,changed_fraction=changed))
            if changed<.01:raise RuntimeError('Blend toggle did not visibly change the terrain view')
        for enabled in (False,True):
            witness([],terrain_blend=enabled);m=read_json(ROOT/'local/bridge/latest.json');label='blended'if enabled else'original';path=ROOT/f'logs/terrain-{label}-benchmark.json'
            subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','5','--warmup','2','--output',str(path),'--grid',*map(str,m['cell_grid'])],check=True,timeout=15,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        try:witness([],terrain_blend=True)
        except (OSError,ValueError,RuntimeError):pass
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in original.items())
        report['passed']=report['passed']and report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns()
        (ROOT/'logs/native-terrain.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
