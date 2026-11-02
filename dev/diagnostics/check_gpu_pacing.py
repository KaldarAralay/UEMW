"""Bounded same-process rendering/presentation control experiment; no saves."""
import json
import subprocess
import sys
import time
from live_probe import ROOT,Reader
from check_normal_play import console,live,wait
from check_native_motion import witness
from check_native_terrain import aim
from input_backend import pulse

def run(r):
    report=dict(passed=False,recording=False,save_writes=False,console_commands=[],cases=[])
    try:
        if r.player_render_state(r.u32(0x7c67dc)).get('vanity'):pulse(r,'key',0x11,.08)
        console(r,'set gamehour to 14',report);console(r,'player->Position -12032 -73436 58 0',report)
        # Prepare the same native resident coverage before changing any
        # renderer controls. This is one spot, not a world/cell survey.
        for target in ((-10032,-73436,175),(-12032,-71436,175),(-14032,-73436,175),(-12032,-75436,175)):
            aim(r,target);time.sleep(2)
        aim(r,[-11600,-72200,140]);wait(lambda:live(r),20);time.sleep(3)
        for label,targeted,sync in (('full-scan',False,False),('targeted',True,False),('synced',True,True),('targeted-repeat',True,False)):
            before=witness([],targeted_render_updates=targeted,presentation_sync=sync);time.sleep(1)
            if before.get('targeted_render_updates')is not targeted or before.get('present_vsync')!=int(sync):raise RuntimeError('Diagnostic control was not applied')
            path=ROOT/f'logs/gpu-pacing-{label}-benchmark.json'
            with(ROOT/f'logs/gpu-pacing-{label}-benchmark.log').open('w')as log:
                subprocess.run([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--seconds','6','--warmup','0','--output',str(path)],check=True,timeout=18,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            b=json.loads(path.read_text());after=witness([])
            report['cases'].append(dict(case=label,before=before,after=after,benchmark=str(path.relative_to(ROOT)),
                gpu_ms=b['ue_gpu_frame_ms'],tick_ms=b['ue_tick_ms'],ue_hz=b['ue_game_thread_hz'],presentation=b['ue_presentation'],
                source_hz=b['source_unique_hz'],pose_age_ms=b['ue_applied_age_ms'],catalog_changes=b['source_catalog_changes'],
                definitions=b['last_source']['geometry_stats']['instances'],valid=b['valid_native_run']))
        report['passed']=all(row['valid']and row['catalog_changes']==0 for row in report['cases'])
    finally:
        witness([],targeted_render_updates=True,presentation_sync=False)
        (ROOT/'logs/gpu-pacing-controls.json').write_text(json.dumps(report,indent=2))
    return report

if __name__=='__main__':
    r=Reader(int((ROOT/'local/bridge/game.pid').read_text()))
    try:
        d=run(r);print(json.dumps(dict(passed=d['passed'],cases=[{k:row[k]for k in('case','gpu_ms','tick_ms','ue_hz','presentation','catalog_changes','definitions')}for row in d['cases']])))
    finally:r.close()
