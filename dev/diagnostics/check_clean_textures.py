"""Matched native wood/stone detail views and short movement; no saves/video."""
import hashlib,json,math,os,subprocess,sys,time
from live_probe import ROOT
from check_normal_play import console,wait,live,feet
from check_native_visuals import capture,read_json
from check_native_motion import witness,source_frame
from check_native_terrain import aim
from native_ui import inspect_ui
from input_backend import require_foreground,pulse
from acceptance_step import look

def run(reader):
    require_foreground(reader);label=os.environ['UEMW_CLEAN_TEXTURE_LABEL']
    if label not in ('before','after'):raise ValueError('Invalid clean texture label')
    saves=ROOT/'local/Morrowind/Saves';hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(passed=False,label=label,recording=False,save_writes=False,console_commands=[],shots=[],motion=[],started_unix_ns=time.time_ns())
    renderer=wait(lambda:live(reader),15)['renderer_pid']
    def accepted():
        w=live(reader,renderer)
        if not w or w.get('partial_geometry'):return None
        p,d=source_frame(w);c=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
        return w,p,d,c
    def shot(case):
        w,p,d,c=wait(accepted,20)
        if label=='after' and not (0<w.get('texture_upgrade_reserved_bytes',0)<=256*1024**2 and 'bounded scene selection'in w.get('texture_upgrade_path','')):raise RuntimeError('New bounded texture selection is not active')
        visible={b['asset']for b,s in zip(c['bindings'],p['instance_states'])if s[0]}
        textures={v['texture']:v.get('source_texture','')for k,v in c['meshes'].items()if k in visible and v.get('texture')}
        report['shots'].append(dict(case=case,image=capture('texture-clean-'+label+'-'+case),witness=w,camera=reader.camera_sample()['camera'],environment=p['environment'],source_md5=d,visible_textures=textures))
    def command(text):
        try:console(reader,text,report)
        except RuntimeError:
            if not text.lower().startswith('coc '):raise
            if inspect_ui(reader)['active_menus']==['MenuConsole']:pulse(reader,'key',0x29,.12)
            wait(lambda:not inspect_ui(reader)['native_ui'],20)
    try:
        if reader.snapshot()['player']['weapon_ready']:pulse(reader,'key',0x21,.12)
        command('tgm')
        for name,cell in (('wood',"Seyda Neen, Arrille's Tradehouse"),('rock','Addamasartus')):
            command('coc "'+cell+'"');wait(lambda:reader.snapshot()['cell']==cell,20);w,p,d,c=wait(accepted,25)
            s=reader.snapshot();camera=s['camera']['position']
            if name=='wood':
                target=next(o for o in s['objects']if o['type']=='NPC_'and o['base_id'].lower().startswith('arrille'));point=[*target['position']];point[2]+=40;aim(reader,point)
            else:
                lights=[v for v in p['environment']['lights']if v['kind']>1 and 90<math.dist(v['position'],camera)<1200]
                if lights:aim(reader,min(lights,key=lambda v:math.dist(v['position'],camera))['position'])
            shot(name+'-close')
            f=reader.camera_sample()['camera']['forward'];yaw=math.atan2(f[0],f[1]);pitch=math.asin(max(-1,min(1,f[2])))
            look(reader,yaw,-.65);shot(name+'-oblique')
            out=ROOT/f'logs/texture-clean-{label}-{name}-benchmark.json'
            with (ROOT/f'logs/texture-clean-{label}-{name}-benchmark-command.log').open('w')as log:
                subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','5','--warmup','1','--cell',cell,'--output',str(out)],stdout=log,stderr=subprocess.STDOUT,timeout=18,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
            start=feet(reader)
            for i,key in enumerate((0x11,0x1f,0x20,0x1e)):
                pulse(reader,'key',key,.18);look(reader,yaw+(.10 if i%2 else-.10),pitch);w,p,_,_=wait(accepted,8)
                report['motion'].append(dict(case=name,sequence=w['sequence'],camera=reader.camera_sample()['camera'],witness=w))
            report.setdefault('movement',{})[name]=math.dist(start,feet(reader));shot(name+'-moved')
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items());report['passed']&=report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns();(ROOT/f'logs/texture-clean-{label}.json').write_text(json.dumps(report,indent=2)+'\n')
    return report
