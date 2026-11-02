"""Local celestial artwork refinement; star locations/phases are never generated."""
import hashlib,json,time
from pathlib import Path
import numpy as np
from PIL import Image
from texture_upscale import ROOT,MODEL_SHA,model,upscale,planned_bytes
from game_assets import Assets

PREFIXES=('tx_stars','tx_masser','tx_secunda','tx_mooncircle','tx_sun')
def decode(rgb):return np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
def encode(rgb):return np.where(rgb<=.0031308,rgb*12.92,1.055*np.maximum(rgb,0)**(1/2.4)-.055)

def faithful_resize(image,preserve_points=False):
    """Linear-light positive interpolation; no ringing or new star points."""
    size=(image.width*2,image.height*2)
    if preserve_points:return image.convert('RGBA').resize(size,Image.Resampling.NEAREST)
    a=np.asarray(image.convert('RGBA'));rgb=decode(a[:,:,:3].astype(np.float32)/255)
    out=np.stack([np.asarray(Image.fromarray(rgb[:,:,i]).resize(size,Image.Resampling.BILINEAR))for i in range(3)],axis=2)
    result=Image.fromarray(np.clip(np.round(encode(out)*255),0,255).astype(np.uint8)).convert('RGBA');result.putalpha(image.getchannel('A').resize(size,Image.Resampling.NEAREST));return result

def main():
    import psutil
    for p in psutil.process_iter(['exe','name']):
        if p.info.get('exe')and str(ROOT).lower()in p.info['exe'].lower()and p.info['name'].lower()in ('morrowind.exe','uemorrowind.exe'):raise RuntimeError('Close this project game/view before the offline bake')
    folder=ROOT/'local/texture-upgrades';index=json.loads((folder/'index.json').read_text());net,torch=model(ROOT/'local/models/realesr-general-x4v3.pth');assets=Assets(None);added=[];start=time.time_ns()
    # Rebuild this additive category deterministically; other images are immutable.
    for key in [k for k,v in index['entries'].items()if v.get('material')=='celestial']:
        v=index['entries'].pop(key);index['planned_mip_bytes']-=planned_bytes(v['width'],v['height'])
    names=sorted({n for archive in assets.archives for n in archive.entries if n.startswith('textures/')and n.rsplit('/',1)[-1].startswith(PREFIXES)and n.endswith(('.dds','.tga','.bmp'))})
    try:
        for name in names:
            key=assets.texture(name)
            if key in index['entries']:continue
            source=ROOT/'local/assets'/key
            with Image.open(source)as im:a=im.convert('RGBA')
            w,h=a.size;cost=planned_bytes(w*2,h*2)
            if max(w,h)>512 or len(index['entries'])>=4096 or index['planned_mip_bytes']+cost>index['budget_bytes']:raise RuntimeError('Celestial library exceeds validated image/index limits')
            moon=name.rsplit('/',1)[-1].startswith(('tx_masser','tx_secunda'))and max(a.getextrema()[i][1]for i in range(3))>0
            stars=name.rsplit('/',1)[-1].startswith('tx_stars')
            b=upscale(a,net,torch,environment='moon')if moon else faithful_resize(a,stars)
            b.putalpha(a.getchannel('A').resize(b.size,Image.Resampling.NEAREST))
            if moon:
                # Additive native lunar maps must retain their black background.
                native=np.asarray(a.convert('RGB').resize(b.size,Image.Resampling.NEAREST));pixels=np.asarray(b).copy();pixels[:,:,:3][np.max(native,axis=2)==0]=0;b=Image.fromarray(pixels)
            method='45% source-anchored inferred lunar colour'if moon else'exact 2x native texel replication; original point flux and placement'if stars else'linear-light bilinear source reconstruction'
            target=folder/'textures'/(Path(key).stem+'-2x.png');b.save(target,format='PNG');index['entries'][key]=dict(file='textures/'+target.name,source_md5=hashlib.md5(source.read_bytes()).hexdigest(),md5=hashlib.md5(target.read_bytes()).hexdigest(),source_width=w,source_height=h,width=w*2,height=h*2,mip_bytes=cost,material='celestial',source_name=name,priority=2,method=method);index['planned_mip_bytes']+=cost;added.append(key);print(json.dumps({'texture':name,'size':list(b.size),'inferred_moon_colour':moon}),flush=True)
    finally:assets.close()
    index['celestial_bake_version']=1;temp=folder/'index.json.tmp';temp.write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8');temp.replace(folder/'index.json');report=dict(added=len(added),total_images=len(index['entries']),planned_library_mip_bytes=index['planned_mip_bytes'],resident_budget_bytes=index['resident_budget_bytes'],model_sha256=MODEL_SHA,started_unix_ns=start,ended_unix_ns=time.time_ns());(ROOT/'logs/celestial-texture-bake.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
