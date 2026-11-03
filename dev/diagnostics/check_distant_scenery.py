"""Opt-in private checkpoint acceptance for the installed distant layer.

Ordinary guarded original console/input only. Mutations are unsaved; reload
the disposable checkpoint afterwards. Never run against a personal save.
"""
import argparse,json,math,struct,time
import numpy as np
from pathlib import Path
from live_probe import ROOT,Reader
from local_files import read_json
from input_backend import pulse,type_ascii,require_foreground
from native_ui import inspect_ui,loading_state
from native_ui_test import tree
from distant_native import NativeStatics,rotation
from tes3_world import WorldIndex
from check_native_motion import witness
from acceptance_step import look


def wait(fn,seconds=15):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:v=fn()
        except(BlockingIOError,OSError):v=None
        if v:return v
        time.sleep(.08)
    raise RuntimeError('Timed out: '+fn.__name__)


def command(r,text,report):
    if inspect_ui(r)['native_ui']:raise RuntimeError('Another original menu is open')
    pulse(r,'key',0x29,1.2);wait(lambda:'MenuConsole'in inspect_ui(r)['active_menus'],4)
    type_ascii(r,text);pulse(r,'key',0x1c,.15);time.sleep(.3)
    output=[v['text']for v in tree(r,'MenuConsole')if v['text']][-12:]
    report['commands'].append(dict(text=text,output=output))
    # Original placement can synchronously load cells and ignore input while
    # doing so. Observe loading completion before sending the close once.
    wait(lambda:not loading_state(r)[0],15);time.sleep(1.5)
    for _ in range(3):
        if 'MenuConsole'not in inspect_ui(r)['active_menus']:break
        pulse(r,'key',0x29,1.2);time.sleep(.3)
    wait(lambda:not inspect_ui(r)['native_ui'],5)
    report['commands'][-1]['closed_unix_ns']=time.time_ns()


def ready(ids=()):
    w=witness(list(ids))
    return w if w['live']and w['distant_status']=='installed terrain/statics / native fog'and w['distant_visible']>0 else None


def row_matches(identifier,expected,after=0):
    w=ready([identifier])
    if not w or w['distant_native_sample_unix_ns']<after:return None
    row=next((r for r in w['distant_instances']if r['id']==identifier),None)
    if not row or row['submitted_visible']!=expected:return None
    return dict(witness=w,row=row)


def run(r):
    require_foreground(r);pulse(r,'key',0x11,.12)
    report=dict(passed=False,recording=False,save_writes=False,commands=[],checks=[],scope='Unsaved private native STAT enable/disable/scale; actual native cell crossing; CPU submitted geometry with independent native-static timestamps.')
    try:
        wait(ready,25)
        n=NativeStatics(r);original=n.overrides([(-2,-9)])[0x010610f7]
        if original['base']!='chargen_plank'or not original['disabled']:raise RuntimeError('Expected disposable checkpoint plank state is absent')
        report['before']=original
        command(r,'"chargen_plank"->Enable',report)
        wait(lambda:not n.overrides([(-2,-9)])[0x010610f7]['disabled'],5)
        # Native console placement is a diagnostic cell transition. Ordinary
        # walking is checked separately; no UE controller moves the player.
        world=WorldIndex(ROOT/'local/Morrowind/Data Files');land=world.terrain((0,-9))
        y=min(range(2,63),key=lambda i:float(np.ptp(land['heights'][i-1:i+2,:3])))
        height=max(float(land['heights'][y,0]),0)+100
        command(r,f'player->Position 64 {-73728+y*128} {height} 90',report)
        wait(lambda:tuple(r.render_metadata().get('cell_grid')or())==(0,-9),8)
        report['crossed_to']=list(r.render_metadata()['cell_grid'])
        identifier='distant:stat:010610f7:0'
        shown=wait(lambda:row_matches(identifier,True),35);report['checks'].append(dict(kind='native-enabled after resident-to-distant handoff',**shown))
        command(r,'"chargen_plank"->SetScale 0.75',report)
        def scaled():
            v=row_matches(identifier,True)
            return v if v and abs(v['row']['transform'][12]-.75)<1e-6 else None
        report['checks'].append(dict(kind='native original scale',**wait(scaled,15)))
        command(r,'"chargen_plank"->Disable',report)
        report['checks'].append(dict(kind='native original disable',**wait(lambda:row_matches(identifier,False,report['commands'][-1]['closed_unix_ns']),15)))
        command(r,'"chargen_plank"->Enable',report)
        report['checks'].append(dict(kind='native original re-enable',**wait(lambda:row_matches(identifier,True,report['commands'][-1]['closed_unix_ns']),15)))
        lease=read_json(ROOT/'local/bridge/distant.json',32768);catalog=json.loads((ROOT/'local/distant-assets'/lease['catalog']).read_bytes());states=(ROOT/'local/distant-assets'/lease['poses']).read_bytes();ids=[identifier]+[b['id']for b in catalog['bindings']if b['id'].startswith('distant:land:')and tuple(map(int,b['cell_key'].split(':')[1].split(',')))not in set(map(tuple,lease['excluded_grids']))][:3]
        w=ready(ids)
        if not w:raise RuntimeError('No current distant submission')
        for row in w['distant_instances']:
            index=next(i for i,b in enumerate(catalog['bindings'])if b['id']==row['id']);visible,*transform=struct.unpack_from('<I13f',states,8+index*56)
            if row['submitted_visible']and row.get('transform')!=transform:raise RuntimeError('Distant submitted pose differs from its immutable converted data')
        report['exact_export_witness']=w;report['lease']=lease;report['passed']=True;return report
    finally:(ROOT/'logs/distant08-live-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);a=p.parse_args();r=Reader(a.pid)
    try:
        v=run(r);print(json.dumps(dict(passed=v['passed'],checks=len(v['checks']),crossed_to=v['crossed_to'],save_writes=False)))
    finally:r.close()
