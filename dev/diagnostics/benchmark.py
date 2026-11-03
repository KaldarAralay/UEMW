"""Short performance check. Poll small manifests, never resolve frame bodies.

UE records every successfully applied unique state and its age AFTER geometry
and camera updates. The engine's legacy render_frames counter counts actor
ticks. It cannot establish displayed FPS, responsiveness or input latency.
"""
import argparse
import json
import re
import time
import ctypes as C
from ctypes import wintypes as W
from input_backend import U
from live_probe import ROOT
from measure_session import manifest,stats
from presentation_stats import summarize as presentation_summary
from ui_timing import perf_windows,runtime_log

def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=18)
    p.add_argument('--output',required=True);p.add_argument('--warmup',type=float,default=4)
    p.add_argument('--moving',action='store_true',help='Label a native walking measurement; do not claim a stationary run')
    p.add_argument('--width',type=int,default=1920);p.add_argument('--height',type=int,default=1080)
    p.add_argument('--wait-gameplay',type=float,default=0,help='Wait up to this many seconds for the expected original gameplay cell before warmup')
    p.add_argument('--grid',type=int,nargs=2,default=[-2,-9]);p.add_argument('--cell',help='Measure this native interior instead of an exterior grid');args=p.parse_args()
    if not 5<=args.seconds<=60:p.error('Use a 5..60 second check')
    if not 0<=args.warmup<=15:p.error('Warmup must be 0..15 seconds')
    if not 0<=args.wait_gameplay<=30:p.error('Gameplay wait must be 0..30 seconds')
    if not 128<=args.width<=8192 or not 96<=args.height<=8192:p.error('Invalid expected viewport dimensions')
    if args.wait_gameplay:
        deadline=time.monotonic()+args.wait_gameplay
        while time.monotonic()<deadline:
            s=manifest()
            if s.get('status')=='live'and not s.get('menu')and(s.get('cell')==args.cell if args.cell else s.get('cell_grid')==args.grid):break
            time.sleep(.05)
        else:raise RuntimeError('Expected original gameplay did not become ready for measurement')
    time.sleep(args.warmup)
    renderer_pid=int((ROOT/'local/bridge/renderer.pid').read_text(encoding='utf-8-sig'));path=runtime_log(ROOT,renderer_pid);offset=path.stat().st_size
    with path.open('rb')as log:boot=log.read(150000).decode(errors='replace')
    backend='Vulkan'if 'LogVulkanRHI:'in boot else'D3D12'if 'LogD3D12RHI:'in boot else'D3D11'if 'LogD3D11RHI:'in boot else'unknown'
    game_pid=int((ROOT/'local/bridge/game.pid').read_text());foreground=[]
    start=time.perf_counter();start_ns=time.time_ns();seen=set();source=[];errors=0;camera_seen=set();camera_source=[]
    source_observations=0;source_stale_or_future=0
    while time.perf_counter()-start<args.seconds:
        owner=W.DWORD();U.GetWindowThreadProcessId(U.GetForegroundWindow(),C.byref(owner));foreground.append(owner.value==game_pid)
        try:
            s=manifest();key=(s['session'],s['sequence'])
            age=time.time_ns()-s['sample_unix_ns'];source_observations+=1
            if not 0<=age<500_000_000:source_stale_or_future+=1
            if key not in seen:
                seen.add(key)
                source.append({k:s.get(k) for k in ('session','sequence','status','cell','cell_grid','stream_cells','sample_unix_ns','read_ms','pose_read_ms','pose_nodes_ms','pose_parts_ms','pose_translate_ms','pose_batch','geometry_stats','frame_ref','frame_ms','menu','camera','preparation','material_frames','material_values','scene_catalog')})
        except (OSError,ValueError,KeyError,TypeError):errors+=1
        try:
            with (ROOT/'local/bridge/camera.json').open('rb')as stream:camera=json.loads(stream.read(256*1024+1))
            key=(camera['session'],camera['sequence'])
            if key not in camera_seen and source and camera['session']==source[-1]['session']and camera['pid']==game_pid:
                camera_seen.add(key);camera_source.append({**{k:camera.get(k)for k in('session','sequence','sample_unix_ns','native_frame_ms','read_ms')},'view_read_ms':camera.get('view',{}).get('read_ms')})
        except (OSError,ValueError,KeyError,TypeError):pass
        time.sleep(.01)
    elapsed=time.perf_counter()-start
    if runtime_log(ROOT,renderer_pid)!=path:raise RuntimeError('Renderer log changed during measurement')
    with path.open('rb') as f:f.seek(offset);tail=f.read().decode('utf-8',errors='replace')
    windows=perf_windows(tail)
    duration=sum(w['seconds'] for w in windows)
    ages=[a for w in windows for a in w['age_ms']]
    result={'scope':f'Stationary supported exterior; {args.width}x{args.height}; original rendering enabled; no recording. Small-manifest observer at 100 Hz. Ages end at game-thread apply, excluding GPU/scanout.',
      'renderer_pid':renderer_pid,'renderer_log_file':str(path.relative_to(ROOT)),'expected_grid':args.grid,'renderer_backend':backend,'native_foreground_samples':len(foreground),'native_foreground_count':sum(foreground),
      'start_unix_ns':start_ns,'end_unix_ns':time.time_ns(),'observer_seconds':elapsed,
      'source_observed_unique':len(source),'source_unique_hz':len(source)/elapsed,
      'source_unique_engine_frame_hz':len({s['frame_ms']for s in source})/elapsed,
      'source_sessions':list(set(s['session'] for s in source)),
      'source_sequence_advance':source[-1]['sequence']-source[0]['sequence'] if source else 0,
      'source_live_count':sum(s['status']=='live' for s in source),'observer_errors':errors,
      'source_read_ms':stats([s['read_ms'] for s in source if s['read_ms'] is not None]),
      'source_pose_nodes_ms':stats([s['pose_nodes_ms']for s in source if s['pose_nodes_ms']is not None]),
      'source_pose_translate_ms':stats([s['pose_translate_ms']for s in source if s['pose_translate_ms']is not None]),
      'source_pose_interval_ms':stats([(b['sample_unix_ns']-a['sample_unix_ns'])/1e6 for a,b in zip(source,source[1:]) if a['session']==b['session']]),
      'ue_seconds':duration,'ue_game_thread_hz':sum(w.get('game_thread_ticks',w.get('render_frames',0)) for w in windows)/duration if duration else 0,
      'ue_unique_native_motion_hz':sum(w['native_motion_frames']for w in windows)/duration if duration and all('native_motion_frames'in w for w in windows)else None,
      'ue_unique_native_motion_scope':'Applied distinct original frame_ms per session/scene, including partial geometry; excludes GPU/scanout and does not imply whole-engine atomic capture.',
      'ue_resource_retargets':sum(w['resource_retargets']for w in windows)if windows and all('resource_retargets'in w for w in windows)else None,
      'ue_resource_rebind_hides':sum(w['resource_rebind_hides']for w in windows)if windows and all('resource_rebind_hides'in w for w in windows)else None,
      'ue_shared_mesh_aliases':sum(w['shared_mesh_aliases']for w in windows)if windows and all('shared_mesh_aliases'in w for w in windows)else None,
      'ue_render_fps':None,'ue_display_fps':None,
      'ue_presentation':presentation_summary([r for w in windows for r in w.get('dxgi_frame_statistics',[])],sum(w.get('dxgi_overflow',0)for w in windows)),
      'ue_game_thread_frame_interval_ms':stats([a for w in windows for a in w.get('frame_interval_ms',[])]),
      'ue_gpu_frame_ms':stats([a for w in windows for a in w.get('gpu_frame_ms',[])]),
      'ue_gpu_frame_scope':'Previous GPU timestamp duration if supported; excludes display/scanout. Empty samples mean unavailable.',
      'display_measurement':'Not measured by this observer. Use the separate display-delivery CSV; actor ticks are not displayed frames.',
      'ue_unique_applied_hz':len(ages)/duration if duration else 0,'ue_applied_count':len(ages),
      'ue_partial_applied_hz':sum(w.get('partial_applied',0)for w in windows)/duration if duration else 0,
      'ue_partial_age_ms':stats([a for w in windows for a in w.get('partial_age_ms',[])]),
      'ue_pending_native_instances_max':max((w.get('pending_native_instances_max',0)for w in windows),default=0),
      'ue_native_view_rectangles':sorted({(w.get('view_width'),w.get('view_height'))for w in windows}),
      'ue_camera_samples_hz':sum(w.get('camera_samples',0)for w in windows)/duration if duration else 0,
      'ue_camera_changes_hz':sum(w.get('camera_changes',0)for w in windows)/duration if duration else 0,
      'camera_source_observed_unique':len(camera_source),'camera_source_unique_hz':len(camera_source)/elapsed,
      'camera_source_native_frame_hz':len({s['native_frame_ms']for s in camera_source})/elapsed,
      'camera_source_read_ms':stats([s['read_ms']for s in camera_source if s['read_ms']is not None]),
      'camera_source_view_read_ms':stats([s['view_read_ms']for s in camera_source if s.get('view_read_ms')is not None]),
      'camera_source_interval_ms':stats([(b['sample_unix_ns']-a['sample_unix_ns'])/1e6 for a,b in zip(camera_source,camera_source[1:])]),
      'ue_camera_age_ms':stats([a for w in windows for a in w.get('camera_age_ms',[])]),
      'ue_bone_pose_update_hz':sum(w.get('bone_pose_updates',0)for w in windows)/duration if duration else 0,
      'ue_texture_frame_update_hz':sum(w.get('texture_frame_updates',0)for w in windows)/duration if duration else 0,
      'ue_material_value_update_hz':sum(w.get('material_value_updates',0)for w in windows)/duration if duration else 0,
      'ue_vertex_pose_update_hz':sum(w.get('vertex_pose_updates',0)for w in windows)/duration if duration else 0,
      'source_catalog_changes':sum(a.get('scene_catalog')!=b.get('scene_catalog')for a,b in zip(source,source[1:])if a['status']==b['status']=='live'),
      'source_texture_frame_changes':sum(a.get('material_frames')!=b.get('material_frames')for a,b in zip(source,source[1:])if a['status']==b['status']=='live')if all(s.get('material_frames')is not None for s in source)else None,
      'source_material_value_changes':sum(a.get('material_values')!=b.get('material_values')for a,b in zip(source,source[1:])if a['status']==b['status']=='live')if all(s.get('material_values')is not None for s in source)else None,
      'source_metadata_change_counter_scope':'Small-manifest observer; packed metadata bodies are not resolved, so unavailable change counts are null',
      'source_preparations':max((s.get('preparation')or{}).get('completed',0)for s in source)if source else 0,
      'max_pending_preparation_ms':max((s.get('preparation')or{}).get('pending_ms',0)for s in source)if source else 0,
      'expected_viewport':[args.width,args.height],
      'ue_applied_age_ms':stats(ages),
      'ue_poll_ms':stats([a for w in windows for a in w['poll_ms']]),
      'ue_geometry_camera_apply_ms':stats([a for w in windows for a in w['apply_ms']]),
      'ue_worker_decode_ms':stats([a for w in windows for a in w.get('decode_ms',[])]),
      'ue_worker_phases_ms':{name:stats([a for w in windows for a in w.get(name,[])]) for name in
          ('manifest_read_ms','channel_read_ms','manifest_json_ms','body_read_ms','body_hash_ms','body_decode_ms','decode_other_ms')},
      'ue_native_geometry_cpu_ms':{name:stats([v for w in windows for v in w.get('native_geometry_cpu_ms',{}).get(name,[])])for name in('total','catalog_materials','compare_resources','submit_changed','reconcile_cache','rigid_flush')},
      'ue_native_geometry_cpu_scope':'Main-owner CPU phase samples per accepted or rejected apply attempt, excluding GPU/display. Phases are nested within total and are not individual frame timelines.',
      'ue_catalog_stage_ms':stats([a for w in windows for a in w.get('stage_ms',[])]),
      'ue_catalog_bind_ms':stats([a for w in windows for a in w.get('catalog_bind_ms',[])]),
      'ue_rigid_membership_scan_ms':stats([a for w in windows for a in w.get('rigid_membership_scan_ms',[])]),
      'ue_resource_stage_ms':stats([a for w in windows for a in w.get('resource_stage_ms',[])]),
      'ue_resource_jobs_pending_max':max((w.get('resource_jobs_pending',0)for w in windows),default=0),
      'ue_resource_jobs_pending_final':windows[-1].get('resource_jobs_pending',0)if windows else None,
      'ue_resource_builds':sum(w.get('resource_builds',0)for w in windows),
      'ue_tick_ms':stats([a for w in windows for a in w.get('tick_ms',[])]),
      'ue_body_resolves':sum(w['body_resolves'] for w in windows),'ue_repeats':sum(w['repeats'] for w in windows),
      'first_source':source[0] if source else None,'last_source':source[-1] if source else None,
      'windows':windows}
    if args.cell:
        result['scope']=result['scope'].replace('Stationary supported exterior','Stationary native interior')
        result['expected_grid']=None;result['expected_cell']=args.cell
    if args.moving:result['scope']=result['scope'].replace('Stationary supported exterior','Native walking exterior').replace('Stationary native interior','Native moving interior')
    expected_key='interior'if args.cell else f'exterior:{args.grid[0]},{args.grid[1]}'
    result['valid_stationary_run']=bool(source and windows and len(result['source_sessions'])==1 and all(s['status']=='live' and (s['cell']==args.cell and s['cell_grid']is None if args.cell else s['cell_grid']==args.grid) and not s['menu'] for s in source) and all(w['session']==source[0]['session'] and w.get('cell_key')==expected_key and w.get('width')==args.width and w.get('height')==args.height for w in windows))
    result['valid_stationary_run']=result['valid_stationary_run']and bool(foreground)and all(foreground)
    result['source_observations']=source_observations
    result['source_stale_or_future_observations']=source_stale_or_future
    result['valid_native_context']=result['valid_stationary_run']
    result['valid_stationary_run']=result['valid_stationary_run']and source_observations>0 and source_stale_or_future==0
    result['valid_native_run']=result['valid_stationary_run']
    if args.moving:result['valid_stationary_run']=False
    result['pipeline_minimum_passed']=bool(result['valid_native_run'] and duration and result['ue_game_thread_hz']>=30 and result['ue_unique_applied_hz']>=20 and ages and result['ue_applied_age_ms']['p95']<100)
    # Deliberately fail the old broad gates: CPU-only evidence cannot validate
    # the slideshow/focus problem reported during actual play.
    result['targets_passed']=False
    result['responsiveness_targets_passed']=False
    result['rendering_acceptance_passed']=None
    result['threshold_scope']={'targets_passed':'False: actual displayed-frame timing is required',
        'responsiveness_targets_passed':'False: actual displayed-frame timing and normal play are required',
        'pipeline_minimum_passed':'CPU pipeline only: 30 UE ticks/s, 20 complete states/s, p95 applied age <100ms',
        'fresh_state_rate_target_passed':'Rate target only: 58 UE ticks/s, 58 complete states/s, 58 observed native engine frames/s; no scanout, sustained-play or animation proof'}
    result['fresh_state_rate_target_passed']=bool(result['valid_native_run'] and result['ue_game_thread_hz']>=58 and result['ue_unique_applied_hz']>=58 and result['source_unique_engine_frame_hz']>=58)
    (ROOT/args.output).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('windows','first_source','last_source')},indent=2))

if __name__=='__main__':main()
