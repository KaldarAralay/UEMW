"""One disposable native NPC/camera probe for the packaged rendering client.

No surveys, save writes, quest automation or pixels. Fixture commands and mouse
input go to original Morrowind; its AI, collision and animation do the work.
CPU witness hashes are checked against the exact immutable source-frame ID.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import uuid
import numpy as np

from live_probe import Reader,ROOT
from input_backend import pulse,type_ascii
from native_ui import inspect_ui
from acceptance_step import look
from scene_reader import SceneReader
from local_files import read_json
from presentation import atomic_json
from frame_transport import filename,read_body
from live_binary import HEADER,decode,guid
from native_motion_fixture import native_grid_fixture


def wait_for(check,seconds,poll=.05):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        try:value=check()
        except BlockingIOError:value=None
        if value:return value
        time.sleep(poll)
    raise RuntimeError('Timed out waiting for '+check.__name__)


def witness(ids,*,poll=.05,visual_profile=None,water_fog_mode=None,terrain_blend=None,water_reflections=None,background_visible=None,ambient_probe=None,water_atmosphere=None,water_planar=None,reflection_capture=None,effect_quality=None,interior_lighting=None,foliage_quality=None,celestial_quality=None,outdoor_lighting=None,surface_reflections=None,targeted_render_updates=None,presentation_sync=None,presentation_latency=None,presentation_frame_limit=None,rain_interpolation=None,lighting_fidelity=None,stable_lighting=None,exterior_fidelity=None,exterior_fog=None,shadow_maps=None,record_seconds=None,distant_scenery=None,memory_trim=None,native_light_reference=None,native_irradiance=None,native_colour_ramp=None,native_material_match=None,native_actor_shadows=None,memory_trim_pages=None):
    token=str(uuid.uuid4());folder=ROOT/'local/bridge'
    request=dict(protocol='uemw.witness.request',version=1,request_id=token,unix_ns=time.time_ns(),ids=ids)
    if native_actor_shadows is not None:
        if type(native_actor_shadows)is not bool:raise ValueError('Invalid native actor-shadow comparison')
        request['native_actor_shadows']=native_actor_shadows
    if native_material_match is not None:
        if type(native_material_match)is not bool:raise ValueError('Invalid native material comparison')
        request['native_material_match']=native_material_match
    if native_colour_ramp is not None:
        if type(native_colour_ramp)is not bool:raise ValueError('Invalid native colour ramp diagnostic')
        request['native_colour_ramp']=native_colour_ramp
    for name,value,allowed in(('native_light_reference',native_light_reference,('off','pixel','vertex')),('native_irradiance',native_irradiance,('pixel','vertex'))):
        if value is not None:
            if value not in allowed:raise ValueError('Invalid native lighting comparison mode')
            request[name]=value
    if memory_trim is not None:
        if memory_trim is not True:raise ValueError('Expected an explicit diagnostic memory trim')
        request['memory_trim']=True
    if memory_trim_pages is not None:
        if memory_trim is not True or type(memory_trim_pages)is not int or not 0<=memory_trim_pages<=4096:raise ValueError('Expected an explicit paused diagnostic trim with 0..4096 owned pages')
        request['memory_trim_pages']=memory_trim_pages
    if presentation_frame_limit is not None:
        if type(presentation_frame_limit)is not int or (presentation_frame_limit!=0 and not 15<=presentation_frame_limit<=60) or (presentation_frame_limit==0 and presentation_sync is not True):raise ValueError('Expected 15..60 FPS, or 0 with explicit renderer VSync enabled')
        request['presentation_frame_limit']=presentation_frame_limit
    if presentation_latency is not None:
        if type(presentation_latency)is not int or not 1<=presentation_latency<=3:raise ValueError('Expected 1..3 renderer-only queued frames')
        request['presentation_latency']=presentation_latency
    if distant_scenery is not None:
        if type(distant_scenery)is not bool:raise ValueError('Invalid distant scenery diagnostic')
        request['distant_scenery']=distant_scenery
    if record_seconds is not None:
        if type(record_seconds)is not int or not 1<=record_seconds<=10:raise ValueError('Expected 1..10 diagnostic capture seconds')
        request['record_seconds']=record_seconds
    if shadow_maps is not None:
        if type(shadow_maps)is not bool:raise ValueError('Invalid shadow-map diagnostic')
        request['shadow_maps']=shadow_maps
    for name,value in (('targeted_render_updates',targeted_render_updates),('presentation_sync',presentation_sync),('rain_interpolation',rain_interpolation),('lighting_fidelity',lighting_fidelity),('stable_lighting',stable_lighting),('exterior_fidelity',exterior_fidelity),('exterior_fog',exterior_fog)):
        if value is not None:
            if type(value)is not bool:raise ValueError('Invalid renderer diagnostic')
            request[name]=value
    if surface_reflections is not None:
        if type(surface_reflections)is not bool:raise ValueError('Invalid surface reflection diagnostic')
        request['surface_reflections']=surface_reflections
    if outdoor_lighting is not None:
        if type(outdoor_lighting)is not bool:raise ValueError('Invalid outdoor lighting diagnostic')
        request['outdoor_lighting']=outdoor_lighting
    if celestial_quality is not None:
        if type(celestial_quality)is not bool:raise ValueError('Invalid celestial diagnostic')
        request['celestial_quality']=celestial_quality
    if foliage_quality is not None:
        if type(foliage_quality)is not bool:raise ValueError('Invalid foliage diagnostic')
        request['foliage_quality']=foliage_quality
    if interior_lighting is not None:
        if type(interior_lighting)is not bool:raise ValueError('Invalid interior lighting diagnostic')
        request['interior_lighting']=interior_lighting
    if effect_quality is not None:
        if type(effect_quality)is not bool:raise ValueError('Invalid effect quality diagnostic')
        request['effect_quality']=effect_quality
    if reflection_capture is not None:
        if type(reflection_capture)is not bool:raise ValueError('Invalid reflection capture diagnostic')
        request['reflection_capture']=reflection_capture
    if water_planar is not None:
        if type(water_planar)is not bool:raise ValueError('Invalid planar water diagnostic toggle')
        request['water_planar']=water_planar
    if water_atmosphere is not None:
        if type(water_atmosphere)is not bool:raise ValueError('Invalid water/atmosphere diagnostic toggle')
        request['water_atmosphere']=water_atmosphere
    if ambient_probe is not None:
        if type(ambient_probe)is not bool:raise ValueError('Invalid ambient diagnostic toggle')
        request['ambient_probe']=ambient_probe
    if background_visible is not None:
        if type(background_visible)is not bool:raise ValueError('Invalid sky visibility diagnostic')
        request['background_visible']=background_visible
    if visual_profile is not None:
        if visual_profile not in('reference','enhanced'):raise ValueError('Unknown diagnostic visual profile')
        request['visual_profile']=visual_profile
    if terrain_blend is not None:
        if type(terrain_blend)is not bool:raise ValueError('Invalid terrain diagnostic toggle')
        request['terrain_blend']=terrain_blend
    if water_reflections is not None:
        if type(water_reflections)is not int or water_reflections not in(2,3):raise ValueError('Invalid water reflection comparison mode')
        request['water_reflections']=water_reflections
    if water_fog_mode is not None:
        if water_fog_mode not in (0,1,2):raise ValueError('Invalid water fog diagnostic mode')
        request['water_fog_mode']=water_fog_mode
    atomic_json(folder/'witness-request.json',request)
    def response():
        try:w=read_json(folder/'witness.json',131072)
        except(OSError,ValueError):return None
        return w if w.get('request_id')==token and 0<=time.time_ns()-w.get('unix_ns',0)<500000000 else None
    return wait_for(response,2,poll)


def source_frame(w):
    ref=w['frame_ref'];expected='frames/'+filename(w,True)
    if ref['file']!=expected or not 0<ref['bytes']<=4*1024*1024:raise ValueError('Witness frame reference is invalid')
    manifest={**w,'version':5 if ref.get('storage')=='shared-v1'else 4}
    body=read_body(manifest,ROOT/'local/bridge')
    if len(body)!=ref['bytes']or hashlib.md5(body).hexdigest()!=ref['md5']:raise ValueError('Witness/source frame size or digest differs')
    magic,version,reserved,session,epoch,sequence,stamp,pid,geometry,count,padding=HEADER.unpack_from(body)
    if (session,epoch,sequence,pid)!=(guid(w['session']),guid(w['scene_epoch']),w['sequence'],w['pid']):raise ValueError('Witness/source frame identity differs')
    # UE seconds->nanoseconds conversion can round the JSON double by a few
    # hundred ns. Decode against the exact original binary header timestamp.
    if abs(stamp-w['sample_unix_ns'])>1024:raise ValueError('Witness/source capture timestamp differs')
    manifest=dict(session=w['session'],scene_epoch=w['scene_epoch'],sequence=sequence,sample_unix_ns=stamp,pid=pid,geometry_version=geometry)
    return decode(body,manifest),hashlib.md5(body).hexdigest()


def relative_rotations(palette):
    linear=np.asarray(palette,dtype='<f4').reshape(-1,3,4)[:,:,:3].astype(np.float64)
    return np.linalg.inv(linear[0])@linear[1:]


def planar_motion(points):
    return max(math.dist(points[0][:2],point[:2])for point in points)


def main():
    p=argparse.ArgumentParser();p.add_argument('--pid',required=True,type=int);p.add_argument('--output',required=True);a=p.parse_args()
    r=Reader(a.pid);benchmark=None;report=dict(passed=False,scope='Native Indrele AITravel and native mouse following; submitted CPU pose hashes, not GPU pixels or a long-session performance proof',started_unix_ns=time.time_ns(),save_writes=False,recording=False)
    try:
        def cancel_vanity():
            if r.player_render_state(r.u32(0x7c67dc)).get('vanity'):
                # Native mouse movement can orbit vanity without cancelling
                # it. A guarded, brief native forward input ends that mode.
                pulse(r,'key',0x11,.08);time.sleep(.15)
                wait_for(lambda:not r.player_render_state(r.u32(0x7c67dc)).get('vanity'),2)
                report['fixture_vanity_cancel_forward_pulses']=report.get('fixture_vanity_cancel_forward_pulses',0)+1
        cancel_vanity()
        state=r.snapshot()
        if state.get('cell')!='Seyda Neen' or state['menu']:raise RuntimeError('Expected the disposable Seyda Neen checkpoint in original gameplay')
        actor=next(o for o in state['objects']if o['type']=='NPC_'and o['base_id'].lower().startswith('indrele rathryon'))
        if '"'in actor['base_id']:raise ValueError('Unexpected native actor ID')
        prefix='"'+actor['base_id']+'"->'
        ref=int(r.player_render_state(r.u32(0x7c67dc))['reference'],16)
        fixture=native_grid_fixture(state['cell_grid'],struct.unpack('<3f',r.read(ref+0x38,12)))
        xyz=lambda values:' '.join(f'{v:.3f}'for v in values)
        commands=[prefix+'AIWander 0 0 0',prefix+'Position '+xyz(fixture['actor_position'])+' 180',
            'player->Position '+xyz(fixture['player_position'])+' 0',prefix+'AITravel '+xyz(fixture['destination'])]
        report['native_path_grid_fixture']=fixture
        pulse(r,'key',0x29,.12)
        for command in commands[:-1]:type_ascii(r,command);pulse(r,'key',0x1c,.12);time.sleep(.25)
        time.sleep(2);pulse(r,'key',0x29,.12)
        wait_for(lambda:not inspect_ui(r)['native_ui'],4)
        cancel_vanity()
        def position():
            ref=int(actor['id'],16)
            if r.read(ref+4,4)!=b'REFR' or r.u32(ref+0x4c)!=actor['target_id']:raise RuntimeError('Fixture actor identity changed')
            return list(struct.unpack('<3f',r.read(ref+0x38,12)))
        def aim():
            camera=r.camera_sample()['camera']['position'];point=position();d=[point[i]-camera[i]for i in range(3)];d[2]+=75
            look(r,math.atan2(d[0],d[1]),math.atan2(d[2],math.hypot(d[0],d[1])),settle=.03)
        aim();time.sleep(.25);focused=r.snapshot().get('focus')
        if not focused or focused['id']!=actor['id']:raise RuntimeError('Original activation ray did not confirm an unobstructed NPC view')
        actor['node']=hex(r.u32(int(actor['id'],16)+0x10))
        graph=SceneReader(r).collect(roots=[int(actor['node'],16)]);source_ids={s['id']for s in graph['shapes']if s['skin']!='0x0'and int(actor['node'],16)in s['parents']}
        def select_ids():
            s=read_json(ROOT/'local/bridge/latest.json')
            if s.get('status')!='live' or s.get('pid')!=a.pid:return None
            catalog=read_json(ROOT/'local/assets'/s['scene_catalog'],16*1024*1024)
            return [b['id']for b in catalog['bindings']if b.get('source_id')in source_ids][:16]
        ids=wait_for(select_ids,8)
        report.update(actor=actor,commands=commands,native_activation_focus=focused,requested_skin_ids=ids)
        pulse(r,'key',0x29,.12);type_ascii(r,commands[-1]);pulse(r,'key',0x1c,.12);pulse(r,'key',0x29,.12)
        wait_for(lambda:not inspect_ui(r)['native_ui'],4)
        started=time.time_ns();positions=[];samples=[];skipped=[];relative_bases={};relative_changes={}
        report.update(native_positions=positions,matched_samples=samples,skipped_samples=skipped,visibility_samples=[])
        benchfile=Path(a.output).with_name(Path(a.output).stem+'-benchmark.json')
        with Path(a.output).with_suffix('.benchmark.log').open('w')as log:
            benchmark=subprocess.Popen([sys.executable,str(ROOT/'dev/diagnostics/benchmark.py'),'--moving','--seconds','6','--warmup','0','--width','1920','--height','1080','--output',str(benchfile)],stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            until=time.monotonic()+5.5
            while time.monotonic()<until:
                aim();positions.append(dict(unix_ns=time.time_ns(),position=position()))
                try:
                    w=witness(ids)
                    if not w.get('live') or w.get('pid')!=a.pid:raise ValueError('UE witness is not live for this native process')
                    packet,digest=source_frame(w);catalog=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
                    index={b['id']:i for i,b in enumerate(catalog['bindings'])};matches=[]
                    report['visibility_samples'].append(dict(sequence=w['sequence'],partial=w.get('partial_geometry'),pending=w.get('pending_native_instances'),rows=[dict(id=row['id'],source_visible=packet['instance_states'][index[row['id']]][0]if row['id']in index else None,submitted_visible=row['submitted_visible'])for row in w['instances']]))
                    for row in w['instances']:
                        if not row['submitted_visible'] or row['id']not in index:continue
                        source=packet['instance_states'][index[row['id']]]
                        if not source[0]or len(source)<3 or not isinstance(source[2],dict)or'palette'not in source[2]:continue
                        palette=np.asarray(source[2]['palette'],dtype='<f4').reshape(-1,12)
                        expected=hashlib.md5(palette.tobytes()).hexdigest();rotation=hashlib.md5(palette[:,[0,1,2,4,5,6,8,9,10]].tobytes()).hexdigest()
                        if row.get('palette_md5','').lower()!=expected or row.get('rotation_md5','').lower()!=rotation:raise RuntimeError('UE submitted palette differs from its exact source frame')
                        # Remove the shape's common world rotation. A turning
                        # or translating rigid actor must not by itself count
                        # as articulated native bone animation.
                        relative=relative_rotations(palette)
                        key=(row['id'],row['asset'],len(palette))
                        baseline=relative_bases.setdefault(key,relative)
                        change=float(np.max(np.abs(relative-baseline)))if relative.size else 0.
                        relative_changes[row['id']]=max(relative_changes.get(row['id'],0),change)
                        matches.append(dict(id=row['id'],palette_md5=expected,rotation_md5=rotation,relative_bone_change=change))
                    if matches:samples.append(dict(unix_ns=time.time_ns(),sequence=w['sequence'],session=w['session'],scene_epoch=w['scene_epoch'],catalog=w['catalog'],body_md5=digest,partial=w.get('partial_geometry'),matches=matches))
                except(OSError,ValueError)as error:skipped.append(str(error))
            if benchmark.wait(10):raise RuntimeError('Native motion benchmark failed')
        distance=max(math.dist(positions[0]['position'],v['position'])for v in positions)
        planar=planar_motion([v['position']for v in positions])
        by_id={item['id']:{m['rotation_md5']for sample in samples for m in sample['matches']if m['id']==item['id']}for sample in samples for item in sample['matches']}
        changed=[key for key,values in by_id.items()if len(values)>1 and relative_changes.get(key,0)>.01]
        report.update(measurement_started_unix_ns=started,measurement_ended_unix_ns=time.time_ns(),native_positions=positions,native_motion_distance=distance,native_planar_motion_distance=planar,matched_samples=samples,skipped_samples=skipped,changed_rotation_ids=changed,relative_bone_changes=relative_changes,benchmark=str(benchfile))
        motion_ok=planar>=20 and len(samples)>=2 and bool(changed)
        report['native_motion_acceptance_passed']=motion_ok
        if os.environ.get('UEMW_VISIBILITY_CHECK')=='after':
            report['scope']='Targeted NPC render-parent visibility regression, exact submitted bone hashes; distance is reported separately and does not establish travel acceptance'
            visibility=report['visibility_samples']
            if len(visibility)<20 or not changed or any(not any(row['source_visible'] and row['submitted_visible']for row in s['rows'])for s in visibility):raise RuntimeError('On-screen NPC disappeared during the visibility regression')
        elif not motion_ok:raise RuntimeError('NPC planar/articulated motion did not reach matching submitted UE palettes')
        b=read_json(benchfile);b['scope']='Six-second observation during original NPC AITravel and native mouse following; no walking, save writes or pixel recording; loop ticks are not scanout FPS';benchfile.write_text(json.dumps(b,indent=2))
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        if benchmark and benchmark.poll()is None:benchmark.terminate();benchmark.wait(3)
        r.close();report['ended_unix_ns']=time.time_ns();Path(a.output).write_text(json.dumps(report,indent=2));print(json.dumps({k:report.get(k)for k in ('passed','error','native_motion_distance','changed_rotation_ids')}))


if __name__=='__main__':main()
