"""Archive the renderer's own periodic PNGs; no screen or process access.

For disconnect evidence only: normal diagnostic cadence is one frame per 5 s.
Movement acceptance uses the separate higher-rate recording.
"""
import argparse,hashlib,io,json,time,uuid
from pathlib import Path
from PIL import Image

def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=900);a=p.parse_args()
    if not 1<=a.seconds<=1800:p.error('Duration must be 1..1800 seconds')
    root=Path(__file__).resolve().parents[2];folder=root/'local/recordings'/('diagnostics-'+uuid.uuid4().hex)
    folder.mkdir(parents=True);(root/'local/bridge/diagnostic-recording.txt').write_text(str(folder))
    source=root/'logs/ue-live.png';last=None;end=time.monotonic()+a.seconds;index=0
    with (folder/'frames.csv').open('w',encoding='utf8') as csv,(folder/'observations.jsonl').open('w',encoding='utf8') as evidence:
        csv.write('file,request_unix_ns,sequence,status\n')
        while time.monotonic()<end:
            try:
                stat=source.stat()
                if stat.st_mtime_ns!=last:
                    data=source.read_bytes();Image.open(io.BytesIO(data)).verify()
                    if source.stat().st_mtime_ns!=stat.st_mtime_ns:continue
                    name=f'frame-{index:06d}.png';(folder/name).write_bytes(data)
                    packet=json.loads((root/'local/bridge/latest.json').read_text())
                    csv.write(f"{name},{stat.st_mtime_ns},{packet.get('sequence',-1)},periodic engine backbuffer\n");csv.flush()
                    evidence.write(json.dumps({'file':name,'png_mtime_unix_ns':stat.st_mtime_ns,'observed_unix_ns':time.time_ns(),'packet_session':packet.get('session'),'packet_sequence':packet.get('sequence'),'packet_status':packet.get('status'),'sha256':hashlib.sha256(data).hexdigest(),'cadence_seconds':5})+'\n');evidence.flush()
                    last=stat.st_mtime_ns;index+=1
            except (OSError,ValueError):pass
            time.sleep(.2)
    print(str(folder),flush=True)

if __name__=='__main__':main()
