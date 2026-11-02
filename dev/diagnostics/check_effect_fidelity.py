"""Short real native flame/smoke/glass/spell fixture; no saves or video."""
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
import numpy as np
from live_probe import ROOT
from check_normal_play import console,live,wait,feet
from check_native_motion import witness,source_frame
from check_native_visuals import capture,read_json
from check_native_terrain import aim
from check_native_combat import observe,submitted
from native_motion_fixture import native_grid_fixture
from input_backend import pulse,require_foreground
from native_ui import inspect_ui
from native_ui_test import act,tree

TOKENS=('firealpha','fireglow','firelight','firespark','smoke','glass','flame','spark','alpha_')

def run(reader):
    require_foreground(reader);label=os.environ['UEMW_EFFECT_LABEL']
    if label not in ('before','after'):raise ValueError('Invalid effect label')
    saves=ROOT/'local/Morrowind/Saves';hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(passed=False,label=label,recording=False,save_writes=False,console_commands=[],shots=[],samples=[],started_unix_ns=time.time_ns())
    renderer=wait(lambda:live(reader),15)['renderer_pid']
    def accepted():
        w=witness([])
        if not w.get('live'):return None
        packet,digest=source_frame(w);c=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
        ids=[b['id']for b in c['bindings']if any(t in c['meshes'][b['asset']].get('source_texture','').lower()for t in TOKENS)][:64]
        w=witness(ids);packet,digest=source_frame(w);c=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024);indices={b['id']:i for i,b in enumerate(c['bindings'])};rows=[]
        for row in w['instances']:
            if not row['submitted_visible']or row['id']not in indices:continue
            state=packet['instance_states'][indices[row['id']]];payload=state[2]if len(state)>2 else None;values={}
            if not state[0]:raise RuntimeError('Natively hidden effect was displayed')
            if isinstance(payload,dict)and'palette'in payload:values['palette']=payload['palette']
            elif payload is not None:
                values['points']=payload['points']if isinstance(payload,dict)else payload
                for field in ('colors','uvs'):
                    value=payload.get(field)if isinstance(payload,dict)else state[3]if field=='colors'and len(state)>3 else None
                    if value is not None:values[field]=value
            else:values['transform']=state[1]
            md5={k:hashlib.md5(np.asarray(v,dtype='<f4').tobytes()).hexdigest()for k,v in values.items()}
            if any(row.get(k+'_md5','').lower()!=v for k,v in md5.items()):raise RuntimeError('Submitted effect attributes differ from exact source frame')
            definition=c['meshes'][row['asset']]
            rows.append(dict(id=row['id'],asset=row['asset'],source_texture=definition.get('source_texture'),alpha_mode=definition['alpha_mode'],shading=definition.get('shading'),hashes=md5))
        return dict(witness=w,source_md5=digest,sequence=w['sequence'],environment=packet['environment'],rows=rows)
    def shot(case):
        state=wait(accepted,8)
        if not state['rows']:raise RuntimeError('No native effect geometry in submitted scene')
        report['shots'].append(dict(case=case,image=capture('effects-'+label+'-'+case),camera=reader.camera_sample()['camera'],**state))
    def pair(case):
        if label=='after':
            witness([],effect_quality=False);time.sleep(.25);shot(case+'-reference')
            witness([],effect_quality=True);time.sleep(.25)
        shot(case)
    def command(text):
        console(reader,text,report)
        if any('script error'in line.lower()or'not found'in line.lower()for line in report['console_output'][-1]):raise RuntimeError('Native effect fixture command rejected')
    try:
        fixture=native_grid_fixture(reader.snapshot()['cell_grid'],feet(reader));report['fixture']=fixture;p=fixture['player_position']
        delta=np.asarray(fixture['actor_position'])-p;direction=delta[:2]/np.linalg.norm(delta[:2]);heading=math.degrees(math.atan2(direction[0],direction[1]))
        target=lambda distance,height:[p[0]+direction[0]*distance,p[1]+direction[1]*distance,p[2]+height]
        command('player->Position '+' '.join(f'{v:.3f}'for v in p)+f' {heading:.3f}')
        if reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        command('set gamehour to 19')
        for item,distance in (('light_fire_small',140),('active_chimney_smoke02',230),('light_com_lantern_02',100),('misc_com_bottle_01',70)):
            command(f'PlaceAtPC "{item}" 1 {distance} 0')
        time.sleep(3);aim(reader,target(180,90));pair('flame-smoke')
        report['samples'].append(wait(accepted,8));time.sleep(.3);report['samples'].append(wait(accepted,8))
        aim(reader,target(100,20));pair('lantern-glass')
        aim(reader,target(70,15));pair('bottle')
        out=ROOT/f'logs/effects-{label}-benchmark.json'
        with (ROOT/f'logs/effects-{label}-benchmark-command.log').open('w')as log:
            subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','6','--warmup','1','--output',str(out)],stdout=log,stderr=subprocess.STDOUT,timeout=18,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        report['benchmark']=str(out.relative_to(ROOT))
        pulse(reader,'right',duration=.12);wait(lambda:'MenuMagic'in inspect_ui(reader)['active_menus'],4)
        candidates=[row for row in tree(reader,'MenuMagic')if row['text']=='Fireball'and row['rect'][2]>0]
        report['native_spell_candidates']=candidates
        if not 1<=len(candidates)<=2:raise RuntimeError('Unexpected Fireball selector set')
        candidate=max(candidates,key=lambda row:row['depth'])
        report['native_spell_selection']=act(reader,menu='MenuMagic',element=candidate['id'],click=True)
        if inspect_ui(reader)['native_ui']:pulse(reader,'right',duration=.12)
        wait(lambda:not inspect_ui(reader)['native_ui'],4)
        command('player->SetDestruction 100');command('player->SetWillpower 100')
        pulse(reader,'key',0x11,.5)
        if not reader.snapshot()['player']['magic_ready']:pulse(reader,'key',0x13,.12)
        current=feet(reader);aim(reader,[current[0]+direction[0]*150,current[1]+direction[1]*150,current[2]+600]);time.sleep(1.2)
        report['magicka_before']=reader.snapshot()['player']['magicka']
        # Screenshot requests are deliberately separate from the frame-time sample.
        from concurrent.futures import ThreadPoolExecutor
        def spell_images():
            time.sleep(.7)
            return [capture('effects-'+label+'-cast-'+str(i))for i in range(2)]
        with ThreadPoolExecutor(max_workers=1)as pool:
            shots=pool.submit(spell_images);report['spell']=observe(reader,3.2,lambda:pulse(reader,'left',duration=.15));report['spell_images']=shots.result()
        report['magicka_after']=reader.snapshot()['player']['magicka']
        if report['magicka_after'][1]>=report['magicka_before'][1]:raise RuntimeError('Native spell input did not spend magicka')
        report['native_projectile_samples']=sum(any(v['layer']=='projectile'for v in s.get('rows',[]))for s in report['spell']['samples'])
        if report['native_projectile_samples']<2:raise RuntimeError('Native projectile did not reach two exact submitted samples')
        start=feet(reader);pulse(reader,'key',0x11,.25);pulse(reader,'key',0x1f,.25);report['movement_distance']=math.dist(start,feet(reader));report['samples'].append(wait(accepted,8))
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items());report['passed']&=report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns();(ROOT/f'logs/effects-{label}.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
