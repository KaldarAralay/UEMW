"""Same private native street/dock/movement route for renderer comparisons.

No save writes, collision toggles, gameplay simulation or video. Run with the
private game already focused and the client started with diagnostic flags.
"""
import argparse
import hashlib
import json
import math
import subprocess
import sys
import time
from live_probe import ROOT,Reader
from check_normal_play import console,live,wait
from check_native_terrain import aim
from check_native_visuals import capture
from check_native_motion import witness
from input_backend import pulse
from native_window_health import probe_native_window


def run(r,label):
    if not label.replace('-','').isalnum() or len(label)>40:raise ValueError('Invalid measurement label')
    protected={p:hashlib.sha256(p.read_bytes()).hexdigest()for p in (ROOT/'local/Morrowind/Saves').glob('*.ess')}
    report=dict(label=label,passed=False,recording=False,save_writes=False,console_commands=[],cases=[],start_unix_ns=time.time_ns())
    try:
        if r.snapshot()['cell']!='Seyda Neen':raise RuntimeError('Expected the loaded disposable Seyda Neen exterior')
        if r.player_render_state(r.u32(0x7c67dc)).get('vanity'):pulse(r,'key',0x11,.08)
        console(r,'set gamehour to 14',report)
        for name,position,target,moving in (
            ('street',(-12032,-73436,58),(-11600,-72200,140),False),
            ('dock',(-9472,-72448,36),(-8448,-72960,0),False),
            ('moving',(-12032,-73436,58),(-11600,-72200,140),True)):
            console(r,'player->Position '+' '.join(map(str,position))+' 0',report);time.sleep(.5);aim(r,target)
            wait(lambda:(w if not w.get('partial_geometry')else None)if(w:=live(r))else None,30);time.sleep(3)
            initial=witness([]);camera=r.camera_sample()['camera'];positions=[camera['position']]
            path=ROOT/f'logs/gpu-{label}-{name}-benchmark.json';began=time.time_ns()
            with(ROOT/f'logs/gpu-{label}-{name}-benchmark.log').open('w')as log:
                proc=subprocess.Popen([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','8'if moving else'6','--warmup','0','--output',str(path)]+(['--moving']if moving else[]),stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    if moving:
                        # Alternate short native walking pulses with calibrated
                        # camera turns. The original engine resolves collision.
                        for i,key in enumerate((0x11,0x1f,0x20,0x1e,0x11,0x1f)):
                            pulse(r,'key',key,.2);aim(r,[-11600+(-300 if i%2 else 300),-72200,140]);positions.append(r.camera_sample()['camera']['position'])
                    proc.wait(20)
                    if proc.returncode:raise RuntimeError('Benchmark observer failed')
                finally:
                    if proc.poll()is None:proc.terminate();proc.wait(3)
            b=json.loads(path.read_text());last=witness([])
            row=dict(case=name,start_unix_ns=began,end_unix_ns=time.time_ns(),benchmark=str(path.relative_to(ROOT)),
                     before=initial,after=last,camera=camera,positions=positions,
                     max_native_displacement=max(math.dist(positions[0],p)for p in positions),
                     image=capture('gpu-'+label+'-'+name),valid=b['valid_native_run'],gpu_ms=b['ue_gpu_frame_ms'],
                     ue_updates_hz=b['ue_game_thread_hz'],presentation=b['ue_presentation'])
            report['cases'].append(row)
            if not row['valid'] or moving and row['max_native_displacement']<10:raise RuntimeError('Invalid native route observation')
        report['health']=probe_native_window(r.pid);report['passed']=report['health']['responding']is True
    finally:
        report['preserved_saves']=all(p.exists()and hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in protected.items())
        report['passed']&=report['preserved_saves'];report['end_unix_ns']=time.time_ns()
        (ROOT/f'logs/gpu-{label}-route.json').write_text(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('label');a=p.parse_args();r=Reader(int((ROOT/'local/bridge/game.pid').read_text()))
    try:
        report=run(r,a.label);print(json.dumps(dict(passed=report['passed'],cases=[{k:row[k]for k in('case','gpu_ms','ue_updates_hz','presentation','max_native_displacement')}for row in report['cases']])))
    finally:r.close()
