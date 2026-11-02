"""Small live lighting/weather comparison, original engine state and UE pixels."""
import hashlib
import json
import math
import os
import pathlib
import time
import numpy as np
from live_probe import ROOT
from check_normal_play import console,live,wait
from check_native_motion import witness,source_frame
from check_native_visuals import capture,read_json
from check_native_terrain import aim
from acceptance_step import look
from input_backend import require_foreground,pulse


def run(reader):
    label=os.environ.get('UEMW_LIGHTING_LABEL','after')
    if label not in ('before','after'):raise ValueError('Invalid comparison label')
    require_foreground(reader)
    saves=ROOT/'local/Morrowind/Saves';hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(passed=False,label=label,recording=False,save_writes=False,shots=[],console_commands=[],started_unix_ns=time.time_ns())
    world=reader.u32(0x7c67dc);controller=reader.u32(world+0x58);region=reader.u32(controller+0x1d0)
    report['native_weather_region']=reader.string(region+0x10,32)if region else 'Bitter Coast Region'
    def scene_sample():
        w=live(reader)
        if not w:return None
        packet,_=source_frame(w);cat=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
        return w,packet,cat
    def rain_ready():
        sample=scene_sample()
        if sample is None:return None
        w,p,c=sample
        count=sum(bool(s[0]) and b.get('layer')=='weather' and 'rain'in c['meshes'][b['asset']].get('source_texture','').lower()for b,s in zip(c['bindings'],p['instance_states']))
        return sample if count>=6 and not w['partial_geometry'] else None
    def shot(name):
        w,packet,cat=wait(scene_sample,6)
        image=capture('light-weather-'+label+'-'+name)
        weather=[(b,s)for b,s in zip(cat['bindings'],packet['instance_states'])if b.get('layer')=='weather' and s[0]]
        rain=[]
        for b,s in weather:
            d=cat['meshes'][b['asset']]
            if 'rain' not in d.get('source_texture','').lower():continue
            raw=(ROOT/'local/assets'/d['file']).read_bytes();count=int.from_bytes(raw[4:8],'little')
            points=np.frombuffer(raw,dtype='<f4',count=count*3,offset=12).reshape(-1,3).astype(float)
            m=np.asarray(s[1]);points=points@(m[:9].reshape(3,3)*m[12]).T+m[9:12]
            rain.append(dict(id=b['id'],asset=b['asset'],minimum=points.min(0).tolist(),maximum=points.max(0).tolist()))
        report['shots'].append(dict(case=name,image=image,witness=w,environment=packet['environment'],camera=reader.camera_sample()['camera'],rain_meshes=rain))
    try:
        if reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        console(reader,'set gamehour to 12',report)
        console(reader,'player->Position -9472 -72448 36 0',report);time.sleep(3);aim(reader,[-8448,-72960,450]);time.sleep(.5)
        wait(rain_ready,35)
        for i in range(3):shot('rain-initial-'+str(i));time.sleep(.15)
        if label=='after':
            witness([],background_visible=False);time.sleep(.3);shot('rain-initial-sky-hidden');witness([],background_visible=True)
        console(reader,'ChangeWeather "'+report['native_weather_region']+'" 0',report)
        console(reader,'player->Position -12032 -73436 58 0',report);time.sleep(5);look(reader,0,.05);time.sleep(1)
        shot('day-masonry')
        if label=='after':
            witness([],ambient_probe=False);time.sleep(.3);shot('ambient-fill-reference')
            witness([],ambient_probe=True);time.sleep(.3);shot('ambient-probe-enhanced')
        shot('overcast-rain-masonry')
        # Native ChangeWeather leaves an in-flight transition running. Let the
        # original engine finish it; never label a requested type as actual.
        weather_wait=time.monotonic()
        def clear_weather():
            current=reader.u32(controller+0x3c)
            if current and reader.u32(current+4)==0:return True
            # ChangeWeather can be ignored while a saved transition is active.
            # Once it ends, issue the native command again; do not alter memory.
            if not reader.u32(controller+0x40):
                console(reader,'ChangeWeather "'+report['native_weather_region']+'" 0',report)
            return False
        wait(clear_weather,165)
        report['native_clear_weather_wait_seconds']=time.monotonic()-weather_wait
        if reader.player_render_state(reader.u32(0x7c67dc)).get('vanity'):
            pulse(reader,'key',0x11,.1);time.sleep(.2)
            wait(lambda:not reader.player_render_state(reader.u32(0x7c67dc)).get('vanity'),3)
        # Native idle vanity can orbit during that wait. Restore the same
        # original-engine fixture pose before comparing day/dusk materials.
        console(reader,'player->Position -12032 -73436 58 0',report);time.sleep(.3);look(reader,0,.05)
        console(reader,'set gamehour to 12',report);time.sleep(.5);shot('clear-day-masonry')
        console(reader,'set gamehour to 19',report);time.sleep(.5);shot('clear-dusk-masonry')
        if label=='after':
            witness([],ambient_probe=False);time.sleep(.3);shot('dusk-ambient-reference')
            witness([],ambient_probe=True);time.sleep(.3);shot('dusk-ambient-enhanced')
        matches=[s for s in report['shots']if s['case']in ('ambient-probe-enhanced','clear-day-masonry','clear-dusk-masonry','dusk-ambient-reference','dusk-ambient-enhanced')]
        origin=matches[0]['camera'];report['matching_views']=all(math.dist(s['camera']['position'],origin['position'])<2 and np.dot(s['camera']['forward'],origin['forward'])>.999 for s in matches)
        if not report['matching_views']:raise RuntimeError('Native comparison camera moved away from the fixture pose')
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        if label=='after':
            try:witness([],ambient_probe=True,background_visible=True)
            except (OSError,ValueError,RuntimeError):pass
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
        report['passed']&=report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns()
        (ROOT/f'logs/lighting-weather-{label}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
