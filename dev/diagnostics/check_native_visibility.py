"""Bounded shoreline visibility diagnostic; no recording or save writes."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from live_probe import ROOT
from input_backend import pulse,require_foreground
from check_normal_play import console,wait,live
from check_native_terrain import aim
from check_native_motion import witness,source_frame
from local_files import read_json
from check_native_visuals import capture


def run(reader):
    require_foreground(reader)
    label=os.environ.get('UEMW_VISIBILITY_CHECK','after')
    if label not in ('before','after'):raise ValueError('Invalid visibility label')
    report=dict(passed=False,label=label,recording=False,save_writes=False,samples=[],catalog_changes=[],console_commands=[])
    catalogs={};previous={}
    def sample(phase):
        nonlocal previous
        w=witness([])
        if not w.get('live'):
            report['samples'].append(dict(phase=phase,live=False,status=w.get('status')));return
        packet,_=source_frame(w);name=w['catalog']
        if name not in catalogs:catalogs[name]=read_json(ROOT/'local/assets'/name,16*1024*1024)
        cat=catalogs[name];bindings=cat['bindings'];states=packet['instance_states']
        current={b['id']:(b['asset'],b.get('layer','world'))for b in bindings}
        if previous and current!=previous:
            changes=[dict(id=k,before=previous.get(k),after=current.get(k))for k in set(previous)|set(current)if previous.get(k)!=current.get(k)]
            report['catalog_changes'].append(dict(sequence=w['sequence'],changes=changes[:128],count=len(changes)))
        previous=current
        water=[b['id']for b,s in zip(bindings,states)if b.get('layer')=='water' and s[0]]
        ids=water[:24]
        ids += [b['id']for b,s in zip(bindings,states)if s[0] and not b.get('layer') and cat['meshes'][b['asset']].get('skin_bones')][:24]
        checked=witness(ids);packet,_=source_frame(checked)
        if checked['catalog']!=name:return
        index={b['id']:i for i,b in enumerate(bindings)}
        report['samples'].append(dict(phase=phase,live=checked['live'],sequence=checked['sequence'],status=checked['status'],
            hud_visible=checked.get('gameplay_hud_visible'),partial=checked['partial_geometry'],pending=checked['pending_native_instances'],water_visible=len(water),
            rows=[dict(id=r['id'],layer=current[r['id']][1],source_visible=packet['instance_states'][index[r['id']]][0],submitted_visible=r['submitted_visible'])for r in checked['instances']]))
    try:
        console(reader,'player->Position -9472 -72448 36 0',report)
        time.sleep(5);wait(lambda:live(reader),15);aim(reader,[-8448,-72960,0]);time.sleep(.5)
        def observe(phase):
            try:sample(phase)
            except (OSError,ValueError)as error:report.setdefault('sampling_retries',[]).append(str(error));time.sleep(.01)
        for i in range(32):observe('stationary');time.sleep(.03)
        report['stationary_image']=capture('visibility-'+label+'-stationary')
        with ThreadPoolExecutor(max_workers=1)as pool:
            for key in (0x1e,0x20,0x1e,0x20):
                moving=pool.submit(pulse,reader,'key',key,1.1)
                while not moving.done():observe('walking')
                moving.result()
        report['walking_image']=capture('visibility-'+label+'-walking')
        report['passed']=len(report['samples'])>=30 and all(s['live']for s in report['samples'])
        if not report['passed']:raise RuntimeError('Visibility diagnostic lost live source')
    except BaseException as error:report['error']=str(error);raise
    finally:
        (ROOT/f'logs/native-visibility-{label}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
