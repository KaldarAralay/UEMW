"""Short private combat check. Every action uses original input/console/UI."""
import hashlib
import json
import math
import threading
import struct
import time
import uuid
import numpy as np
from live_probe import ROOT
from local_files import read_json
from input_backend import pulse,require_foreground
from native_ui import inspect_ui
from native_ui_test import act,choose,tree
from native_actor_state import actor_state
from acceptance_step import look
from check_normal_play import wait,feet,live,console,save_menu
from check_native_motion import witness as source_witness,source_frame,relative_rotations
from native_motion_fixture import native_grid_fixture

_catalogs={}
def witness(ids):return source_witness(ids,poll=.008)

def catalog(name):
    if name not in _catalogs:
        if len(_catalogs)>=8:_catalogs.clear()
        _catalogs[name]=read_json(ROOT/'local/assets'/name,16*1024*1024)
    return _catalogs[name]


def submitted(reader):
    # The witness is intentionally limited to 10 Hz. Discover request IDs from
    # the current producer catalog, then make ONE query, rather than halving
    # the observer rate with a separate empty-ID query. Every returned pose is
    # still compared with its exact accepted binary source frame below.
    latest=read_json(ROOT/'local/bridge/latest.json',1024*1024)
    c=catalog(latest['scene_catalog'])
    ids=[b['id']for b in c['bindings']if b.get('layer')in('first-person','projectile','world_effect')or b.get('effect_target')][:64]
    w=witness(ids)
    if not w.get('live'):return dict(live=False,status=w.get('status'))
    packet,digest=source_frame(w);c=catalog(w['catalog']);index={b['id']:i for i,b in enumerate(c['bindings'])};rows=[]
    for row in w['instances']:
        if not row['submitted_visible']or row['id']not in index:continue
        i=index[row['id']];state=packet['instance_states'][i]
        if not state[0]:raise ValueError('UE displayed a natively hidden combat object')
        payload=state[2]if len(state)>2 else None;values={};center=state[1][9:12]
        if isinstance(payload,dict)and'palette'in payload:values['palette']=payload['palette']
        elif payload is not None:
            values['points']=payload['points']if isinstance(payload,dict)else payload
            colors=payload.get('colors')if isinstance(payload,dict)else state[3]if len(state)>3 else None
            if colors is not None:values['colors']=colors
            if isinstance(payload,dict)and'uvs'in payload:values['uvs']=payload['uvs']
            points=np.asarray(values['points']).reshape(-1,3)
            if colors is not None:
                active=np.asarray(colors).reshape(-1,4)[:,3]>.001
                if not active.any():continue
                points=points[active]
            center=np.mean(points,axis=0).tolist()
        else:values['transform']=state[1]
        hashes={}
        for field,data in values.items():
            expected=hashlib.md5(np.asarray(data,dtype='<f4').tobytes()).hexdigest()
            if row.get(field+'_md5','').lower()!=expected:raise ValueError('Combat '+field+' differs from its exact accepted source frame')
            hashes[field]=expected
        signature=hashlib.md5(relative_rotations(np.asarray(payload['palette']).reshape(-1,12)).astype('<f4').tobytes()).hexdigest()if isinstance(payload,dict)and'palette'in payload else row.get('rotation_md5')
        rows.append(dict(id=row['id'],asset=row['asset'],layer=c['bindings'][i].get('layer'),effect_target=c['bindings'][i].get('effect_target'),hashes=hashes,center=center,pose_signature=signature))
    return dict(live=True,sequence=w['sequence'],scene_epoch=w['scene_epoch'],renderer_pid=w['renderer_pid'],body_md5=digest,
                retaining_catalog=w.get('retaining_catalog',False),partial=w.get('partial_geometry'),rows=rows)


def observe(reader,seconds,action=None):
    errors=[];thread=None;native=[];stop=threading.Event()
    def trace():
        # Test-only telemetry distinguishes missed bindings from early hits.
        world=reader.u32(0x7c67dc);mob=reader.u32(world+0x5c);manager=reader.u32(mob+0x28)
        last=None
        while not stop.is_set():
            try:
                count,link=struct.unpack('<2I',reader.read(manager+4,8));rows=[]
                for _ in range(min(count,16)):
                    previous,following,mobile=struct.unpack('<3I',reader.read(link,12));ref=reader.u32(mobile+0x14)
                    rows.append(dict(mobile=hex(mobile),reference=hex(ref),node=hex(reader.u32(ref+0x10)),position=struct.unpack('<3f',reader.read(ref+0x38,12))))
                    link=following
                source={}
                try:
                    meta=read_json(ROOT/'local/bridge/latest.json',1024*1024);name=meta.get('scene_catalog')
                    source=dict(sequence=meta.get('sequence'),sample_unix_ns=meta.get('sample_unix_ns'),catalog=name,
                        preparation=meta.get('preparation'),stats=meta.get('geometry_stats'),
                        projectile_bindings=sum(b.get('layer')=='projectile'for b in catalog(name)['bindings'])if name else 0)
                except(OSError,ValueError,KeyError):pass
                state=dict(count=count,rows=rows,source=source)
                if state!=last:native.append(dict(unix_ns=time.time_ns(),**state));last=state
            except(OSError,ValueError):pass
            stop.wait(.01)
    probe=threading.Thread(target=trace);probe.start()
    if action:
        def run():
            try:action()
            except BaseException as error:errors.append(error)
        thread=threading.Thread(target=run);thread.start()
    end=time.monotonic()+seconds;samples=[];skipped=[]
    try:
        while time.monotonic()<end:
            try:samples.append(submitted(reader))
            except(OSError,ValueError,RuntimeError,KeyError)as error:skipped.append(str(error))
            time.sleep(.015)
    finally:
        if thread:thread.join(timeout=3)
        stop.set();probe.join(timeout=1)
    if errors:raise errors[0]
    return dict(samples=samples,skipped=skipped,native_projectiles=native)


def first_person(reader):
    s=submitted(reader)
    return s if s.get('live')and any(r['layer']=='first-person'for r in s['rows'])else None


def run(reader):
    require_foreground(reader)
    report=dict(version=1,passed=False,pid=reader.pid,started_unix_ns=time.time_ns(),console_commands=[],recording=False,
                scope='Private native weapon switching, normal attack/cast input, accepted-source combat geometry, native damage, unique native save/reload; no UE gameplay or full-game acceptance claim')
    saves=ROOT/'local/Morrowind/Saves';existing={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')};report['existing_save_hashes']=existing
    try:
        base=reader.snapshot()
        if tuple(base['cell_grid']or())!=(-2,-9)or base['menu']:raise RuntimeError('Expected the private Seyda Neen checkpoint')
        renderer=wait(lambda:live(reader),6)['renderer_pid']
        fixture=native_grid_fixture(base['cell_grid'],feet(reader));report['fixture']=fixture
        def command(text):
            console(reader,text,report)
            if any('script error'in s.lower()or'not found'in s.lower()for s in report['console_output'][-1]):raise RuntimeError('Original console rejected combat fixture command')
        for text in('player->SetHealth 200','player->SetMagicka 200','player->SetLongBlade 100','player->SetShortBlade 100','player->SetDestruction 100','player->SetWillpower 100',
                     'player->AddItem "iron longsword" 1','player->AddItem "steel shortsword" 1','player->AddSpell "fireball"'):
            command(text)
        x,y,z=fixture['player_position'];command(f'player->Position {x:.3f} {y:.3f} {z:.3f} 180')
        if reader.player_render_state(reader.u32(0x7c67dc)).get('third_person'):pulse(reader,'key',0x0f,.12)
        command('player->Equip "iron longsword"')
        if not reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        report['iron']=wait(lambda:first_person(reader),10)
        iron={r['asset']for r in report['iron']['rows']if r['layer']=='first-person'}
        command('player->Equip "steel shortsword"')
        def steel_ready():
            s=first_person(reader)
            return s if s and {r['asset']for r in s['rows']if r['layer']=='first-person'}!=iron else None
        report['steel']=wait(steel_ready,10)
        pulse(reader,'right',duration=.12);wait(lambda:'MenuMagic'in inspect_ui(reader)['active_menus'],4)
        act(reader,menu='MenuMagic',text='Fireball',click=True)
        if inspect_ui(reader)['native_ui']:pulse(reader,'right',duration=.12)
        wait(lambda:not inspect_ui(reader)['native_ui'],4)
        if not reader.snapshot()['player']['magic_ready']:pulse(reader,'key',0x13,.12)
        wait(lambda:first_person(reader),8);look(reader,math.pi,1.25)
        # Native draw/ready animations can ignore an early attack press even
        # while arms are visible. Let the original animation finish first.
        wait(lambda:reader.snapshot()['player']['magic_ready'],4);time.sleep(1.2)
        report['magicka_before_sky']=reader.snapshot()['player']['magicka']
        report['sky_cast']=observe(reader,4,lambda:pulse(reader,'left',duration=.15))
        report['magicka_after_sky']=reader.snapshot()['player']['magicka']
        if report['magicka_after_sky'][1]>=report['magicka_before_sky'][1]:raise RuntimeError('Original spell input was not accepted or did not spend magicka')
        projectiles=[r for s in report['sky_cast']['samples']if s.get('live')for r in s['rows']if r['layer']=='projectile']
        if len(projectiles)<2:raise RuntimeError('Native projectile did not reach two submitted UE samples')
        origin={};travel=0.
        for row in projectiles:
            first=origin.setdefault(row['id'],row['center']);travel=max(travel,math.dist(first,row['center']))
        report['projectile_travel']=travel
        if travel<4:raise RuntimeError('Submitted native projectile did not move')
        before={o['id']for o in reader.snapshot()['objects']}
        command('PlaceAtPC "rat_cave_fgrh" 1 400 0')
        def created():
            rows=[o for o in reader.snapshot()['objects']if o['id']not in before and o['type']=='CREA'and o['base_id'].startswith('rat_cave_fgrh')]
            return rows[0]if len(rows)==1 else None
        rat=wait(created,5);report['rat']=rat
        tx,ty,tz=fixture['destination'];command('"'+rat['base_id']+f'"->Position {tx:.3f} {ty:.3f} {tz+8:.3f} 0')
        def aim():
            target=next(o for o in reader.snapshot()['objects']if o['id']==rat['id']);cam=reader.camera_sample()['camera']['position'];d=[target['position'][i]-cam[i]for i in range(3)];d[2]+=20
            look(reader,math.atan2(d[0],d[1]),math.atan2(d[2],math.hypot(d[0],d[1])),.05)
            return target
        target=aim();report['spell_target_position']=target['position'];report['rat_before_spell']=actor_state(reader,rat['id'])
        report['target_cast']=observe(reader,3,lambda:pulse(reader,'left',duration=.15));report['rat_after_spell']=actor_state(reader,rat['id'])
        if report['rat_after_spell']['health'][1]>=report['rat_before_spell']['health'][1]:raise RuntimeError('Original spell did not damage the target')
        impacts=[r for s in report['target_cast']['samples']if s.get('live')for r in s['rows']if r.get('effect_target')==rat['id']]
        if not impacts:raise RuntimeError('Native hit effect owned by the target reference did not reach submitted UE geometry')
        report['impact_matches']=impacts
        if report['rat_after_spell']['health'][1]<=0:
            before={o['id']for o in reader.snapshot()['objects']};command('PlaceAtPC "rat_cave_fgrh" 1 80 0');rat=wait(created,5);report['melee_rat']=rat
        command('player->Equip "steel shortsword"')
        if not reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        wait(lambda:first_person(reader),8)
        target=aim();cam=reader.camera_sample()['camera']['position'];distance=math.dist(target['position'][:2],cam[:2])
        if distance>90:pulse(reader,'key',0x11,min(1.6,(distance-75)/130));aim()
        report['rat_before_melee']=actor_state(reader,rat['id']);report['melee']=[]
        for _ in range(4):
            aim();report['melee'].append(observe(reader,1.3,lambda:pulse(reader,'left',duration=.25)))
            if actor_state(reader,rat['id'])['health'][1]<report['rat_before_melee']['health'][1]:break
        report['rat_after_melee']=actor_state(reader,rat['id'])
        if report['rat_after_melee']['health'][1]>=report['rat_before_melee']['health'][1]:raise RuntimeError('Original melee input did not damage the target')
        poses={}
        for phase in report['melee']:
            for s in phase['samples']:
                for row in s.get('rows',[]):
                    if row['layer']=='first-person'and row['pose_signature']:poses.setdefault(row['id'],set()).add(row['pose_signature'])
        if not any(len(values)>1 for values in poses.values()):raise RuntimeError('Native first-person attack poses did not change in submitted UE state')
        save_name='combat_'+uuid.uuid4().hex[:10];save_menu(reader,save_name,report)
        def saved():
            new=[p for p in saves.glob('*.ess')if p.name not in existing]
            if len(new)!=1:return None
            body=new[0].read_bytes();return dict(name=save_name,path=str(new[0].relative_to(ROOT)),sha256=hashlib.sha256(body).hexdigest())if len(body)>1000 else None
        report['native_save']=wait(saved,10);old=wait(lambda:live(reader,renderer),6)
        pulse(reader,'key',1,.12);wait(lambda:'MenuOptions'in inspect_ui(reader)['active_menus'],3);act(reader,menu='MenuOptions',name='MenuOptions_Load_container',click=True)
        wait(lambda:choose(reader,menu='MenuLoad',text=save_name),4);act(reader,menu='MenuLoad',text=save_name,click=True)
        def prompt():
            if 'MenuMessage'not in inspect_ui(reader)['active_menus']:return None
            if 'Do you want to Load a save game and lose your current game?'not in{' '.join(row['text'].split())for row in tree(reader,'MenuMessage')}:raise ValueError('Unexpected load warning')
            return choose(reader,menu='MenuMessage',text='Yes')
        wait(prompt,4);act(reader,menu='MenuMessage',text='Yes',click=True)
        def restored():
            s=first_person(reader)
            return s if s and s['renderer_pid']==renderer and s['scene_epoch']!=old['scene_epoch']else None
        report['reloaded']=wait(restored,25);report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in existing.items())
        if not report['existing_saves_preserved']:report['passed']=False
        report['ended_unix_ns']=time.time_ns();(ROOT/'logs/native-combat.json').write_text(json.dumps(report,indent=2))
        if not report['existing_saves_preserved']:raise RuntimeError('An existing private save changed')
    return report
