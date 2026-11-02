"""Bounded native-input acceptance actions for the disposable ship fixture.

These are test actions in Morrowind, never Unreal gameplay implementations.
The original game must already be focused. Every input uses the guarded backend.
"""
import argparse,json,math,time
from live_probe import Reader,ROOT
from input_backend import move,pulse,type_ascii

def summary(s):
    return {k:s[k] for k in ('pid','frame_ms','cell','menu','camera','focus')}|{'references':len(s['objects']),'actors':[o for o in s['objects']if o['type']=='NPC_']}

def look(r,yaw,pitch,settle=.25):
    # Idle vanity has a different heading from player-controlled mouse look.
    # Cancel that native mode before calculating relative test input.
    if hasattr(r,'player_render_state') and r.player_render_state(r.u32(0x7C67DC)).get('vanity'):
        move(r,1,0);time.sleep(.2)
    f=r.snapshot()['camera']['forward'];current=math.atan2(f[0],f[1]);elevation=math.asin(max(-1,min(1,f[2])))
    delta=(yaw-current+math.pi)%(2*math.pi)-math.pi
    move(r,round(delta/.002),round((elevation-pitch)/.002));time.sleep(settle)

def main():
    p=argparse.ArgumentParser();p.add_argument('--pid',required=True,type=int);p.add_argument('step',choices=['save','pickup','walk','npc','create','reload']);a=p.parse_args()
    r=Reader(a.pid);event={'step':a.step,'start_unix_ns':time.time_ns(),'passed':False}
    statefile=ROOT/'local/bridge/pickup-fixture.json'
    try:
        before=r.snapshot()
        if before.get('cell')!='Imperial Prison Ship' or before['menu']:raise RuntimeError('Expected the disposable ship fixture in gameplay')
        event['before']=summary(before)
        if a.step=='save':
            save=ROOT/'local/Morrowind/Saves/quiksave.ess';old=save.stat().st_mtime_ns if save.exists()else 0
            pulse(r,'key',0x3f,.12);deadline=time.monotonic()+12
            while time.monotonic()<deadline:
                if save.exists()and save.stat().st_mtime_ns>old and save.stat().st_size>1000 and not save.with_suffix('.tes').exists():break
                time.sleep(.2)
            else:raise RuntimeError('Original quicksave did not finish')
            event['save_bytes']=save.stat().st_size;event['save_mtime_ns']=save.stat().st_mtime_ns
        elif a.step=='pickup':
            focus=before['focus']
            if not focus or focus['name']!='Bucket':raise RuntimeError('Aim at the bucket solid rim first')
            item=next(o for o in before['objects']if o['id']==focus['id']);statefile.write_text(json.dumps(item))
            pulse(r,'key',0x39,.12);time.sleep(1.5)
            if any(o['id']==item['id']for o in r.snapshot()['objects']):raise RuntimeError('Original pickup did not remove the world reference')
            event['picked_reference']=item['id']
        elif a.step=='walk':
            look(r,math.radians(30),-.09);origin=r.snapshot()['camera']['position'];pulse(r,'key',0x11,.8);time.sleep(.25)
            event['distance']=math.dist(origin,r.snapshot()['camera']['position'])
            if event['distance']<10:raise RuntimeError('Movement was blocked; do not count this as walking')
        elif a.step=='npc':
            actor=next(o for o in before['objects']if o['base_id'].startswith('chargen boat guard 2'))
            command='"'+actor['base_id']+'"->AITravel 90 -90 -88'
            pulse(r,'key',0x29,.12);time.sleep(.2);type_ascii(r,command);pulse(r,'key',0x1c,.12);time.sleep(.2)
            position=r.snapshot()['camera']['position'];target=[(actor['position'][0]+90)/2,(actor['position'][1]-90)/2,actor['position'][2]+110]
            pulse(r,'key',0x29,.12);time.sleep(.25)
            d=[target[i]-position[i]for i in range(3)];look(r,math.atan2(d[0],d[1]),math.atan2(d[2],math.hypot(d[0],d[1])))
            event['command']=command;event['motion']=[]
            for _ in range(12):
                sample=r.snapshot();current=next(o for o in sample['objects']if o['id']==actor['id']);event['motion'].append({'unix_ns':time.time_ns(),'position':current['position']});time.sleep(.4)
            points=[x['position']for x in event['motion']]
            event['travel_distance']=max(math.dist(points[0],v)for v in points)
            if event['travel_distance']<20:raise RuntimeError('Original NPC did not move enough')
        elif a.step=='create':
            old={o['id']for o in before['objects']};pulse(r,'key',0x29,.12);time.sleep(.2)
            type_ascii(r,'PlaceAtPC "misc_com_bucket_01" 1 80 0');pulse(r,'key',0x1c,.12);time.sleep(.2);pulse(r,'key',0x29,.12);time.sleep(1.5)
            new=[o for o in r.snapshot()['objects']if o['id']not in old and o['base_id']=='misc_com_bucket_01']
            if len(new)!=1:raise RuntimeError('Expected one original-game-created bucket')
            event['created_reference']=new[0]
        else:
            original=json.loads(statefile.read_text());pulse(r,'key',0x43,.12);deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                try:
                    s=r.snapshot();b=[o for o in s.get('objects',[])if o['base_id']==original['base_id']and math.dist(o['position'],original['position'])<1]
                    if b and b[0]['node']!='0x0':break
                except(OSError,RuntimeError,ValueError):pass
                time.sleep(.2)
            else:raise RuntimeError('Original reload did not restore bucket')
            time.sleep(2);event['restored_reference']=b[0]['id']
        event['after']=summary(r.snapshot());event['passed']=True
    finally:
        event['end_unix_ns']=time.time_ns();r.close()
        with(ROOT/'logs/final-acceptance-steps.jsonl').open('a',encoding='utf8')as f:f.write(json.dumps(event,separators=(',',':'))+'\n')
        print(json.dumps(event,separators=(',',':')))

if __name__=='__main__':main()
