"""Owned CPU capture/classification A/B; no game, assets, GPU or playback."""
import importlib.util
import json
from pathlib import Path
import statistics
import struct
import sys
import time
import hashlib
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bridge'))
from read_batch import ReadPlan,capture_ranges
from pose_frame import PoseFrame,PoseLayout
from test_pose_frame import header,CAMERA

baseline=ROOT/'tools/fixtures/flat_capture_baseline_pose.py'
spec=importlib.util.spec_from_file_location('flat_capture_baseline_pose',baseline)
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
spec=importlib.util.spec_from_file_location('flat_capture_baseline_read',ROOT/'tools/fixtures/flat_capture_baseline_read.py')
old_read=importlib.util.module_from_spec(spec);spec.loader.exec_module(old_read)
records=[];raw={}
for i in range(8192):
    p=0x10000+i*256;identity=(0x500000+i,0)
    visible=i<800;bound=(0,30+i*.001,0,1)if visible else(4000,20,0,1)
    raw[p]=header(identity,flags=int(i%29==0),bound=bound)
    records.append((p,identity,(p,),None,None))
plan=ReadPlan((p,len(data))for p,data in raw.items())
old_plan=old_read.ReadPlan(list(plan))
storage=bytearray(plan.total)
for p,(offset,count)in plan.offsets.items():storage[offset:offset+count]=raw[p]
storage=bytes(storage)
old_layout=old.PoseLayout(records);new_layout=PoseLayout(records,read_plan=plan)
def blocks(p):
    offset=0;result=[]
    for _,count,_ in p.groups:
        result.append(memoryview(storage)[offset:offset+count].tobytes());offset+=count
    return result
def flat(p):return memoryview(storage).tobytes(),(True,)*len(p.groups)
def legacy():return old.PoseFrame(old_read.copy_ranges(None,old_plan,{},blocks),old_layout,CAMERA)
def prepared():return PoseFrame(capture_ranges(None,plan,{},flat),new_layout,CAMERA)
before=legacy();after=prepared()
np.testing.assert_array_equal(before.nodes,after.nodes)
np.testing.assert_array_equal(before.visible,after.visible)
assert dict(before.raw)==dict(after.raw)
old_ms=[];new_ms=[]
for i in range(50):
    for fn,out in ((legacy,old_ms),(prepared,new_ms))if i%2 else((prepared,new_ms),(legacy,old_ms)):
        started=time.perf_counter();fn();out.append((time.perf_counter()-started)*1000)
report=dict(scope='Owned CPU capture copying + all-node pose classification, 8192 bindings, 800 in-frustum candidates; both paths copy identical total span bytes once; excludes process reads, skin translation, GPU, gameplay and scanout',
    baseline_pose_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),bindings=len(records),spans=len(plan.groups),span_bytes=plan.total,
    requested_bytes=sum(n for _,n in plan),headers_and_visibility_identical=True,all_requested_bytes_identical=True,
    legacy_ms=old_ms,flat_ms=new_ms,legacy_median_ms=statistics.median(old_ms),flat_median_ms=statistics.median(new_ms))
(ROOT/'logs/flat-capture-owned-comparison.json').write_text(json.dumps(report,indent=2))
print(json.dumps({k:v for k,v in report.items()if k not in('legacy_ms','flat_ms')},indent=2))
