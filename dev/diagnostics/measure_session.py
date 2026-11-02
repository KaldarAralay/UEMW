"""Short, recording-free measurements of real producer packets and UE health."""
import argparse
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import re
import time
import numpy as np
from live_probe import ROOT
from frame_transport import resolve
from local_files import read_json
from compact_geometry import expand

K=C.WinDLL('kernel32',use_last_error=True)
K.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE];K.CreateFileW.restype=W.HANDLE
K.GetFileSizeEx.argtypes=[W.HANDLE,C.POINTER(C.c_longlong)]
K.ReadFile.argtypes=[W.HANDLE,C.c_void_p,W.DWORD,C.POINTER(W.DWORD),C.c_void_p]
K.CloseHandle.argtypes=[W.HANDLE]

def manifest():
    """Read only the bounded commit record; no large frame resolution."""
    return read_json(ROOT/'local/bridge/latest.json')

def packet():
    return expand(resolve(manifest(),ROOT/'local/bridge'))

def stats(values):
    return {'median':round(float(np.median(values)),3),'p95':round(float(np.percentile(values,95)),3),'max':round(float(max(values)),3)} if values else None

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=12);args=parser.parse_args()
    if not 1<=args.seconds<=60:parser.error('Use a short 1..60 second check')
    log=ROOT/'logs/ue-runtime.log';offset=log.stat().st_size
    start=time.perf_counter();start_ns=time.time_ns();seen=set();samples=[]
    while time.perf_counter()-start<args.seconds:
        try:
            sample=packet();key=(sample['session'],sample['sequence'])
            age=(time.time_ns()-sample['sample_unix_ns'])/1e9
            if key not in seen and sample.get('status')=='live' and sample.get('geometry_stats',{}).get('instances',0)>1000 and 0<=age<=.5:
                seen.add(key)
                samples.append({k:sample[k]for k in ('frame_ms','menu','read_ms','pose_read_ms','sample_spanned_frames','pose_attempts')})
        except (OSError,ValueError,KeyError):pass
        time.sleep(.02)
    with log.open('rb') as stream:stream.seek(offset);tail=stream.read().decode('utf-8',errors='replace')
    fps=[float(value) for value in re.findall(r'health status=LIVE[^\n]* fps=([\d.]+)',tail)]
    ages=[float(value) for value in re.findall(r'UEMW live[^\n]* age=([\d.]+)ms',tail)]
    result={'scope':'Short stationary interior check; no video/PNG recording. Includes diagnostic sampling overhead.',
            'start_unix_ns':start_ns,'end_unix_ns':time.time_ns(),
            'seconds':args.seconds,'unique_live_packets':len(samples),'observed_packet_hz':round(len(samples)/args.seconds,2),
            'source_time_advanced_ms':((samples[-1]['frame_ms']-samples[0]['frame_ms'])&0xffffffff) if samples else None,
            'samples_with_original_menu_open':sum(s['menu'] for s in samples),
            'read_ms':stats([s['read_ms'] for s in samples]),'pose_read_ms':stats([s['pose_read_ms'] for s in samples]),
            'pose_spanned_frame_percent':round(100*sum(s['sample_spanned_frames'] for s in samples)/len(samples),2) if samples else None,
            'two_pose_attempts_percent':round(100*sum(s['pose_attempts']==2 for s in samples)/len(samples),2) if samples else None,
            'ue_health_fps':stats(fps),'ue_consumed_packet_age_ms':stats(ages),'passed':len(samples)>=args.seconds*10}
    (ROOT/'logs/hardening-measurement.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
