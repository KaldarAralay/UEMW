"""Opt-in independent stop deadline for a disposable private smoke test.

Uses a held process handle, exact executable path and source hash. It cannot
terminate another game/editor or a later process that happens to reuse a PID.
No UI input, injection, debugger, screenshots, or normal-launch integration.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import time
from live_probe import ROOT,GAME,EXPECTED_SHA256,K

K.WaitForSingleObject.argtypes=[W.HANDLE,W.DWORD];K.WaitForSingleObject.restype=W.DWORD
K.TerminateProcess.argtypes=[W.HANDLE,W.UINT];K.TerminateProcess.restype=W.BOOL

def main():
    p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--seconds',type=int,required=True);p.add_argument('--renderer',action='store_true');a=p.parse_args()
    if not 10<=a.seconds<=180:p.error('Use a bounded 10..180 second private test deadline')
    handle=K.OpenProcess(0x1000|0x100000|1,False,a.pid)
    if not handle:raise C.WinError(C.get_last_error())
    target=ROOT/'local/client/Windows/UEMorrowind/Binaries/Win64/UEMorrowind.exe'if a.renderer else GAME
    expected=json.loads((ROOT/'local/client/build-info.json').read_text(encoding='utf-8-sig'))['executable_sha256'].lower()if a.renderer else EXPECTED_SHA256
    report=dict(pid=a.pid,kind='renderer'if a.renderer else 'native',seconds=a.seconds,started_unix_ns=time.time_ns())
    try:
        path=C.create_unicode_buffer(32768);count=W.DWORD(len(path))
        if not K.QueryFullProcessImageNameW(handle,0,path,C.byref(count)) or os.path.normcase(str(Path(path.value).resolve()))!=os.path.normcase(str(target.resolve())):
            raise RuntimeError('Deadline refused a process outside the private test')
        if hashlib.sha256(target.read_bytes()).hexdigest()!=expected:raise RuntimeError('Deadline refused an unsupported executable')
        print(json.dumps({**report,'guarded':True}),flush=True)
        result=K.WaitForSingleObject(handle,a.seconds*1000)
        if result==258:
            if not K.TerminateProcess(handle,0):raise C.WinError(C.get_last_error())
            report['result']='deadline_stopped_private_test'
        elif result==0:report['result']='process_exited_before_deadline'
        else:raise C.WinError(C.get_last_error())
        report['ended_unix_ns']=time.time_ns()
        (ROOT/('logs/renderer-deadline.json'if a.renderer else 'logs/native-only-deadline.json')).write_text(json.dumps(report,indent=2))
        print(json.dumps(report),flush=True)
    finally:K.CloseHandle(handle)

if __name__=='__main__':main()
