"""Brief matched live canopy/undergrowth views; native movement, no saves/video."""
import hashlib,json,math,os,struct,subprocess,sys,time
import numpy as np
from live_probe import ROOT
from check_normal_play import console,wait,live,feet
from check_native_visuals import capture,read_json
from check_native_motion import witness,source_frame
from check_native_terrain import aim
from native_ui import inspect_ui
from input_backend import require_foreground,pulse
from scene_reader import SceneReader

TERMS=('leaves','leaf','fern','grassblade','grass_blade','flower','goldkanet','comberry','bittergreen','anther','vine','heather','hackle','cork_bulb','podplant')

def run(reader):
    require_foreground(reader);label=os.environ['UEMW_FOLIAGE_LABEL']
    if label not in ('before','after'):raise ValueError('Invalid foliage label')
    saves=ROOT/'local/Morrowind/Saves';hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(passed=False,label=label,recording=False,save_writes=False,shots=[],motion=[],console_commands=[],native_pose_checks=0,started_unix_ns=time.time_ns());ids=[]
    def command(text):
        try:console(reader,text,report)
        except RuntimeError:
            if not text.lower().startswith(('coc ','player->position ')):raise
            if inspect_ui(reader)['active_menus']==['MenuConsole']:pulse(reader,'key',0x29,.12)
            wait(lambda:not inspect_ui(reader)['native_ui'],18)
    def accepted():
        w=live(reader)
        if not w or w.get('partial_geometry'):return None
        p,d=source_frame(w);c=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
        if ids:
            visible=[b['id']for b,state in zip(c['bindings'],p['instance_states'])if state[0]and any(t in c['meshes'][b['asset']].get('source_texture','').lower()for t in TERMS)][:16]
            if not visible:return None
            w=witness(visible);p,d=source_frame(w);c=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
        byid={b['id']:s for b,s in zip(c['bindings'],p['instance_states'])}
        verified=0
        for row in w['instances']:
            s=byid.get(row['id'])
            if not s or not s[0]:continue
            if not row['submitted_visible']:raise RuntimeError('Visible native foliage was not submitted')
            payload=s[2]if len(s)>2 else None
            if payload and 'points'in payload:field='points_md5';value=payload['points']
            elif payload and 'palette'in payload:field='palette_md5';value=payload['palette']
            else:field='transform_md5';value=s[1]
            if row.get(field)!=hashlib.md5(np.asarray(value,dtype='<f4').tobytes()).hexdigest():raise RuntimeError('Native foliage pose digest mismatch')
            report['native_pose_checks']+=1
            verified+=1
        if ids and not verified:return None
        return w,p,d,c
    def shot(case):
        w,p,d,c=wait(accepted,18)
        if label=='after'and w.get('foliage_materials',0)<=0:raise RuntimeError('Dedicated foliage material is not active')
        report['shots'].append(dict(case=case,image=capture('foliage-'+label+'-'+case),witness=w,environment=p['environment'],camera=reader.camera_sample()['camera'],source_md5=d))
    def measure(case):
        p=read_json(ROOT/'local/bridge/latest.json');path=ROOT/f'logs/foliage-{label}-{case}-benchmark.json'
        with (ROOT/f'logs/foliage-{label}-{case}-benchmark-command.log').open('w')as log:subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','5','--warmup','1','--grid',*map(str,p['cell_grid']),'--output',str(path)],check=True,timeout=18,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        if reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        command('tgm');command('set gamehour to 12');command('player->Position -11600 -71000 200 0')
        world=reader.u32(0x7c67dc);controller=reader.u32(world+0x58);region=reader.u32(controller+0x1d0);name=reader.string(region+0x10,32)if region else'Bitter Coast Region'
        command('ChangeWeather "'+name+'" 0');start=time.monotonic();last_request=start
        def clear():
            nonlocal last_request
            current=reader.u32(controller+0x3c)
            if current and reader.u32(current+4)==0:return True
            if not reader.u32(controller+0x40)and time.monotonic()-last_request>2:command('ChangeWeather "'+name+'" 0');last_request=time.monotonic()
        wait(clear,165);report['native_clear_wait_seconds']=time.monotonic()-start
        # Restore the view after any original-engine idle/vanity camera.
        pulse(reader,'key',0x11,.08);command('player->Position -11600 -71000 200 0');time.sleep(.5)
        s=reader.snapshot();g=SceneReader(reader).collect(view_roots=s['view_roots'],aux_roots=s['aux_roots']);camera=s['camera']['position'];targets=[]
        for shape in g['shapes']:
            texture=shape.get('texture','').lower()
            if shape.get('alpha_mode')not in ('masked','translucent')or not any(t in texture for t in TERMS):continue
            bound=struct.unpack('<4f',reader.read(int(shape['id'],16)+0x1c,16))
            if 10<bound[3]<2400 and math.dist(bound[:3],camera)<3000:targets.append(dict(texture=shape['texture'],bound=bound,id=shape['id']))
        canopy=min((t for t in targets if 'leaves'in t['texture'].lower()),key=lambda t:math.dist(t['bound'][:3],camera))
        plants=[t for t in targets if 'leaves'not in t['texture'].lower()and t['bound'][2]<camera[2]+180]
        plant=min(plants,key=lambda t:math.dist(t['bound'][:3],camera))if plants else canopy
        report['targets']={'canopy':canopy,'undergrowth':plant}
        w,p,d,c=wait(accepted,20);ids=[b['id']for b,state in zip(c['bindings'],p['instance_states'])if state[0]and any(t in c['meshes'][b['asset']].get('source_texture','').lower()for t in TERMS)][:16]
        if not ids:raise RuntimeError('No native foliage IDs to verify')
        for case,target in report['targets'].items():
            ground=feet(reader)
            if label=='after'and case=='canopy':
                # Native collision-toggle inspection above an occluding roof.
                # This is a visual close-up, never a normal walking proof.
                command('tcl');b=target['bound'];eye_offset=reader.camera_sample()['camera']['position'][2]-ground[2]
                command(f'player->Position {b[0]:.3f} {b[1]-750:.3f} {b[2]-eye_offset:.3f} 0');time.sleep(.4)
                report['canopy_inspection']='Native TCL close-up above roof; restored before walking. Lighting-reference pair retains candidate colour.'
            aim(reader,target['bound'][:3]);time.sleep(.3)
            if label=='after':witness([],foliage_quality=False);shot(case+'-lighting-reference');witness([],foliage_quality=True)
            shot(case);measure(case)
            if label=='after'and case=='canopy':
                command('player->Position '+' '.join(f'{v:.3f}'for v in ground)+' 0');command('tcl');time.sleep(.5)
        aim(reader,plant['bound'][:3])
        for key in (0x11,0x1f,0x20,0x1e):
            pulse(reader,'key',key,.18);aim(reader,plant['bound'][:3]);w,p,d,c=wait(accepted,10);report['motion'].append(dict(witness=w,camera=reader.camera_sample()['camera'],source_md5=d,wind=p['environment']['weather']['wind']))
        shot('undergrowth-moved');report['passed']=report['native_pose_checks']>0
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items());report['passed']&=report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns();(ROOT/f'logs/foliage-{label}.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
