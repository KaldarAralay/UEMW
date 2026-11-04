"""Source-owned UI-only render-state lane; never captures a game window."""
import argparse,ctypes as C,hashlib,json,os,subprocess,sys,time
from collections import Counter
from ctypes import wintypes as W
from pathlib import Path
from live_probe import ROOT,Reader,K,SceneReadChanged
from local_files import read_file_json
from shared_channel import validate_descriptor,Writer as ChannelWriter
from ui_scene import UICapture,encode
from asset_files import publish
from distant_stream import atomic


def start(pid,session):
    log=(ROOT/'logs/ui-worker.log').open('w',encoding='utf-8')
    try:return subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--pid',str(pid),'--session',session,'--owner',str(os.getpid())],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    finally:log.close()


def source_identity(value,pid,session,owner):
    # UI only needs the publishing owner's identity. Resolving a world-pose
    # slot here coupled cursor capture to unrelated shared-copy contention.
    # The already-open owner process handle is independently checked alive.
    if value.get('protocol')=='uemw.channel':
        value=validate_descriptor(value)
        return value['pid']==pid and value['session']==session and value['writer_pid']==owner
    return value.get('protocol')=='uemw.live'and value.get('version')==1 and value.get('pid')==pid and value.get('session')==session


def trim(folder,history,frames,limit=256*1024*1024):
    while True:
        keep={t['file']:t['bytes']for row in history for t in row['textures']}
        if sum(keep.values())<=limit or len(history)<=2:break
        history.pop(0)
    if sum(keep.values())>limit:raise ValueError('Native UI cache exceeds 256 MiB')
    keep_frames={row['frame_ref']['file']for row in history}
    removed=set()
    for path in folder.glob('*.utx'):
        if path.name not in keep:
            try:path.unlink();removed.add(path.name)
            except PermissionError:pass
    for path in frames.glob('*.uui'):
        if 'ui-frames/'+path.name not in keep_frames:
            try:path.unlink()
            except PermissionError:pass
    return removed,sum(keep.values())


def retire_cached_images(capture,removed):
    # Retiring one old menu image must not evict still-referenced fonts and
    # every other menu image. Only entries whose actual file retired are cold.
    for key,row in list(capture.files.items()):
        if row['file']in removed:del capture.files[key]
    for key,(_,row)in list(capture.pixel_cache.items()):
        if row['file']in removed:del capture.pixel_cache[key]


def wait_period(capture,began,period):
    # HUD publication stays at 30 Hz, but entering a native menu must not wait
    # out that slower interval. This is a read-only mode probe, never input or
    # a UI clock. Every published menu still requires a complete fresh capture.
    remaining=period-(time.perf_counter()-began)
    if remaining<=0:
        # A completed capture already consumed the interval. Yield without
        # adding another 2 ms to every over-budget native menu sample.
        time.sleep(0);return
    time.sleep(min(.002,remaining))
    probe=getattr(capture,'menu_probe',None)
    while time.perf_counter()-began<period:
        if probe:
            world,menu=probe
            try:
                if capture.native.u32(0x7c67dc)!=world or bool(capture.native.read(world+0xd6,1)[0])!=menu:return
            except OSError:return
        time.sleep(min(.002,max(0,period-(time.perf_counter()-began))))


def main():
    p=argparse.ArgumentParser();p.add_argument('--pid',required=True,type=int);p.add_argument('--session',required=True);p.add_argument('--owner',required=True,type=int);a=p.parse_args()
    owner=K.OpenProcess(0x1000,False,a.owner)
    if not owner:raise RuntimeError('Native UI source owner is absent')
    r=Reader(a.pid);capture=UICapture(r);folder=ROOT/'local/bridge';frames=folder/'ui-frames';frames.mkdir(parents=True,exist_ok=True)
    channel=None if os.environ.get('UEMW_UI_SHARED_CHANNEL')=='0'else ChannelWriter(a.pid,a.session)
    advertised=False
    def publish_ui(value,body=b''):
        nonlocal advertised
        if channel:
            result,_=channel.publish_ui(value,body)
            if not advertised:atomic(folder/'ui.json',channel.d);advertised=True
            return result
        atomic(folder/'ui.json',value);return value
    sequence=0;history=[];last_log=0;last_status=None;last_menus=None;drops=0;period=1/30;wire_cache={};drop_reasons=Counter()
    try:
        while True:
            code=W.DWORD()
            if not K.GetExitCodeProcess(owner,C.byref(code))or code.value!=259:break
            began=time.perf_counter();stamp=time.time_ns();frame_sequence=sequence;sequence+=1
            try:
                source=read_file_json(folder/'latest.json')
                if not source_identity(source,a.pid,a.session,a.owner):raise SceneReadChanged('Native UI source session changed')
                # An attempted publication already owns its immutable filename.
                # A busy shared copy must not reuse that identity next time.
                sample=capture.sample();capture_end=time.time_ns();body=encode(sample,a.session,frame_sequence,stamp,a.pid,wire_cache);encoded=time.time_ns();name='ui-frames/'+a.session.replace('-','')+'-'+str(frame_sequence)+'.uui';publish(folder/name,body);body_ready=time.time_ns()
                value=dict(protocol='uemw.ui',version=1,status='live',pid=a.pid,session=a.session,sequence=frame_sequence,sample_unix_ns=stamp,frame_ref=dict(file=name,md5=hashlib.md5(body).hexdigest(),bytes=len(body)),textures=sample['textures'],native_regions=sample['native_regions'],ui=sample['ui'],ui_root=sample['root'],width=sample['width'],height=sample['height'],draws=len(sample['draws']),vertices=sample['vertices'],indices=sample['indices'],texture_bytes=sample['texture_bytes'],capture_ms=(time.perf_counter()-began)*1000,input_events_sent=0,dropped_captures=drops)
                value['capture_parts']=sample.get('capture_parts',{});period=.05 if os.environ.get('UEMW_UI_CAPTURE_LEGACY')=='1'else 1/(60 if sample['ui']['native_ui']else 30)
                history.append(value);history=history[-64:];removed,cache_bytes=trim(capture.folder,history,frames)
                if removed:retire_cached_images(capture,removed)
                value['drop_reasons']=dict(drop_reasons)
                value['cache_bytes']=cache_bytes;value['timing']=dict(capture_end_ns=capture_end,encoded_ns=encoded,body_ready_ns=body_ready,maintenance_end_ns=time.time_ns(),publish_begin_ns=time.time_ns());value=publish_ui(value,body)
            except (BlockingIOError,SceneReadChanged)as e:
                drops+=1;reason=str(e)[:160]
                if reason in drop_reasons or len(drop_reasons)<16:drop_reasons[reason]+=1
                wait_period(capture,began,period);continue
            except (OSError,ValueError,RuntimeError)as e:
                value=dict(protocol='uemw.ui',version=1,status='unavailable',pid=a.pid,session=a.session,sequence=frame_sequence,sample_unix_ns=stamp,error=str(e),input_events_sent=0)
                try:value=publish_ui(value)
                except BlockingIOError:
                    # Startup/loading can fail capture while the consumer owns
                    # the channel. A busy fault publication must not kill this
                    # lane. Keep old stamps unchanged and try a new capture.
                    drops+=1;wait_period(capture,began,period);continue
            menus=tuple(value.get('ui',{}).get('active_menus',[]))
            if time.monotonic()-last_log>=5 or value['status']!=last_status or menus!=last_menus:
                print(json.dumps({k:v for k,v in value.items()if k!='textures'},separators=(',',':')),flush=True);last_log=time.monotonic();last_status=value['status']
                last_menus=menus
            wait_period(capture,began,period)
    finally:
        if channel:channel.close()
        capture.close();r.close();K.CloseHandle(owner)


if __name__=='__main__':main()
