"""Source-owned UI-only render-state lane; never captures a game window."""
import argparse,ctypes as C,hashlib,json,os,subprocess,sys,time
from ctypes import wintypes as W
from pathlib import Path
from live_probe import ROOT,Reader,K,SceneReadChanged
from local_files import read_json
from ui_scene import UICapture,encode
from asset_files import publish
from distant_stream import atomic


def start(pid,session):
    log=(ROOT/'logs/ui-worker.log').open('w',encoding='utf-8')
    try:return subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--pid',str(pid),'--session',session,'--owner',str(os.getpid())],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    finally:log.close()


def trim(folder,history,frames,limit=256*1024*1024):
    while True:
        keep={t['file']:t['bytes']for row in history for t in row['textures']}
        if sum(keep.values())<=limit or len(history)<=2:break
        history.pop(0)
    if sum(keep.values())>limit:raise ValueError('Native UI cache exceeds 256 MiB')
    keep_frames={row['frame_ref']['file']for row in history}
    removed=False
    for path in folder.glob('*.utx'):
        if path.name not in keep:
            try:path.unlink();removed=True
            except PermissionError:pass
    for path in frames.glob('*.uui'):
        if 'ui-frames/'+path.name not in keep_frames:
            try:path.unlink()
            except PermissionError:pass
    return removed,sum(keep.values())


def main():
    p=argparse.ArgumentParser();p.add_argument('--pid',required=True,type=int);p.add_argument('--session',required=True);p.add_argument('--owner',required=True,type=int);a=p.parse_args()
    owner=K.OpenProcess(0x1000,False,a.owner)
    if not owner:raise RuntimeError('Native UI source owner is absent')
    r=Reader(a.pid);capture=UICapture(r);folder=ROOT/'local/bridge';frames=folder/'ui-frames';frames.mkdir(parents=True,exist_ok=True)
    sequence=0;history=[];last_log=0;last_status=None;drops=0
    try:
        while True:
            code=W.DWORD()
            if not K.GetExitCodeProcess(owner,C.byref(code))or code.value!=259:break
            began=time.perf_counter();stamp=time.time_ns()
            try:
                source=read_json(folder/'latest.json')
                if source.get('pid')!=a.pid or source.get('session')!=a.session:raise SceneReadChanged('Native UI source session changed')
                sample=capture.sample();body=encode(sample,a.session,sequence,stamp,a.pid);name='ui-frames/'+a.session.replace('-','')+'-'+str(sequence)+'.uui';publish(folder/name,body)
                value=dict(protocol='uemw.ui',version=1,status='live',pid=a.pid,session=a.session,sequence=sequence,sample_unix_ns=stamp,frame_ref=dict(file=name,md5=hashlib.md5(body).hexdigest(),bytes=len(body)),textures=sample['textures'],native_regions=sample['native_regions'],ui=sample['ui'],ui_root=sample['root'],width=sample['width'],height=sample['height'],draws=len(sample['draws']),vertices=sample['vertices'],indices=sample['indices'],texture_bytes=sample['texture_bytes'],capture_ms=(time.perf_counter()-began)*1000,input_events_sent=0,dropped_captures=drops)
                history.append(value);history=history[-16:];removed,cache_bytes=trim(capture.folder,history,frames)
                if removed:capture.files.clear()
                value['cache_bytes']=cache_bytes;atomic(folder/'ui.json',value);sequence+=1
            except (BlockingIOError,SceneReadChanged):
                drops+=1;time.sleep(max(.002,.05-(time.perf_counter()-began)));continue
            except (OSError,ValueError,RuntimeError)as e:
                value=dict(protocol='uemw.ui',version=1,status='unavailable',pid=a.pid,session=a.session,sequence=sequence,sample_unix_ns=stamp,error=str(e),input_events_sent=0);atomic(folder/'ui.json',value)
            if time.monotonic()-last_log>=5 or value['status']!=last_status:
                print(json.dumps({k:v for k,v in value.items()if k!='textures'},separators=(',',':')),flush=True);last_log=time.monotonic();last_status=value['status']
            time.sleep(max(.002,.05-(time.perf_counter()-began)))
    finally:capture.close();r.close();K.CloseHandle(owner)


if __name__=='__main__':main()
