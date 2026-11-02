"""Two native interior lighting views; no surveys, save writes or video."""
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from live_probe import ROOT
from check_normal_play import console,wait,live,feet
from check_native_visuals import capture,read_json
from check_native_motion import witness,source_frame
from check_native_terrain import aim
from acceptance_step import look
from input_backend import require_foreground,pulse
from native_ui import inspect_ui

def run(reader):
    require_foreground(reader);label=os.environ['UEMW_INTERIOR_LABEL']
    if label not in ('before','after'):raise ValueError('Invalid interior label')
    saves=ROOT/'local/Morrowind/Saves';hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(passed=False,label=label,recording=False,save_writes=False,console_commands=[],shots=[],walk=[],started_unix_ns=time.time_ns())
    renderer=wait(lambda:live(reader),15)['renderer_pid']
    def accepted():
        source=read_json(ROOT/'local/bridge/latest.json');w=witness([])
        report['last_wait_state']=dict(source_cell=source.get('cell'),source_status=source.get('status'),source_menu=source.get('menu'),source_epoch=source.get('scene_epoch'),witness={k:w.get(k)for k in ('live','status','scene_epoch','partial_geometry','native_menu_open','interior_lighting','interior_ambient_probe','interior_probe_ready','native_light_ids')})
        if source.get('status')!='live'or source.get('menu')or not 0<=time.time_ns()-source.get('sample_unix_ns',0)<500_000_000:return None
        if not w.get('live')or w.get('renderer_pid')!=renderer or w.get('pid')!=reader.pid or w.get('scene_epoch')!=source.get('scene_epoch')or w.get('partial_geometry'):return None
        if label=='after' and w.get('interior_lighting') and not w.get('interior_ambient_probe'):return None
        packet,digest=source_frame(w)
        return w,packet,digest
    def shot(case):
        w,p,digest=wait(accepted,20);report['shots'].append(dict(case=case,image=capture('interior-'+label+'-'+case),witness=w,camera=reader.camera_sample()['camera'],environment=p['environment'],source_md5=digest))
    def pair(case):
        if label=='after':
            witness([],interior_lighting=False);time.sleep(.4);shot(case+'-reference')
            witness([],interior_lighting=True);time.sleep(.4)
        shot(case)
    def command(text):
        try:console(reader,text,report)
        except RuntimeError:
            if not text.lower().startswith('coc '):raise
            if inspect_ui(reader)['active_menus']==['MenuConsole']:pulse(reader,'key',0x29,.12)
            wait(lambda:not inspect_ui(reader)['native_ui'],20)
    try:
        if reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        command('tgm') # disposable fixture protection; native AI/animation continues
        for name,cell in (('room',"Seyda Neen, Arrille's Tradehouse"),('cave','Addamasartus')):
            command('coc "'+cell+'"')
            wait(lambda:reader.snapshot()['cell']==cell,20);w,p,digest=wait(accepted,25)
            s=reader.snapshot()
            if name=='room':
                npcs=[o for o in s['objects']if o['type']=='NPC_'];target=next((o for o in npcs if o['base_id'].lower().startswith('arrille')),None)
                if target:aim(reader,[target['position'][0],target['position'][1],target['position'][2]+100])
            else:
                lights=p['environment']['lights'];camera=reader.camera_sample()['camera']['position']
                candidates=[v for v in lights if v['kind']>1 and 90<math.dist(v['position'],camera)<1200]
                if candidates:aim(reader,min(candidates,key=lambda v:math.dist(v['position'],camera))['position'])
            pair(name)
            out=ROOT/f'logs/interior-{label}-{name}-benchmark.json'
            with (ROOT/f'logs/interior-{label}-{name}-benchmark-command.log').open('w')as log:
                subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','5','--warmup','1','--cell',cell,'--output',str(out)],stdout=log,stderr=subprocess.STDOUT,timeout=18,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
            camera=reader.camera_sample()['camera'];forward=camera['forward'];yaw=math.atan2(forward[0],forward[1]);pitch=math.asin(max(-1,min(1,forward[2])))
            start=feet(reader)
            for i,key in enumerate((0x11,0x1f,0x20,0x1e)):
                pulse(reader,'key',key,.18);look(reader,yaw+(.10 if i%2 else-.10),pitch)
                w,p,_=wait(accepted,8);report['walk'].append(dict(case=name,sequence=w['sequence'],camera=reader.camera_sample()['camera'],witness=w,native_lights=p['environment']['lights']))
            report.setdefault('movement',{})[name]=math.dist(start,feet(reader))
            shot(name+'-moved')
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items());report['passed']&=report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns();(ROOT/f'logs/interior-lighting-{label}.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
