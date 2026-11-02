"""Fault-only v2 conformance check. Stop the real producer before running.

Every injected envelope is deliberately invalid. No synthetic scene is ever
presented as successful gameplay; the original game remains untouched.
"""
import copy
import argparse
import hashlib
import json
import re
import uuid
import time
from live_probe import ROOT,Reader,snapshot_lease
from geometry_stream import write_latest
from frame_transport import resolve,filename,MAX_FRAME_BYTES


@snapshot_lease()
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prefix',default='exterior');args=parser.parse_args()
    if not re.fullmatch('[a-z0-9-]{1,40}',args.prefix):parser.error('Use a short lowercase log prefix')
    reader=Reader(int((ROOT/'local/bridge/game.pid').read_text()))
    original=json.loads((ROOT/'local/bridge/latest.json').read_text())
    promoted=None
    if original.get('version')==1 and original.get('status')=='live' and original.get('geometry_version')in(1,2,3,4):
        # Wrap the exact genuine inline sample in memory for fault cases only.
        # This valid manifest is NEVER published as successful gameplay.
        raw=json.dumps(original,separators=(',',':'),allow_nan=False).encode()
        if len(raw)>MAX_FRAME_BYTES:raise ValueError('Genuine inline frame exceeds bound')
        promoted=ROOT/'local/bridge/frames'/filename(original)
        if promoted.exists():raise RuntimeError('Unexpected existing fault-test body')
        promoted.write_bytes(raw)
        original={k:v for k,v in original.items()if k not in('instances','instance_states','objects')}
        original.update(version=2,frame_ref=dict(file='frames/'+promoted.name,bytes=len(raw),md5=hashlib.md5(raw).hexdigest()))
    if original.get('version')!=2:raise RuntimeError('A genuine geometry sample is required before fault checks')
    resolve(original,ROOT/'local/bridge') # Validate bounded generated paths before fault-only file edits.
    results=[];log=ROOT/'logs/ue-runtime.log'
    body_path=ROOT/'local/bridge'/original['frame_ref']['file'];original_body=body_path.read_bytes()
    invalid_catalog=None;fault_bodies=[]
    cases=['missing_body','bad_digest','mixed_identity','escaped_path','oversize_ref','visible_missing_transform','unsupported_geometry','unsupported_cell_owner']
    genuine=json.loads(original_body)
    if genuine.get('geometry_version')==4 and any(len(row)==4 for row in genuine.get('instance_states',[])):
        cases+=['particle_color_range','particle_color_count']
    try:
        if True: # The decorator holds the single-writer lease for the whole check.
            for name in cases:
                packet=copy.deepcopy(original)
                body_path.write_bytes(original_body)
                if name=='missing_body':
                    packet['sequence']+=999999
                    packet['frame_ref']['file']='frames/'+filename(packet)
                elif name=='bad_digest':packet['frame_ref']['md5']='0'*32
                elif name=='mixed_identity':packet['pid']+=1
                elif name=='escaped_path':packet['frame_ref']['file']='../latest.json'
                elif name=='oversize_ref':packet['frame_ref']['bytes']=4*1024*1024+1
                else:
                    body=json.loads(original_body)
                    compact=body.get('geometry_version')in(3,4)
                    if name=='visible_missing_transform':
                        if compact:next(r for r in body['instance_states']if r[0]).pop(1)
                        else:next(i for i in body['instances']if i['visible']).pop('transform')
                    elif name=='unsupported_geometry':body['geometry_version']=packet['geometry_version']=99
                    elif name.startswith('particle_color_'):
                        row=next(row for row in body['instance_states']if len(row)==4)
                        if name=='particle_color_range':row[3][0]=2
                        else:row[3].pop()
                    elif compact:
                        packet['sequence']+=1;body['sequence']=packet['sequence']
                        catalog=json.loads((ROOT/'local/assets'/body['scene_catalog']).read_text())
                        catalog['bindings'][0]['cell_key']='exterior:0,0'
                        invalid_catalog=ROOT/'local/assets'/('catalog-'+uuid.uuid4().hex+'.json')
                        invalid_catalog.write_text(json.dumps(catalog,separators=(',',':')))
                        body['scene_catalog']=packet['scene_catalog']=invalid_catalog.name
                    else:next(i for i in body['instances']if i['visible'])['cell_key']='exterior:0,0'
                    raw=json.dumps(body,separators=(',',':')).encode()
                    target=body_path
                    if compact and name=='unsupported_cell_owner':
                        target=body_path.parent/filename(packet);fault_bodies.append(target)
                        packet['frame_ref']['file']='frames/'+target.name
                    target.write_bytes(raw)
                    packet['frame_ref'].update(bytes=len(raw),md5=hashlib.md5(raw).hexdigest())
                offset=log.stat().st_size;started=time.monotonic()
                while time.monotonic()-started<1.4:
                    if name=='unsupported_cell_owner' and packet.get('geometry_version')in(3,4):
                        # Keep this deliberately INVALID binding case fresh so
                        # the stale-frame guard cannot mask catalog validation.
                        body['sample_unix_ns']=packet['sample_unix_ns']=time.time_ns()
                        raw=json.dumps(body,separators=(',',':')).encode();target.write_bytes(raw)
                        packet['frame_ref'].update(bytes=len(raw),md5=hashlib.md5(raw).hexdigest())
                    write_latest(packet);time.sleep(.05)
                with log.open('rb')as stream:stream.seek(offset);tail=stream.read().decode(errors='replace')
                expected='INVALID OR UNAVAILABLE ORIGINAL GEOMETRY' if name=='unsupported_cell_owner' and packet.get('geometry_version')in(3,4) else 'INVALID'
                matches=[line for line in tail.splitlines() if 'UEMW health status='+expected in line and 'visible=0 ' in line]
                entry={'case':name,'passed':bool(matches),'evidence':matches[-1:]}
                results.append(entry);print(json.dumps(entry),flush=True)
        report={'passed':all(r['passed']for r in results),'cases':results,'original_alive':True,'recording':False,
                'scope':'Only malformed manifests; no valid substitute scene or gameplay inputs'}
        reader.check_alive();(ROOT/'logs'/(args.prefix+'-v2-renderer-check.json')).write_text(json.dumps(report,indent=2))
        if not report['passed']:raise SystemExit(1)
    finally:
        body_path.write_bytes(original_body)
        if invalid_catalog:invalid_catalog.unlink(missing_ok=True)
        if promoted:promoted.unlink(missing_ok=True)
        for path in fault_bodies:path.unlink(missing_ok=True)
        reader.close()

if __name__=='__main__':main()
