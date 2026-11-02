"""Three bounded native views for texture/material comparison; no saves or video."""
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import time
import numpy as np
import psutil
from PIL import Image
from live_probe import ROOT
from acceptance_step import look
from input_backend import require_foreground, pulse
from check_native_visuals import console, wait, live, read_json
from check_native_motion import witness
from scene_reader import SceneReader
from native_ui import inspect_ui


def run(reader):
    require_foreground(reader)
    label=os.environ.get('UEMW_TEXTURE_LABEL','after')
    prefix=os.environ.get('UEMW_TEXTURE_PREFIX','texture')
    if prefix not in ('texture','hd'):raise ValueError('Invalid texture fixture prefix')
    if label not in ('before','after'):raise ValueError('Expected before/after')
    saves=ROOT/'local/Morrowind/Saves'
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in saves.glob('*.ess')}
    report=dict(version=1,label=label,passed=False,recording=False,shots=[],console_commands=[],started_unix_ns=time.time_ns())
    renderer=wait(lambda:live(reader),10)['renderer_pid']
    def command(text):
        try:console(reader,text,report)
        except RuntimeError:
            if not text.lower().startswith('coc '):raise
            if inspect_ui(reader)['active_menus']==['MenuConsole']:pulse(reader,'key',0x29,.15)
            wait(lambda:not inspect_ui(reader)['native_ui'],18)
    def complete():
        w=live(reader,renderer)
        return w if w and not w.get('partial_geometry') else None
    def aim(target):
        camera=reader.camera_sample()['camera']['position'];d=[target[i]-camera[i] for i in range(3)]
        look(reader,math.atan2(d[0],d[1]),math.atan2(d[2],math.hypot(d[0],d[1])))
    def shot(case,measure=False):
        wait(complete,25);m=read_json(ROOT/'local/bridge/latest.json')
        if measure:
            path=ROOT/f'logs/{prefix}-{label}-{case}-benchmark.json'
            location=['--grid',*map(str,m['cell_grid'])] if m.get('cell_grid') is not None else ['--cell',m['cell']]
            subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','5','--warmup','3','--output',str(path),*location],check=True,timeout=15,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        flag=ROOT/'local/bridge/capture.once';source=ROOT/'logs/ue-inspect.png';dest=ROOT/f'logs/{prefix}-{label}-{case}.png'
        for attempt in range(3):
            wait(complete,12);w=witness([]);stamp=time.time_ns();flag.write_text(str(stamp))
            try:
                wait(lambda:source.exists() and source.stat().st_mtime_ns>=stamp,6)
                shutil.copyfile(source,dest)
            finally:flag.unlink(missing_ok=True)
            with Image.open(dest) as img:visible=float(np.mean(np.max(np.asarray(img.convert('RGB').crop((250,180,1670,980)).resize((128,72))),axis=2)>5))
            if visible>.05:break
            shutil.copyfile(dest,dest.with_name(dest.stem+f'-rejected-{attempt+1}.png'));time.sleep(.5)
        else:raise RuntimeError('No live scene in bounded capture attempts')
        memory={}
        for key,pid in [('native',reader.pid),('renderer',renderer)]:
            memory[key+'_resident_bytes']=psutil.Process(pid).memory_info().rss
        report['shots'].append(dict(case=case,image=str(dest.relative_to(ROOT)),witness=w,memory=memory,camera=reader.camera_sample()['camera'],visible_fraction=visible))
    try:
        command('set gamehour to 12');look(reader,0,-.10);pulse(reader,'key',0x20,.7)
        look(reader,-.8,-.12);shot('masonry',True)
        base=reader.snapshot();graph=SceneReader(reader).collect(view_roots=base['view_roots'],aux_roots=base['aux_roots'])
        leaves=[];camera=base['camera']['position']
        for s in graph['shapes']:
            if s.get('alpha_mode') in ('masked','translucent') and any(t in s.get('texture','').lower() for t in ('leaves',)):
                bound=struct.unpack('<4f',reader.read(int(s['id'],16)+0x1c,16))
                if 100<bound[3]<2400 and math.dist(bound[:3],camera)<3000:leaves.append((math.dist(bound[:3],camera),s,bound))
        if not leaves:raise RuntimeError('Native comparison foliage not found')
        _,shape,bound=min(leaves,key=lambda x:x[0]);aim(bound[:3]);report['foliage_target']=dict(texture=shape['texture'],bound=bound)
        shot('foliage')
        command('coc "Seyda Neen, Arrille\'s Tradehouse"')
        wait(lambda:read_json(ROOT/'local/bridge/latest.json').get('cell')=="Seyda Neen, Arrille's Tradehouse",15)
        s=reader.snapshot();target=next((o for o in s['objects'] if o['type']=='NPC_' and o.get('name')=='Arrille'),None)
        if target:aim([target['position'][0],target['position'][1],target['position'][2]+80])
        shot('interior-materials',True);report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['existing_saves_preserved']=all((saves/n).is_file() and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
        report['passed']=report['passed'] and report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns()
        (ROOT/f'logs/{prefix}-{label}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
