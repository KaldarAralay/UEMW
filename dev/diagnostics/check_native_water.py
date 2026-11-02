"""Bounded private water smoke check; original input/physics/saves only."""
import hashlib
import json
import math
import shutil
import subprocess
import sys
import time
import uuid
import numpy as np
from PIL import Image
from live_probe import ROOT
from local_files import read_json
from native_environment import capture as environment
from native_ui import inspect_ui
from native_ui_test import act,choose,tree
from input_backend import pulse,require_foreground
from acceptance_step import look
from check_normal_play import wait,feet,live,console,save_menu
from check_native_motion import witness,source_frame
from water_test_fixture import deep_water


def water_witness(reader,underwater,renderer):
    base=reader.render_metadata();native=environment(reader,base)
    water_witness.last_probe=dict(expected_underwater=underwater,native_underwater=native['weather']['underwater'],camera=base['camera']['position'])
    def pending(reason):water_witness.last_probe['waiting_for']=reason;return None
    if native['weather']['underwater']!=underwater:return pending('native underwater state')
    first=witness([])
    if not first.get('live')or first.get('renderer_pid')!=renderer:return pending('live UE state')
    packet,_=source_frame(first);catalog=read_json(ROOT/'local/assets'/first['catalog'],16*1024*1024)
    ids=[b['id']for b,s in zip(catalog['bindings'],packet['instance_states'])if b.get('layer')=='water'and s[0]][:8]
    if not ids and not underwater:return pending('visible native water bindings')
    w=witness(ids)
    if not w.get('live')or w.get('renderer_pid')!=renderer or w.get('native_underwater')!=underwater:return pending('matching submitted underwater state')
    packet,digest=source_frame(w)
    if packet['environment']['weather']['underwater']!=underwater:return pending('matching exact source-frame underwater state')
    catalog=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024);index={b['id']:i for i,b in enumerate(catalog['bindings'])}
    matched=[];frames={}
    for row in w['instances']:
        if not row['submitted_visible']:continue
        state=packet['instance_states'][index[row['id']]]
        if not state[0]or len(state)<3 or not isinstance(state[2],dict):return pending('mutable water points')
        values=state[2]
        for field in('points','colors','uvs'):
            expected=hashlib.md5(np.asarray(values.get(field,[]),dtype='<f4').tobytes()).hexdigest()
            if row.get(field+'_md5','').lower()!=expected:raise ValueError('Submitted water '+field+' differs from its exact native source frame')
        definition=catalog['meshes'][row['asset']];animation=definition.get('texture_animation')
        if animation:
            native_index=packet['material_frames']['frames'][animation['id']]
            if row.get('texture_frame')!=native_index:raise ValueError('Submitted water texture differs from its original resolved flip frame')
            frames[animation['id']]=native_index
        matched.append(row)
    if not matched and not underwater:return pending('submitted visible water')
    return dict(renderer_pid=renderer,scene_epoch=w['scene_epoch'],sequence=w['sequence'],body_md5=digest,
                native_underwater=underwater,water_level=native['water_level'],fog_color=native['fog_color'],fog_density=native['fog_density'],
                camera=w['camera_native_position'],native_camera=base['camera']['position'],cell_grid=list(base['cell_grid'])if base['cell_grid']is not None else None,
                texture_frames=frames,matched_water=matched)


def capture_image(label):
    stamp=time.time_ns();flag=ROOT/'local/bridge/capture.once';source=ROOT/'logs/ue-inspect.png';target=ROOT/('logs/water-'+label+'.png')
    flag.write_text(str(stamp))
    try:
        def ready():
            if not source.exists()or source.stat().st_mtime_ns<stamp:return None
            try:
                shutil.copyfile(source,target)
                with Image.open(target)as decoded:decoded.verify()
            except(OSError,SyntaxError):return None
            return str(target.relative_to(ROOT))
        return wait(ready,6)
    finally:flag.unlink(missing_ok=True)


def run(reader):
    require_foreground(reader)
    report=dict(version=1,passed=False,pid=reader.pid,started_unix_ns=time.time_ns(),recording=False,console_commands=[],
                scope='Short native water placement/swim, texture/vertex submitted-state checks, adjacent-cell transition and unique native save/reload; not full-game or GPU-motion acceptance')
    saves=ROOT/'local/Morrowind/Saves';existing={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report['existing_save_hashes']=existing
    try:
        initial=reader.render_metadata()
        report['initial_context']={k:initial.get(k)for k in('cell','cell_grid','menu')}
        if initial['menu']or tuple(initial['cell_grid']or())!=(-2,-9):raise RuntimeError('Expected the private Seyda Neen checkpoint')
        renderer=wait(lambda:live(reader),6)['renderer_pid']
        water=environment(reader,initial)['water_level'];point=deep_water(initial['cell_grid'],feet(reader),water)
        report['fixture']=point;x,y=point['position'];initial_feet=feet(reader)
        def place(px,py,pz):console(reader,f'player->Position {px:.3f} {py:.3f} {pz:.3f} 0',report)
        def shore_look():
            camera=reader.camera_sample()['camera']['position'];delta=[x+1500-camera[0],y-camera[1],water-camera[2]]
            look(reader,math.atan2(delta[0],delta[1]),math.atan2(delta[2],math.hypot(delta[0],delta[1])))
        shore_look()
        report['above']=wait(lambda:water_witness(reader,False,renderer),10)
        time.sleep(.6);report['animated']=wait(lambda:water_witness(reader,False,renderer),8)
        if not report['above']['texture_frames']or report['above']['texture_frames']==report['animated']['texture_frames']:
            raise RuntimeError('Native water texture animation did not reach submitted UE materials')
        report['above_image']=capture_image('above')
        place(x,y,water-256);look(reader,math.pi,.15)
        report['underwater']=wait(lambda:water_witness(reader,True,renderer),10)
        before=feet(reader);pulse(reader,'key',0x11,.4);time.sleep(.15);after=feet(reader)
        world=reader.u32(0x7c67dc);mob=reader.u32(world+0x5c);actor=reader.u32(reader.u32(mob+0x24))
        movement=int.from_bytes(reader.read(actor+8,2),'little')
        report['swimming']=dict(before=before,after=after,distance=math.dist(before,after),native_movement_flags=movement,native_swimming=bool(movement&0x800))
        if report['swimming']['distance']<4 or not movement&0x800:raise RuntimeError('Original swimming state/input did not meet the movement requirement')
        report['after_swim']=wait(lambda:water_witness(reader,True,renderer),8)
        if math.dist(report['after_swim']['camera'],report['after_swim']['native_camera'])>3:raise RuntimeError('UE camera did not match native swimming camera')
        report['underwater_image']=capture_image('underwater')
        benchmark=ROOT/'logs/water-underwater-benchmark.json'
        with (ROOT/'logs/water-underwater-benchmark-command.log').open('w')as log:
            subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','6','--warmup','0','--width','1920','--height','1080','--output',str(benchmark)],
                           stdout=log,stderr=subprocess.STDOUT,timeout=12,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        report['underwater_benchmark']=str(benchmark.relative_to(ROOT))
        save_name='water_'+uuid.uuid4().hex[:10];save_menu(reader,save_name,report)
        def saved():
            new=[p for p in saves.glob('*.ess')if p.name not in existing]
            if len(new)!=1:return None
            body=new[0].read_bytes()
            return dict(name=save_name,path=str(new[0].relative_to(ROOT)),bytes=len(body),sha256=hashlib.sha256(body).hexdigest())if len(body)>1000 else None
        report['native_save']=wait(saved,10);before_reload=wait(lambda:water_witness(reader,True,renderer),8)
        place(*initial_feet);shore_look()
        report['exited_water']=wait(lambda:water_witness(reader,False,renderer),10)
        neighbor=deep_water((-2,-10),[x,y,water],water);report['neighbor_fixture']=neighbor
        place(*neighbor['position'],water-256);look(reader,math.pi,.15)
        def changed_cell():
            value=water_witness(reader,True,renderer)
            return value if value and value['cell_grid']==[-2,-10]else None
        report['adjacent_cell']=wait(changed_cell,12)
        pulse(reader,'key',1,.12);wait(lambda:'MenuOptions'in inspect_ui(reader)['active_menus'],3)
        act(reader,menu='MenuOptions',name='MenuOptions_Load_container',click=True)
        wait(lambda:choose(reader,menu='MenuLoad',text=save_name),4);act(reader,menu='MenuLoad',text=save_name,click=True)
        def prompt():
            if 'MenuMessage'not in inspect_ui(reader)['active_menus']:return None
            labels={' '.join(row['text'].split())for row in tree(reader,'MenuMessage')}
            if 'Do you want to Load a save game and lose your current game?'not in labels:raise ValueError('Unexpected native load warning')
            return choose(reader,menu='MenuMessage',text='Yes')
        wait(prompt,4);act(reader,menu='MenuMessage',text='Yes',click=True)
        def restored():
            value=water_witness(reader,True,renderer)
            return value if value and value['matched_water']and value['scene_epoch']!=before_reload['scene_epoch']and value['cell_grid']==[-2,-9]else None
        report['reloaded']=wait(restored,24);report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['last_probe']=getattr(water_witness,'last_probe',None)
        report['existing_saves_preserved']=all((saves/name).is_file()and hashlib.sha256((saves/name).read_bytes()).hexdigest()==digest for name,digest in existing.items())
        if not report['existing_saves_preserved']:report['passed']=False
        report['ended_unix_ns']=time.time_ns();(ROOT/'logs/native-water.json').write_text(json.dumps(report,indent=2))
        if not report['existing_saves_preserved']:raise RuntimeError('An existing private save changed')
    return report
