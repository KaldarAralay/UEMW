"""Offline, local 2x texture bake; never imported by the live bridge.

SRVGGNetCompact is adapted from Real-ESRGAN, copyright (c) 2021 Xintao Wang,
BSD-3-Clause. Full notice and source revision: docs/third-party-licenses/Real-ESRGAN.txt.
Weights and all Bethesda-derived output stay in ignored local/ directories.
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import time
import urllib.request
import numpy as np
from PIL import Image, ImageFilter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'bridge'))
from game_assets import Assets

MODEL_URL='https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesr-general-x4v3.pth'
MODEL_SHA='8dc7edb9ac80ccdc30c3a5dca6616509367f05fbc184ad95b731f05bece96292'
BUDGET=192*1024*1024
BAKE_VERSION=2

def category(name):
    n=name.replace('\\','/').rsplit('/',1)[-1].lower()
    if any(t in n for t in ('metal','hinge','keyhole')):return None
    if n.startswith(('tx_b_','tx_a_','tx_w_','tx_c_','tx_creature','tx_sky','tx_water')):return None
    if n.startswith(('tx_sign','tx_flag_')) or '_sign_'in n:return None
    if any(t in n for t in ('banner','tapestry','carpet','plant','lava','fire','glow','flame','smoke','spark','ripple')):return None
    if any(t in n for t in ('leaves','leaf','flower','fern','grassblade','grass_blade','heather','goldkanet','comberry','bittergreen','anther','vine','hackle','cork_bulb','podplant')):return None
    if any(t in n for t in ('wood','plank','bark','thatch','crate','barrel','treering','door')):return 'wood'
    if any(t in n for t in ('stone','brick','rock','stucco','foundation','plaster','wall','ceiling','floor','roof','tile','cavern','cave','hlaalu','redoran','velothi','dwrv')):return 'stone'
    if any(t in n for t in ('dirt','sand','grass','moss','muck','mud','road','undergrowth')):return 'ground'
    return None

def mip_bytes(w,h):
    total=0
    while True:
        total+=w*h*4
        if w==h==1:return total
        w=max(1,w//2);h=max(1,h//2)

def planned_bytes(w,h):
    dw,dh=w,h
    while max(dw,dh)>512:dw=max(1,dw//2);dh=max(1,dh//2)
    return mip_bytes(w,h)+mip_bytes(dw,dh)

def model(path):
    import torch
    from torch import nn
    if hashlib.sha256(path.read_bytes()).hexdigest()!=MODEL_SHA:raise RuntimeError('Pinned model hash mismatch')
    class Compact(nn.Module):
        def __init__(self):
            super().__init__();self.body=nn.ModuleList([nn.Conv2d(3,64,3,1,1),nn.PReLU(64)])
            for _ in range(32):self.body.extend([nn.Conv2d(64,64,3,1,1),nn.PReLU(64)])
            self.body.append(nn.Conv2d(64,48,3,1,1));self.upsampler=nn.PixelShuffle(4)
        def forward(self,x):
            y=x
            for layer in self.body:y=layer(y)
            return self.upsampler(y)+torch.nn.functional.interpolate(x,scale_factor=4,mode='nearest')
    net=Compact();weights=torch.load(path,map_location='cpu',weights_only=True)
    net.load_state_dict(weights.get('params_ema',weights.get('params',weights)),strict=True)
    device='cuda' if torch.cuda.is_available() else 'cpu'
    if device=='cpu':raise RuntimeError('GPU PyTorch is required for this optional offline bake; original textures remain usable')
    net=net.eval().to(device).half();torch.set_num_threads(2)
    return net,torch

def upscale(original,net,torch,character=None,environment=None):
    # Wrap context prevents the network from introducing clamp-padding seams.
    # It does not repair seams already present in the original artwork.
    source=np.asarray(original.convert('RGB'));pad=40 # 34 convolutions plus resampling support
    padded=np.pad(source,((pad,pad),(pad,pad),(0,0)),mode='reflect'if character or environment in ('foliage','moon')else'wrap')
    tensor=torch.from_numpy(padded.copy()).permute(2,0,1).unsqueeze(0).to('cuda',dtype=torch.float16)/255
    with torch.inference_mode():output=net(tensor).float().clamp(0,1)[0].permute(1,2,0).cpu().numpy()
    if not np.isfinite(output).all():raise RuntimeError('Nonfinite inference output')
    h,w=source.shape[:2];full_size=((w+2*pad)*2,(h+2*pad)*2);region=(pad*2,pad*2,(pad+w)*2,(pad+h)*2)
    result=Image.fromarray(np.uint8(np.round(output*255))).resize(full_size,Image.Resampling.LANCZOS).crop(region)
    base=Image.fromarray(padded).resize(full_size,Image.Resampling.LANCZOS).crop(region)
    # Anchor low-frequency colour; retain learned high-frequency interpretation.
    def lowpass(image):
        a=np.pad(np.asarray(image),((12,12),(12,12),(0,0)),mode='reflect'if character or environment in ('foliage','moon')else'wrap')
        return np.asarray(Image.fromarray(a).filter(ImageFilter.GaussianBlur(2)).crop((12,12,image.width+12,image.height+12)),dtype=np.float32)
    low_base=lowpass(base);low_result=lowpass(result)
    corrected=np.asarray(result,dtype=np.float32)+low_base-low_result
    strength=.40 if character=='skin'else .65 if character else {'stone':.55,'wood':.70,'ground':.50,'foliage':.55,'moon':.45}.get(environment,.85)
    enhanced=np.clip(strength*corrected+(1-strength)*np.asarray(base),0,255).round().astype(np.uint8)
    if character:
        # Anchor atlas borders to the source; do not infer a different limb seam.
        b=np.asarray(base);enhanced[:2]=b[:2];enhanced[-2:]=b[-2:];enhanced[:,:2]=b[:,:2];enhanced[:,-2:]=b[:,-2:]
    result=Image.fromarray(enhanced).convert('RGBA')
    if character:result.putalpha(original.getchannel('A').resize(result.size,Image.Resampling.NEAREST))
    return result

def character_category(name):
    n=name.replace('\\','/').rsplit('/',1)[-1].lower()
    if n.startswith('tx_b_'):return 'hair'if 'hair'in n or'beard'in n else'skin'
    if n.startswith('tx_c_'):return 'cloth'
    if n.startswith(('tx_a_','tx_w_')):return 'equipment'
    return None

def main():
    p=argparse.ArgumentParser();p.add_argument('--download-model',action='store_true');p.add_argument('--limit',type=int,default=0);p.add_argument('--contains',default='');mode=p.add_mutually_exclusive_group();mode.add_argument('--characters',action='store_true');mode.add_argument('--environment-full',action='store_true');args=p.parse_args()
    checkpoint=ROOT/'local/models/realesr-general-x4v3.pth'
    if not checkpoint.exists():
        if not args.download_model:raise RuntimeError('Missing optional model. Re-run with --download-model; no packages are installed')
        checkpoint.parent.mkdir(exist_ok=True)
        with urllib.request.urlopen(MODEL_URL,timeout=30)as response:payload=response.read(16*1024*1024+1)
        if len(payload)>16*1024*1024 or hashlib.sha256(payload).hexdigest()!=MODEL_SHA:raise RuntimeError('Official model download did not match pinned hash')
        checkpoint.write_bytes(payload)
    import psutil
    running=[p.info['name']for p in psutil.process_iter(['name','exe'])if p.info.get('exe') and str(ROOT).lower()in p.info['exe'].lower() and p.info['name'].lower()in ('morrowind.exe','uemorrowind.exe')]
    if running:raise RuntimeError('Close this project game/view before the offline GPU bake')
    net,torch=model(checkpoint);assets=Assets(None);folder=ROOT/'local/texture-upgrades';(folder/'textures').mkdir(parents=True,exist_ok=True)
    cache_valid=False;previous={}
    try:
        previous=json.loads((folder/'index.json').read_text(encoding='utf-8'));cache_valid=previous.get('bake_version')==BAKE_VERSION and previous.get('model_sha256')==MODEL_SHA
    except (OSError,ValueError):pass
    report=dict(protocol='uemw.texture-upgrades',version=1,bake_version=BAKE_VERSION,method='Real-ESRGAN general-x4v3, 4x inference reduced to 2x; wrap context and colour anchoring; inferred detail',model_url=MODEL_URL,model_sha256=MODEL_SHA,budget_bytes=BUDGET,planned_mip_bytes=0,entries={},skipped=[],started_unix_ns=time.time_ns())
    added=0
    if args.characters:
        # Preserve the installed architecture pack and extend it by at most 64 MiB.
        if not previous.get('entries'):raise RuntimeError('Character extension requires the existing validated base pack')
        report['entries']={k:v for k,v in previous['entries'].items()if v.get('material')not in ('skin','hair','cloth','equipment')};report['planned_mip_bytes']=sum(planned_bytes(v['width'],v['height'])for v in report['entries'].values())
        report.update(budget_bytes=256*1024*1024,character_bake_version=1,method='Existing architecture plus source-colour-anchored 2x characters; 40% inferred skin / 65% hair-equipment detail; original alpha and source atlas borders')
    if args.environment_full:
        if not previous.get('entries'):raise RuntimeError('Environment expansion requires the existing local pack; character images are retained')
        report['entries']={k:{**v,'priority':{'foliage':5,'celestial':2}.get(v.get('material'),0)}for k,v in previous['entries'].items()if v.get('material')in ('skin','hair','cloth','equipment','foliage','celestial')}
        report['planned_mip_bytes']=sum(planned_bytes(v['width'],v['height'])for v in report['entries'].values())
        report.update(version=2,budget_bytes=8*1024**3,resident_budget_bytes=256*1024**2,environment_bake_version=3,method='Source-colour-anchored 2x environment expansion; 55% stone / 70% wood / 50% ground inferred colour; retained character images; runtime scene selection capped at 256 MiB colour/detail mips')
    names={name for archive in assets.archives for name in archive.entries if name.startswith('textures/') and name.endswith(('.dds','.tga','.bmp')) and category(name)}
    names=sorted(names,key=lambda n:(0 if any(t in n for t in ('tx_wall_stone_01','tx_common_door_02','tx_stone_plain','tx_stucco_imp_02','tx_bc_grass.','tx_bc_dirt.','tx_bc_mud.','tx_bc_muck_01','tx_ai_dirt_01','tx_ai_dirtroad_01')) else 1 if any(t in n for t in ('tx_wood','tx_wall','tx_stucco','tx_bc_','tx_ai_')) else 2,n))
    if args.characters:
        names={name for archive in assets.archives for name in archive.entries if name.startswith('textures/')and name.endswith(('.dds','.tga','.bmp'))and character_category(name)}
        visible=set();first_person=set()
        try:
            witness=json.loads((ROOT/'local/bridge/witness.json').read_text());cat=json.loads((ROOT/'local/assets'/witness['catalog']).read_text())
            stem=lambda s:Path(s.replace('\\','/').lower()).stem
            visible={stem(v.get('source_texture',''))for v in cat['meshes'].values()}
            first_person={stem(cat['meshes'][b['asset']].get('source_texture',''))for b in cat['bindings']if b.get('layer')=='first-person'}
        except(OSError,ValueError,KeyError):pass
        def priority(n):
            s=Path(n).stem;kind=character_category(n)
            # Catalogs retain original .BMP/.TGA aliases even when the BSA
            # supplies .DDS. Match the asset resolver's extension-independent name.
            return (0 if s in first_person else 1 if s in visible and kind in ('skin','hair')else 2 if s in visible and kind=='cloth'else 3 if s in visible else 4 if 'dagger_iron'in s else 5,n)
        names=sorted(names,key=priority)
    if args.contains:names=[n for n in names if args.contains.lower()in n]
    try:
        for name in names:
            source=assets.texture(name)
            if source in report['entries']:continue
            with Image.open(ROOT/'local/assets'/source)as image:original=image.convert('RGBA')
            w,h=original.size;cost=planned_bytes(w*2,h*2)
            if max(w,h)>512 or min(w,h)<16 or (not args.characters and original.getextrema()[3]!=(255,255)) or report['planned_mip_bytes']+cost>report['budget_bytes'] or len(report['entries'])>=(4096 if args.environment_full else 512):
                report['skipped'].append(name);continue
            start=time.perf_counter();target=folder/'textures'/(Path(source).stem+'-2x.png')
            if args.characters or args.environment_full or not cache_valid or not target.exists():
                enhanced=upscale(original,net,torch,character_category(name)if args.characters else None,category(name)if args.environment_full else None);out=BytesIO();enhanced.save(out,format='PNG');target.write_bytes(out.getvalue())
            else:
                with Image.open(target)as cached:
                    if cached.size!=(w*2,h*2):raise RuntimeError('Invalid cached upgrade dimensions')
            entry=dict(file='textures/'+target.name,source_md5=hashlib.md5((ROOT/'local/assets'/source).read_bytes()).hexdigest(),md5=hashlib.md5(target.read_bytes()).hexdigest(),source_width=w,source_height=h,width=w*2,height=h*2,mip_bytes=cost,material=character_category(name)if args.characters else category(name),source_name=name)
            if args.environment_full:entry['priority']=previous.get('entries',{}).get(source,{}).get('priority',10 if source in previous.get('entries',{})else 20)
            report['entries'][source]=entry;report['planned_mip_bytes']+=cost
            print(json.dumps(dict(texture=name,source=[w,h],output=[w*2,h*2],seconds=round(time.perf_counter()-start,3),total=len(report['entries']))),flush=True)
            added+=1
            if args.limit and added>=args.limit:break
    finally:assets.close()
    report['ended_unix_ns']=time.time_ns();report['gpu']=torch.cuda.get_device_name(0)
    temporary=folder/'index.json.tmp';temporary.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');temporary.replace(folder/'index.json')
    (ROOT/('logs/environment-texture-bake.json'if args.environment_full else'logs/character-texture-bake.json'if args.characters else'logs/hd-bake.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(completed=len(report['entries']),planned_mib=round(report['planned_mip_bytes']/1048576,2),seconds=(report['ended_unix_ns']-report['started_unix_ns'])/1e9)))

if __name__=='__main__':main()
