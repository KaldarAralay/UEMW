"""Opt-in exact native dialogue-hover timing; no clicks, saves or video.

Requires native dialogue already open and the unified renderer launched with
presentation statistics. Times actual original glyph-colour changes, excluding
the cursor, against matching source bodies actually submitted by UE Canvas.
"""
import argparse,hashlib,json,struct,threading,time
from pathlib import Path
import numpy as np
from live_probe import ROOT,Reader
from local_files import read_json
from native_ui_test import choose
from native_ui import inspect_ui
from input_backend import point,require_foreground
from scene_reader import SceneReader
from ui_timing import rows,summarize,stats,draw_colours,runtime_log


def run(r,topic,events,label):
    require_foreground(r)
    if inspect_ui(r)['active_menus']!=['MenuDialog']:raise RuntimeError('Open genuine native NPC dialogue first')
    element=choose(r,menu='MenuDialog',text=topic);address=int(element['id'],16);node=r.u32(address+0x88)
    shapes=[s for s in SceneReader(r).collect(roots=[node])['shapes']if s['visible']]
    if not shapes or any(s['type']!='NiTriShape'or s['color_mode']==0 or s['material']!='0x0'for s in shapes):raise RuntimeError('Expected native vertex-coloured dialogue glyphs')
    identities={int(s['id'],16)for s in shapes};archive={};stop=threading.Event();ready=threading.Event();errors=[];observations=[]
    def native():
        if choose(r,menu='MenuDialog',text=topic)!=element:raise RuntimeError('Native dialogue target changed')
        result={}
        for s in shapes:
            p=int(s['id'],16);model=int(s['model'],16)
            if r.u32(p+0x98)!=model:raise RuntimeError('Native glyph storage changed')
            h=r.read(model,0x48);n=struct.unpack_from('<H',h,8)[0];colours=struct.unpack_from('<I',h,0x24)[0]
            if n!=s['vertex_count']or not colours:raise RuntimeError('Native glyph colour count changed')
            rgba=np.frombuffer(r.read(colours,n*4),dtype=np.uint8).reshape(-1,4)[:,[2,1,0,3]].tobytes()
            result[p]=hashlib.md5(rgba).hexdigest()
        return result
    def collect():
        try:
            while not stop.is_set():
                try:
                    v=read_json(ROOT/'local/bridge/ui.json');key=v['session'],int(v['sequence'])
                    if key not in archive:
                        ref=v['frame_ref'];body=(ROOT/'local/bridge'/ref['file']).read_bytes();digest=hashlib.md5(body).hexdigest()
                        if digest!=ref['md5']:raise RuntimeError('Native UI body digest mismatch')
                        archive[key]=(digest,draw_colours(body,identities));ready.set()
                    if len(archive)>4096:raise RuntimeError('Hover observation budget exceeded')
                except(OSError,ValueError,KeyError):pass
                # Python's high-resolution sleep avoids Windows condition
                # wait rounding losing a 60 Hz source frame in this observer.
                time.sleep(.001)
        except Exception as e:errors.append(repr(e))
    x,y,w,h=element['rect'];inside=(round(x+w/2),round(y+h/2));outside=(100,100)
    point(r,*outside);time.sleep(.3);thread=threading.Thread(target=collect);thread.start()
    try:
        if not ready.wait(3):raise RuntimeError('Hover source observation did not initialize')
        began=time.time()
        for i in range(events):
            before=native();sent=time.time();point(r,*(inside if i%2==0 else outside));deadline=time.monotonic()+2
            while True:
                value=native();changed=time.time()
                if value!=before:break
                if time.monotonic()>deadline:raise RuntimeError('Original hover did not change native glyph colours')
                time.sleep(.001)
            observations.append(dict(sent=sent,native_observed=changed,colours=value,inside=i%2==0));time.sleep(.3)
        end=time.time();time.sleep(1.2)
    finally:stop.set();thread.join()
    if errors:raise RuntimeError(errors)
    draws=rows(runtime_log(ROOT).read_text(encoding='utf-8',errors='replace'),began,end+.7)
    for e in observations:
        for d in sorted(draws,key=lambda d:d['times'][11]):
            if d['times'][0]<e['native_observed']:continue # conservative: require a new capture after native colour change
            original=archive.get((d['session'],int(d['sequence'])))
            if original and original[0]==d['md5'].lower()and original[1]==e['colours']:
                e.update(sequence=d['sequence'],body_md5=d['md5'],input_to_draw_ms=(d['times'][11]-e['sent'])*1000,native_to_draw_ms=(d['times'][11]-e['native_observed'])*1000,native_to_render_probe_ms=(d['times'][13]-e['native_observed'])*1000);break
    missing=len({(d['session'],int(d['sequence']))for d in draws if d['times'][0]>=began and(d['session'],int(d['sequence']))not in archive})
    report=dict(passed=all('sequence'in e for e in observations)and not missing,scope='Actual original dialogue glyph RGBA changes matched to verified immutable source bodies submitted through Canvas; no cursor substitution, GPU completion or scanout claim.',topic=topic,events=observations,unarchived_draw_sequences=missing,pipeline=summarize(draws),save_writes=False,recording=False)
    for field in('input_to_draw_ms','native_to_draw_ms','native_to_render_probe_ms'):report[field]=stats([e[field]for e in observations if field in e])
    (ROOT/f'logs/ui10-{label}-hover.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items()if k not in('events','pipeline')}));assert report['passed'],'Not every native glyph colour change reached an observed draw'


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pid',type=int,required=True);p.add_argument('--topic',default='Background');p.add_argument('--events',type=int,default=12);p.add_argument('--label',default='current');a=p.parse_args()
    if not 12<=a.events<=60 or not a.label.replace('-','').isalnum()or len(a.label)>32:p.error('Use 12..60 events and a short alphanumeric label')
    r=Reader(a.pid)
    try:run(r,a.topic,a.events,a.label)
    finally:r.close()
