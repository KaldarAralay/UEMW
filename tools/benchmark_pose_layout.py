"""Owned CPU snapshot comparison; no original game, assets, GPU or input."""
from pathlib import Path
import argparse
import hashlib
import json
import statistics
import struct
import sys
import time
import types
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'bridge'))
from geometry_stream import Geometry
from pose_frame import PoseLayout,PoseFrame
from skin_math import Skin
from live_binary import encode

def main():
    p=argparse.ArgumentParser();p.add_argument('--baseline-source',default='logs/pose-layout-baseline-geometry.py');p.add_argument('--output',default='logs/pose-layout-owned-comparison.json');a=p.parse_args()
    source=(ROOT/a.baseline_source).read_bytes();legacy=types.ModuleType('owned_legacy_geometry');exec(compile(source,str(ROOT/a.baseline_source),'exec'),legacy.__dict__)
    count=8192;visible=800;root=0x10000;raw={};records=[];skins={};rng=np.random.default_rng(7)
    def node(ptr,t,identity=(0,0),bound=(0,20,0,1),flags=0):
        b=bytearray(0xac);struct.pack_into('<H',b,0x14,flags);struct.pack_into('<4f',b,0x1c,*bound);struct.pack_into('<13f',b,0x40,*t);struct.pack_into('<2I',b,0x98,*identity);raw[ptr]=bytes(b)
    unit=[1,0,0,0,1,0,0,0,1,0,0,0,1];node(root,unit)
    bones=tuple(0x20000+i*0x100 for i in range(40))
    for i,b in enumerate(bones):t=unit.copy();t[9:12]=[i*.25,i*.1,0];node(b,t)
    for i in range(count):
        ptr=0x100000+i*0x100;identity=(0x400000+i,1 if i<8 else 0);t=unit.copy();t[9:12]=[i%10,25,0];node(ptr,t,identity,bound=(0,25 if i<visible else 5000,0,2),flags=int(i%29==0));skin=None
        if i<8:
            skin=Skin.__new__(Skin);skin.shape=ptr;skin.root=root;skin.bones=bones;skin.skin_transform=np.eye(4);skin.binds=[np.eye(4)for b in bones];skins[i]=skin
        records.append((ptr,identity,(root,ptr),skin,i%4))
    camera=dict(position=[0,0,0],forward=[0,1,0],up=[0,0,1],frustum=[-1,1,1,-1,1,1000],fov=90)
    base=dict(world='0x10000',data='0x20000',cell_ptr='0x30000',camera=camera,frame_ms=1)
    layout=PoseLayout(records)
    class Reader:
        def u32(self,p):return 0x20000 if p==0x7c67e0 else 0x30000
    def state(cls,prepared):
        g=cls.__new__(cls);g.r=Reader();g.records=records;g.shapes=[dict(particles=False)]*count;g.skins=skins;g.native_attributes={};g.cell='0x30000';g.transform_cache={};g.view_pointers=set();g.cell_definitions=[{}for _ in range(4)];g.epoch='11112222-3333-4444-5555-666677778888';g.catalog='owned.json';g.terrain_count=0;g.membership_hash='owned';g.assets=types.SimpleNamespace(meshes={},textures={});g.catalog_history=[];g.pose_layout=layout
        g.capture_pose=lambda b:(base,PoseFrame(raw,layout,camera)if prepared else raw,{},{},{})
        return g
    old=state(legacy.Geometry,False);new=state(Geometry,True);outputs=[]
    for g in(old,new):
        sample=g.snapshot(base,prepared=True);outputs.append(encode(dict(sample,protocol='uemw.live',version=1,session='99998888-7777-6666-5555-444433332222',sequence=1,sample_unix_ns=1793520000000000000,pid=42)))
    if outputs[0]!=outputs[1]:raise RuntimeError('Owned old/new binary snapshots differ')
    for _ in range(6):old.snapshot(base,prepared=True);new.snapshot(base,prepared=True)
    timings=[[],[]]
    for _ in range(40):
        for i,g in enumerate((old,new)):
            began=time.perf_counter();g.snapshot(base,prepared=True);timings[i].append((time.perf_counter()-began)*1000)
    report=dict(scope='Owned CPU snapshot classification + translation, 8192 bindings, 800 in-frustum candidates, eight 40-bone skins; no process reads, original assets, GPU or scanout',baseline_source_sha256=hashlib.sha256(source).hexdigest(),binary_snapshots_identical=True,binary_bytes=len(outputs[0]),legacy_ms=timings[0],prepared_ms=timings[1],legacy_median_ms=statistics.median(timings[0]),prepared_median_ms=statistics.median(timings[1]))
    (ROOT/a.output).write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items()if k not in('legacy_ms','prepared_ms')},indent=2))

if __name__=='__main__':main()
