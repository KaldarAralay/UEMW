"""Guarded D3D11 queue-depth ABBA experiment in an already loaded private save.

Launch the managed client with PresentationStats and DiagnosticScreenshots.
Requires a safe exterior checkpoint, original focus and the normal 1024x768
unified viewport. No console commands, saves, recording or visual-quality
changes. Native walking and original controls remain authoritative. The
original renderer controls are restored and gameplay is paused on exit.
With --sync-paced, compare the normal 60 FPS CPU cap against VSync pacing
without that extra cap, at fixed queue depth 3. Requires measured 60 Hz output.
"""
import argparse,json,os,re,subprocess,sys,threading,time
from pathlib import Path
from live_probe import Reader,ROOT
from native_ui import inspect_ui,pause_gameplay
from input_backend import pulse,require_foreground
from check_normal_play import wait,feet
from check_native_motion import witness
from local_files import read_file_json
from ui_timing import build_identity

def run(r,label,seconds=7,sync_paced=False):
    require_foreground(r);identity=build_identity(ROOT);original=witness([],poll=.01)
    sync=bool(original['present_vsync']);latency=original['present_maximum_frame_latency']
    limit=original['present_frame_limit']
    if latency not in(1,2,3):raise RuntimeError('Existing queue depth is outside this bounded experiment; controls were preserved')
    if limit!=int(limit)or not(limit==0 and sync or 15<=limit<=60):raise RuntimeError('Existing frame limit is outside the bounded experiment; controls were preserved')
    limit=int(limit)
    report=dict(passed=False,build=identity,scope='Renderer-only ABBA '+('CPU cap versus VSync pacing at fixed depth 3 on a measured 60 Hz output.'if sync_paced else'queue depth with VSync off.')+' Actual device depth must match. Counters are polling evidence, not photons.',save_writes=False,recording=False,cases=[],original_controls=dict(vsync=sync,latency=latency,frame_limit=limit))
    try:
        if 'MenuOptions'in inspect_ui(r)['active_menus']:pulse(r,'key',1,.15);wait(lambda:not inspect_ui(r)['native_ui'],4)
        elif inspect_ui(r)['native_ui']:raise RuntimeError('Begin in native gameplay or Options')
        pulse(r,'key',0x11,.12);time.sleep(.4)
        if r.player_render_state(r.u32(0x7c67dc)).get('third_person'):pulse(r,'key',0x0f,.15)
        wait(lambda:r.camera_sample()['first_person_active'],4)
        deadline=time.monotonic()+60
        while True:
            w=witness([],poll=.01)
            if w.get('live')and not w.get('partial_geometry')and w.get('distant_visible',0)>0 and w.get('distant_partial_geometry')is False and not w.get('distant_catalog_staging')and not w.get('distant_resource_jobs_pending'):break
            if time.monotonic()>deadline:raise RuntimeError('Both scene resource owners did not become warm')
            time.sleep(.25)
        cases=[(3,False,60),(3,True,0),(3,True,0),(3,False,60)]if sync_paced else[(d,False,60)for d in(3,1,1,3)]
        for index,(depth,case_sync,case_limit) in enumerate(cases):
            if 'MenuOptions'in inspect_ui(r)['active_menus']:pulse(r,'key',1,.15);wait(lambda:not inspect_ui(r)['native_ui'],4)
            w=witness([],presentation_sync=case_sync,presentation_latency=depth,presentation_frame_limit=case_limit,poll=.01)
            assert w['present_vsync']==int(case_sync)and w['present_maximum_frame_latency']==depth and w['present_frame_limit']==case_limit
            time.sleep(1);before=feet(r);camera=r.camera_sample();errors=[]
            presentation=read_file_json(ROOT/'local/bridge/presentation.json')
            if not presentation.get('visible')or not presentation.get('ui_mirrored'):raise RuntimeError('Visible unified presentation is required')
            def moving():
                try:
                    for _ in range(max(1,int((seconds+2)/1.4)+1)):pulse(r,'key',0x1f,.7);pulse(r,'key',0x11,.7)
                except Exception as e:errors.append(repr(e))
            mover=threading.Thread(target=moving);mover.start();mode='sync'if case_sync else'cap';path=ROOT/f'logs/{label}-{index+1}-{mode}-depth{depth}.json'
            try:subprocess.run([sys.executable,str(ROOT/'dev/run.py'),'benchmark','--seconds',str(seconds),'--warmup','1','--moving','--width','1024','--height','768','--output',str(path)],check=True,stdout=subprocess.DEVNULL,timeout=seconds+12)
            finally:mover.join();pause_gameplay(r)
            if errors:raise RuntimeError(errors)
            b=json.loads(path.read_text(encoding='utf-8'));actual=b['ue_presentation']['maximum_frame_latency_values']
            if not b['valid_native_context']or actual!=[depth]:raise RuntimeError('Native context or actual DXGI queue depth did not match the case')
            report['cases'].append(dict(depth=depth,vsync=case_sync,frame_limit=case_limit,feet_before=before,feet_after=feet(r),camera_before=camera,benchmark=str(path.relative_to(ROOT)),**{k:b[k]for k in('ue_game_thread_frame_interval_ms','ue_gpu_frame_ms','ue_presentation','ue_catalog_stage_ms','ue_tick_ms')if k in b}))
            refresh=b['ue_presentation'].get('refresh_hz_estimate')
            if sync_paced and (refresh is None or not 59<=refresh<=61):raise RuntimeError('Sync-paced comparison requires measured 60 Hz output; no further cases will run')
        report['passed']=True
    finally:
        try:
            restored=witness([],presentation_sync=sync,presentation_latency=latency,presentation_frame_limit=limit,poll=.01);report['restored']=dict(vsync=bool(restored.get('present_vsync')),latency=restored.get('present_maximum_frame_latency'),frame_limit=restored.get('present_frame_limit'))
            if report['restored']!=report['original_controls']:report['passed']=False;raise RuntimeError('Renderer controls did not restore exactly')
            if not inspect_ui(r)['native_ui']:pause_gameplay(r)
        finally:(ROOT/f'logs/{label}-queue-comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pid',type=int,required=True);p.add_argument('--label',default='present-queue');p.add_argument('--seconds',type=int,default=7);p.add_argument('--sync-paced',action='store_true');a=p.parse_args()
    if not re.fullmatch('[a-z0-9-]{1,32}',a.label)or not 5<=a.seconds<=15:p.error('Use a short lowercase label and 5..15 seconds')
    os.environ['PYTHONPATH']=os.pathsep.join(str(ROOT/d)for d in('bridge','dev/diagnostics','tools'));r=Reader(a.pid)
    try:report=run(r,a.label,a.seconds,a.sync_paced);print(json.dumps({k:report[k]for k in('passed','cases','restored')},indent=2))
    finally:r.close()
