"""Separate, read-only installed scenery worker. No hot-pose-thread conversion.

uemw.distant v1 leases immutable UDF1 poses to an exact live source epoch.
The original's current static state is resampled after every conversion.
"""
import argparse,ctypes as C,hashlib,json,math,os,subprocess,sys,time
from ctypes import wintypes as W
from pathlib import Path
from live_probe import ROOT,Reader,SceneReadChanged,K
from local_files import read_json
from distant_assets import DistantAssets
from distant_native import NativeStatics
from loaded_cells import loaded_exteriors


def atomic(path,value):
    body=json.dumps(value,separators=(',',':'),allow_nan=False).encode()
    tmp=path.with_suffix('.'+str(os.getpid())+'.tmp');tmp.write_bytes(body)
    try:
        for _ in range(20):
            try:os.replace(tmp,path);return True
            except PermissionError:time.sleep(.002)
        return False # A reader lock drops publication, never the worker.
    finally:tmp.unlink(missing_ok=True)


def live_source(value,pid,session,now):
    stamp=value.get('sample_unix_ns',0)
    return (type(stamp)in(int,float)and math.isfinite(stamp)and type(value.get('cell_flags'))is int and value.get('protocol')=='uemw.live'and value.get('version')in(1,2,3,4,5) and value.get('status')=='live'
        and value.get('pid')==pid and value.get('session')==session and isinstance(value.get('scene_epoch'),str)
        and 0<=now-stamp<=500_000_000 and not value.get('cell_flags',1)&1 and isinstance(value.get('cell_grid'),list)
        and len(value['cell_grid'])==2 and all(type(x)is int and abs(x)<=65536 for x in value['cell_grid']))


def fingerprint(center,overrides,moved,suppressed):
    # Native allocation addresses are guards, not visual state or file identity.
    def visual(rows):return {k:{x:v for x,v in row.items()if x not in('reference','target')}for k,row in rows.items()}
    return hashlib.sha256(json.dumps([center,visual(overrides),visual(moved),sorted(suppressed)],sort_keys=True,separators=(',',':')).encode()).hexdigest()


def collect_cache(builder,history,budget=512*1024*1024):
    """Only this dedicated derived cache; never game, save or live assets dirs."""
    folder=builder.folder;keep=set();pending=[]
    def paths(value):
        if isinstance(value,dict):
            for v in value.values():paths(v)
        elif isinstance(value,list):
            for v in value:paths(v)
        elif isinstance(value,str)and value.startswith(('meshes/','textures/')):
            if '..'in Path(value).parts or ':'in value or '\\'in value:raise ValueError('Invalid distant cache path')
            keep.add(value)
    for row in history[-16:]:
        keep.update((row['catalog'],row['poses']));paths(json.loads((folder/row['catalog']).read_bytes()))
    total=sum((folder/p).stat().st_size for p in keep)
    if total>budget:raise ValueError('Protected distant resource generations exceed 512 MiB')
    deleted=False
    for p in folder.rglob('*'):
        if p.is_file()and p.relative_to(folder).as_posix()not in keep:
            pending.append(p)
    # Deleting an immutable old generation may race a decoder; that decode
    # fails closed. Sixteen completed generations remain available for readers.
    for p in pending:
        try:p.unlink();deleted=True
        except PermissionError:pass
    if deleted:
        builder.prototypes.clear();builder.terrain_cache.clear();builder.assets.textures.clear()
    return total


class Worker:
    def __init__(self,pid,session):
        self.pid=pid;self.session=session;self.r=Reader(pid);self.native=NativeStatics(self.r);self.builder=DistantAssets(ROOT)
        self.key=None;self.prepared=None;self.history=[];self.cache_bytes=0;self.epoch=None

    def source(self):
        v=read_json(ROOT/'local/bridge/latest.json')
        if not live_source(v,self.pid,self.session,time.time_ns()):raise SceneReadChanged('No fresh exterior source')
        return v

    def capture(self,source):
        a=self.r.render_metadata()
        if a.get('status')!='live'or a.get('native_loading')or a.get('cell_flags',1)&1 or a.get('menu'):raise SceneReadChanged('Original exterior is not active')
        center=tuple(a['cell_grid'])
        if center!=tuple(source['cell_grid'])or a['cell_ptr']!=source.get('cell_ptr'):raise SceneReadChanged('Native scenery/source cell changed')
        grids=[(x,y)for x in range(center[0]-3,center[0]+4)for y in range(center[1]-3,center[1]+4)]
        excluded=[c['grid']for c in loaded_exteriors(self.r,int(a['data'],16))]
        overrides=self.native.overrides(grids);moved,suppressed=self.native.moved();stamp=time.time_ns()
        b=self.r.camera_sample()
        if any(a[k]!=b[k]for k in('world','data','cell_ptr','player_ref','load_serial'))or b.get('native_loading'):raise SceneReadChanged('Native scenery epoch changed during capture')
        return center,excluded,overrides,moved,suppressed,stamp

    def tick(self):
        began=time.perf_counter();source=self.source()
        if source['scene_epoch']!=self.epoch:self.native=NativeStatics(self.r);self.epoch=source['scene_epoch'];self.key=None
        capture=self.capture(source);center,excluded,o,m,hidden,stamp=capture;key=fingerprint(center,o,m,hidden)
        if key!=self.key:
            prepared=self.builder.build(center,excluded,o,m,hidden)
            # Never grant a fresh lease to state sampled before a slow bake.
            after=self.source()
            if after['scene_epoch']!=source['scene_epoch']:raise SceneReadChanged('Source epoch changed during distant bake')
            current=self.capture(after)
            if fingerprint(current[0],current[2],current[3],current[4])!=key:raise SceneReadChanged('Original static state changed during distant bake')
            source=after;stamp=current[5];excluded=current[1]
            self.history.append(prepared);self.history=self.history[-16:]
            self.cache_bytes=collect_cache(self.builder,self.history)
            self.key=key;self.prepared=prepared
        after=self.source()
        if after['scene_epoch']!=source['scene_epoch']or after['cell_grid']!=source['cell_grid']:raise SceneReadChanged('Source changed before distant publication')
        return {**self.prepared,**dict(protocol='uemw.distant',version=1,status='live',pid=self.pid,session=self.session,scene_epoch=source['scene_epoch'],source_sample_unix_ns=source['sample_unix_ns'],native_sample_unix_ns=stamp,worker_pid=os.getpid(),excluded_grids=[list(g)for g in excluded],cache_bytes=self.cache_bytes,work_ms=(time.perf_counter()-began)*1000)}

    def close(self):self.builder.close();self.r.close()


def start(pid,session):
    log=(ROOT/'logs/distant-worker.log').open('w',encoding='utf-8')
    try:
        p=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--pid',str(pid),'--session',session,'--owner',str(os.getpid())],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW|subprocess.BELOW_NORMAL_PRIORITY_CLASS)
    finally:log.close()
    return p


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pid',type=int,required=True);parser.add_argument('--session',required=True);parser.add_argument('--owner',type=int,required=True);args=parser.parse_args()
    owner=K.OpenProcess(0x1000,False,args.owner)
    if not owner:raise RuntimeError('Scenery owner is unavailable')
    worker=Worker(args.pid,args.session);target=ROOT/'local/bridge/distant.json';last_log=0
    try:
        while True:
            exit_code=W.DWORD()
            if not K.GetExitCodeProcess(owner,C.byref(exit_code))or exit_code.value!=259:break
            began=time.perf_counter()
            try:worker.r.check_alive();value=worker.tick()
            except BlockingIOError:
                # Shared transport contention is not a native hide. Keep only
                # the existing bounded lease; never refresh its timestamps.
                time.sleep(max(.005,.2-(time.perf_counter()-began)));continue
            except (OSError,ValueError,RuntimeError,KeyError)as error:value=dict(protocol='uemw.distant',version=1,status='unavailable',pid=args.pid,session=args.session,error=str(error),native_sample_unix_ns=time.time_ns())
            atomic(target,value)
            if time.monotonic()-last_log>=5 or value['status']!='live':print(json.dumps(value,separators=(',',':')),flush=True);last_log=time.monotonic()
            # A dead/replaced producer never renews the lease. Its parent owns
            # this process and terminates it on normal/exceptional shutdown.
            time.sleep(max(.02,.2-(time.perf_counter()-began)))
    finally:worker.close();K.CloseHandle(owner)


if __name__=='__main__':main()
