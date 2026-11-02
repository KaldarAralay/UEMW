"""Opt-in native-game UI test accessibility when window capture is unavailable.

Read-only TES3::UI::Element labels/bounds, from pinned MWSE headers. Actions
are guarded ordinary mouse input, never native calls or memory writes. This
module is not imported by the renderer, producer or normal launcher.
"""
import argparse
import json
import struct
import time
from live_probe import Reader
from input_backend import point,pulse


def tree(reader,menu=None):
    root=reader.u32(0x7d1c28);world=reader.u32(0x7c67dc)
    width,height=struct.unpack('<2I',reader.read(world+0x78,8))
    if not root or not 320<=width<=8192 or not 200<=height<=8192:raise RuntimeError('Native UI not ready')
    root_header=reader.read(root+0x1c,12)
    pending=[(root,0,'')];seen=set();rows=[]
    while pending:
        ptr,depth,owner=pending.pop()
        if not ptr:continue
        if ptr in seen or depth>64 or len(seen)>=4096:raise ValueError('Invalid or unbounded native UI tree')
        seen.add(ptr);raw=reader.read(ptr,0x184)
        if raw[0x75]>1 or raw[0x76]>1:raise ValueError('Invalid native UI visibility')
        if not raw[0x75]and ptr!=root:continue
        name=reader.string(struct.unpack_from('<I',raw,8)[0],96)
        if depth==1:
            owner=name
            if menu and owner!=menu:continue
        label=reader.string(struct.unpack_from('<I',raw,0x168)[0],2048)
        content=reader.string(struct.unpack_from('<I',raw,0x178)[0],512)
        x,y,w,h=struct.unpack_from('<4i',raw,0xe4)
        rows.append(dict(id=hex(ptr),menu=owner,name=name,text=label,content=content,
                         rect=[x+width//2,height//2-y,w,h],depth=depth))
        first,end,cap=struct.unpack_from('<3I',raw,0x1c)
        if not first<=end<=cap or (end-first)%4 or end-first>4096*4:raise ValueError('Invalid native UI child vector')
        if end>first:
            children=struct.unpack('<'+'I'*((end-first)//4),reader.read(first,end-first))
            pending.extend((p,depth+1,owner)for p in reversed(children)if p)
    if reader.u32(0x7d1c28)!=root or reader.read(root+0x1c,12)!=root_header:raise RuntimeError('Native UI changed during inspection')
    return rows


def choose(reader,*,menu=None,text=None,name=None,element=None):
    rows=tree(reader,menu)
    found=[r for r in rows if(text is None or r['text']==text)and(name is None or r['name']==name)and(element is None or r['id']==element)]
    if len(found)!=1:raise RuntimeError(f'Expected one native UI element; found {len(found)}')
    return found[0]


def act(reader,*,click=False,**selector):
    # Startup can expose menu elements before their cached screen coordinates
    # have been laid out. Wait for a real native frame, then select afresh.
    world=reader.u32(0x7c67dc);stamp=reader.u32(world+0x24);deadline=time.monotonic()+1
    while reader.u32(world+0x24)==stamp:
        if time.monotonic()>=deadline:raise RuntimeError('Native UI frame is not advancing; input refused')
        time.sleep(.01)
    item=choose(reader,**selector);x,y,w,h=item['rect']
    if not 1<=w<=8192 or not 1<=h<=8192:raise ValueError('Native UI target has no valid bounds')
    # Re-observe the exact native element after computing the target. Never
    # retain a coordinate selected from a previous menu/layout.
    current=choose(reader,element=item['id'],menu=item['menu'])
    if current!=item:raise RuntimeError('Native UI target changed before input')
    point(reader,round(x+w/2),round(y+h/2));time.sleep(.12)
    if click:pulse(reader,'left',0,.15)
    return item


def main():
    p=argparse.ArgumentParser();p.add_argument('--pid',type=int,required=True);p.add_argument('--menu');p.add_argument('--text');p.add_argument('--name');p.add_argument('--id',dest='element');p.add_argument('--click',action='store_true');p.add_argument('--hover',action='store_true');a=p.parse_args()
    if(a.click or a.hover)and not any((a.text,a.name,a.element)):p.error('Actions require one explicit native selector')
    r=Reader(a.pid)
    try:
        if a.click or a.hover:result=act(r,menu=a.menu,text=a.text,name=a.name,element=a.element,click=a.click)
        else:result=[v for v in tree(r,a.menu)if v['text']or v['name']or v['content']]
        print(json.dumps(result,indent=2))
    finally:r.close()


if __name__=='__main__':main()
