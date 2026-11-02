"""Local alpha-aware 2x vegetation bake; no inference or geometry work in play."""
import hashlib,json,time
from pathlib import Path
import numpy as np
from PIL import Image,ImageFilter
from texture_upscale import ROOT,MODEL_SHA,model,upscale,planned_bytes
from game_assets import Assets

TERMS=('leaves','leaf','fern','grassblade','grass_blade','flower','goldkanet','comberry','bittergreen','anther','vine','heather','hackle','cork_bulb','podplant')
CUT=85

def fill_hidden_rgb(image):
    """Extend nearby visible colour into transparent texels before inference."""
    original=np.asarray(image.convert('RGBA'));out=original.copy();valid=original[:,:,3]>=CUT
    # Normalized convolution only fills hidden colour, never erodes visible RGB.
    known=valid.copy()
    for radius in (1,2,4,8,16,32):
        weighted=out.copy();weighted[:,:,:3]=np.where(known[:,:,None],out[:,:,:3],0);weighted[:,:,3]=known.astype(np.uint8)*255
        blurred=np.asarray(Image.fromarray(weighted).filter(ImageFilter.GaussianBlur(radius)),dtype=np.float32)
        use=(~known)&(blurred[:,:,3]>=1)
        rgb=np.clip(np.round(blurred[:,:,:3]*255/np.maximum(blurred[:,:,3:4],1)),0,255).astype(np.uint8)
        out[use,:3]=rgb[use];known|=use
        if known.all():break
    out[:,:,3]=original[:,:,3]
    return Image.fromarray(out)

def upscale_alpha(image,size):
    """Resample native alpha, retaining coverage at the unchanged 1/3 cutoff."""
    source=np.asarray(image.getchannel('A'));a=np.asarray(image.getchannel('A').resize(size,Image.Resampling.BILINEAR),dtype=np.float32)
    target=float(np.mean(source>=CUT));best=1.;error=abs(float(np.mean(a>=CUT))-target);lo,hi=0.,8.
    for _ in range(20):
        scale=(lo+hi)*.5;fraction=float(np.mean(np.round(a*scale)>=CUT));e=abs(fraction-target)
        if e<error:best,error=scale,e
        if fraction<target:lo=scale
        else:hi=scale
    return Image.fromarray(np.clip(np.round(a*best),0,255).astype(np.uint8))

def main():
    import psutil
    for p in psutil.process_iter(['exe','name']):
        if p.info.get('exe')and str(ROOT).lower()in p.info['exe'].lower()and p.info['name'].lower()in ('morrowind.exe','uemorrowind.exe'):raise RuntimeError('Close this project game/view before the offline GPU bake')
    folder=ROOT/'local/texture-upgrades';index=json.loads((folder/'index.json').read_text(encoding='utf-8'))
    if index.get('version')!=2 or index.get('model_sha256')!=MODEL_SHA:raise RuntimeError('Requires the validated version-2 environment/character pack')
    net,torch=model(ROOT/'local/models/realesr-general-x4v3.pth');assets=Assets(None);start=time.time_ns();added=[];skipped=[]
    names=sorted({n for archive in assets.archives for n in archive.entries if n.startswith('textures/')and n.endswith(('.dds','.tga','.bmp'))and any(t in n for t in TERMS)and not Path(n).name.startswith(('tx_b_','tx_c_','tx_a_','tx_w_'))})
    try:
        for name in names:
            key=assets.texture(name)
            if key in index['entries']:continue
            source=ROOT/'local/assets'/key
            with Image.open(source)as image:original=image.convert('RGBA')
            w,h=original.size;cost=planned_bytes(w*2,h*2)
            if max(w,h)>512 or min(w,h)<16 or original.getextrema()[3][1]<CUT or len(index['entries'])>=4096 or index['planned_mip_bytes']+cost>index['budget_bytes']:skipped.append(name);continue
            enhanced=upscale(fill_hidden_rgb(original),net,torch,environment='foliage');enhanced.putalpha(upscale_alpha(original,enhanced.size))
            target=folder/'textures'/(Path(key).stem+'-2x.png');enhanced.save(target,format='PNG')
            entry=dict(file='textures/'+target.name,source_md5=hashlib.md5(source.read_bytes()).hexdigest(),md5=hashlib.md5(target.read_bytes()).hexdigest(),source_width=w,source_height=h,width=w*2,height=h*2,mip_bytes=cost,material='foliage',source_name=name,priority=5)
            index['entries'][key]=entry;index['planned_mip_bytes']+=cost;added.append(key);print(json.dumps(dict(texture=name,source=[w,h],output=list(enhanced.size))),flush=True)
    finally:assets.close()
    index['foliage_bake_version']=1;index['foliage_method']='55% inferred 2x colour with hidden RGB extension; bilinear native alpha and 1/3-cutoff coverage preservation; existing images unchanged'
    temporary=folder/'index.json.tmp';temporary.write_text(json.dumps(index,indent=2)+'\n',encoding='utf-8');temporary.replace(folder/'index.json')
    report=dict(added=len(added),keys=added,skipped=skipped,started_unix_ns=start,ended_unix_ns=time.time_ns(),model_sha256=MODEL_SHA,gpu=torch.cuda.get_device_name(0),total_images=len(index['entries']),planned_library_mip_bytes=index['planned_mip_bytes'],resident_budget_bytes=index['resident_budget_bytes']);(ROOT/'logs/foliage-texture-bake.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
