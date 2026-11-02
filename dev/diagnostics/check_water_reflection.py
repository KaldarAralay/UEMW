"""Dock/shore reflection A/B on live native geometry; no saves or video."""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
import numpy as np
from PIL import Image
from live_probe import ROOT
from check_normal_play import console,live,wait,feet
from check_native_motion import witness,source_frame
from check_native_visuals import capture
from check_native_terrain import aim
from check_native_water import water_witness
from input_backend import require_foreground,pulse
from acceptance_step import look
from water_test_fixture import deep_water


def run(reader):
    require_foreground(reader);saves=ROOT/'local/Morrowind/Saves'
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(passed=False,recording=False,save_writes=False,shots=[],benchmarks=[],console_commands=[],started_unix_ns=time.time_ns())
    dock_only=os.environ.get('UEMW_REFLECTION_DOCK_ONLY')=='1'
    report['dock_only']=dock_only
    renderer=wait(lambda:live(reader),15)['renderer_pid']
    def sample():
        w=live(reader,renderer)
        if not w or w['partial_geometry']:return None
        packet,_=source_frame(w);return w,packet
    def enable(value):
        witness([],water_planar=value)
        def ready():
            w=witness([]);return w if w.get('water_planar_active')else None
        if value:wait(ready,8)
        time.sleep(.2)
    def shot(name,export=False):
        w,packet=wait(sample,15);image=capture('water-reflection-'+name)
        with Image.open(ROOT/image)as decoded:a=np.asarray(decoded.convert('RGB'))[180:980,260:1660]
        row=dict(case=name,image=image,witness=w,environment=packet['environment'],camera=reader.camera_sample()['camera'],near_white_fraction=float(np.mean(np.min(a,axis=2)>250)))
        if export:
            source=ROOT/'logs/water-reflection-target.png';stamp=time.time_ns();witness([],reflection_capture=True)
            wait(lambda:source.is_file()and source.stat().st_mtime_ns>=stamp,5)
            dest=ROOT/f'logs/reflection-target-{name}.png';shutil.copyfile(source,dest);row['reflection_target']=str(dest.relative_to(ROOT))
        report['shots'].append(row)
    def pair(name):
        enable(False);shot(name+'-reference');enable(True);shot(name+'-enhanced',True)
        a,b=report['shots'][-2:]
        if math.dist(a['camera']['position'],b['camera']['position'])>2 or np.dot(a['camera']['forward'],b['camera']['forward'])<.999:raise RuntimeError('Reference/enhanced native camera moved')
    def place(x,y,z):console(reader,f'player->Position {x} {y} {z} 0',report);time.sleep(2)
    def benchmark(name):
        out=ROOT/f'logs/water-reflection-{name}-benchmark.json';before=witness([]);started=time.monotonic()
        with(ROOT/f'logs/water-reflection-{name}-benchmark-command.log').open('w')as log:
            subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','6','--warmup','1','--grid','-2','-9','--output',str(out)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=18,creationflags=subprocess.CREATE_NO_WINDOW)
        after=witness([]);seconds=time.monotonic()-started
        report['benchmarks'].append(dict(case=name,path=str(out.relative_to(ROOT)),capture_requests=after['water_reflection_capture_requests']-before['water_reflection_capture_requests'],elapsed_seconds=seconds,capture_request_hz=(after['water_reflection_capture_requests']-before['water_reflection_capture_requests'])/seconds))
    try:
        if reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        console(reader,'set gamehour to 12',report)
        place(-9472,-72448,36);aim(reader,[-8448,-72960,0]);pair('dock-seaward')
        if dock_only:
            report['matching_native_camera_pairs']=True;report['passed']=True;return report
        place(-12032,-73436,58);aim(reader,[-12600,-72800,-35]);pair('pond-day')
        enable(False);benchmark('reference');enable(True);benchmark('enhanced')
        aim(reader,[-12250,-73160,-45]);pair('close-shore')
        first=wait(lambda:water_witness(reader,False,renderer),12);time.sleep(.4)
        second=wait(lambda:water_witness(reader,False,renderer),8)
        if first['texture_frames']==second['texture_frames']:raise RuntimeError('Original water animation did not advance')
        report['water_source_checks']=[first,second]
        before=feet(reader)
        for i,key in enumerate((0x11,0x1f,0x11,0x1f)):
            pulse(reader,'key',key,.2);wait(sample,8);shot('walk-'+str(i))
        report['walk_end_distance']=math.dist(before,feet(reader))
        point=deep_water((-2,-9),feet(reader),0);place(*point['position'],-220);look(reader,math.pi,.15)
        report['underwater']=wait(lambda:water_witness(reader,True,renderer),12)
        submerged=witness([])
        if submerged['water_planar_active']:raise RuntimeError('Surface reflection remained active underwater')
        report['underwater_reflection_disabled']=True;shot('underwater')
        place(-12032,-73436,58);aim(reader,[-12600,-72800,-35])
        report['resurfaced']=wait(lambda:water_witness(reader,False,renderer),12);enable(True)
        console(reader,'set gamehour to 19',report);time.sleep(.4);pair('pond-dusk')
        report['matching_native_camera_pairs']=True;report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        try:witness([],water_planar=True)
        except(OSError,ValueError,RuntimeError):pass
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
        report['passed']&=report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns()
        (ROOT/('logs/water-reflection-dock.json'if dock_only else'logs/water-reflection-live.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
