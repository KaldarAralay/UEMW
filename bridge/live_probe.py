"""Read-only, external x64 reader for the installed Steam x86 Morrowind build.

No injection, writes, hooks, debugger attachment, or gameplay implementation.
Memory layout reference: MWSE 4bdb158457fbe15943119b90a916bc2f54a752dd.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import time
import uuid
import threading
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
class SceneReadChanged(RuntimeError):
    """An original scene mutation invalidated a read, not the last good frame."""

GAME = ROOT / 'local' / 'Morrowind' / 'Morrowind.exe'
EXPECTED_SHA256 = 'eac72e1b3524ee0012d080d3c2e2e00e401464e41ee54f9afd6aaaadf2c221f5'
K = C.WinDLL('kernel32', use_last_error=True)
K.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
K.OpenProcess.restype = W.HANDLE
K.CloseHandle.argtypes = [W.HANDLE]
K.ReadProcessMemory.argtypes = [W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
K.ReadProcessMemory.restype = W.BOOL
K.QueryFullProcessImageNameW.argtypes = [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]
K.QueryFullProcessImageNameW.restype = W.BOOL
K.IsWow64Process.argtypes = [W.HANDLE, C.POINTER(W.BOOL)]
K.IsWow64Process.restype = W.BOOL
K.GetExitCodeProcess.argtypes=[W.HANDLE,C.POINTER(W.DWORD)]
K.GetExitCodeProcess.restype=W.BOOL
K.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR]
K.CreateMutexW.restype=W.HANDLE

@contextmanager
def snapshot_lease():
    """One writer for the versioned snapshot in this workspace."""
    name='Local\\UEMW-'+hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:20]
    handle=K.CreateMutexW(None,False,name)
    error=C.get_last_error()
    if not handle:raise C.WinError(error)
    try:
        if error==183:raise RuntimeError('A snapshot producer is already running for this workspace')
        yield
    finally:K.CloseHandle(handle)


class Reader:
    def __init__(self, pid):
        self.pid=pid
        self._scratch=threading.local()
        self.handle = K.OpenProcess(0x0400 | 0x0010, False, pid)
        if not self.handle:
            error=C.WinError(C.get_last_error())
            raise RuntimeError(f'Cannot open private Morrowind PID {pid}: {error}. If it exited, restart the bridge with the new private PID.') from error
        try:self._validate(pid)
        except BaseException:
            self.close();raise
        from native_read_batch import NativeBatch
        self._native_batch=NativeBatch(self.handle)

    def _validate(self,pid):
        self.check_alive()
        path = C.create_unicode_buffer(32768)
        size = W.DWORD(len(path))
        if not K.QueryFullProcessImageNameW(self.handle, 0, path, C.byref(size)):
            error=C.WinError(C.get_last_error())
            self.check_alive() # An exited process can report misleading WinError 31 here.
            raise error
        self.path = Path(path.value)
        if os.path.normcase(str(self.path)) != os.path.normcase(str(GAME)):
            raise RuntimeError(f'Refusing non-isolated process: {self.path}')
        if hashlib.sha256(self.path.read_bytes()).hexdigest() != EXPECTED_SHA256:
            raise RuntimeError('Unsupported executable SHA256; offsets must be revalidated.')
        wow = W.BOOL()
        if not K.IsWow64Process(self.handle, C.byref(wow)) or not wow.value:
            raise RuntimeError('Expected a 32-bit game running on 64-bit Windows.')
        if self.read(0x400000, 2) != b'MZ':
            raise RuntimeError('Unsupported loaded image base.')
        self.pid = pid

    def check_alive(self):
        code=W.DWORD()
        if not K.GetExitCodeProcess(self.handle,C.byref(code)):
            raise C.WinError(C.get_last_error())
        if code.value!=259: # STILL_ACTIVE; the handle remains bound to this exact process.
            raise RuntimeError(f'Private Morrowind PID {self.pid} exited with code {code.value:#010x}; restart the bridge with the new private PID')

    def close(self):
        bulk=getattr(self,'_native_batch',None)
        if bulk:bulk.handle=None
        self._native_batch=None
        if self.handle:
            K.CloseHandle(self.handle)
            self.handle = None
        self._scratch=None

    def camera_sample(self):
        """Small render fence; no traversal or CPU deformation between reads."""
        self.check_alive()
        world=self.u32(0x7C67DC)
        data=self.u32(0x7C67E0)
        header=self.read(world,0x17C)
        camera=struct.unpack_from('<I',header,0x134)[0]
        cell=self.u32(data+0xB540)
        if not camera or not cell:
            raise RuntimeError('Camera/cell not ready during pose capture')
        raw=self.read(camera,0x128)
        values=struct.unpack_from('<13f',raw,0x40)
        if not all(math.isfinite(v) and abs(v)<1e8 for v in values):
            raise ValueError('Invalid camera transform')
        arm_root=struct.unpack_from('<I',header,0x158)[0]
        visual=self.player_render_state(world)
        from native_ui import loading_state
        loading,load_serial=loading_state(self)
        return {'world':hex(world),'data':hex(data),'cell_ptr':hex(cell),
                'player_ref':visual.get('reference'),
                'weather_controller':hex(struct.unpack_from('<I',header,0x58)[0]),
                'native_loading':loading,'load_serial':load_serial,
                'view_roots':[hex(arm_root)]if arm_root else [],
                'first_person_active':visual['first_person'],
                'first_person_items_active':visual.get('items_active',True),'first_person_model_root':visual.get('item_root'),
                'aux_roots':self.auxiliary_roots(world,data,header,visual),
                'camera_ptr':hex(camera),'frame_ms':struct.unpack_from('<I',header,0x24)[0],
                'first_person_camera_ptr':hex(struct.unpack_from('<I',header,0x160)[0]),
                'window':struct.unpack_from('<I',header,0xCC)[0],'menu':bool(header[0xD6]),
                'camera':{'rotation':values[:9],'position':values[9:12],'scale':values[12],
                          'forward':struct.unpack_from('<3f',raw,0xDC),
                          'up':struct.unpack_from('<3f',raw,0xE8),
                          'frustum':struct.unpack_from('<6f',raw,0x100),
                          'fov':struct.unpack_from('<f',header,0x13C)[0]}}

    def player_render_state(self,world):
        """Copy the native player's render root and actual camera-pass mode."""
        result=dict(root=None,first_person=True)
        mob=self.u32(world+0x5C)
        process=self.u32(mob+0x24)if mob else 0
        player=self.u32(process)if process else 0
        if not player:return result
        ref=self.u32(player+0x14)
        controller=self.u32(player+0x244)
        if not ref or self.read(ref+4,4)!=b'REFR' or not controller:return result
        mode=self.read(controller+0xE8,8)
        vanity=struct.unpack_from('<i',mode,4)[0]
        if mode[0]>1 or not -16<=vanity<=16:raise SceneReadChanged('Invalid native camera-pass mode')
        node=self.u32(ref+0x10)
        readiness=self.read(player+0x5bd,2)
        if any(v>1 for v in readiness):raise SceneReadChanged('Invalid native first-person item readiness')
        first=self.u32(player+0x660);item_root=0
        if first:
            if self.read(first+4,4)!=b'REFR':raise SceneReadChanged('Native first-person reference changed')
            item_root=self.u32(first+0x10)
        return dict(root=hex(node)if node else None,reference=hex(ref),first_person=not(mode[0]or vanity),
                    third_person=bool(mode[0]),vanity=vanity,items_active=bool(any(readiness)),item_root=hex(item_root)if item_root else None)

    def auxiliary_roots(self,world,data,header=None,visual=None):
        header=self.read(world,0x80)if header is None else header
        roots=[]
        def add(layer,ptr,visible=None,target=None):
            if not ptr:return
            # Root identity is independent of its current app-cull flag. Keep
            # disabled passes bound; live ancestor flags suppress their draw
            # and particle work without repeatedly rebuilding the whole scene.
            roots.append(dict(layer=layer,root=hex(ptr),**({'visible':visible}if visible is not None else {}),**({'target_ref':hex(target)}if target is not None else{})))
        weather,mob,vfx=struct.unpack_from('<I',header,0x58)[0],struct.unpack_from('<I',header,0x5C)[0],struct.unpack_from('<I',header,0x74)[0]
        if weather:
            raw=self.read(weather,0x80)
            for layer,offset in (('sky',0x4C),('weather',0x5C),('weather',0x60),('weather',0x6C)):add(layer,struct.unpack_from('<I',raw,offset)[0])
            # Sunglare is borrowed by the native near pass, but is not a hand
            # or weapon. Bind its authoritative weather-controller root first
            # so draw/sheath and third-person gates cannot suppress it.
            add('sun_glare',struct.unpack_from('<I',raw,0x8)[0])
        water=self.u32(data+0xB4EC)
        if water:
            raw=self.read(water,0xB8)
            if raw[5]>1:raise SceneReadChanged('Invalid native water visibility')
            add('water',struct.unpack_from('<I',raw,0xB4)[0],bool(raw[5]));add('ripple',struct.unpack_from('<I',raw,0xB0)[0],bool(raw[5]))
        # Deque is 12 bytes (its +8 field is the live effect count).
        # VFXManager.h's old +8 comment is stale; sizeof(VFXManager)==0x14,
        # the Deque static assertions and the native NiNode verify +0xC.
        if vfx:
            add('world_effect',self.u32(vfx+0xC))
            from native_projectiles import effect_roots
            # Actor-attached hit effects live outside the shared world root.
            for node,target in effect_roots(self,vfx,include_targets=True).items():add('world_effect',node,target=target)
        if mob:
            projectiles=self.u32(mob+0x28)
            if projectiles:add('projectile',self.u32(projectiles+0x14))
        visual=self.player_render_state(world)if visual is None else visual
        if mob and projectiles:
            from native_projectiles import roots as projectile_roots
            # Spell visuals can be owned by VFXManager rather than the shared
            # arrow root. Visit their actual native nodes first during traversal.
            for node in projectile_roots(self,projectiles,vfx):
                if not any(item['layer']=='projectile'and item['root']==hex(node)for item in roots):add('projectile',node)
        if visual['root']:
            add('player',int(visual['root'],16))
            # The player is not enumerated as an ordinary cell actor. Preserve
            # its actual REFR so traversal/pose capture can fence ownership
            # while a native auxiliary pass borrows the third-person root.
            roots[-1]['owner_ref']=visual['reference']
        return roots

    def read(self, address, count):
        if not 0x10000 <= address < 0xFFF00000 or not 0 < count <= 4*1024*1024:
            raise ValueError(f'Invalid read {address:#x} size {count}')
        # ctypes array types/buffers are expensive to recreate for thousands
        # of small scene reads. Reuse bounded scratch storage per thread; only
        # independent immutable bytes escape this method.
        local=getattr(self,'_scratch',None)
        if local is None:local=self._scratch=threading.local()
        buffers=getattr(local,'buffers',None)
        if buffers is None:buffers=local.buffers={}
        capacity=max(4096,1<<(count-1).bit_length())
        if capacity not in buffers:buffers[capacity]=(C.create_string_buffer(capacity),C.c_size_t())
        buf,got=buffers[capacity];got.value=0
        if not K.ReadProcessMemory(self.handle, address, buf, count, C.byref(got)) or got.value != count:
            raise OSError(f'ReadProcessMemory({address:#x}, {count}): {C.get_last_error()}')
        return C.string_at(buf,count)

    def read_many(self,requests):
        """Copy nearby nodes in <=64 KiB spans; unreadable gaps use exact reads.

        Any unreadable requested node still drops the entire pose. Independent
        returned bytes and the existing native frame/identity fences are kept.
        """
        from read_batch import copy_ranges
        bulk=getattr(self,'_native_batch',None)
        stats={};result=copy_ranges(self.read,requests,stats,bulk=bulk.copy if bulk and bulk.api else None);self.last_batch_stats=stats
        return result

    def capture_many(self,requests):
        """Owned flat capture with the same bounded/exact gap-read policy."""
        from read_batch import capture_ranges
        bulk=getattr(self,'_native_batch',None)
        stats={};result=capture_ranges(self.read,requests,stats,bulk=bulk.copy_flat if bulk and bulk.api else None)
        self.last_batch_stats=stats
        return result

    def u32(self, address):
        return struct.unpack('<I', self.read(address, 4))[0]

    def string(self, address, limit=256):
        if not address:
            return ''
        out = bytearray()
        while len(out)<limit:
            current=address+len(out)
            chunk=self.read(current,min(limit-len(out),0x1000-(current&0xFFF)))
            end=chunk.find(b'\0')
            if end>=0:
                out+=chunk[:end]
                break
            out+=chunk
        return out.decode('cp1252', errors='replace')

    def transform(self, address):
        values = struct.unpack('<13f', self.read(address + 0x40, 52))
        if not all(math.isfinite(v) and abs(v) < 1e8 for v in values):
            raise ValueError('Invalid NiAVObject world transform')
        return {'rotation':values[:9], 'position':values[9:12], 'scale':values[12]}

    def player_state(self,world):
        """Read original statistics/readiness. This never evaluates damage/stats."""
        mob=self.u32(world+0x5C)
        if not mob:return None
        process=self.u32(mob+0x24)
        if not process:return None
        player=self.u32(process)
        if not player:return None
        raw=self.read(player,0x5C0);ref=struct.unpack_from('<I',raw,0x14)[0]
        if not ref or self.read(ref+4,4)!=b'REFR':return None
        stats={name:list(struct.unpack_from('<2f',raw,offset+4))for name,offset in (('health',0x2B4),('magicka',0x2C0),('fatigue',0x2D8))}
        if not all(math.isfinite(v)and abs(v)<=1e8 for pair in stats.values()for v in pair):return None
        if self.u32(process)!=player:raise SceneReadChanged('Player replaced during stat capture')
        return dict(reference=hex(ref),**stats,weapon_ready=bool(raw[0x5BD]),magic_ready=bool(raw[0x5BE]))

    def focus_metadata(self,target):
        if not target:return None
        raw=self.read(target,0x50)
        if raw[4:8]!=b'REFR':raise SceneReadChanged('Native focus reference changed')
        physical=struct.unpack_from('<I',raw,0x28)[0];kind=self.read(physical+4,4)
        focus=dict(id=hex(target),base_id=self.string(self.u32(physical+0x2c)),name='Object')
        if kind in(b'NPC_',b'CREA',b'CONT')and not self.u32(physical+0x34)&8:physical=self.u32(physical+0x6c)
        offset={b'MISC':0x44,b'BOOK':0x44,b'WEAP':0x44,b'ARMO':0x44,b'CLOT':0x44,b'ALCH':0x44,b'LIGH':0x48,b'NPC_':0x70,b'CREA':0x70,b'CONT':0x6c,b'ACTI':0x38}.get(kind)
        if offset:focus['name']=self.string(self.u32(physical+offset))
        elif kind==b'DOOR':focus['name']=self.string(physical+0x34,32)
        elif kind in(b'INGR',b'LOCK',b'PROB',b'REPA'):focus['name']=self.string(physical+0x44,32)
        elif kind==b'APPA':focus['name']=self.string(physical+0x64,32)
        return focus

    def render_metadata(self,anchor=None):
        """Native UI metadata only; live geometry owns visual membership/poses.

        The legacy diagnostic snapshot still traverses complete reference lists.
        Normal rendering needs their counts, the native target and player stats.
        """
        anchor=self.camera_sample()if anchor is None else anchor
        if anchor.get('native_loading'):return {**anchor,'status':'no_scene','pid':self.pid}
        world=int(anchor['world'],16);data=int(anchor['data'],16);cell=int(anchor['cell_ptr'],16)
        counts=[struct.unpack('<3I',self.read(cell+offset,12))[0]for offset in(0x30,0x40,0x58)]
        if any(count>10000 for count in counts):raise ValueError('Implausible native reference count')
        target=self.u32(self.u32(0x7c6cdc)+0xe8);focus=self.focus_metadata(target)
        flags=self.u32(cell+0x18);grid=struct.unpack('<2i',self.read(cell+0x24,8))if not flags&1 else None
        name=self.string(self.u32(cell+0x10));fps=struct.unpack('<f',self.read(world+0x14,4))[0]
        try:player=self.player_state(world)
        except(OSError,ValueError):player=None
        if self.u32(0x7c67dc)!=world or self.u32(0x7c67e0)!=data or self.u32(data+0xb540)!=cell or self.u32(self.u32(0x7c6cdc)+0xe8)!=target:
            raise SceneReadChanged('Native render metadata identity changed')
        if player and player['reference']!=anchor.get('player_ref'):raise SceneReadChanged('Native player changed during render metadata capture')
        return {**anchor,'pid':self.pid,'status':'live','cell':name,'cell_flags':flags,'cell_grid':grid,'game_fps':fps,
                'objects':[],'object_count':sum(counts),'focus':focus,'player':player}

    def snapshot(self,include_object_transforms=True):
        self.check_alive()
        world = self.u32(0x7C67DC)
        data = self.u32(0x7C67E0)
        if not world or not data:
            raise RuntimeError('World/data controller not initialized')
        header = self.read(world, 0x17C)
        camera = struct.unpack_from('<I', header, 0x134)[0]
        cell = self.u32(data + 0xB540)
        visual=self.player_render_state(world)
        from native_ui import loading_state
        loading,load_serial=loading_state(self)
        base = {'pid':self.pid, 'world':hex(world), 'data':hex(data),
                'player_ref':visual.get('reference'),
                'weather_controller':hex(struct.unpack_from('<I',header,0x58)[0]),
                'native_loading':loading,'load_serial':load_serial,
                'view_roots':[hex(struct.unpack_from('<I',header,0x158)[0])]if struct.unpack_from('<I',header,0x158)[0]else [],
                'first_person_active':visual['first_person'],
                'first_person_items_active':visual.get('items_active',True),'first_person_model_root':visual.get('item_root'),
                'aux_roots':self.auxiliary_roots(world,data,header,visual),
                'window':struct.unpack_from('<I',header,0xCC)[0],
                'frame_ms':struct.unpack_from('<I',header,0x24)[0],
                'game_fps':struct.unpack_from('<f',header,0x14)[0],
                'menu':bool(header[0xD6]), 'cell_ptr':hex(cell), 'camera_ptr':hex(camera)}
        if not cell or not camera or loading:
            return {**base, 'status':'no_scene'}
        name = self.string(self.u32(cell + 0x10))
        cam = self.transform(camera)
        cam['forward'] = struct.unpack('<3f',self.read(camera+0xDC,12))
        cam['up'] = struct.unpack('<3f',self.read(camera+0xE8,12))
        cam['fov'] = struct.unpack_from('<f', header, 0x13C)[0]
        cam['frustum'] = struct.unpack('<6f',self.read(camera+0x100,24))
        refs=[]
        visited=set()
        for list_offset in (0x30,0x40,0x58):
            count, current, tail = struct.unpack('<3I', self.read(cell+list_offset,12))
            if count>10000:
                raise ValueError('Implausible cell reference count')
            for _ in range(count+1):
                if not current or current in visited:
                    break
                visited.add(current)
                raw=self.read(current,0x50)
                if raw[4:8] != b'REFR':
                    raise ValueError(f'Unexpected reference type {raw[4:8]!r}')
                physical=struct.unpack_from('<I',raw,0x28)[0]
                node=struct.unpack_from('<I',raw,0x10)[0]
                record={'id':hex(current),'source_id':struct.unpack_from('<I',raw,0x48)[0],
                        'target_id':struct.unpack_from('<I',raw,0x4C)[0],
                        'flags':struct.unpack_from('<I',raw,8)[0],
                        'base_id':self.string(self.u32(physical+0x2C)),
                        'type':self.read(physical+4,4).decode('ascii',errors='replace'),
                        'position':struct.unpack_from('<3f',raw,0x38),
                        'orientation':struct.unpack_from('<3f',raw,0x2C),
                        'node':hex(node)}
                if node and include_object_transforms:
                    record['transform']=self.transform(node)
                refs.append(record)
                current=struct.unpack_from('<I',raw,0x20)[0]
        # Reject a sample spanning a cell unload/reload. Read-only access cannot
        # provide an engine frame lock; document the remaining tearing risk.
        if cell != self.u32(data+0xB540) or world != self.u32(0x7C67DC):
            raise SceneReadChanged('Cell/world changed during sample; dropped')
        target=self.u32(self.u32(0x7C6CDC)+0xE8)
        focus=next((dict(id=o['id'],base_id=o['base_id'],name='Object') for o in refs if int(o['id'],16)==target),None)
        if focus:
            physical=self.u32(target+0x28)
            kind=self.read(physical+4,4)
            # NPC/container instances store a base-actor pointer at +0x6C;
            # their +0x70 is instance state, not a display-name pointer.
            if kind in (b'NPC_',b'CREA',b'CONT') and not self.u32(physical+0x34)&0x8:
                physical=self.u32(physical+0x6C)
            offset={b'MISC':0x44,b'BOOK':0x44,b'WEAP':0x44,b'ARMO':0x44,b'CLOT':0x44,b'ALCH':0x44,
                    b'LIGH':0x48,b'NPC_':0x70,b'CREA':0x70,b'CONT':0x6C,b'ACTI':0x38}.get(kind)
            if offset:focus['name']=self.string(self.u32(physical+offset))
            elif kind==b'DOOR':focus['name']=self.string(physical+0x34,32)
            elif kind in (b'INGR',b'LOCK',b'PROB',b'REPA'):focus['name']=self.string(physical+0x44,32)
            elif kind==b'APPA':focus['name']=self.string(physical+0x64,32)
        flags=self.u32(cell+0x18)
        grid=struct.unpack('<2i',self.read(cell+0x24,8)) if not flags&1 else None
        try:player=self.player_state(world)
        except (OSError,ValueError):player=None
        return {**base,'status':'live','cell':name,'cell_flags':flags,'cell_grid':grid,
                'camera':cam,'objects':refs,'focus':focus,'player':player}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pid',required=True,type=int)
    parser.add_argument('--seconds',type=float,default=0,help='0 = one probe; negative = until interrupted')
    parser.add_argument('--hz',type=float,default=30)
    parser.add_argument('--trace',action='store_true',help='Log full snapshots at sample rate for a bounded acceptance recording')
    args=parser.parse_args()
    if not 1 <= args.hz <= 120:
        parser.error('--hz must be between 1 and 120')
    (ROOT/'local'/'bridge').mkdir(parents=True,exist_ok=True)
    (ROOT/'logs').mkdir(exist_ok=True)
    output=ROOT/'local'/'bridge'/'latest.json'
    log_path=ROOT/'logs'/'live-probe.jsonl'
    session=str(uuid.uuid4())
    start=time.perf_counter()
    reader=Reader(args.pid)
    sequence=0
    try:
        with log_path.open('a',encoding='utf-8') as log:
            while True:
                tick=time.perf_counter()
                capture_ns=time.time_ns()
                try:
                    sample=reader.snapshot()
                except (OSError,ValueError,RuntimeError) as e:
                    sample={'status':'unavailable','error':str(e),'pid':args.pid}
                packet={'protocol':'uemw.live','version':1,'session':session,'sequence':sequence,
                        'sample_unix_ns':capture_ns,**sample}
                packet['read_ms']=(time.perf_counter()-tick)*1000
                text=json.dumps(packet,separators=(',',':'),allow_nan=False)
                temporary=output.with_suffix('.tmp')
                temporary.write_text(text,encoding='utf-8')
                # A third-party reader can briefly deny DELETE sharing. Keep
                # the last complete packet and retry without touching the game.
                for attempt in range(20):
                    try:
                        os.replace(temporary,output)
                        break
                    except PermissionError:
                        if attempt==19:
                            print('Snapshot replacement delayed by a reader file lock',flush=True)
                        time.sleep(0.002)
                if sequence==0 or sequence % max(1,round(args.hz))==0:
                    summary={k:v for k,v in packet.items() if k!='objects'}
                    summary['object_count']=len(packet.get('objects',[]))
                    summary['actors']=[o for o in packet.get('objects',[]) if o['type'].startswith(('NPC','CREA','CREC'))]
                    print(json.dumps(summary),flush=True)
                    if not args.trace:
                        log.write(json.dumps(summary,separators=(',',':'))+'\n')
                        log.flush()
                if args.trace:
                    log.write(text+'\n')
                    log.flush()
                sequence+=1
                if args.seconds==0 or (args.seconds>0 and time.perf_counter()-start>=args.seconds):
                    break
                time.sleep(max(0,1/args.hz-(time.perf_counter()-tick)))
    finally:
        reader.close()


if __name__=='__main__':
    with snapshot_lease():main()
