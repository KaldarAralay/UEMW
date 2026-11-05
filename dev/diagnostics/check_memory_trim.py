"""Opt-in, paused-only temporary-page cleanup diagnostic; never a play benchmark."""
import argparse
import json
import re
from check_native_motion import witness
from live_probe import ROOT
from ui_timing import build_identity


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pages',type=int,nargs='+',default=[0],help='Owned 64 KiB pages per sample; 0..4096, at most eight total samples')
    p.add_argument('--repeat',type=int,default=1)
    p.add_argument('--label',default='memory-trim')
    a=p.parse_args()
    if not 1<=a.repeat<=3 or len(a.pages)*a.repeat>8 or any(not 0<=n<=4096 for n in a.pages):p.error('Use 0..4096 pages, 1..3 repeats and at most eight samples')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}',a.label):p.error('Use a short filename label with letters, numbers, underscores or hyphens')
    w=witness([])
    if not w.get('live') or w.get('partial_geometry') or not w.get('native_menu_open'):raise RuntimeError('Pause the private original in a complete live scene before this diagnostic')
    report=dict(scope='Explicit paused cleanup CPU scopes. Owned allocation/preparation is excluded from trim duration. Not gameplay, GPU or display timing.',
                recording=False,save_writes=False,build=build_identity(ROOT),allocator=w['allocator'],renderer_pid=w['renderer_pid'],
                scene={k:w.get(k)for k in('session','scene_epoch','catalog','terrain_signature')},samples=[])
    for pages in a.pages:
        for _ in range(a.repeat):
            current=witness([],memory_trim=True,memory_trim_pages=pages)
            if current.get('renderer_pid')!=report['renderer_pid'] or current.get('session')!=report['scene']['session'] or not current.get('native_menu_open'):raise RuntimeError('Diagnostic ownership or native pause changed')
            sample={k:v for k,v in current.items()if k.startswith('memory_trim_')}
            if sample.get('memory_trim_owned_pages')!=pages:raise RuntimeError('The renderer did not execute the requested diagnostic')
            report['samples'].append(sample)
    path=ROOT/'logs'/(a.label+'-'+report['allocator'].lower()+'.json')
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(dict(path=str(path),allocator=report['allocator'],samples=report['samples'])))


if __name__=='__main__':main()
