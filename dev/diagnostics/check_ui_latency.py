"""Opt-in guarded private-game UI timing; no saves, video or gameplay writes.

Matches the live original cursor's projected geometry to the immutable body
actually submitted by UE Canvas. The render-thread probe is not scanout.
Requires a managed unified client with -PresentationStats, original focus and
a safe disposable exterior checkpoint. Both resource owners must become warm.
"""
import sys,time,json,struct,hashlib,threading,subprocess,os,argparse,re
from pathlib import Path
import numpy as np
sys.path[:0]=['bridge','dev/diagnostics','tools']
from live_probe import Reader,ROOT
from input_backend import pulse,point,require_foreground
from native_ui import inspect_ui,pause_gameplay
from local_files import read_json
from local_files import read_file_json
from scene_reader import SceneReader
from ui_scene import project,HEADER,DRAW,VERTEX
from check_normal_play import wait
from ui_timing import rows,summarize,stats,build_identity,runtime_log
from check_native_motion import witness
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pid',required=True,type=int);p.add_argument('--label',default='current');p.add_argument('--events',type=int,default=24);p.add_argument('--transitions',type=int,default=0);a=p.parse_args()
if not re.fullmatch('[a-z0-9-]{1,32}',a.label)or not 12<=a.events<=60 or not 0<=a.transitions<=24 or a.transitions%2:p.error('Use a short lowercase label, 12..60 cursor events and an even 0..24 inventory transitions')
root=ROOT;os.chdir(root);os.environ['PYTHONPATH']=os.pathsep.join(str(root/p)for p in('bridge','dev/diagnostics','tools'));pid=a.pid;r=Reader(pid);archive={};stop=threading.Event();archive_ready=threading.Event();events=[];errors=[];label=a.label
def collect(shape):
 while not stop.is_set():
  try:
   v=read_json(root/'local/bridge/ui.json');key=(v['session'],v['sequence']);ref=v['frame_ref']
   if key not in archive:
    body=(root/'local/bridge'/ref['file']).read_bytes()
    if hashlib.md5(body).hexdigest()!=ref['md5']:raise RuntimeError('UI body digest mismatch')
    # Retain verified body identities and original cursor vertices, not whole
    # image manifests/bodies. The full 60-event window fits without eviction.
    archive[key]=(ref['md5'].lower(),body_box(body,shape),tuple(v['ui']['active_menus']));archive_ready.set()
   if len(archive)>4096:raise RuntimeError('UI diagnostic exceeded its bounded observation window')
  except(OSError,ValueError,KeyError):pass
  time.sleep(.001)
def cursor_box(shape):
 w=r.u32(0x7c67dc);c=r.read(r.u32(w+0x18c),0x148);m=r.u32(shape+0x98);h=r.read(m,0x48);n=struct.unpack_from('<H',h,8)[0];p=np.frombuffer(r.read(struct.unpack_from('<I',h,0x1c)[0],n*12),dtype='<f4').reshape(-1,3);t=struct.unpack('<13f',r.read(shape+0x40,52));p=p@np.array(t[:9]).reshape(3,3).T*t[12]+t[9:12]
 camera=dict(position=struct.unpack_from('<3f',c,0x64),forward=struct.unpack_from('<3f',c,0xdc),up=struct.unpack_from('<3f',c,0xe8),right=struct.unpack_from('<3f',c,0xf4),frustum=struct.unpack_from('<6f',c,0x100));w,h=struct.unpack('<2I',r.read(w+0x78,8));xy,_=project(p,camera,w,h);return[*xy.min(0),*xy.max(0)]
def body_box(body,shape):
 h=HEADER.unpack_from(body);at=HEADER.size
 for _ in range(h[-1]):
  identity,tex,n,indices=DRAW.unpack_from(body,at);at+=16
  if identity==shape:
   v=np.frombuffer(body,dtype=VERTEX,count=n,offset=at)['values'][:,:2];return np.array([*v.min(0),*v.max(0)])
  at+=n*20+indices*2
 return None
def run():
 identity=build_identity(root)
 require_foreground(r)
 menu=inspect_ui(r)
 if 'MenuOptions'in menu['active_menus']:pulse(r,'key',1,.15);wait(lambda:not inspect_ui(r)['native_ui'],4)
 elif 'MenuInventory'in menu['active_menus']:pulse(r,'right',0,.15);wait(lambda:not inspect_ui(r)['native_ui'],4)
 elif menu['native_ui']:raise RuntimeError('Start in gameplay, inventory or pause menu')
 pulse(r,'key',0x11,.12);time.sleep(.4)
 if r.player_render_state(r.u32(0x7c67dc)).get('third_person'):pulse(r,'key',0x0f,.15);time.sleep(.3)
 # The auxiliary scenery owner has independent staging, so checking the
 # main owner's empty queue alone did not establish a warm comparison.
 warm=[];deadline=time.monotonic()+60
 while True:
  w=witness([],poll=.005);warm.append({k:w.get(k)for k in('live','distant_status','distant_visible','distant_partial_geometry','distant_catalog_staging','distant_resource_jobs_pending','distant_resource_error')})
  if w.get('live')and w.get('distant_visible',0)>0 and w.get('distant_partial_geometry')is False and not w.get('distant_catalog_staging')and not w.get('distant_resource_jobs_pending'):break
  if time.monotonic()>=deadline:raise RuntimeError('Distant resources did not become genuinely warm')
  time.sleep(.25)
 (root/f'logs/ui10-{label}-warmup.json').write_text(json.dumps(warm,indent=2));time.sleep(1)
 pulse(r,'key',0x11,.12);time.sleep(.3)
 if r.player_render_state(r.u32(0x7c67dc)).get('third_person'):pulse(r,'key',0x0f,.15);time.sleep(.3)
 if not inspect_ui(r)['native_ui']:pulse(r,'right',0,.15)
 wait(lambda:'MenuInventory'in inspect_ui(r)['active_menus'],4);time.sleep(1)
 def visible_overlay():
  state=read_file_json(root/'local/bridge/presentation.json')
  if state.get('reason')=='fallback_latched_restart_overlay':raise RuntimeError('Overlay fell back during menu warmup; CPU Canvas draws cannot establish visible UI response')
  return state if state.get('mode')=='overlay'and state.get('visible')and state.get('game_pid')==pid and 0<=time.time_ns()-state.get('unix_ns',0)<500_000_000 else None
 presentation_start=wait(visible_overlay,3)
 c=r.u32(r.u32(0x7c67dc)+0x18c);g=SceneReader(r).collect(roots=[r.u32(c+0x128)]);ids=[int(s['id'],16)for s in g['shapes']if s['visible']and s['name']=='cursor'and s['texture'].lower()=='tx_cursor.tga'];assert len(ids)==1;shape=ids[0]
 t=threading.Thread(target=collect,args=(shape,));t.start()
 if not archive_ready.wait(3):raise RuntimeError('UI source archive did not initialize before input')
 began=time.time()
 try:
  for i in range(a.events):
   before=r.read(shape+0x40,52);requested=time.time();dispatch=point(r,450+((i+1)%7)*31,100+((i+1)%4)*29);sent=dispatch['input_dispatch_unix_ns']/1e9;deadline=time.monotonic()+2
   while r.read(shape+0x40,52)==before:
    if time.monotonic()>=deadline:raise RuntimeError('Native cursor did not change')
    time.sleep(.001)
   changed=time.time();box=cursor_box(shape);events.append(dict(sent=sent,requested=requested,enqueue_return=dispatch['input_enqueued_unix_ns']/1e9,native_observed=changed,bbox=box));time.sleep(.3)
  menu_events=[]
  for i in range(a.transitions):
   before=inspect_ui(r)['native_ui'];failures=[];dispatches=[]
   def toggle():
    try:dispatches.append(pulse(r,'right',0,.08))
    except Exception as e:failures.append(repr(e))
   requested=time.time();action=threading.Thread(target=toggle);action.start();deadline=time.monotonic()+3
   while True:
    native=inspect_ui(r);changed=time.time()
    if native['native_ui']!=before:break
    if time.monotonic()>deadline:raise RuntimeError('Native inventory did not toggle')
    time.sleep(.001)
   action.join();assert not failures,failures
   menus=tuple(inspect_ui(r)['active_menus']) # after a full original input pulse/layout frame
   dispatch=dispatches[0];sent=dispatch['input_dispatch_unix_ns']/1e9
   menu_events.append(dict(sent=sent,requested=requested,enqueue_return=dispatch['input_enqueued_unix_ns']/1e9,native_observed=changed,menus=menus));time.sleep(.25)
  end=time.time();time.sleep(1.2)
  presentation_end=visible_overlay()
  if not presentation_end:raise RuntimeError('Overlay was not visible at the end of the UI measurement')
 finally:stop.set();t.join()
 raw=runtime_log(root).read_text(encoding='utf-8',errors='replace');draws=rows(raw,began,end+.7);result=dict(passed=False,scope='Guarded native input to first matching original cursor geometry submitted through actual UE Canvas; ordered render probe is not GPU completion/scanout.',build=identity,presentation_start=presentation_start,presentation_end=presentation_end,pid=pid,session=next(iter(archive))[0],events=events,pipeline=summarize(draws),save_writes=False,recording=False)
 for e in events:
  for d in sorted(draws,key=lambda d:d['times'][11]):
   if d['times'][11]<e['native_observed']:continue
   original=archive.get((d['session'],int(d['sequence'])))
   if not original or original[0]!=d['md5'].lower():continue
   box=original[1]
   if box is not None and np.max(np.abs(box-e['bbox']))<.75:
    e.update(draw_sequence=d['sequence'],input_to_draw_ms=(d['times'][11]-e['sent'])*1000,native_to_draw_ms=(d['times'][11]-e['native_observed'])*1000,native_to_render_probe_ms=(d['times'][13]-e['native_observed'])*1000,body_md5=d['md5']);break
 result['matched_events']=sum('draw_sequence'in e for e in events)
 for i,e in enumerate(menu_events):
  next_change=menu_events[i+1]['native_observed']if i+1<len(menu_events)else float('inf')
  for d in sorted(draws,key=lambda d:d['times'][11]):
   # A source capture may start before our menu walk returns yet already
   # contain the genuine new menu. Require capture after actual OS dispatch,
   # its verified new menu/body identity, and this transaction's lifetime.
   if not e['sent']<=d['times'][0]<next_change or d['times'][11]<e['native_observed']:continue
   original=archive.get((d['session'],int(d['sequence'])))
   if original and original[0]==d['md5'].lower()and original[2]==e['menus']:
    e.update(draw_sequence=d['sequence'],body_md5=d['md5'],input_to_draw_ms=(d['times'][11]-e['sent'])*1000,native_to_draw_ms=(d['times'][11]-e['native_observed'])*1000,native_to_render_probe_ms=(d['times'][13]-e['native_observed'])*1000);break
 result['inventory_transitions']=menu_events
 result['inventory_transition_input_to_draw_ms']=stats([e['input_to_draw_ms']for e in menu_events if 'input_to_draw_ms'in e])
 result['inventory_transition_native_to_draw_ms']=stats([e['native_to_draw_ms']for e in menu_events if 'native_to_draw_ms'in e])
 result['unarchived_draw_sequences']=len({(d['session'],int(d['sequence']))for d in draws if d['times'][0]>=began and(d['session'],int(d['sequence']))not in archive})
 for field in('input_to_draw_ms','native_to_draw_ms','native_to_render_probe_ms'):result[field]=stats([e[field]for e in events if field in e])
 result['passed']=result['matched_events']==len(events)and result['unarchived_draw_sequences']==0 and all('draw_sequence'in e for e in menu_events);(root/f'logs/ui10-{label}-ui.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items()if k not in('events','pipeline','inventory_transitions')}));print(json.dumps(result['pipeline']))
 assert result['passed'],'Not every native cursor event was observed in a matching drawn UI frame'
 pulse(r,'right',0,.15)
 wait(lambda:not inspect_ui(r)['native_ui'],4)
 errors=[]
 def moving():
  try:
   for _ in range(6):pulse(r,'key',0x1f,.7);pulse(r,'key',0x11,.7)
  except Exception as e:errors.append(repr(e))
 thread=threading.Thread(target=moving);thread.start()
 viewport=json.loads(raw.rsplit('UEMW perf ',1)[1].splitlines()[0]);source=read_json(root/'local/bridge/latest.json')
 context=['--width',str(viewport['width']),'--height',str(viewport['height'])]
 context+=['--grid',*map(str,source['cell_grid'])]if source.get('cell_grid')else['--cell',source['cell']]
 try:subprocess.run([sys.executable,'dev/diagnostics/benchmark.py','--seconds','7','--warmup','1','--moving',*context,'--output',f'logs/ui10-{label}-walk.json'],check=True,stdout=subprocess.DEVNULL,timeout=18)
 finally:thread.join()
 assert not errors,errors
 pulse(r,'key',1,.15)
try:run()
finally:
 stop.set()
 try:
  if not inspect_ui(r)['native_ui']:pause_gameplay(r)
 finally:r.close()
