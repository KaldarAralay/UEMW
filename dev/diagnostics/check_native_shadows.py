"""Opt-in shadow-map A/B on live installed geometry; no saves or video.

Launch with -DiagnosticScreenshots, focus private Morrowind and choose a static
view. Only the renderer's shadow-map switch changes. Use --roi to exclude HUD,
actors and animated flames from a region containing actual scene surfaces.
"""
import argparse
import json
import re
import time
import numpy as np
from PIL import Image
from live_probe import Reader,ROOT
from input_backend import require_foreground,pulse
from check_normal_play import wait,live
from check_native_motion import witness,source_frame
from check_native_visuals import capture
from local_files import read_json


def pair(reader,label,roi):
    require_foreground(reader)
    report=dict(passed=False,recording=False,save_writes=False,roi=roi,shots=[])
    try:
        if reader.player_render_state(reader.u32(0x7c67dc)).get('vanity'):pulse(reader,'key',0x11,.05)
        for enabled in(False,True):
            witness([],shadow_maps=enabled)
            def ready():
                w=live(reader)
                if not w or w['partial_geometry']or w['shadow_maps']!=enabled:return None
                if (w['ue_shadowed_local_lights']>0)!=enabled and not w['exterior_fidelity_active']:return None
                try:p,d=source_frame(w)
                except BlockingIOError:return None
                return w,p,d
            wait(ready,15);time.sleep(.25);w,p,d=wait(ready,8)
            report['shots'].append(dict(image=capture('shadow-'+label+('-on'if enabled else'-off')),witness=w,
                source_md5=d,environment=p['environment'],camera=reader.camera_sample()['camera'],
                geometry_stats=read_json(ROOT/'local/bridge/latest.json').get('geometry_stats')))
        before,after=report['shots']
        for name in('position','forward'):
            if not np.allclose(before['camera'][name],after['camera'][name],atol=.002,rtol=0):raise RuntimeError('Native camera moved during paired capture')
        a,b=[np.asarray(Image.open(ROOT/s['image']).convert('RGB'),dtype=np.float32)for s in report['shots']]
        if a.shape!=b.shape:raise RuntimeError('Backbuffer dimensions changed')
        x0,y0,x1,y1=roi
        if not 0<=x0<x1<=a.shape[1]or not 0<=y0<y1<=a.shape[0]:raise ValueError('ROI outside backbuffer')
        delta=(a[y0:y1,x0:x1]-b[y0:y1,x0:x1])@np.array([.2126,.7152,.0722])
        report['pixel_measurement']=dict(scope='Display-RGB luma delta in the specified scene ROI; animated geometry must be excluded by the operator',
            mean_luma_darkening=float(delta.mean()),darkened_over_2_levels_fraction=float((delta>2).mean()),brightened_over_2_levels_fraction=float((delta< -2).mean()))
        if (delta>2).mean()<.005:raise RuntimeError('No significant shadow darkening in selected scene ROI')
        report['passed']=True
    finally:
        try:witness([],shadow_maps=True)
        except RuntimeError as error:
            report['passed']=False;report['restore_error']=str(error)
            raise
        finally:(ROOT/'logs'/('shadow-'+label+'-pair.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pid',type=int,required=True);p.add_argument('--case',required=True);p.add_argument('--roi',type=int,nargs=4,required=True);a=p.parse_args()
    if not re.fullmatch('[a-z0-9-]{1,40}',a.case):p.error('Use a short lowercase case name')
    r=Reader(a.pid)
    try:d=pair(r,a.case,a.roi)
    finally:r.close()
    print(json.dumps(dict(passed=d['passed'],pixels=d['pixel_measurement'],images=[s['image']for s in d['shots']])))
