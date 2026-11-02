"""Independent read-only camera sampling; no input, prediction or game clock.

Only sample the exact published scene identity. Full pose frames retain their
own 500 ms watchdog; a fresh camera must not keep stale geometry declared live.
"""
import json
import math
import os
from pathlib import Path
import struct
import multiprocessing as mp
import time
from live_probe import Reader,ROOT
from native_ui import loading_state

def capture(reader,base):
    reader.check_alive()
    world=reader.u32(0x7C67DC);data=reader.u32(0x7C67E0)
    if (hex(world),hex(data),hex(reader.u32(data+0xB540)))!=(base['world'],base['data'],base['cell_ptr']):raise ValueError('Camera lane scene changed')
    header=reader.read(world,0x17C);camera=struct.unpack_from('<I',header,0x134)[0]
    if hex(camera)!=base['camera_ptr'] or loading_state(reader)[0]:raise ValueError('Camera lane loading or changed camera')
    visual=reader.player_render_state(world)
    if visual.get('reference')!=base.get('player_ref') or visual['first_person']!=base['first_person_active']:raise ValueError('Camera lane player/pass changed')
    raw=reader.read(camera,0x128);transform=struct.unpack_from('<13f',raw,0x40)
    forward=struct.unpack_from('<3f',raw,0xDC);up=struct.unpack_from('<3f',raw,0xE8);fov=struct.unpack_from('<f',header,0x13C)[0]
    if not all(math.isfinite(v)and abs(v)<=1e8 for v in (*transform,*forward,*up,fov)) or not 10<fov<170:raise ValueError('Invalid native camera lane numbers')
    if reader.u32(0x7C67DC)!=world or reader.u32(data+0xB540)!=int(base['cell_ptr'],16):raise ValueError('Camera lane fence advanced')
    return dict(position=transform[9:12],forward=forward,up=up,fov=fov),struct.unpack_from('<I',header,0x24)[0]

def committed_base(path,pid,session,now_ns):
    """Use only the parent's atomic commit, never a pending/unpublished pose."""
    from local_files import read_json
    packet=read_json(path)
    if not isinstance(packet,dict)or packet.get('protocol')!='uemw.live'or packet.get('version')not in(1,2,3,4,5)or packet.get('status')!='live' or packet.get('pid')!=pid or packet.get('session')!=session:
        raise ValueError('Camera base is not this live source')
    if packet['version']in(4,5) and packet.get('state_metadata_version')!=1:raise ValueError('Unsupported camera base metadata format')
    keys=('world','data','cell_ptr','camera_ptr','player_ref','first_person_active','scene_epoch','sequence','sample_unix_ns')
    if not all(k in packet for k in keys)or type(packet['sequence'])is not int or not 0<=packet['sequence']<=9007199254740991:
        raise ValueError('Incomplete camera base')
    if not 0<now_ns-packet['sample_unix_ns']<400_000_000:raise ValueError('Camera base is stale')
    return {k:packet[k]for k in (*keys,*(('view_layout',)if packet.get('view_layout')else()))}

def camera_process(pid,session,stop):
    # A separate interpreter prevents topology traversal/encoding from delaying
    # native camera reads under the producer's GIL. No input or prediction.
    parent=mp.parent_process();reader=None;sequence=0;view_name=None;view=None;discovery=None;cache=None;view_epoch=None
    target=ROOT/'local/bridge/camera.json';temporary=target.with_suffix(f'.{os.getpid()}.tmp')
    try:
        reader=Reader(pid)
        from native_first_person import Discovery,DefinitionCache,NearPass
        discovery=Discovery(reader);cache=DefinitionCache(reader)
        while not stop.is_set()and(parent is None or parent.is_alive()):
            began=time.perf_counter()
            reader.check_alive() # A dead native source ends this child.
            try:
                base=committed_base(target.with_name('latest.json'),pid,session,time.time_ns())
                if view_epoch!=base['scene_epoch']:view=None;view_name=None;view_epoch=base['scene_epoch']
                stamp=time.time_ns();camera,frame=capture(reader,base)
                packet=dict(protocol='uemw.camera',version=1,pid=pid,session=session,scene_epoch=base['scene_epoch'],
                    sequence=sequence,source_sequence=base['sequence'],sample_unix_ns=stamp,native_frame_ms=frame,
                    read_ms=(time.perf_counter()-began)*1000,camera=camera)
                if base.get('view_layout')and view_name!=base['view_layout']:
                    candidate=NearPass(base['view_layout']);cache.ingest(candidate.definition,base['scene_epoch']);view_name=base['view_layout']
                    discovery.reported=None
                    observed={(int(s['id'],16),int(s['model'],16),int(s['skin'],16))for s in getattr(discovery,'graph',{}).get('shapes',[])}
                    expected={(s['ptr'],*s['identity'])for s in candidate.rows}
                    if view is None or view.definition['root']!=candidate.definition['root']or view.definition.get('item_root')!=candidate.definition.get('item_root')or expected==observed:view=candidate
                try:
                    signature=discovery.poll(base,view.definition if view else None)
                    if signature:
                        from presentation import atomic_json
                        atomic_json(target.with_name('view-refresh.json'),dict(protocol='uemw.view.discovery',version=1,pid=pid,session=session,scene_epoch=base['scene_epoch'],signature=signature,unix_ns=time.time_ns()))
                        if view:
                            rebound=cache.prepare(discovery.graph,view.definition,base)
                            if rebound:view=rebound
                except(OSError,ValueError,RuntimeError,KeyError,TypeError):pass
                if base.get('view_layout'):
                    try:
                        if view is None:view=NearPass(base['view_layout'])
                        near=view.capture(reader,base)
                        packet.update(version=2,view=near)
                    except(OSError,ValueError,RuntimeError,KeyError,TypeError):pass
                temporary.write_bytes(json.dumps(packet,separators=(',',':'),allow_nan=False).encode())
                os.replace(temporary,target);sequence+=1
            except (OSError,ValueError,RuntimeError,KeyError,TypeError):pass
            # Python's high-resolution sleep avoids Windows Event.wait's
            # observed ~31 ms rounding at this cadence. No busy loop.
            time.sleep(max(0,1/60-(time.perf_counter()-began)))
    except (OSError,ValueError,RuntimeError)as error:
        print(json.dumps(dict(camera_lane_error=str(error))),flush=True)
    finally:
        if cache:cache.close()
        if reader:reader.close()
        temporary.unlink(missing_ok=True)

class CameraLane:
    def __init__(self,pid,session):
        ctx=mp.get_context('spawn');self.stop=ctx.Event()
        self.process=ctx.Process(target=camera_process,args=(pid,session,self.stop),name='native-camera',daemon=True)
        self.process.start()
        print(json.dumps(dict(camera_reader_started=True,source_pid=pid,reader_pid=self.process.pid)),flush=True)
    def close(self):
        self.stop.set();self.process.join(2)
        if self.process.is_alive():self.process.terminate();self.process.join(2)
        self.process.close()
