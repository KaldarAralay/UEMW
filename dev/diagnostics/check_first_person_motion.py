"""Bounded native first-person regression: exact near frames and UE placement.

Requires the private original focused, a disposable checkpoint, first person,
and a safe walking area. No video, saves, attacks or game-memory writes.
"""
import argparse,bisect,hashlib,json,math,threading,time
import numpy as np
from live_probe import Reader,ROOT
from input_backend import pulse,require_foreground
from check_normal_play import wait,feet,live
from check_native_motion import witness
from check_native_visuals import read_json,capture
from local_files import read_json as quick_json


def projection(point,camera):
    f=np.asarray(camera['forward'],dtype=float);f/=np.linalg.norm(f)
    u=np.asarray(camera['up'],dtype=float);r=np.cross(f,u);r/=np.linalg.norm(r);u=np.cross(r,f)
    return np.asarray([r,u,f])@(np.asarray(point)-np.asarray(camera['position']))


def run(reader,seconds=12,screenshots=False,draw_cycles=4):
    require_foreground(reader);world=reader.u32(0x7c67dc)
    report=dict(version=2,passed=False,recording=False,save_writes=False,draws=[],walk=[],shots=[],near_frames=[],errors=[],scope='Live native near-pass payloads versus UE submitted palette/transform hashes and actual rigid projected placement; not a displayed-FPS measurement.')
    stop=threading.Event();frames={};packet_rows=[]
    def collect():
        last=None
        while not stop.is_set():
            try:
                p=quick_json(ROOT/'local/bridge/camera.json',256*1024)
                if p.get('view')and p.get('sequence')!=last:
                    last=p['sequence'];v=p['view'];frames[int(v['sample_unix_ns'])]=v
                    packet_rows.append(dict(sequence=p['sequence'],stamp=p['sample_unix_ns'],view_stamp=v['sample_unix_ns'],view_read_ms=v['read_ms'],session=p['session'],epoch=p['scene_epoch']))
            except(OSError,ValueError,KeyError):pass
            time.sleep(.003)
    collector=threading.Thread(target=collect);collector.start()
    try:
        report['initial_camera_mode']=reader.player_render_state(world)
        if reader.player_render_state(world).get('vanity'):
            pulse(reader,'key',0x11,.08);wait(lambda:not reader.player_render_state(world).get('vanity'),2)
        if reader.player_render_state(world).get('third_person'):pulse(reader,'key',0x0f,.12)
        wait(lambda:reader.camera_sample()['first_person_active'],3)
        if not reader.player_state(world)['weapon_ready']:pulse(reader,'key',0x21,.12)
        def ready():
            p=quick_json(ROOT/'local/bridge/camera.json',256*1024);v=p.get('view')
            return v if v and len(v['states'])>=18 and all(s['visible']for s in v['states']) else None
        v=wait(ready,8);ids=[s['id']for s in v['states']];time.sleep(.3)
        w=wait(lambda:live(reader),8)
        if not w.get('first_person_lane_updates'):raise RuntimeError('Renderer is not consuming independent near poses')
        report['feet_before']=feet(reader);source=[]
        def walk():
            try:
                for i in range(max(1,int(seconds/1.4))):
                    pulse(reader,'key',0x1f,.7);pulse(reader,'key',0x11,.7)
            except BaseException as error:report['errors'].append(str(error))
        mover=threading.Thread(target=walk);mover.start();began=time.perf_counter();shot_at=-3
        try:
            while mover.is_alive():
                w=witness(ids,poll=.01);s=read_json(ROOT/'local/bridge/latest.json');stamp=int(w['first_person_pose_unix_ns'])
                keys=sorted(frames);index=bisect.bisect_left(keys,stamp);options=keys[max(0,index-1):index+2]
                if not options:raise RuntimeError('No retained independent near source frames')
                key=min(options,key=lambda x:abs(x-stamp))
                if abs(key-stamp)>1024:raise RuntimeError('UE near timestamp did not match a retained native payload')
                near=frames[key];expected={r['id']:r for r in near['states']};checks=[]
                target=dict(position=w['camera_native_position'],forward=w['camera_native_forward'],up=w['camera_native_up'])
                for row in w['instances']:
                    native=expected[row['id']]
                    if not native['visible']or not row['submitted_visible']:raise RuntimeError('A native weapon/hand section disappeared during walking: '+row['id'])
                    field='palette'if 'palette'in native else'transform';digest=hashlib.md5(np.asarray(native[field],dtype='<f4').tobytes()).hexdigest()
                    if row.get(field+'_md5','').lower()!=digest:raise RuntimeError('UE pose differs from its exact independent native payload')
                    error=None
                    if field=='transform':
                        expected_ray=projection(native['transform'][9:12],near['camera'])*w['first_person_depth_scale']
                        actual_ray=projection(row['first_person_visual_position'],target);error=float(np.linalg.norm(expected_ray-actual_ray))
                        if error>.002:raise RuntimeError('Weapon camera-relative placement diverged: '+str(error))
                    checks.append(dict(id=row['id'],kind=field,md5=digest,projection_error=error))
                if len(checks)!=len(ids):raise RuntimeError('Missing near-pass witness entries')
                report['walk'].append(dict(ms=(time.perf_counter()-began)*1000,world_sequence=s['sequence'],world_read_ms=s['read_ms'],preparation=s['preparation'],near_stamp=key,near_read_ms=near['read_ms'],near_age_ms=(w['unix_ns']-key)/1e6,lane_updates=w['first_person_lane_updates'],matches=checks,complete=not w.get('partial_geometry')))
                if screenshots and len(report['shots'])<3 and time.perf_counter()-began-shot_at>2:
                    shot_at=time.perf_counter()-began;report['shots'].append(capture('weapon57-final-moving-'+str(len(report['shots']))))
                time.sleep(.02)
        finally:mover.join()
        report['feet_after']=feet(reader)
        expected_count=len(ids)
        for _ in range(draw_cycles):
            if reader.player_state(world)['weapon_ready']:pulse(reader,'key',0x21,.12)
            wait(lambda:not reader.player_state(world)['weapon_ready'],3);time.sleep(.8)
            start=time.perf_counter();pulse(reader,'key',0x21,.12)
            def drawn():
                p=quick_json(ROOT/'local/bridge/camera.json',256*1024);v=p.get('view')
                if not v or len(v['states'])<expected_count or not all(s['visible']for s in v['states']):return None
                ids=[s['id']for s in v['states']];w=witness(ids,poll=.01)
                return w if w['first_person_lane_updates']and len(w['instances'])==len(ids)and all(s['submitted_visible']for s in w['instances'])else None
            w=wait(drawn,5);report['draws'].append(dict(ue_ms=(time.perf_counter()-start)*1000,near_updates=w['first_person_lane_updates'],pose_stamp=w['first_person_pose_unix_ns'],sections=len(w['instances']),post_draw=[]))
            new_ids=[s['id']for s in w['instances']]
            def post_walk():
                try:pulse(reader,'key',0x1f,.7);pulse(reader,'key',0x11,.7)
                except BaseException as error:report['errors'].append(str(error))
            mover=threading.Thread(target=post_walk);mover.start()
            try:
                while mover.is_alive():
                    w=witness(new_ids,poll=.01)
                    if len(w['instances'])!=expected_count or not all(s['submitted_visible']for s in w['instances']):raise RuntimeError('Weapon disappeared during post-draw walking/catalog reconciliation')
                    report['draws'][-1]['post_draw'].append(dict(stamp=w['first_person_pose_unix_ns'],sections=len(w['instances']),catalog=w['render_catalog']))
                    time.sleep(.02)
            finally:mover.join()
        report.update(passed=not report['errors'],near_frames=list(frames.values()),camera_samples=packet_rows)
        return report
    except BaseException as error:report['errors'].append(str(error));raise
    finally:
        stop.set();collector.join();report['near_frames']=list(frames.values());report['camera_samples']=packet_rows
        (ROOT/'logs/weapon57-live-regression.json').write_text(json.dumps(report,indent=2),encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--seconds',type=float,default=12);p.add_argument('--screenshots',action='store_true');p.add_argument('--draw-cycles',type=int,default=4);a=p.parse_args()
    if not 3<=a.seconds<=45:p.error('Use a bounded 3..45 second movement probe')
    if not 2<=a.draw_cycles<=8:p.error('Use 2..8 native draw cycles')
    r=Reader(a.pid)
    try:
        result=run(r,a.seconds,a.screenshots,a.draw_cycles);walk=result['walk'];print(json.dumps(dict(passed=result['passed'],witnesses=len(walk),draw_ms=[x['ue_ms']for x in result['draws']],world_read_ms=np.percentile([x['world_read_ms']for x in walk],[50,95,100]).tolist(),near_read_ms=np.percentile([x['near_read_ms']for x in walk],[50,95,100]).tolist(),near_age_ms=np.percentile([x['near_age_ms']for x in walk],[50,95,100]).tolist(),near_updates=walk[-1]['lane_updates']-walk[0]['lane_updates']),indent=2))
    finally:r.close()
