"""Read opt-in UE UI pipeline timestamps. No input, pixels or scanout claim."""
import json,math,re,statistics,time
import hashlib,struct
from pathlib import Path

STAGES=('capture','capture_end','encoded','body_ready','maintenance_end','publish_begin','read_queued','read_started','read_finished','promoted','draw_start','draw_end','end_frame','render_probe')


def renderer_log_path(root,state,renderer_pid,now_ns):
    """Select this fresh renderer's actual file, including UE's lock suffix.

    Do not guess the newest log or fall back to a previous process's output.
    The renderer publishes the file reported by UE's log-open callback.
    """
    root=Path(root).resolve()
    valid=(type(renderer_pid)is int and renderer_pid>0 and isinstance(state,dict)
        and type(state.get('version'))is int and state['version']==1
        and type(state.get('renderer_pid'))is int and state['renderer_pid']==renderer_pid
        and type(state.get('unix_ns'))in(int,float)and math.isfinite(state['unix_ns'])
        and 0<=now_ns-state['unix_ns']<=500_000_000)
    if not valid:raise RuntimeError('A fresh matching renderer heartbeat is required to select its log')
    name=state.get('renderer_log_file')
    if not isinstance(name,str)or not name or not Path(name).is_absolute():
        raise RuntimeError('Renderer did not publish its actual log file; rebuild the client')
    path=Path(name).resolve()
    if not path.is_relative_to(root/'logs')or path.suffix.lower()!='.log'or not path.is_file():
        raise RuntimeError('Renderer log must be an existing file inside this project logs directory')
    return path


def runtime_log(root,renderer_pid=None):
    from local_files import read_file_json
    root=Path(root).resolve();current=int((root/'local/bridge/renderer.pid').read_text(encoding='utf-8-sig'))
    if renderer_pid is not None and current!=renderer_pid:raise RuntimeError('Renderer changed during measurement')
    return renderer_log_path(root,read_file_json(root/'local/bridge/render-state.json'),current,time.time_ns())


def build_identity(root):
    """Refuse to benchmark a stale C++ package after a failed/omitted build."""
    root=Path(root).resolve();build=json.loads((root/'local/client/build-info.json').read_text(encoding='utf-8-sig'));checked=0
    for row in build['sources']:
        name=row['path'].replace('\\','/')
        if not name.startswith(('ue/UEMorrowind/Source/','ue/UEMorrowind/Config/','shaders/')):continue
        path=(root/name).resolve()
        if not path.is_relative_to(root)or hashlib.sha256(path.read_bytes()).hexdigest().lower()!=row['sha256'].lower():raise RuntimeError('Stale renderer package: '+name+'; run tools/package-client.ps1 before live checks')
        checked+=1
    if not checked:raise RuntimeError('Renderer build lacks compiled-source identities')
    for name,key in(('Windows/UEMorrowind/Binaries/Win64/UEMorrowind.exe','executable_sha256'),('Windows/UEMorrowind/Content/Paks/UEMorrowind-Windows.pak','pak_sha256')):
        if hashlib.sha256((root/'local/client'/name).read_bytes()).hexdigest().lower()!=build[key].lower():raise RuntimeError('Renderer package hash mismatch: '+name)
    return dict(built_utc=build.get('built_utc'),executable_sha256=build['executable_sha256'],pak_sha256=build['pak_sha256'],compiled_sources_checked=checked)


def draw_colours(body,identities):
    """Exact original packed RGBA bytes for selected actually-carried draws."""
    if not 56<=len(body)<=2*1024*1024 or body[:8]!=b'UUI1\x01\x00\x00\x00':raise ValueError('Invalid diagnostic UI body')
    count=struct.unpack_from('<I',body,52)[0]
    if count>2048:raise ValueError('Unbounded diagnostic UI draws')
    at=56;out={}
    for _ in range(count):
        if at+16>len(body):raise ValueError('Short diagnostic UI draw')
        identity,texture,n,indices=struct.unpack_from('<4I',body,at);at+=16;end=at+n*20+indices*2
        if not 0<n<=65536 or not 0<indices<=196608 or end>len(body):raise ValueError('Invalid diagnostic UI draw bounds')
        if identity in identities:
            if identity in out:raise ValueError('Duplicate diagnostic UI draw identity')
            colour=b''.join(body[p+16:p+20]for p in range(at,at+n*20,20));out[identity]=hashlib.md5(colour).hexdigest()
        at=end
    if at!=len(body):raise ValueError('Trailing diagnostic UI bytes')
    return out


def perf_windows(text):
    """Read complete log records while the renderer may still be writing EOF.

    Never turn a truncated nested object at EOF into a complete perf record.
    A malformed complete record is an error, rather than a silently lost stall.
    """
    out=[]
    for line in text.splitlines(keepends=True):
        if not line.endswith(('\n','\r')):continue
        marker='UEMW perf '
        if marker in line:out.append(json.loads(line.split(marker,1)[1]))
    return out


def rows(text,start=0,end=float('inf')):
    result=[]
    for body in re.findall(r'UEMW perf (\{[^\n]+\})',text):
        try:packet=json.loads(body)
        except ValueError:continue
        for row in packet.get('ui_pipeline',[]):
            t=row.get('times',[])
            if len(t)!=15 or any(type(v)not in(int,float)or not math.isfinite(v)for v in t):continue
            if not isinstance(row.get('session'),str)or type(row.get('sequence'))not in(int,float)or not isinstance(row.get('md5'),str):continue
            if not 0<t[0]<=t[10]<=t[11]<=t[12]<=t[13]or not start<=t[11]<=end:continue
            result.append(row)
    return result


def stats(values):
    values=sorted(values)
    if not values:return dict(count=0,median=None,p95=None,max=None)
    at=(len(values)-1)*.95;low=int(at);p95=values[low]+(values[min(low+1,len(values)-1)]-values[low])*(at-low)
    return dict(count=len(values),median=statistics.median(values),p95=p95,max=values[-1])


def summarize(values):
    first={}
    for row in values:
        key=(row['session'],row['sequence']);old=first.get(key)
        if old and old['md5']!=row['md5']:raise ValueError('One UI source sequence has conflicting body identities')
        if old is None or row['times'][11]<old['times'][11]:first[key]=row
    unique=list(first.values());pairs={'capture_ms':(0,1),'encode_ms':(1,2),'body_publish_ms':(2,3),'cache_maintenance_ms':(3,4),'publish_to_read_finished_ms':(5,8),'read_queue_wait_ms':(6,7),'read_ms':(7,8),'read_to_promote_ms':(8,9),'promote_to_draw_ms':(9,10),'draw_cpu_ms':(10,11),'capture_to_first_draw_ms':(0,11),'capture_to_render_probe_ms':(0,13),'end_frame_to_render_probe_ms':(12,13)}
    out=dict(draw_observations=len(values),unique_ui_frames=len(unique),scope='Actual native capture to CPU Canvas submission and an ordered render-thread probe; not GPU completion, display or photon timing.')
    for label,(a,b)in pairs.items():out[label]=stats([(r['times'][b]-r['times'][a])*1000 for r in unique if r['times'][a]>0 and r['times'][b]>=r['times'][a]])
    out['capture_to_all_draws_ms']=stats([(r['times'][11]-r['times'][0])*1000 for r in values]);return out
