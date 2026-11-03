"""UBI2: immutable catalog-bound rows for the latency-sensitive pose reader.

Preparation computes surface identities; no poses, clocks or gameplay live in
this table. The renderer also checks the rows against the decoded full catalog.
"""
from collections import OrderedDict
import hashlib
import json
import math
import re
import struct

HEADER=struct.Struct('<4sHH16sII')
LIMIT=16*1024*1024
_identities=OrderedDict()

def resource_identity(definition):
    root=dict(definition)
    if isinstance(root.get('shading'),dict):root['shading']={k:v for k,v in root['shading'].items()if k not in('native_lights','native_sun')}
    key=json.dumps(root,sort_keys=True,separators=(',',':'),allow_nan=False,ensure_ascii=True)
    if key in _identities:_identities.move_to_end(key);return _identities[key]
    chunks=['URD1'];budget=[4096]
    def string(value):chunks.extend((str(len(value.encode('utf-16-le'))//2),':',value))
    def value(v,depth=0):
        budget[0]-=1
        if depth>16 or budget[0]<0:raise ValueError('Surface identity budget exceeded')
        if v is None:chunks.append('N')
        elif type(v)is bool:chunks.append('T'if v else'F')
        elif isinstance(v,(int,float)):
            n=float(v)
            if not math.isfinite(n):raise ValueError('Nonfinite surface metadata')
            chunks.extend(('D',struct.pack('>d',n if n else 0.).hex()))
        elif isinstance(v,str):chunks.append('S');string(v)
        elif isinstance(v,(list,tuple)):
            chunks.extend(('A',str(len(v)),':'))
            for item in v:value(item,depth+1)
        elif isinstance(v,dict):
            keys=sorted(v,key=lambda k:k.encode('utf-16-be'));chunks.extend(('O',str(len(keys)),':'))
            for k in keys:string(k);value(v[k],depth+1)
        else:raise ValueError('Unsupported surface metadata type')
    try:
        value(root);result=''.join(chunks)
        if len(result.encode('utf-16-le'))>32768:result=''
    except ValueError as error:
        if str(error)!='Surface identity budget exceeded':raise
        result=''
    _identities[key]=result
    while len(_identities)>8192:_identities.popitem(last=False)
    return result

def encode(catalog,catalog_md5):
    if not re.fullmatch('[0-9a-f]{32}',catalog_md5):raise ValueError('Invalid binding catalog digest')
    definitions=catalog['meshes'];bindings=catalog['bindings']
    if not 0<len(definitions)<=8192 or not 0<len(bindings)<=16384:raise ValueError('Invalid binding index counts')
    chunks=[HEADER.pack(b'UBI2',2,0,bytes.fromhex(catalog_md5),len(definitions),len(bindings))]
    def text(value,limit,empty=False):
        if not isinstance(value,str)or(not value and not empty)or '\0'in value or len(value.encode('utf-16-le'))//2>limit:raise ValueError('Invalid binding index string')
        raw=value.encode('utf-8');chunks.extend((struct.pack('<I',len(raw)),raw))
    assets=sorted(definitions);indices={name:i for i,name in enumerate(assets)}
    for name in assets:text(name,160);text(resource_identity(definitions[name]),16384,True)
    seen=set()
    for row in bindings:
        if row['id']in seen:raise ValueError('Duplicate binding identity')
        seen.add(row['id']);text(row['id'],64);chunks.append(struct.pack('<I',indices[row['asset']]));text(row.get('cell_key',''),64,True)
    result=b''.join(chunks)
    if len(result)>LIMIT:raise ValueError('Binding index exceeds budget')
    return result

def publish(folder,catalog_name,catalog,catalog_md5):
    if not re.fullmatch(r'catalog-[0-9a-f]{32}\.json',catalog_name):raise ValueError('Invalid binding catalog filename')
    from asset_files import publish as publish_asset
    name='bindings-'+catalog_name[8:-5]+'.bin';body=encode(catalog,catalog_md5)
    publish_asset(folder/name,body)
    return dict(file=name,bytes=len(body),md5=hashlib.md5(body).hexdigest())
