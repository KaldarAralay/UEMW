"""Opt-in original UI acceptance. Uses only guarded native mouse/key input.

Requires a focused disposable private game and managed unified UE view. Tests
HUD/inventory/map/filter/journal/pause/load-list/cancel without writing a save.
No gameplay rules, input forwarding or game-window image capture are involved.
"""
import argparse,hashlib,json,struct,time
from pathlib import Path
from live_probe import ROOT,Reader
from local_files import read_json
from native_ui import inspect_ui
from native_ui_test import act,choose
from input_backend import pulse,require_foreground
from check_normal_play import wait
from ui_scene import HEADER


def observe(r,label,capture=False,seconds=.7):
    def current():
        p=read_json(ROOT/'local/bridge/presentation.json');v=p.get('renderer_state',{});u=inspect_ui(r)
        if not p.get('visible')or not p.get('ui_mirrored')or v.get('ui_menus')!=u['active_menus']or p.get('foreground')!=u['window']:return None
        if p.get('game_pid')!=r.pid or p.get('input_events_sent')!=0:raise RuntimeError('UI ownership/input mismatch')
        return p
    wait(current,10);out=[];began=time.monotonic()
    while time.monotonic()-began<seconds:
        p=current()
        if p is None:raise RuntimeError('Unified original UI stopped presenting during '+label)
        v=p['renderer_state'];stamp=time.time_ns();out.append(dict(time_unix_ns=stamp,sequence=v['ui_sequence'],age_ms=(stamp-v['ui_sample_unix_ns'])/1e6,regions=p['native_ui_regions'],reason=p['reason'],source_live=p['source_live'],renderer_live=p['renderer_live']))
        time.sleep(.04)
    v=p['renderer_state'];session=v['session'];seq=int(v['ui_sequence']);body=(ROOT/'local/bridge/ui-frames'/f'{session.replace("-","")}-{seq}.uui').read_bytes();h=HEADER.unpack_from(body)
    if h[0]!=b'UUI1'or h[4]!=seq or h[6]!=r.pid:raise RuntimeError('Accepted UI carrier identity mismatch')
    result=dict(label=label,menus=inspect_ui(r)['active_menus'],source_session=session,accepted_sequence=seq,accepted_body_md5=hashlib.md5(body).hexdigest(),draws=h[-1],observations=out,input_events_sent_by_runtime=0)
    if capture:
        from check_native_visuals import capture as image
        result['ue_image']=image('ui09-'+label)
    return result


def run(r,capture=False):
    require_foreground(r);report=dict(passed=False,recording=False,save_writes=False,checks=[])
    path=ROOT/'logs/ui09-core-acceptance.json'
    try:
        ui=inspect_ui(r)
        if ui['native_ui']and 'MenuInventory'not in ui['active_menus']:raise RuntimeError('Begin in gameplay or native inventory')
        if not ui['native_ui']:pulse(r,'right',0,.15)
        wait(lambda:'MenuInventory'in inspect_ui(r)['active_menus'],4)
        report['checks'].append(observe(r,'inventory',capture))
        act(r,menu='MenuMap',text='World',click=True);wait(lambda:choose(r,menu='MenuMap',text='Local'),4)
        report['checks'].append(observe(r,'world-map',capture))
        act(r,menu='MenuMap',text='Local',click=True);wait(lambda:choose(r,menu='MenuMap',text='World'),4)
        act(r,menu='MenuInventory',text='Weapon',click=True)
        report['checks'].append(observe(r,'inventory-filter',capture))
        pulse(r,'right',0,.15);wait(lambda:not inspect_ui(r)['native_ui'],4)
        report['checks'].append(observe(r,'hud',capture))
        pulse(r,'key',0x24,.15);wait(lambda:'MenuJournal'in inspect_ui(r)['active_menus'],4)
        report['checks'].append(observe(r,'journal',capture))
        pulse(r,'key',0x24,.15);wait(lambda:not inspect_ui(r)['native_ui'],4)
        pulse(r,'key',1,.15);wait(lambda:'MenuOptions'in inspect_ui(r)['active_menus'],4)
        report['checks'].append(observe(r,'pause',capture))
        act(r,menu='MenuOptions',name='MenuOptions_Load_container',click=True);wait(lambda:'MenuLoad'in inspect_ui(r)['active_menus'],4)
        report['checks'].append(observe(r,'load-list',capture))
        act(r,menu='MenuLoad',text='Cancel',click=True);wait(lambda:'MenuOptions'in inspect_ui(r)['active_menus'],4)
        pulse(r,'key',1,.15);wait(lambda:not inspect_ui(r)['native_ui'],4)
        report['checks'].append(observe(r,'hud-restored',capture));report['passed']=True;return report
    finally:path.write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--capture',action='store_true');a=p.parse_args();r=Reader(a.pid)
    try:report=run(r,a.capture);print(json.dumps(dict(passed=report['passed'],checks=[c['label']for c in report['checks']])))
    finally:r.close()
