"""Opt-in native movement/UI/object/save smoke check, never a runtime service.

All input goes through the foreground-guarded original-game test backend.
Only the original game creates objects, picks them up, saves and reloads.
Existing saves are hashed and retained; the new save uses a unique name.
"""
import hashlib
import json
import math
from pathlib import Path
import struct
import time
import uuid

from live_probe import ROOT
from input_backend import pulse,type_ascii,require_foreground
from native_ui import inspect_ui,loading_state
from native_ui_test import act,choose,tree
from acceptance_step import look
from scene_reader import SceneReader
from local_files import read_json
from check_native_motion import witness
from check_native_motion import source_frame
import numpy as np


def wait(check,seconds=8):
    end=time.monotonic()+seconds;last=None
    while time.monotonic()<end:
        try:
            value=check()
            if value:return value
        except (OSError,ValueError,RuntimeError,KeyError)as error:last=str(error)
        time.sleep(.05)
    raise RuntimeError('Timed out: '+check.__name__+((': '+last)if last else''))


def feet(reader):
    world=reader.u32(0x7c67dc);player=reader.player_render_state(world);reference=int(player['reference'],16)
    if reader.read(reference+4,4)!=b'REFR':raise RuntimeError('Native player reference changed')
    return list(struct.unpack('<3f',reader.read(reference+0x38,12)))


def live(reader,renderer=None):
    source=read_json(ROOT/'local/bridge/latest.json')
    if source.get('pid')!=reader.pid or source.get('status')!='live'or source.get('menu')or not 0<=time.time_ns()-source.get('sample_unix_ns',0)<500_000_000:return None
    w=witness([])
    if not w.get('live')or w.get('pid')!=reader.pid or(renderer is not None and w.get('renderer_pid')!=renderer):return None
    if w.get('session')!=source.get('session')or w.get('scene_epoch')!=source.get('scene_epoch'):return None
    return w


def console(reader,text,report):
    if inspect_ui(reader)['native_ui']:raise RuntimeError('Console command refused while another native menu is open')
    pulse(reader,'key',0x29,.12)
    wait(lambda:'MenuConsole'in inspect_ui(reader)['active_menus'],3)
    type_ascii(reader,text);pulse(reader,'key',0x1c,.12);time.sleep(.2)
    report['console_commands'].append(text)
    report.setdefault('console_output',[]).append([row['text']for row in tree(reader,'MenuConsole')if row['text']][-8:])
    if 'MenuConsole'in inspect_ui(reader)['active_menus']:pulse(reader,'key',0x29,.12)
    wait(lambda:not inspect_ui(reader)['native_ui'],6)


def save_menu(reader,name,report):
    pulse(reader,'key',1,.12)
    wait(lambda:'MenuOptions'in inspect_ui(reader)['active_menus'],3)
    act(reader,menu='MenuOptions',name='MenuOptions_Save_container',click=True)
    wait(lambda:choose(reader,menu='MenuSave',text='New Save Game'),3)
    act(reader,menu='MenuSave',text='New Save Game',click=True)
    wait(lambda:choose(reader,menu='MenuInputSave',name='MenuInputSave_NameSpace'),3)
    item=act(reader,menu='MenuInputSave',name='MenuInputSave_NameSpace',click=True)
    report['save_input_before']=item
    # Morrowind's rendered text includes a trailing blinking caret. It is
    # presentation, not part of the save name submitted by the original UI.
    initial_text=item['text'].removesuffix('|')
    if len(initial_text)>128:raise RuntimeError('Unexpected native save-name field length')
    for _ in initial_text:pulse(reader,'key',0x0e,.05)
    type_ascii(reader,name)
    report['save_input_after']=choose(reader,menu='MenuInputSave',name='MenuInputSave_NameSpace')
    wait(lambda:choose(reader,menu='MenuInputSave',name='MenuInputSave_NameSpace')['text'].removesuffix('|')==name,3)
    act(reader,menu='MenuInputSave',name='MenuInputSave_OkNextbutton',click=True)
    def closed():
        menus=inspect_ui(reader)['active_menus']
        return 'MenuInputSave'not in menus and 'MenuLoading'not in menus
    wait(closed,10)
    menus=inspect_ui(reader)['active_menus']
    if 'MenuSave'in menus:act(reader,menu='MenuSave',name='MenuSave_Cancelbutton',click=True)
    if 'MenuOptions'in inspect_ui(reader)['active_menus']:pulse(reader,'key',1,.12)
    wait(lambda:not inspect_ui(reader)['native_ui'],4)


def render_ids(reader,reference):
    node=int(reference['node'],16)
    if not node:raise RuntimeError('Created native object has no render node')
    graph=SceneReader(reader).collect(roots=[node])
    source_ids={s['id']for s in graph['shapes']}
    if not source_ids:raise RuntimeError('Native object has no actual scene shapes')
    def bindings():
        source=read_json(ROOT/'local/bridge/latest.json')
        if source.get('pid')!=reader.pid or source.get('status')!='live':return None
        catalog=read_json(ROOT/'local/assets'/source['scene_catalog'],16*1024*1024)
        ids=[b['id']for b in catalog['bindings']if b.get('source_id')in source_ids]
        return ids if len(ids)==len(source_ids)else None
    return wait(bindings,8)


def accepted_objects(w,ids,present):
    """Bind submitted object evidence to the exact accepted native body."""
    packet,digest=source_frame(w)
    catalog=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
    indices={b['id']:i for i,b in enumerate(catalog['bindings'])}
    for row in w['instances']:
        index=indices.get(row['id'])
        if present:
            if index is None:return False
            state=packet['instance_states'][index]
            if row['submitted_visible']and not state[0]:return False
            if 'transform_md5'in row and len(state)>1 and isinstance(state[1],list):
                expected=hashlib.md5(np.asarray(state[1],dtype='<f4').tobytes()).hexdigest()
                if row['transform_md5'].lower()!=expected:return False
        elif index is not None:return False
    if {r['id']for r in w['instances']}!=set(ids):return False
    w['matched_native_body_md5']=digest
    return True


def aim_at(reader,item):
    x,y,z=item['position'];attempts=[]
    for target in((x+12,y,z+20),(x-12,y,z+20),(x,y+12,z+20),(x,y,z+8),(x,y,z+28)):
        camera=reader.camera_sample()['camera']['position'];delta=[target[i]-camera[i]for i in range(3)]
        look(reader,math.atan2(delta[0],delta[1]),math.atan2(delta[2],math.hypot(delta[0],delta[1])),.15)
        focus=reader.snapshot().get('focus');attempts.append(dict(target=target,focus=focus))
        if focus and focus['id']==item['id']:return attempts
    raise RuntimeError('Original activation ray did not acquire the created bucket')


def run(reader):
    report=dict(version=1,passed=False,pid=reader.pid,started_unix_ns=time.time_ns(),recording=False,
        scope='Short original-game movement, inventory UI, bucket creation/pickup, unique native save and native UI reload; UE CPU submitted-state witnesses, not broad gameplay/GPU-motion acceptance',
        console_commands=[])
    saves=ROOT/'local/Morrowind/Saves'
    existing={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report['existing_save_hashes']=existing
    try:
        require_foreground(reader)
        initial=reader.snapshot()
        report['initial_context']={k:initial.get(k)for k in('pid','cell','cell_grid','menu','frame_ms')}
        if initial.get('cell')!='Seyda Neen'or tuple(initial.get('cell_grid')or())!=(-2,-9)or initial['menu']:raise RuntimeError('Expected private disposable Seyda Neen gameplay')
        if reader.player_render_state(reader.u32(0x7c67dc)).get('vanity'):
            pulse(reader,'key',0x11,.08);time.sleep(.2)
        first=wait(lambda:live(reader),8);renderer=first['renderer_pid']
        start=feet(reader);before_camera=first['camera_native_position']
        pulse(reader,'key',0x11,.35);time.sleep(.2);forward=feet(reader)
        if math.dist(start[:2],forward[:2])<4:raise RuntimeError('Original collision blocked forward movement; not a walking pass')
        def matched_camera():
            w=live(reader,renderer);native=reader.camera_sample()['camera']['position']
            return dict(witness=w,native=native)if w and math.dist(w['camera_native_position'],native)<2 else None
        forward_camera=wait(matched_camera,4)
        if math.dist(before_camera,forward_camera['witness']['camera_native_position'])<4:raise RuntimeError('Submitted UE camera did not follow native walking')
        pulse(reader,'key',0x1f,.35);time.sleep(.2)
        report['movement']=dict(before=start,forward=forward,back=feet(reader),forward_distance=math.dist(start,forward),camera=forward_camera)
        pulse(reader,'right',0,.12)
        menus=wait(lambda:inspect_ui(reader)if 'MenuInventory'in inspect_ui(reader)['active_menus']else None,4)
        require_foreground(reader);report['inventory_ui']=menus
        pulse(reader,'right',0,.12);wait(lambda:not inspect_ui(reader)['native_ui'],4)
        wait(lambda:live(reader,renderer),6)
        old_ids={o['id']for o in reader.snapshot()['objects']}
        console(reader,'PlaceAtPC "misc_com_bucket_01" 1 80 0',report)
        def created():
            values=[o for o in reader.snapshot()['objects']if o['id']not in old_ids and o['base_id']=='misc_com_bucket_01'and o['node']!='0x0']
            return values[0]if len(values)==1 else None
        bucket=wait(created,6);report['created_bucket']=bucket
        report['activation_aim']=aim_at(reader,bucket)
        ids=render_ids(reader,bucket)
        def visible():
            w=witness(ids)
            return w if w.get('live')and w.get('renderer_pid')==renderer and len(w['instances'])==len(ids)and all(x['present_in_catalog']for x in w['instances'])and any(x['submitted_visible']for x in w['instances'])and accepted_objects(w,ids,True)else None
        report['created_bucket_witness']=wait(visible,8)
        save_name='uemw_'+uuid.uuid4().hex[:12]
        saved_position=feet(reader);saved_bucket_position=list(bucket['position'])
        report['saved_player_position']=saved_position;report['saved_bucket_position']=saved_bucket_position
        save_menu(reader,save_name,report)
        def saved():
            new=[p for p in saves.glob('*.ess')if p.name not in existing]
            candidates=new
            if len(candidates)!=1:return None
            p=candidates[0];body=p.read_bytes()
            return dict(name=save_name,path=str(p.relative_to(ROOT)),bytes=len(body),sha256=hashlib.sha256(body).hexdigest())if len(body)>1000 else None
        report['native_save']=wait(saved,10)
        report['activation_aim_after_save']=aim_at(reader,bucket)
        pulse(reader,'key',0x39,.12)
        wait(lambda:not any(o['id']==bucket['id']for o in reader.snapshot()['objects']),6)
        def retired():
            w=witness(ids)
            return w if w.get('live')and w.get('renderer_pid')==renderer and all(not x['present_in_catalog']and not x['submitted_visible']for x in w['instances'])and accepted_objects(w,ids,False)else None
        report['removed_bucket_witness']=wait(retired,8)
        pulse(reader,'key',0x1f,.2);time.sleep(.2);report['position_before_reload']=feet(reader)
        before_reload=wait(lambda:live(reader,renderer),5);report['before_reload']=before_reload
        pulse(reader,'key',1,.12);wait(lambda:'MenuOptions'in inspect_ui(reader)['active_menus'],3)
        act(reader,menu='MenuOptions',name='MenuOptions_Load_container',click=True)
        wait(lambda:choose(reader,menu='MenuLoad',text=save_name),4)
        act(reader,menu='MenuLoad',text=save_name,click=True)
        def load_prompt():
            menus=inspect_ui(reader)['active_menus']
            if 'MenuMessage'not in menus:return None
            rows=tree(reader,'MenuMessage');report['load_confirmation']=rows
            labels={' '.join(row['text'].split())for row in rows}
            if 'Do you want to Load a save game and lose your current game?'not in labels:
                raise ValueError('Unexpected native load warning; it was not accepted')
            return choose(reader,menu='MenuMessage',text='Yes')
        wait(load_prompt,4)
        act(reader,menu='MenuMessage',text='Yes',click=True)
        report['reload_observations']=[]
        def reloaded():
            state=reader.snapshot()
            position=feet(reader);loading=loading_state(reader)[0]
            report['reload_observations'].append(dict(unix_ns=time.time_ns(),position=position,menu=state['menu'],loading=loading,cell=state['cell']))
            if state['menu']or loading or math.dist(position,saved_position)>.25:return None
            restored=[o for o in state['objects']if o['base_id']=='misc_com_bucket_01'and o['node']!='0x0'and math.dist(o['position'],saved_bucket_position)<1]
            return restored[0]if len(restored)==1 else None
        restored=wait(reloaded,20);report['restored_bucket']=restored
        restored_ids=render_ids(reader,restored)
        def reload_witness():
            w=witness(restored_ids)
            return w if w.get('live')and w.get('renderer_pid')==renderer and w.get('scene_epoch')!=before_reload['scene_epoch']and all(x['present_in_catalog']for x in w['instances'])and any(x['submitted_visible']for x in w['instances'])and accepted_objects(w,restored_ids,True)else None
        report['reload_witness']=wait(reload_witness,15)
        report['restored_player_position']=feet(reader)
        report['passed']=True
    except BaseException as error:
        report['error']=str(error);raise
    finally:
        report['ended_unix_ns']=time.time_ns()
        report['existing_saves_preserved']=all((saves/name).is_file()and hashlib.sha256((saves/name).read_bytes()).hexdigest()==digest for name,digest in existing.items())
        if not report['existing_saves_preserved']:report['passed']=False
        (ROOT/'logs/normal-play.json').write_text(json.dumps(report,indent=2))
        if not report['existing_saves_preserved']:raise RuntimeError('An existing private save changed; check the preservation report')
    return report
