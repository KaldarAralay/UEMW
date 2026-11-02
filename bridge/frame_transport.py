"""Protocol v2 bounded immutable frame bodies; small v1 snapshots stay inline.

The atomic latest.json commit references an already complete body by exact
session/sequence, byte length and MD5. MD5 detects accidental corruption; this
local same-user transport is not an authentication boundary.
"""
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

MAX_FRAME_BYTES=4*1024*1024
HISTORY=8
FRAME_NAME=re.compile(r'frame-[0-9a-f]{32}-[0-9]{10,16}\.(?:json|bin)\Z')


def filename(packet,binary=False):
    session=uuid.UUID(packet['session']).hex
    sequence=packet['sequence']
    if type(sequence) is not int or not 0<=sequence<=9007199254740991:
        raise ValueError('Invalid frame sequence')
    return f'frame-{session}-{sequence:010d}.'+('bin' if binary else 'json')


class FrameStore:
    def __init__(self,folder):
        self.folder=Path(folder)/'frames';self.folder.mkdir(parents=True,exist_ok=True)
        self.history=deque();self.cleaned=False

    def prepare(self,packet,body,binary=False):
        if not 0<len(body)<=MAX_FRAME_BYTES:
            raise ValueError('Frame body exceeds the 4 MiB limit')
        name=filename(packet,binary);target=self.folder/name
        if self.trim()>=HISTORY*2:
            raise ValueError('Retired frame bodies are held by readers; publication deferred')
        target.write_bytes(body) # New immutable file; manifest is committed later.
        manifest={k:v for k,v in packet.items() if k not in ('instances','instance_states','objects')}
        packed=binary and body[:4]==b'UFB3'
        if packed:
            for field in('environment','material_frames','material_values'):manifest.pop(field,None)
            manifest['state_metadata_version']=1
        manifest.update(version=4 if packed else 3 if binary else 2,object_count=packet.get('object_count',len(packet.get('objects',[]))),
            frame_ref=dict(file='frames/'+name,bytes=len(body),md5=hashlib.md5(body).hexdigest()))
        return manifest,name

    def commit(self,name):
        self.history.append(name)
        if not self.cleaned:
            # Single-writer lease is held by the caller. Only recognized files
            # in this exact generated directory are retired during reconnect.
            for old in self.folder.iterdir():
                if FRAME_NAME.fullmatch(old.name) and old.name!=name:
                    self.remove(old.name)
            self.cleaned=True
        while len(self.history)>HISTORY:self.remove(self.history.popleft())

    def trim(self):
        keep=set(self.history)
        latest=self.folder.parent/'latest.json'
        if not self.cleaned:
            try:
                if latest.stat().st_size<=1024*1024:
                    current=json.loads(latest.read_bytes()).get('frame_ref',{}).get('file','')
                    if current.startswith('frames/') and FRAME_NAME.fullmatch(current[7:]):keep.add(current[7:])
            except (OSError,ValueError,AttributeError,TypeError):pass
        for old in self.folder.iterdir():
            if FRAME_NAME.fullmatch(old.name) and old.name not in keep:self.remove(old.name)
        return sum(bool(FRAME_NAME.fullmatch(p.name))for p in self.folder.iterdir())

    def remove(self,name):
        if not FRAME_NAME.fullmatch(name):raise ValueError('Invalid generated frame name')
        target=(self.folder/name).resolve()
        if target.parent!=self.folder.resolve():raise ValueError('Frame path escaped generated directory')
        try:target.unlink(missing_ok=True)
        except PermissionError:pass # A bounded reader can be finishing this file.


def read_body(manifest,folder):
    binary=manifest['version']in(3,4,5)
    ref=manifest.get('frame_ref')
    if not isinstance(ref,dict) or ref.get('file')!='frames/'+filename(manifest,binary):
        raise ValueError('Invalid frame reference')
    count=ref.get('bytes')
    if type(count)is not int or not 0<count<=MAX_FRAME_BYTES:
        raise ValueError('Invalid frame length')
    if manifest['version']==5:
        from local_files import read_file_json
        from shared_channel import Reader
        if ref.get('storage')!='shared-v1':raise ValueError('Invalid shared body storage')
        with Reader(read_file_json(Path(folder)/'latest.json',65536))as reader:
            if ref.get('channel_nonce')!=reader.d['nonce']:raise ValueError('Shared body from another channel')
            packet,body=reader.read(body=True,generation=ref.get('commit_generation'))
            if packet.get('frame_ref')!=ref or any(packet.get(k)!=manifest.get(k)for k in('pid','session','sequence','scene_epoch')):raise ValueError('Shared body identity mismatch')
    else:
        target=(Path(folder)/ref['file']).resolve()
        if target.parent!=(Path(folder)/'frames').resolve():raise ValueError('Frame path escaped transport')
        with target.open('rb')as stream:body=stream.read(MAX_FRAME_BYTES+1)
    if len(body)!=count or hashlib.md5(body).hexdigest()!=ref.get('md5'):
        raise ValueError('Frame length/digest mismatch')
    return body

def resolve(manifest,folder):
    if manifest.get('version')not in(2,3,4,5):return manifest
    body=read_body(manifest,folder)
    if manifest['version']in(3,4,5):
        from live_binary import decode
        return decode(body,manifest)
    packet=json.loads(body)
    if packet.get('version')!=1:raise ValueError('Invalid referenced frame version')
    for key in ('protocol','session','sequence','sample_unix_ns','pid','scene_epoch','status','geometry_version'):
        if packet.get(key)!=manifest.get(key):raise ValueError('Frame identity mismatch')
    return packet
