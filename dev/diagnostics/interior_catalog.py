"""Inspect native TES3 door links for test selection, not for UE level creation.

Geometry still comes solely from the running original scene graph. Generated
reference/door metadata stays under local/ and is excluded from distribution.
"""
import argparse
import json
from pathlib import Path
import struct
from live_probe import ROOT

def text(raw):return raw.split(b'\0',1)[0].decode('cp1252')

def records(path):
    with path.open('rb') as stream:
        while header:=stream.read(16):
            if len(header)!=16:raise ValueError('Truncated TES3 record header')
            kind,size,unknown,flags=struct.unpack('<4sIII',header)
            if size>32*1024*1024:raise ValueError('Unbounded TES3 record')
            payload=stream.read(size)
            if len(payload)!=size:raise ValueError('Truncated TES3 record')
            yield kind,payload

def fields(payload):
    offset=0
    while offset<len(payload):
        if offset+8>len(payload):raise ValueError('Truncated subrecord')
        kind,size=struct.unpack_from('<4sI',payload,offset);offset+=8
        if offset+size>len(payload):raise ValueError('Invalid subrecord size')
        yield kind,payload[offset:offset+size];offset+=size

def cells(path):
    result={}
    for kind,payload in records(path):
        if kind!=b'CELL':continue
        name='';flags=0;refs=[];current=None
        for key,raw in fields(payload):
            if key==b'FRMR':
                current={'ref':struct.unpack('<I',raw)[0]};refs.append(current)
            elif current is None:
                if key==b'NAME':name=text(raw)
                elif key==b'DATA':flags=struct.unpack_from('<I',raw)[0]
            elif key==b'NAME':current['base_id']=text(raw)
            elif key==b'DNAM':current['destination']=text(raw)
            elif key in (b'DATA',b'DODT') and len(raw)==24:
                current['position' if key==b'DATA' else 'arrival']=struct.unpack('<6f',raw)
            elif key==b'FLTV':current['lock']=struct.unpack('<I',raw)[0]
            elif key==b'TNAM':current['trap']=text(raw)
            elif key==b'DELE':current['deleted']=True
        if flags&1 and name:result[name]={'flags':flags,'references':len(refs),'doors':[r for r in refs if r.get('destination') and not r.get('deleted')]}
    return result

def connected_pairs(items):
    found=[]
    for name,cell in items.items():
        for door in cell['doors']:
            other=door['destination']
            if other not in items or name>=other or door.get('lock',0)>0 or door.get('trap'):continue
            for back in items[other]['doors']:
                if back['destination']==name and back.get('lock',0)<=0 and not back.get('trap'):
                    found.append({'cells':[name,other],'references':[cell['references'],items[other]['references']],
                                  'doors':[door,back]});break
    return sorted(found,key=lambda pair:sum(pair['references']))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--cell');parser.add_argument('--output',default='local/fixtures/interior-links.json');args=parser.parse_args()
    data=cells(ROOT/'local/Morrowind/Data Files/Morrowind.esm')
    pairs=connected_pairs(data)
    target=(ROOT/args.output).resolve()
    if not target.is_relative_to(ROOT/'local'):raise ValueError('Generated metadata must remain under local/')
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({'format':'uemw.native-door-links','version':1,'pairs':pairs},indent=2))
    print(json.dumps(data.get(args.cell) if args.cell else [{k:v for k,v in pair.items() if k!='doors'} for pair in pairs[:25]],indent=2))

if __name__=='__main__':main()
