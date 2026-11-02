"""Short live lighting comparisons in the current private room; no saves/video."""
import argparse
import json
import math
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'bridge'))
from live_probe import Reader,ROOT
from input_backend import pulse,require_foreground
from check_native_terrain import aim
from check_native_motion import witness,source_frame
from check_native_visuals import capture


def run(reader):
    require_foreground(reader)
    if reader.player_render_state(reader.u32(0x7c67dc)).get('vanity'):pulse(reader,'key',0x11,.05)
    camera=reader.camera_sample()['camera'];position=camera['position'];forward=camera['forward']
    target=[position[i]+forward[i]*1000 for i in range(3)]
    yaw=math.atan2(forward[0],forward[1]);pitch=math.asin(max(-1,min(1,forward[2])))
    report=dict(passed=False,recording=False,save_writes=False,initial_camera=camera,shots=[],samples=[])
    def sample(case):
        for attempt in range(15):
            try:
                w=witness([]);packet,digest=source_frame(w)
                if not w['live']or w['pid']!=reader.pid:raise RuntimeError('Not live for this private native process')
                environment=packet['environment'];ids=[v['id']for v in environment['lights']]
                if ids!=w['native_light_ids']:raise RuntimeError('UE light ownership differs from exact source frame')
                if w['lighting_fidelity']and not w['native_attenuation_functions']:raise RuntimeError('Native falloff functions are missing')
                if w['stable_lighting']and w['sun_contact_shadow_length']!=0:raise RuntimeError('Screen-space sun contacts were not disabled')
                row=dict(case=case,sequence=w['sequence'],source_md5=digest,witness=w,environment=environment)
                report['samples'].append(row);return row
            except(BlockingIOError,OSError,ValueError):time.sleep(.025)
        raise RuntimeError('Could not acquire an exact lighting/source pair')
    def profile(fidelity,stable):
        witness([],lighting_fidelity=fidelity,stable_lighting=stable);time.sleep(.45)
        row=sample('profile')
        if(row['witness']['lighting_fidelity'],row['witness']['stable_lighting'])!=(fidelity,stable):raise RuntimeError('Lighting comparison was not applied')
    def shot(case):
        report['shots'].append(dict(case=case,image=capture('atmosphere-'+case),sample=sample(case),camera=reader.camera_sample()['camera']))
    try:
        for case,fidelity,stable in(('old-style',False,False),('colour-falloff',True,False),('final',True,True)):
            aim(reader,target);profile(fidelity,stable);shot(case)
        for stable in(False,True):
            profile(True,stable)
            for delta in(-.35,.35,0):
                direction=[math.sin(yaw+delta)*math.cos(pitch),math.cos(yaw+delta)*math.cos(pitch),math.sin(pitch)]
                aim(reader,[position[i]+direction[i]*1000 for i in range(3)])
                case=('stable'if stable else'contacts-ao')+('-left'if delta<0 else'-right'if delta>0 else'-centre')
                shot(case)
                for _ in range(3):sample(case)
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        profile(True,True);aim(reader,target);report['final_camera']=reader.camera_sample()['camera']
        (ROOT/'logs/atmosphere-live-check.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pid',type=int,required=True);args=parser.parse_args();reader=Reader(args.pid)
    try:
        report=run(reader);print(json.dumps(dict(passed=report['passed'],shots=len(report['shots']),exact_source_checks=len(report['samples'])),indent=2))
    finally:reader.close()
