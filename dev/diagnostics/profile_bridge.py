"""Profile real producer work after warmup; no synthetic scene or game input."""
import argparse
import cProfile
import pstats
import re
import sys
import time
import geometry_stream
from live_probe import ROOT,snapshot_lease

def main():
    p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--prefix',required=True)
    p.add_argument('--seconds',type=float,default=8);p.add_argument('--warmup',type=float,default=3);a=p.parse_args()
    if not re.fullmatch('[a-z0-9-]{1,40}',a.prefix)or not 1<=a.warmup<a.seconds<=20:p.error('Use a short prefix and 1 <= warmup < seconds <= 20')
    profiler=cProfile.Profile();original=geometry_stream.Geometry.snapshot;started=time.perf_counter();enabled=False
    def snapshot(self,base,*args,**kwargs):
        nonlocal enabled
        if not enabled and time.perf_counter()-started>=a.warmup:profiler.enable();enabled=True
        return original(self,base,*args,**kwargs)
    geometry_stream.Geometry.snapshot=snapshot
    sys.argv=['geometry_stream.py','--pid',str(a.pid),'--seconds',str(a.seconds),'--hz','60']
    try:
        with snapshot_lease():geometry_stream.main()
    finally:
        profiler.disable();geometry_stream.Geometry.snapshot=original
        profiler.dump_stats(str(ROOT/'logs'/(a.prefix+'.prof')))
        with (ROOT/'logs'/(a.prefix+'.txt')).open('w')as out:pstats.Stats(profiler,stream=out).strip_dirs().sort_stats('cumtime').print_stats(45)

if __name__=='__main__':main()
