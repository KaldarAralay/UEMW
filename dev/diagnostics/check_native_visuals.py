"""Brief real-scene visual comparisons; no recordings or save writes."""
import hashlib
import json
import math
import shutil
import struct
import time
import subprocess
import sys
from PIL import Image
from live_probe import ROOT
from input_backend import require_foreground,pulse
from acceptance_step import look
from check_normal_play import console,wait,live
from check_native_motion import witness,source_frame
from native_ui import inspect_ui
from local_files import read_json as _read_json


def read_json(path,max_bytes=1024*1024):
    # Diagnostics can wait for the next committed slot. Runtime readers stay
    # nonblocking; a busy shared-memory copy is not a failed live connection.
    return wait(lambda:_read_json(path,max_bytes),3)


def capture(name):
    requested=time.time_ns();flag=ROOT/'local/bridge/capture.once';source=ROOT/'logs/ue-inspect.png'
    destination=ROOT/'logs'/('visual-'+name+'.png');flag.write_text(str(requested))
    def ready():
        if not source.exists()or source.stat().st_mtime_ns<requested:return None
        try:
            shutil.copyfile(source,destination)
            with Image.open(destination)as image:image.verify()
            return str(destination.relative_to(ROOT))
        except(OSError,SyntaxError):return None
    try:return wait(ready,6)
    finally:flag.unlink(missing_ok=True)


def run(reader):
    require_foreground(reader);saves=ROOT/'local/Morrowind/Saves'
    existing={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(version=1,passed=False,recording=False,console_commands=[],shots=[],started_unix_ns=time.time_ns(),
        scope='Real installed geometry in live native exterior and interior; previous emissive lighting/filmic curve versus native-driven UE DefaultLit/shadows/SDR midtones. Both use pixel normals and original texture mips. No GPU-motion FPS claim.')
    renderer=wait(lambda:live(reader),8)['renderer_pid'];initial=reader.snapshot();armed=initial['player']['weapon_ready']
    manifest=read_json(ROOT/'local/bridge/latest.json');catalog=read_json(ROOT/'local/assets'/manifest['scene_catalog'],16*1024*1024)
    initial_items=[b['id']for b in catalog['bindings']if b.get('layer')=='first-person'][:40]
    def command(text):
        try:console(reader,text,report)
        except RuntimeError:
            report['native_ui_after_command']=inspect_ui(reader)
            if not text.lower().startswith('coc '):raise
            if report['native_ui_after_command']['active_menus']==['MenuConsole']:
                pulse(reader,'key',0x29,.15)
            wait(lambda:not inspect_ui(reader)['native_ui'],18)
        if any('script error'in s.lower()or'not found'in s.lower()for s in report['console_output'][-1]):raise RuntimeError('Original console rejected visual fixture')
    def complete():
        w=live(reader,renderer)
        return w if w and not w.get('partial_geometry')and w.get('mipmapped_textures',0)>0 else None
    def pair(label):
        wait(complete,20)
        for profile in('reference','enhanced'):
            w=witness(initial_items,visual_profile=profile)
            if w.get('visual_profile')!=profile:raise RuntimeError('Visual profile did not apply')
            time.sleep(.4);wait(complete,6);w=witness(initial_items);m=read_json(ROOT/'local/bridge/latest.json')
            if label.startswith('exterior')and armed and any(row['submitted_visible']for row in w['instances']):
                raise RuntimeError('Sheathed first-person item still submitted to UE')
            packet,_=source_frame(w);image=capture(label+'-'+profile)
            if label in ('exterior-day','interior'):
                path=ROOT/'logs'/('lighting-'+label+'-'+profile+'-benchmark.json')
                location=['--grid',*map(str,m['cell_grid'])]if m.get('cell_grid')is not None else['--cell',m['cell']]
                subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','5','--warmup','1','--output',str(path),*location],check=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW,capture_output=True)
                report.setdefault('benchmarks',[]).append(str(path.relative_to(ROOT)))
            if label=='exterior-day'and profile=='enhanced':
                (ROOT/'logs/visual-day-source.json').write_text(json.dumps(dict(packet=packet,camera=m['camera'],catalog=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024))),encoding='utf-8')
            report['shots'].append(dict(case=label,profile=profile,image=image,witness=w,
                camera=m.get('camera'),cell=m.get('cell'),environment=packet.get('environment'),geometry_stats=m.get('geometry_stats')))
    try:
        if armed:pulse(reader,'key',0x21,.12);time.sleep(1)
        command('set gamehour to 12')
        look(reader,0,-.10);time.sleep(.2)
        before=reader.camera_sample()['camera']['position'];pulse(reader,'key',0x20,.7);time.sleep(.3)
        after=reader.camera_sample()['camera']['position'];report['native_camera_strafe']=dict(before=before,after=after,distance=math.dist(before,after))
        pair('exterior-day')
        from scene_reader import SceneReader
        from native_environment import light
        base=reader.snapshot();graph=SceneReader(reader).collect(view_roots=base['view_roots'],aux_roots=base['aux_roots'])
        report['day_light_diagnostics']=[dict(light(reader,p),name=reader.string(reader.u32(p+8)),owners=graph['light_owners'].get(p))for p in graph['lights']]
        nearby=[]
        for shape in graph['shapes']:
            bound=struct.unpack('<4f',reader.read(int(shape['id'],16)+0x1c,16))
            distance=math.dist(bound[:3],base['camera']['position'])
            if distance<500 and bound[3]<500:
                nearby.append(dict(shape,distance=distance,bound=bound))
        report['day_near_geometry']=sorted(nearby,key=lambda s:s['distance'])[:64]
        (ROOT/'logs/visual-day-debug.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        command('set gamehour to 21');time.sleep(1);pair('exterior-night')
        command('coc "Seyda Neen, Arrille\'s Tradehouse"')
        wait(lambda:read_json(ROOT/'local/bridge/latest.json').get('cell')=="Seyda Neen, Arrille's Tradehouse",15)
        s=reader.snapshot();npcs=[o for o in s['objects']if o['type']=='NPC_']
        target=next((o for o in npcs if o.get('name')=='Arrille'),npcs[0]if npcs else None)
        if target:
            cam=s['camera']['position'];d=[target['position'][i]-cam[i]for i in range(3)];d[2]+=105
            look(reader,math.atan2(d[0],d[1]),math.atan2(d[2],math.hypot(d[0],d[1])))
        pair('interior')
        if armed and not reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12);time.sleep(1)
        wait(complete,10);report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        try:witness([],visual_profile='enhanced')
        except(OSError,ValueError,RuntimeError):pass
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in existing.items())
        if not report['existing_saves_preserved']:report['passed']=False
        report['ended_unix_ns']=time.time_ns();(ROOT/'logs/native-visuals.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if not report['existing_saves_preserved']:raise RuntimeError('Existing private save changed')
    return report
