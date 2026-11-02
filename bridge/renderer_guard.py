"""Independent local renderer cutoff. Never sends input or terminates Morrowind.

The held process handle is checked against the launcher's exact executable and
successful package hash. A stopped client is never automatically restarted.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid

from live_probe import ROOT, GAME, EXPECTED_SHA256, K, Reader
from native_ui import loading_state
from local_files import read_json
from presentation import alive, atomic_json
from native_window_health import NativeWindowDeadline, probe_native_window

K.TerminateProcess.argtypes=[W.HANDLE,W.UINT];K.TerminateProcess.restype=W.BOOL


class HeartbeatDeadline:
    def __init__(self,now,renderer_pid,game_pid,startup=45,timeout=3):
        self.started=now;self.last=None;self.stamp=0
        self.renderer=renderer_pid;self.game=game_pid;self.startup=startup;self.timeout=timeout
    def poll(self,record,now,unix_ns):
        try:
            stamp=record['unix_ns'];age=(unix_ns-stamp)/1e9
            valid=(record['version']==1 and record['renderer_pid']==self.renderer and
                record['pid'] in (0,self.game) and type(stamp) in (int,float) and math.isfinite(stamp) and
                0<=age<=.5 and stamp>self.stamp)
        except (KeyError,TypeError,ValueError):valid=False
        if valid:self.last=now;self.stamp=stamp
        if self.last is None:
            return 'renderer_startup_timeout' if now-self.started>=self.startup else None
        return 'renderer_heartbeat_timeout' if now-self.last>=self.timeout else None


def source_stop_matches(record,session,game_pid):
    return (isinstance(record,dict) and record.get('protocol')=='uemw.source-stop' and record.get('version')==1
        and record.get('session')==session and record.get('game_pid')==game_pid)


def renderer_stop_matches(record,token,game_pid,renderer_pid):
    return (isinstance(record,dict) and record.get('protocol')=='uemw.renderer-stop' and record.get('version')==1
        and record.get('run_token')==token and record.get('game_pid')==game_pid and record.get('renderer_pid')==renderer_pid)


def open_exact(pid,path,sha256,terminate=False):
    handle=K.OpenProcess(0x1000|0x100000|(1 if terminate else 0),False,pid)
    if not handle:raise C.WinError(C.get_last_error())
    try:
        code=W.DWORD()
        if not K.GetExitCodeProcess(handle,C.byref(code)):raise C.WinError(C.get_last_error())
        if code.value!=259:raise RuntimeError(f'Process PID {pid} exited with code {code.value:#010x} before image validation')
        name=C.create_unicode_buffer(32768);size=W.DWORD(len(name))
        if not K.QueryFullProcessImageNameW(handle,0,name,C.byref(size)):
            error=C.WinError(C.get_last_error())
            if K.GetExitCodeProcess(handle,C.byref(code))and code.value!=259:
                raise RuntimeError(f'Process PID {pid} exited with code {code.value:#010x} during image validation')from error
            raise error
        if os.path.normcase(str(Path(name.value).resolve()))!=os.path.normcase(str(path.resolve())):
            raise RuntimeError('Cutoff refused a process with a different executable path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha256.lower():
            raise RuntimeError('Cutoff refused a process with a different executable hash')
        return handle
    except BaseException:K.CloseHandle(handle);raise


def load(path,max_bytes=8192):
    try:return read_json(path,max_bytes)
    except (OSError,ValueError):return {}


def run(args):
    executable=Path(args.renderer_exe).resolve()
    if executable.name.lower()!='uemorrowind.exe':raise RuntimeError('Cutoff requires the packaged project client')
    expected=ROOT/'local/client/Windows/UEMorrowind/Binaries/Win64/UEMorrowind.exe'
    if executable!=expected.resolve():raise RuntimeError('Cutoff refused a renderer outside this project')
    digest=read_json(ROOT/'local/client/build-info.json')['executable_sha256']
    game=open_exact(args.pid,GAME,EXPECTED_SHA256)
    renderer=None;lease=None;observer=None;session=None;armed=False;token=str(uuid.uuid4())
    folder=ROOT/'local/bridge';reason='guard_error'
    log=(ROOT/'logs/renderer-guard.jsonl').open('a',encoding='utf-8')
    def event(kind,**extra):
        record=dict(version=1,unix_ns=time.time_ns(),guard_pid=os.getpid(),game_pid=args.pid,
            renderer_pid=args.renderer,run_token=token,event=kind,**extra)
        atomic_json(folder/'renderer-guard.json',record)
        log.write(json.dumps(record,separators=(',',':'))+'\n');log.flush()
    def stop_source(reason):
        if session:
            atomic_json(folder/'source-stop.json',dict(protocol='uemw.source-stop',version=1,
                session=session,game_pid=args.pid,renderer_pid=args.renderer,reason=reason))
    try:
        renderer=open_exact(args.renderer,executable,digest,True)
        lease=K.CreateMutexW(None,False,'Local\\UEMW-renderer-cutoff-'+str(args.renderer))
        if not lease or C.get_last_error()==183:raise RuntimeError('Renderer cutoff already exists')
        armed=True
        observer=Reader(args.pid)
        event('started',startup_seconds=45,heartbeat_timeout_seconds=3,native_window_timeout_seconds=3,
            native_loading_timeout_seconds=20)
        deadline=HeartbeatDeadline(time.monotonic(),args.renderer,args.pid)
        native_deadline=NativeWindowDeadline()
        last_probe=0.;last_native_log=0.
        while alive(renderer):
            began=time.monotonic();stamp=time.time_ns()
            if not alive(game):reason='native_process_exited';break
            source=load(folder/'latest.json',1024*1024)
            if source.get('pid')==args.pid:
                try:session=str(uuid.UUID(source['session']))
                except (ValueError,KeyError,TypeError,AttributeError):pass
            request=load(folder/'renderer-stop.json')
            if renderer_stop_matches(request,token,args.pid,args.renderer):
                reason='explicit_view_stop';break
            reason=deadline.poll(load(folder/'render-state.json'),began,stamp)
            if reason:break
            if began-last_probe>=.5:
                native=probe_native_window(args.pid)
                try:native['native_loading']=loading_state(observer)[0]
                except (OSError,ValueError,RuntimeError):native['native_loading']=None
                last_probe=time.monotonic()
                reason=native_deadline.poll(native,last_probe)
                if last_probe-last_native_log>=1 or reason:
                    # Keep the launch-token record stable: this separate log
                    # is diagnostic, not a renewed renderer heartbeat.
                    log.write(json.dumps(dict(version=1,unix_ns=time.time_ns(),event='native_window_probe',
                        guard_pid=os.getpid(),game_pid=args.pid,renderer_pid=args.renderer,
                        run_token=token,**native),separators=(',',':'))+'\n');log.flush()
                    last_native_log=last_probe
                if reason:break
            time.sleep(max(0,.1-(time.monotonic()-began)))
        else:reason='renderer_process_exited'
        if alive(renderer):
            if not K.TerminateProcess(renderer,0):raise C.WinError(C.get_last_error())
        stop_source(reason)
        event('stopped',reason=reason,native_terminated=False,automatic_restart=False)
    except BaseException as error:
        if armed and renderer:
            if alive(renderer):K.TerminateProcess(renderer,0)
            try:
                stop_source('guard_error')
                event('stopped',reason='guard_error',error=str(error),native_terminated=False,automatic_restart=False)
            except (OSError,ValueError):pass
        raise
    finally:
        if observer:observer.close()
        if lease:K.CloseHandle(lease)
        if renderer:K.CloseHandle(renderer)
        K.CloseHandle(game);log.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--pid',type=int,required=True)
    parser.add_argument('--renderer',type=int,required=True)
    parser.add_argument('--renderer-exe',required=True)
    run(parser.parse_args())
