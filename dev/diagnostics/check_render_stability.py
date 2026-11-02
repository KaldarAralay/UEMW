"""Short original-game weapon walk and water draw/reflection diagnostics."""
import hashlib
import json
import os
import struct
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
from live_probe import ROOT
from input_backend import require_foreground,pulse,move
from check_normal_play import console,wait,live,feet
from check_native_visuals import read_json,capture
from check_native_motion import witness,source_frame
from check_native_terrain import aim
from check_native_combat import submitted
from check_native_water import water_witness


def water_geometry(w):
    packet,_=source_frame(w);catalog=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
    rows=[];triangles={};duplicates=0
    for binding,state in zip(catalog['bindings'],packet['instance_states']):
        if binding.get('layer')!='water' or not state[0]:continue
        definition=catalog['meshes'][binding['asset']];payload=state[2]if len(state)>2 else None
        if not isinstance(payload,dict) or 'points'not in payload:continue
        points=np.asarray(payload['points']).reshape(-1,3)
        raw=(ROOT/'local/assets'/definition['file']).read_bytes();count,indices=struct.unpack_from('<2I',raw,4)
        stride=36 if raw[:4]==b'UEM3'else 24 if raw[:4]==b'UEM2'else 20
        faces=np.frombuffer(raw,dtype='<u2',count=indices,offset=12+count*stride).reshape(-1,3)
        for face in faces:
            key=tuple(sorted(tuple(np.round(p,3))for p in points[face]))
            if key in triangles:duplicates+=1
            else:triangles[key]=binding['id']
        rows.append(dict(id=binding['id'],asset=binding['asset'],texture=definition.get('source_texture'),alpha_mode=definition.get('alpha_mode'),vertices=count,triangles=len(faces),minimum=points.min(0).tolist(),maximum=points.max(0).tolist()))
    return dict(meshes=rows,duplicate_triangles=duplicates,unique_triangles=len(triangles))


def run(reader):
    if os.environ.get('UEMW_FOLIAGE_LABEL'):
        from check_foliage import run as foliage_run
        return foliage_run(reader)
    if os.environ.get('UEMW_CLEAN_TEXTURE_LABEL'):
        from check_clean_textures import run as clean_texture_run
        return clean_texture_run(reader)
    if os.environ.get('UEMW_INTERIOR_LABEL'):
        from check_interior_lighting import run as interior_run
        return interior_run(reader)
    if os.environ.get('UEMW_EFFECT_LABEL'):
        from check_effect_fidelity import run as effect_run
        return effect_run(reader)
    if os.environ.get('UEMW_CHARACTER_LABEL'):
        from check_character_fidelity import run as character_run
        return character_run(reader)
    if os.environ.get('UEMW_WATER_REFLECTION'):
        from check_water_reflection import run as water_reflection_run
        return water_reflection_run(reader)
    if os.environ.get('UEMW_WATER_ATMOSPHERE'):
        from check_water_atmosphere import run as water_atmosphere_run
        return water_atmosphere_run(reader)
    if os.environ.get('UEMW_LIGHTING_LABEL'):
        from check_lighting_weather import run as lighting_run
        return lighting_run(reader)
    if os.environ.get('UEMW_VISIBILITY_CHECK'):
        from check_native_visibility import run as visibility_run
        return visibility_run(reader)
    if os.environ.get('UEMW_STABILITY_MOVING')=='1':return moving_run(reader)
    require_foreground(reader);saves=ROOT/'local/Morrowind/Saves'
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(version=1,passed=False,recording=False,console_commands=[],started_unix_ns=time.time_ns(),walk=[],water=[])
    default_mode=witness([])['water_reflection_mode']
    report['default_water_reflection_mode']=default_mode
    try:
        console(reader,'set gamehour to 12',report)
        console(reader,'player->Position -12032 -73436 58 0',report)
        time.sleep(5);wait(lambda:live(reader),15);aim(reader,[-12032,-73100,60])
        first=submitted(reader)
        if not first.get('live')or not reader.camera_sample().get('first_person_items_active')or not any(r['layer']=='first-person'for r in first['rows']):raise RuntimeError('Drawn first-person item not ready')
        start=feet(reader)
        # Input owns its down/up pair; the observer only reads submitted state.
        with ThreadPoolExecutor(max_workers=1)as pool:
            walking=pool.submit(pulse,reader,'key',0x11,1.2)
            until=time.monotonic()+1.3
            while time.monotonic()<until:
                state=submitted(reader);w=witness([])
                if state.get('live'):
                    report['walk'].append(dict(sequence=w['sequence'],camera=w['camera_native_position'],pose_camera=w['first_person_pose_camera'],corrected_materials=w['first_person_corrected_materials'],rotation=w['first_person_correction_rotation'],translation=w['first_person_correction_translation'],exact_native_shapes=sum(r['layer']=='first-person'for r in state['rows'])))
            walking.result()
        report['walk_distance']=float(np.linalg.norm(np.asarray(feet(reader))-start))
        if report['walk_distance']<10 or len(report['walk'])<3 or not all(s['corrected_materials']>0 for s in report['walk']):raise RuntimeError('Native walk or first-person correction did not advance')
        report['weapon_image']=capture('stability-weapon')
        console(reader,'player->Position -9472 -72448 36 0',report)
        time.sleep(5);wait(lambda:live(reader),15);aim(reader,[-8448,-72960,0]);time.sleep(.5)
        renderer=witness([])['renderer_pid']
        report['water_source_before']=wait(lambda:water_witness(reader,False,renderer),12)
        report['water_geometry']=water_geometry(witness([]))
        for mode in (3,2):
            witness([],water_reflections=mode);time.sleep(.5);frames=[];images=[]
            for i in range(4):
                path=capture(f'stability-water-{mode}-{i}');frames.append(path)
                with Image.open(ROOT/path)as image:images.append(np.asarray(image.convert('RGB'),dtype=np.float32)[300:850,400:1100])
                time.sleep(.12)
            differences=[float(np.mean(np.abs(b-a)))for a,b in zip(images,images[1:])]
            flashes=[float(np.mean(np.max(np.abs(b-a),axis=2)>40))for a,b in zip(images,images[1:])]
            report['water'].append(dict(reflection_mode=mode,images=frames,mean_absolute_rgb_change=differences,large_pixel_change_fraction=flashes))
        report['water_source_after']=wait(lambda:water_witness(reader,False,renderer),12)
        if report['water_source_before']['texture_frames']==report['water_source_after']['texture_frames']:raise RuntimeError('Native water texture animation did not advance')
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        try:witness([],water_reflections=default_mode)
        except(OSError,ValueError,RuntimeError):pass
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
        report['passed']=report['passed']and report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns()
        (ROOT/'logs/render-stability.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def moving_run(reader):
    """Reproduce the reported case: moving at the shore with SSR already off."""
    require_foreground(reader);label=os.environ.get('UEMW_MOTION_LABEL','after')
    if label not in('before','after'):raise ValueError('Invalid motion comparison label')
    saves=ROOT/'local/Morrowind/Saves';hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in saves.glob('*.ess')}
    report=dict(version=1,passed=False,label=label,recording=False,console_commands=[],shots=[],started_unix_ns=time.time_ns())
    def shot(phase,index):
        w=witness([]);packet,_=source_frame(w);catalog=read_json(ROOT/'local/assets'/w['catalog'],16*1024*1024)
        path=capture(f'sky-water-{label}-{phase}-{index}')
        with Image.open(ROOT/path)as image:
            pixels=np.asarray(image.convert('RGB'),dtype=np.float32)[550:850,400:1100]
            white=float(np.mean(np.min(pixels,axis=2)>220));mean=float(np.mean(pixels))
        sky=None
        candidates=[(b,s)for b,s in zip(catalog['bindings'],packet['instance_states'])if b.get('layer')=='sky'and s[0]and catalog['meshes'][b['asset']].get('shading',{}).get('background')]
        candidates.sort(key=lambda v:'cloud'not in catalog['meshes'][v[0]['asset']].get('source_texture','').lower())
        for binding,state in candidates:
            definition=catalog['meshes'][binding['asset']];payload=state[2]if len(state)>2 else None
            if isinstance(payload,dict)and'points'in payload:points=np.asarray(payload['points']).reshape(-1,3)
            else:
                raw=(ROOT/'local/assets'/definition['file']).read_bytes();count=struct.unpack_from('<I',raw,4)[0]
                points=np.frombuffer(raw,dtype='<f4',count=count*3,offset=12).reshape(-1,3)
                matrix=np.asarray(state[1]);points=points@matrix[:9].reshape(3,3).T*matrix[12]+matrix[9:12]
            source=np.asarray(w['first_person_pose_camera']);current=np.asarray(w['camera_native_position'])
            offset=points-source;valid=np.linalg.norm(offset,axis=1)>100
            if not valid.any():continue
            point=points[np.flatnonzero(valid)[0]];expected=point-source
            anchor=np.asarray(w.get('background_pose_origin',w['camera_native_position']))if w.get('background_anchored_materials',0)>0 else current
            ray=point-anchor;cos=float(np.dot(expected,ray)/(np.linalg.norm(expected)*np.linalg.norm(ray)))
            old_ray=point-current;old_cos=float(np.dot(expected,old_ray)/(np.linalg.norm(expected)*np.linalg.norm(old_ray)))
            sky=dict(id=binding['id'],texture=definition.get('source_texture'),camera_separation=float(np.linalg.norm(source-current)),anchored_materials=w.get('background_anchored_materials',0),ray_error_degrees=float(np.degrees(np.arccos(np.clip(cos,-1,1)))),uncorrected_ray_error_degrees=float(np.degrees(np.arccos(np.clip(old_cos,-1,1)))))
            break
        report['shots'].append(dict(phase=phase,image=path,water_reflections=w['water_reflection_mode'],white_water_fraction=white,mean_water_rgb=mean,sky=sky,camera=w['camera_native_position'],native_weather=packet.get('environment',{}).get('weather'),native_sun=packet.get('environment',{}).get('sun_color')))
    try:
        report['native_checkpoint_time_retained']=os.environ.get('UEMW_MOTION_NATIVE_TIME')=='1'
        if not report['native_checkpoint_time_retained']:console(reader,'set gamehour to 12',report)
        console(reader,'player->Position -9472 -72448 36 0',report)
        time.sleep(6);wait(lambda:live(reader),20);aim(reader,[-8448,-72960,0]);time.sleep(.5)
        renderer=witness([])['renderer_pid'];report['water_before']=wait(lambda:water_witness(reader,False,renderer),12)
        shot('stationary',0);start=feet(reader)
        report['walk_path_distance']=0
        with ThreadPoolExecutor(max_workers=1)as pool:
            for i in range(6):
                before=feet(reader);walking=pool.submit(pulse,reader,'key',0x1e if i%2==0 else 0x20,.8)
                time.sleep(.15);shot('walking',i);walking.result()
                report['walk_path_distance']+=float(np.linalg.norm(np.asarray(feet(reader))-before))
        report['walk_distance']=float(np.linalg.norm(np.asarray(feet(reader))-start))
        for i in range(3):move(reader,28,0);time.sleep(.12);shot('turning',i)
        report['water_after']=wait(lambda:water_witness(reader,False,renderer),12)
        if report['walk_path_distance']<10 or not all(s['sky']for s in report['shots']):raise RuntimeError('Native walking or sky witness missing')
        if label=='after'and any(s['sky']['anchored_materials']<1 or s['sky']['ray_error_degrees']>.001 for s in report['shots']):raise RuntimeError('Sky origin correction did not preserve sampled native rays')
        if any(s['water_reflections']!=2 for s in report['shots']):raise RuntimeError('Moving comparison did not use stable reflection mode')
        report['passed']=True
    except BaseException as error:report['error']=str(error);raise
    finally:
        report['existing_saves_preserved']=all((saves/n).is_file()and hashlib.sha256((saves/n).read_bytes()).hexdigest()==h for n,h in hashes.items())
        report['passed']=report['passed']and report['existing_saves_preserved'];report['ended_unix_ns']=time.time_ns()
        (ROOT/f'logs/sky-water-{label}.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
