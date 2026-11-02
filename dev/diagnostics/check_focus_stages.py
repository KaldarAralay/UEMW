"""Short opt-in native/bridge/UE check, with explicit gameplay/image options.

Requires existing psutil for diagnostic resource counters. Each native clock
observation is a read, not a present/scanout or animation-performance metric.
The enclosing tools/check-focus-isolation.ps1 owns final native cleanup.
"""
import argparse
import concurrent.futures
import ctypes as C
from ctypes import wintypes as W
import json
import hashlib
import subprocess
import sys
import time
import shutil

import psutil

from live_probe import ROOT,Reader
from local_files import read_json,read_file_json
from native_window_health import probe_native_window,U
from measure_session import stats
from native_ui_test import choose,act,tree
from input_backend import require_foreground,move,wheel


def command(name,*args):
    # Start-Process children can inherit a captured anonymous pipe even when
    # their standard streams are redirected. Waiting for pipe EOF then waits
    # for the bridge lifetime instead of the launcher. A file has no EOF wait.
    path=ROOT/'logs'/('focus-isolation-'+name+'.log')
    with path.open('w')as output:
        result=subprocess.run(['pwsh.exe','-NoProfile','-File',str(ROOT/'tools'/name),*map(str,args)],
            cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW,stdout=output,stderr=subprocess.STDOUT,timeout=20)
    text=path.read_text(errors='replace')
    if result.returncode:raise RuntimeError(name+': '+text)
    print(text.strip(),flush=True)


def sample(reader,name,seconds,report,move_camera=False,composition=False):
    process=psutil.Process(reader.pid)
    records=[];windows=[];resources=[];desktop=[];last_stamp=None;changes=[];last_tick=None;ticks=[]
    start=time.monotonic();last_resource=0.;last_probe=0.;last_mouse=0.;last_desktop=0.;pending=None
    if composition:from desktop_timing import capture as capture_desktop
    phase=dict(name=name,started_unix_ns=time.time_ns(),seconds=seconds,
        started_qpc_ms=time.perf_counter()*1000,native_mouse_sweep=move_camera)
    (ROOT/'local/bridge/focus-stage.json').write_text(json.dumps(phase))
    print(json.dumps(dict(event='stage',**phase)),flush=True)
    with concurrent.futures.ThreadPoolExecutor(1) as executor:
        while time.monotonic()-start<seconds:
            now=time.monotonic()
            if last_tick is not None:ticks.append((now-last_tick)*1000)
            last_tick=now
            reader.check_alive()
            if move_camera and now-last_mouse>=1/120:
                move(reader,1,0);last_mouse=now
            if composition and now-last_desktop>=.05:
                desktop.append(capture_desktop());last_desktop=now
            world=reader.u32(0x7c67dc);stamp=reader.u32(world+0x24)
            owner=W.DWORD();U.GetWindowThreadProcessId(U.GetForegroundWindow(),C.byref(owner))
            native_foreground=owner.value==reader.pid
            records.append(dict(elapsed=now-start,native_frame_ms=stamp,foreground=native_foreground))
            if native_foreground and stamp!=last_stamp:changes.append(now)
            last_stamp=stamp
            if pending and pending.done():
                windows.append(dict(elapsed=now-start,**pending.result()));pending=None
            if not pending and now-last_probe>=.5:
                pending=executor.submit(probe_native_window,reader.pid);last_probe=now
            if now-last_resource>=1:
                with process.oneshot():
                    mem=process.memory_info();cpu=process.cpu_times()
                    record=dict(elapsed=now-start,native_working_mb=mem.rss/2**20,
                        native_private_mb=getattr(mem,'private',0)/2**20,
                        native_cpu_seconds=cpu.user+cpu.system,available_memory_mb=psutil.virtual_memory().available/2**20)
                for tag,pidfile in [('bridge','reader.pid'),('ue','renderer.pid')]:
                    try:
                        pid=int((ROOT/'local/bridge'/pidfile).read_text());p=psutil.Process(pid)
                        expected='geometry_stream.py'if tag=='bridge'else'UEMorrowind.exe'
                        if expected.lower()not in' '.join(p.cmdline()).lower():continue
                        with p.oneshot():
                            memory=p.memory_info();cpu=p.cpu_times()
                            record[tag+'_working_mb']=memory.rss/2**20
                            record[tag+'_private_mb']=getattr(memory,'private',0)/2**20
                            record[tag+'_cpu_seconds']=cpu.user+cpu.system
                    except (OSError,ValueError,psutil.Error):pass
                resources.append(record);last_resource=now
            time.sleep(max(0,.01-(time.monotonic()-now)))
        if pending:windows.append(dict(elapsed=time.monotonic()-start,**pending.result(timeout=1)))
    elapsed=time.monotonic()-start
    result=dict(**phase,elapsed_seconds=elapsed,ended_qpc_ms=time.perf_counter()*1000,
        scope='Native checkpoint with an explicit mouse sweep when enabled. Clock observations and WM_NULL are not presents or scanout.',
        observations=len(records),foreground_observations=sum(r['foreground']for r in records),
        observed_native_clock_changes=len(changes),observed_native_clock_hz=len(changes)/elapsed,
        native_clock_change_interval_ms=stats([(b-a)*1000 for a,b in zip(changes,changes[1:])]),
        observer_scheduling_interval_ms=stats(ticks),window_probe_ms=stats([w['probe_ms']for w in windows]),
        unresponsive_window_probes=sum(w['responding']is False for w in windows),
        records=records,windows=windows,resources=resources,desktop_composition=desktop)
    if len(desktop)>1:
        first,last=desktop[0],desktop[-1];span=(last['qpc_ms']-first['qpc_ms'])/1000
        result['global_dwm']=dict(scope='Global composition counters; not per-window displayed FPS',
            composed_hz=(last['frame']-first['frame'])/span,confirmed_hz=(last['confirmed']-first['confirmed'])/span,
            late=last['late']-first['late'])
    report['stages'].append(result)
    (ROOT/'logs/focus-isolation.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({k:v for k,v in result.items()if k not in('records','windows','resources','desktop_composition')}),flush=True)
    if result['unresponsive_window_probes']>=4:raise RuntimeError('Native window non-response observed; stop isolation instead of adding more load')


def wait_live(pid,renderer=None,seconds=25):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            source=read_json(ROOT/'local/bridge/latest.json')
            if (source.get('pid')==pid and source.get('status')=='live' and not source.get('menu')
                    and 0<=time.time_ns()-source.get('sample_unix_ns',0)<500_000_000):
                if renderer is None:return
                state=read_file_json(ROOT/'local/bridge/render-state.json')
                if (state.get('renderer_pid')==renderer and state.get('live')and state.get('session')==source['session']
                        and state.get('scene_epoch')==source.get('scene_epoch')
                        and 0<=time.time_ns()-state.get('unix_ns',0)<500_000_000):return
        except (OSError,ValueError):pass
        time.sleep(.05)
    raise RuntimeError('Expected fresh current live state did not become ready within isolation deadline')


def load_checkpoint(reader,report,checkpoint='UEMW Broad Quest Complete'):
    """Existing native-cursor test API: two fresh selectors, no save writes.

    Absolute OS cursor clicks do not position Morrowind's DirectInput cursor.
    Use its already guarded relative-menu helper, with held-button transitions
    spanning native polls. No ordinary runtime client input is introduced.
    """
    end=time.monotonic()+60;last_skip=time.monotonic()
    while time.monotonic()<end:
        try:
            require_foreground(reader)
            item=choose(reader,menu='MenuOptions',name='MenuOptions_Load_container')
            ready=item['rect']!=[512,384,120,50]and 0<=item['rect'][0]<1024 and 0<=item['rect'][1]<768
            if ready:break
        except (OSError,ValueError,RuntimeError):pass
        if time.monotonic()-last_skip>=2:
            # Skip only the original startup movie before any native cell is
            # loaded. Never send an Escape into a running gameplay fixture.
            try:
                data=reader.u32(0x7c67e0)
                if not data or not reader.u32(data+0xb540):
                    from input_backend import pulse
                    pulse(reader,'key',1,.08)
                    report['native_intro_skip_pulses']=report.get('native_intro_skip_pulses',0)+1
            except(OSError,ValueError,RuntimeError):pass
            last_skip=time.monotonic()
        time.sleep(.1)
    else:raise RuntimeError('Private native load menu/foreground did not become ready')
    report['native_load_menu']=act(reader,menu='MenuOptions',name='MenuOptions_Load_container',click=True)
    end=time.monotonic()+14;last_scroll=0.;scrolls=0
    while time.monotonic()<end:
        try:
            choose(reader,menu='MenuLoad',text=checkpoint);break
        except (OSError,ValueError,RuntimeError):
            rows=tree(reader,'MenuLoad');report['native_checkpoint_menu_rows']=rows
            titles=[r for r in rows if r['text'].startswith(('water_','combat_','UEMW','uemw'))and r['rect'][2]>0 and r['rect'][3]>0]
            if titles and scrolls<20 and time.monotonic()-last_scroll>.35:
                act(reader,menu='MenuLoad',element=titles[0]['id']);wheel(reader,-3);scrolls+=1;last_scroll=time.monotonic()
                report['native_checkpoint_scrolls']=scrolls
            time.sleep(.05)
    else:raise RuntimeError('Exact disposable checkpoint was not in the current native load menu')
    report['native_checkpoint_selection']=act(reader,menu='MenuLoad',text=checkpoint,click=True)
    report['native_menu_selection_clicks']=2
    end=time.monotonic()+15
    while time.monotonic()<end:
        try:
            s=reader.camera_sample()
            if not s['menu']and not s['native_loading']:
                report['loaded_native_camera']=s
                return
        except (OSError,ValueError,RuntimeError):pass
        time.sleep(.1)
    raise RuntimeError('Disposable native checkpoint did not become ready')


def main():
    p=argparse.ArgumentParser();p.add_argument('--pid',required=True,type=int);p.add_argument('--trace',action='store_true')
    p.add_argument('--rhi',choices=('vulkan','d3d11'),default='d3d11')
    p.add_argument('--combined-only',action='store_true');p.add_argument('--capture-once',action='store_true');p.add_argument('--normal-play',action='store_true')
    p.add_argument('--npc-motion',action='store_true');p.add_argument('--display-timing',action='store_true')
    p.add_argument('--water-play',action='store_true')
    p.add_argument('--stability-check',action='store_true')
    p.add_argument('--combat-play',action='store_true')
    p.add_argument('--visual-check',action='store_true');p.add_argument('--outdoor-check',action='store_true');p.add_argument('--texture-check',action='store_true');p.add_argument('--terrain-check',action='store_true')
    p.add_argument('--checkpoint',default='UEMW Broad Quest Complete')
    p.add_argument('--composition-timing',action='store_true');p.add_argument('--native-only',action='store_true');args=p.parse_args()
    sweep=args.display_timing or args.composition_timing
    if args.display_timing and (args.combined_only or args.normal_play or args.npc_motion or args.water_play):p.error('Elevated display isolation requires its three phases without gameplay fixtures')
    if args.composition_timing and (args.normal_play or args.npc_motion or args.water_play):p.error('Composition check must be separate from gameplay fixtures')
    if args.native_only and (args.display_timing or args.combined_only or args.normal_play or args.npc_motion or args.water_play):p.error('Native-only check cannot launch a renderer or elevated observer')
    report=dict(version=1,pid=args.pid,rhi=args.rhi,started_unix_ns=time.time_ns(),stages=[],recording=False,
        benchmark_mouse_sweep=sweep,normal_play_input_requested=args.normal_play,npc_motion_input_requested=args.npc_motion)
    r=Reader(args.pid);gpu=None;gpu_log=None
    try:
        if args.checkpoint!='UEMW Broad Quest Complete':
            saved=read_json(ROOT/'logs/native-combat.json',4*1024*1024)['native_save'];path=(ROOT/saved['path']).resolve()
            if saved['name']!=args.checkpoint or path.parent!=(ROOT/'local/Morrowind/Saves').resolve()or hashlib.sha256(path.read_bytes()).hexdigest()!=saved['sha256']:raise RuntimeError('Only the recorded unchanged disposable combat save may override the diagnostic checkpoint')
        report['checkpoint']=args.checkpoint
        load_checkpoint(r,report,args.checkpoint)
        if args.display_timing:command('start-display-capture.ps1')
        gpu_log=(ROOT/'logs/focus-isolation-gpu.csv').open('w')
        try:
            gpu=subprocess.Popen(['nvidia-smi.exe','--query-gpu=timestamp,index,utilization.gpu,utilization.memory,memory.used,power.draw',
                '--format=csv,noheader,nounits','--loop-ms=500'],stdout=gpu_log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as e:report['gpu_counter_error']=str(e)
        if not args.combined_only:sample(r,'native_only',5 if args.native_only else 10,report,move_camera=sweep,composition=args.composition_timing)
        if args.native_only:
            report['completed']=True;report['scope']='Private native-only presentation check; bridge and UE were not started';return
        command('start-bridge.ps1','-GamePid',args.pid,'-Hz',60,'-Background')
        wait_live(args.pid)
        if not args.combined_only:sample(r,'native_plus_bridge',8,report,move_camera=sweep,composition=args.composition_timing)
        flags=['-DiagnosticTrace']if args.trace else[]
        if args.capture_once or args.water_play or args.combat_play or args.visual_check or args.outdoor_check or args.texture_check or args.terrain_check or args.stability_check:flags.append('-DiagnosticScreenshots')
        renderer_start=time.monotonic()
        command('start-renderer.ps1','-TwoWindows','-Width',1920,'-Height',1080,'-MaxFPS',60,'-RHI',args.rhi,*flags)
        renderer=int((ROOT/'local/bridge/renderer.pid').read_text())
        wait_live(args.pid,renderer)
        report['renderer_launch_to_live_seconds']=time.monotonic()-renderer_start
        bench_path=ROOT/('logs/'+args.rhi+'-live-benchmark.json')
        with (ROOT/('logs/'+args.rhi+'-live-benchmark-command.log')).open('w')as output:
            bench_args=['--moving']if sweep else[]
            bench=subprocess.Popen([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','10','--warmup','2','--width','1920','--height','1080','--output',str(bench_path),*bench_args],
                stdout=output,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                sample(r,'native_bridge_ue',15,report,move_camera=sweep,composition=args.composition_timing)
                report['benchmark_exit_code']=bench.wait(timeout=3)
                report['benchmark']=str(bench_path.relative_to(ROOT))
            finally:
                if bench.poll()is None:bench.terminate();bench.wait(timeout=3)
        if args.normal_play:
            from check_normal_play import run
            report['normal_play']=run(r)
        if args.water_play:
            from check_native_water import run
            report['water_play']=run(r)
        if args.combat_play:
            from check_native_combat import run
            report['combat_play']=run(r)
        if args.outdoor_check:
            from check_native_outdoors import run
            report['outdoor_check']=run(r)
        if args.terrain_check:
            from check_native_terrain import run
            report['terrain_check']=run(r)
        if args.texture_check:
            from check_native_textures import run
            report['texture_check']=run(r)
        if args.visual_check:
            from check_native_visuals import run
            report['visual_check']=run(r)
        if args.npc_motion:
            output=ROOT/'logs/native-motion.json'
            with (ROOT/'logs/native-motion-command.log').open('w')as log:
                motion=subprocess.Popen([sys.executable,str(ROOT/'dev/diagnostics/check_native_motion.py'),'--pid',str(args.pid),'--output',str(output)],
                    stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    if motion.wait(timeout=60):raise RuntimeError('Native NPC motion failed; see logs/native-motion.json')
                    report['npc_motion']=read_json(output)
                finally:
                    if motion.poll()is None:motion.terminate();motion.wait(timeout=3)
        if args.stability_check:
            from check_render_stability import run
            report['render_stability']=run(r)
        if args.capture_once:
            if args.checkpoint!='UEMW Broad Quest Complete':
                from check_native_combat import submitted,catalog
                from check_native_motion import witness
                view_sample=submitted(r)
                if not view_sample.get('live')or not r.camera_sample().get('first_person_active'):raise RuntimeError('Expected live original first-person view for body visibility check')
                meta=read_json(ROOT/'local/bridge/latest.json');bindings=catalog(meta['scene_catalog'])['bindings']
                ids=[b['id']for b in bindings if b.get('layer')=='player'and not b.get('effect_target')]
                if not 0<len(ids)<=64:raise RuntimeError('Native third-person body witness exceeds this bounded check')
                body=witness(ids);report['first_person_body_gate']=dict(passed=body.get('live')and all(not row['submitted_visible']for row in body['instances']),checked=len(ids),first_person_state=view_sample)
                if not report['first_person_body_gate']['passed']:raise RuntimeError('Third-person player body is visible in the original first-person mode')
            requested=time.time_ns();flag=ROOT/'local/bridge/capture.once';image=ROOT/'logs/ue-inspect.png'
            flag.write_text(str(requested))
            try:
                end=time.monotonic()+6
                while time.monotonic()<end:
                    if image.exists()and image.stat().st_mtime_ns>=requested:
                        destination=ROOT/('logs/'+args.rhi+'-live-ue.png')
                        try:
                            # UE can set the timestamp before closing its
                            # exclusive PNG writer. Retry until a complete
                            # fresh image can actually be copied and decoded.
                            from PIL import Image
                            shutil.copyfile(image,destination)
                            with Image.open(destination)as decoded:decoded.verify()
                        except (OSError,SyntaxError):
                            time.sleep(.1);continue
                        report['one_shot_image']=str(destination.relative_to(ROOT));break
                    time.sleep(.1)
                else:raise RuntimeError('Requested fresh one-shot UE backbuffer did not arrive')
            finally:
                if flag.exists():flag.unlink()
        report['completed']=True
    except BaseException as e:
        report['completed']=False;report['error']=str(e)
        raise
    finally:
        r.close()
        if gpu:
            gpu.terminate();gpu.wait(timeout=3)
        if gpu_log:gpu_log.close()
        report['ended_unix_ns']=time.time_ns()
        (ROOT/'logs/focus-isolation.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':main()


