"""Targeted real-water/atmosphere A/B, native animation and movement checks."""
import hashlib
import json
import math
import time
import numpy as np
from PIL import Image
from live_probe import ROOT
from check_normal_play import console,live,wait,feet
from check_native_motion import witness,source_frame
from check_native_visuals import capture,read_json
from check_native_terrain import aim
from check_native_water import water_witness
from input_backend import require_foreground,pulse
from acceptance_step import look


def run(reader):
    require_foreground(reader)
    saves=ROOT/'local/Morrowind/Saves'
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(passed=False,recording=False,save_writes=False,shots=[],console_commands=[],started_unix_ns=time.time_ns())
    world=reader.u32(0x7c67dc);controller=reader.u32(world+0x58);region=reader.u32(controller+0x1d0)
    region_name=reader.string(region+0x10,32)if region else 'Bitter Coast Region'
    renderer=wait(lambda:live(reader),10)['renderer_pid']
    def sample():
        w=live(reader,renderer)
        if not w or w['partial_geometry']:return None
        packet,_=source_frame(w)
        return w,packet
    def shot(name):
        w,packet=wait(sample,15)
        image=capture('water-atmosphere-'+name)
        a=np.asarray(Image.open(ROOT/image).convert('RGB'))[150:980,260:1660]
        report['shots'].append(dict(case=name,image=image,witness=w,environment=packet['environment'],camera=reader.camera_sample()['camera'],near_white_fraction=float(np.mean(np.min(a,axis=2)>250))))
    def pair(name):
        witness([],water_atmosphere=False);time.sleep(.25);shot(name+'-reference')
        witness([],water_atmosphere=True);time.sleep(.25);shot(name+'-enhanced')
        a,b=report['shots'][-2:]
        if math.dist(a['camera']['position'],b['camera']['position'])>2 or np.dot(a['camera']['forward'],b['camera']['forward'])<.999:raise RuntimeError('A/B native camera moved')
    def place(x,y,z):
        console(reader,f'player->Position {x} {y} {z} 0',report);time.sleep(2)
    try:
        if reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        console(reader,'set gamehour to 12',report)
        place(-9472,-72448,36);aim(reader,[-8448,-72960,450])
        def rainy():
            current=sample()
            if not current:return None
            w,packet=current;catalog=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
            rain=sum(bool(s[0])and b.get('layer')=='weather'and 'rain'in catalog['meshes'][b['asset']].get('source_texture','').lower()for b,s in zip(catalog['bindings'],packet['instance_states']))
            return rain if rain>=6 else None
        rain=wait(rainy,25)
        report['initial_visible_native_rain_meshes']=rain
        pair('weather-sky')
        console(reader,'ChangeWeather "'+region_name+'" 0',report)
        place(-12032,-73436,58);look(reader,0,.05);pair('rain-day-fog')
        # Native LAND shoreline and actual dock supports; neither is recreated.
        aim(reader,[-12600,-72800,-35]);pair('shore-day')
        first=wait(lambda:water_witness(reader,False,renderer),15)
        time.sleep(.4);second=wait(lambda:water_witness(reader,False,renderer),10)
        if first['texture_frames']==second['texture_frames']:raise RuntimeError('Native water flip frame did not advance')
        report['water_source_checks']=[first,second]
        # Same native swimming/underwater path as normal play, with no save writes.
        from water_test_fixture import deep_water
        point=deep_water((-2,-9),feet(reader),0);report['deep_fixture']=point
        place(*point['position'],-220);look(reader,math.pi,.15)
        report['underwater']=wait(lambda:water_witness(reader,True,renderer),15)
        pair('underwater')
        before=feet(reader);pulse(reader,'key',0x11,.3);after=feet(reader)
        report['native_swim_distance']=math.dist(before,after)
        if report['native_swim_distance']<2:raise RuntimeError('Native swimming did not advance')
        place(-12032,-73436,58);look(reader,0,.05)
        report['resurfaced']=wait(lambda:water_witness(reader,False,renderer),15)
        weather_wait=time.monotonic()
        def clear():
            p=reader.u32(controller+0x3c)
            if p and reader.u32(p+4)==0:return True
            if not reader.u32(controller+0x40):console(reader,'ChangeWeather "'+region_name+'" 0',report)
            return False
        wait(clear,165);report['native_clear_weather_wait_seconds']=time.monotonic()-weather_wait
        if reader.player_render_state(world).get('vanity'):
            pulse(reader,'key',0x11,.1);time.sleep(.2)
            wait(lambda:not reader.player_render_state(world).get('vanity'),3)
        place(-12032,-73436,58);look(reader,0,.05)
        console(reader,'set gamehour to 12',report);time.sleep(.4);pair('clear-day-fog')
        aim(reader,[-12600,-72800,-35]);pair('clear-day-shore')
        # Bounded original-input camera movement, actual water pixels retained.
        for i,key in enumerate((0x11,0x1f,0x11,0x1f)):
            pulse(reader,'key',key,.18);wait(sample,8);shot('moving-water-'+str(i))
        place(-12032,-73436,58);look(reader,0,.05)
        console(reader,'set gamehour to 19',report);time.sleep(.4);pair('clear-dusk-fog')
        aim(reader,[-12600,-72800,-35]);pair('clear-dusk-shore')
        report['matching_native_camera_pairs']=True;report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        try:witness([],water_atmosphere=True)
        except(OSError,ValueError,RuntimeError):pass
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
        report['passed']&=report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns()
        (ROOT/'logs/water-atmosphere-live.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
