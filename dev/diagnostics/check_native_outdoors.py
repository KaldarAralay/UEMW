"""Short real outdoor/water comparison; native console/input, no save writes."""
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from PIL import Image
from live_probe import ROOT
from acceptance_step import look
from input_backend import require_foreground,pulse
from check_normal_play import console,wait,live,feet
from check_native_motion import witness,source_frame
from local_files import read_json as _read_json
from native_environment import capture as environment
from water_test_fixture import deep_water,heights
from interior_catalog import records,fields

def read_json(path,limit=1024*1024):return wait(lambda:_read_json(path,limit),3)

def run(reader):
    require_foreground(reader);label=os.environ.get('UEMW_OUTDOOR_LABEL','after')
    if label not in ('before','after'):raise ValueError('Expected before/after comparison label')
    saves=ROOT/'local/Morrowind/Saves';existing={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(version=1,label=label,passed=False,recording=False,started_unix_ns=time.time_ns(),shots=[],console_commands=[],benchmarks=[])
    renderer=wait(lambda:live(reader),10)['renderer_pid'];original=feet(reader)
    def complete():
        w=live(reader,renderer)
        return w if w and not w.get('partial_geometry') else None
    def command(text):console(reader,text,report)
    def aim(target):
        cam=reader.camera_sample()['camera']['position'];d=[target[i]-cam[i]for i in range(3)]
        look(reader,math.atan2(d[0],d[1]),math.atan2(d[2],math.hypot(d[0],d[1])))
    def shot(case,benchmark=False):
        wait(complete,25);m=read_json(ROOT/'local/bridge/latest.json')
        if benchmark:
            path=ROOT/f'logs/outdoor-{label}-{case}-benchmark.json'
            location=['--grid',*map(str,m['cell_grid'])]if m.get('cell_grid')is not None else['--cell',m['cell']]
            subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','5','--warmup','3','--output',str(path),*location],check=True,timeout=15,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            report['benchmarks'].append(str(path.relative_to(ROOT)))
        flag=ROOT/'local/bridge/capture.once';source=ROOT/'logs/ue-inspect.png';target=ROOT/f'logs/outdoor-{label}-{case}.png'
        for attempt in range(3):
            wait(complete,15);w=witness([]);packet,_=source_frame(w);m=read_json(ROOT/'local/bridge/latest.json')
            stamp=time.time_ns();flag.write_text(str(stamp))
            def captured():
                if not source.exists()or source.stat().st_mtime_ns<stamp:return None
                shutil.copyfile(source,target)
                with Image.open(target)as img:img.verify()
                return True
            try:wait(captured,6)
            finally:flag.unlink(missing_ok=True)
            with Image.open(target)as img:
                sample=np.asarray(img.convert('RGB').crop((250,180,1670,980)).resize((128,72)))
                scene_pixels=float(np.mean(np.max(sample,axis=2)>5))
            if scene_pixels>.05:break
            rejected=target.with_name(target.stem+f'-rejected-{attempt+1}.png');shutil.copyfile(target,rejected)
            report.setdefault('rejected_captures',[]).append(str(rejected.relative_to(ROOT)));time.sleep(.5)
        else:raise RuntimeError('No visible live scene in three bounded capture attempts')
        report['shots'].append(dict(case=case,image=str(target.relative_to(ROOT)),witness=w,environment=packet['environment'],camera=m['camera'],cell=m['cell'],scene_pixel_fraction=scene_pixels))
    try:
        command('set gamehour to 12');look(reader,0,-.10);pulse(reader,'key',0x20,.7)
        base=reader.render_metadata();env=environment(reader,base);fog=reader.u32(int(base['data'],16)+0x9c)
        report['native_fog_property']=dict(pointer=hex(fog),raw=reader.read(fog+0x14,12).hex(),decoded=env)
        shot('horizon-day',True)
        command('set gamehour to 21');time.sleep(.5);shot('horizon-night')
        command('set gamehour to 12')
        grid=tuple(base['cell_grid']);water=env['water_level'];deep=deep_water(grid,original,water);report['deep_fixture']=deep
        elevations=None
        for kind,payload in records(ROOT/'local/Morrowind/Data Files/Morrowind.esm'):
            if kind==b'LAND':
                data=dict(fields(payload))
                if struct.unpack('<2i',data[b'INTV'])==grid:elevations=heights(data[b'VHGT']);break
        if elevations is None:raise RuntimeError('Installed shore LAND not found')
        choices=[]
        for y in range(2,63):
            for x in range(2,63):
                h=float(elevations[y,x])
                if not water+24<=h<=water+160:continue
                p=[grid[0]*8192+x*128,grid[1]*8192+y*128,h+4]
                choices.append((math.dist(p[:2],deep['position']),p))
        if not choices:raise RuntimeError('No low shore in native LAND fixture')
        shore=min(choices)[1];report['shore_fixture']=shore
        def place(point):command('player->Position '+' '.join(f'{v:.3f}'for v in point)+' 0')
        place(shore);aim([*deep['position'],water]);time.sleep(.6);shot('water-shore',True)
        if os.environ.get('UEMW_WATER_DEBUG')=='1':
            for mode in (0,2):
                witness([],water_fog_mode=mode);time.sleep(.3);shot('water-depth-debug-'+str(mode))
            witness([],water_fog_mode=1)
        from check_native_water import water_witness
        report['surface_state']=wait(lambda:water_witness(reader,False,renderer),12)
        time.sleep(.3);report['surface_animated']=wait(lambda:water_witness(reader,False,renderer),8)
        if report['surface_state']['texture_frames']==report['surface_animated']['texture_frames']:raise RuntimeError('Native surface animation did not advance')
        place([*deep['position'],water-220]);aim([shore[0],shore[1],water-80])
        report['submerged_state']=wait(lambda:water_witness(reader,True,renderer),15);shot('underwater',True)
        before=feet(reader);pulse(reader,'key',0x11,.3);after=feet(reader)
        report['native_swim_distance']=math.dist(before,after)
        if report['native_swim_distance']<2:raise RuntimeError('Native underwater movement did not advance')
        place(shore);aim([*deep['position'],water]);report['resurfaced_state']=wait(lambda:water_witness(reader,False,renderer),12)
        shot('resurfaced');report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in existing.items())
        report['ended_unix_ns']=time.time_ns();report['passed']=report['passed']and report['existing_saves_preserved']
        (ROOT/f'logs/outdoor-{label}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
