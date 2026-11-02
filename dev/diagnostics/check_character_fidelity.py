"""Short native character/hand comparisons. No saves or video recording."""
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import time
import numpy as np
from live_probe import ROOT
from check_normal_play import console,live,wait,feet
from check_native_motion import witness,source_frame
from check_native_visuals import capture,read_json
from check_native_terrain import aim
from check_native_combat import submitted
from native_motion_fixture import native_grid_fixture
from scene_reader import SceneReader
from input_backend import require_foreground,pulse


def run(reader):
    require_foreground(reader);label=os.environ['UEMW_CHARACTER_LABEL']
    if label not in ('before','after'):raise ValueError('Invalid character comparison label')
    saves=ROOT/'local/Morrowind/Saves';hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(passed=False,label=label,save_writes=False,recording=False,console_commands=[],shots=[],poses=[],started_unix_ns=time.time_ns())
    renderer=wait(lambda:live(reader),15)['renderer_pid']
    def complete():
        w=live(reader,renderer)
        return w if w and not w.get('partial_geometry')else None
    def shot(case,ids):
        wait(complete,20)
        def accepted():
            w=witness(ids);packet,digest=source_frame(w);return w,packet,digest
        w,packet,digest=wait(accepted,5)
        c=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024);index={b['id']:i for i,b in enumerate(c['bindings'])};matches=[]
        for row in w['instances']:
            if not row['submitted_visible']or row['id']not in index:continue
            state=packet['instance_states'][index[row['id']]];payload=state[2]if len(state)>2 else None
            if not state[0]:raise RuntimeError('Native-hidden character was displayed')
            if isinstance(payload,dict)and'palette'in payload:
                expected=hashlib.md5(np.asarray(payload['palette'],dtype='<f4').tobytes()).hexdigest()
                if row.get('palette_md5','').lower()!=expected:raise RuntimeError('Character pose differs from exact source frame')
                matches.append(dict(id=row['id'],palette_md5=expected))
        if ids and not matches:raise RuntimeError('No submitted native character bones in close-up')
        report['shots'].append(dict(case=case,image=capture('character-'+label+'-'+case),witness=w,environment=packet['environment'],camera=reader.camera_sample()['camera'],source_body_md5=digest,matching_native_palettes=matches))
    try:
        if reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        state=reader.snapshot();actor=next(o for o in state['objects']if o['type']=='NPC_'and o['base_id'].lower().startswith('indrele rathryon'))
        fixture=native_grid_fixture(state['cell_grid'],feet(reader));report['fixture']=fixture;report['actor']=actor
        position=list(fixture['actor_position']);player=list(position);player[1]-=145
        xyz=lambda v:' '.join(f'{n:.3f}'for n in v)
        prefix='"'+actor['base_id']+'"->'
        console(reader,'set gamehour to 12',report)
        console(reader,prefix+'AIWander 0 0 0',report)
        console(reader,prefix+'Position '+xyz(position)+' 180',report)
        console(reader,'player->Position '+xyz(player)+' 0',report);time.sleep(2)
        root=reader.u32(int(actor['id'],16)+0x10)
        graph=SceneReader(reader).collect(roots=[root]);source_ids={s['id']for s in graph['shapes']if s['skin']!='0x0'}
        def ids():
            w=witness([]);c=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
            return [b['id']for b in c['bindings']if b.get('source_id')in source_ids][:48]
        skin_ids=wait(ids,15);report['requested_ids']=skin_ids
        def target():
            p=list(struct.unpack('<3f',reader.read(int(actor['id'],16)+0x38,12)));p[2]+=103;return p
        aim(reader,target());shot('daylight',skin_ids)
        # Reverse the native viewing direction to inspect the opposite, shaded
        # side; this is not an assertion that a building casts a shadow here.
        player[1]=position[1]+145
        console(reader,prefix+'SetAngle z 0',report)
        console(reader,'player->Position '+xyz(player)+' 180',report);time.sleep(.5);aim(reader,target());shot('opposite-light',skin_ids)
        player[1]=position[1]-145
        console(reader,prefix+'SetAngle z 180',report)
        console(reader,'player->Position '+xyz(player)+' 0',report);time.sleep(.5)
        console(reader,'set gamehour to 19',report);time.sleep(.5);aim(reader,target());shot('dusk',skin_ids)
        console(reader,'set gamehour to 12',report)
        console(reader,'player->AddItem "iron dagger" 1',report)
        console(reader,'player->Equip "iron dagger"',report)
        if not reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        time.sleep(1);aim(reader,[position[0]+400,position[1],position[2]+60]);wait(complete,15)
        first=wait(lambda:(v if (v:=submitted(reader)).get('live')and any(r['layer']=='first-person'for r in v['rows'])else None),10)
        report['poses'].append(first);shot('hands-weapon',[])
        start=feet(reader)
        for key in (0x11,0x1f,0x11,0x1f):
            pulse(reader,'key',key,.2);v=wait(lambda:submitted(reader),5)
            if v.get('live'):report['poses'].append(v)
        report['walk_end_distance']=math.dist(start,feet(reader))
        out=ROOT/f'logs/character-{label}-benchmark.json'
        with (ROOT/f'logs/character-{label}-benchmark-command.log').open('w')as log:
            subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','6','--warmup','1','--output',str(out)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=18,creationflags=subprocess.CREATE_NO_WINDOW)
        report['benchmark']=str(out.relative_to(ROOT))
        if len(report['poses'])<3:raise RuntimeError('Insufficient exact first-person native pose checks')
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
        report['passed']&=report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns()
        (ROOT/f'logs/character-fidelity-{label}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
