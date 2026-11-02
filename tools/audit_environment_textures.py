"""Verify the expanded local library without confusing disk size with residency."""
import hashlib,json
from collections import Counter
from pathlib import Path
import numpy as np
from PIL import Image
from texture_upscale import planned_bytes

ROOT=Path(__file__).resolve().parents[1]
CHARACTER={'skin','hair','cloth','equipment'}

def main():
    folder=ROOT/'local/texture-upgrades'
    index=json.loads((folder/'index.json').read_text())
    baseline=ROOT/'local/baselines/interior-lighting/texture-upgrades'
    previous=json.loads((baseline/'index.json').read_text())
    failures=[];categories=Counter();drift=[];planned=0;unchanged=0;new=0;disk=0
    for key,v in index['entries'].items():
        source=ROOT/'local/assets'/key;output=folder/v['file'];raw=source.read_bytes();enhanced=output.read_bytes();disk+=len(enhanced)
        if hashlib.md5(raw).hexdigest()!=v['source_md5'] or hashlib.md5(enhanced).hexdigest()!=v['md5']:failures.append('Digest mismatch: '+key)
        with Image.open(source)as image:a=image.convert('RGBA')
        with Image.open(output)as image:b=image.convert('RGBA')
        if b.size!=(a.width*2,a.height*2) or b.size!=(v['width'],v['height']) or a.size!=(v['source_width'],v['source_height']):failures.append('Dimension mismatch: '+key)
        if v['material']!='foliage'and not np.array_equal(np.asarray(b.getchannel('A')),np.asarray(a.getchannel('A').resize(b.size,Image.Resampling.NEAREST))):failures.append('Original alpha changed: '+key)
        categories[v['material']]+=1;planned+=planned_bytes(*b.size)
        if v['material'] in CHARACTER:
            old=previous['entries'].get(key)
            if not old or enhanced!=(baseline/old['file']).read_bytes():failures.append('Character image changed: '+key)
            else:unchanged+=1
        elif v['material']not in ('foliage','celestial'):
            new+=key not in previous['entries']
            if a.getextrema()[3]!=(255,255):failures.append('Environment opacity not solid: '+key)
            drift.append(float(np.abs(np.asarray(a.convert('RGB'),dtype=float).mean((0,1))-np.asarray(b.convert('RGB'),dtype=float).mean((0,1))).mean()))
    expected=sum(v.get('material')in CHARACTER for v in previous['entries'].values())
    if unchanged!=expected:failures.append('Character image set changed')
    missing=sorted(set(previous['entries'])-set(index['entries']))
    if missing:failures.append('Existing optional texture coverage was lost: '+str(missing))
    if index['version']!=2 or planned!=index['planned_mip_bytes'] or not planned<=index['budget_bytes']<=8*1024**3 or not 0<index['resident_budget_bytes']<=256*1024**2:failures.append('Library/reservation budget mismatch')
    result=dict(passed=not failures,total_images=len(index['entries']),environment_images=sum(n for k,n in categories.items()if k not in CHARACTER and k not in ('foliage','celestial')),new_environment_images=new,character_images_unchanged=unchanged,categories=dict(categories),planned_library_mip_bytes=planned,compressed_png_bytes=disk,scene_upgrade_reservation_bytes=index['resident_budget_bytes'],mean_channel_drift_median=float(np.median(drift)),mean_channel_drift_max=max(drift),failures=failures,scope='Exact local file hashes, dimensions, environment alpha and character preservation. Resampled foliage alpha is separately validated by audit_foliage_textures.py. Scene reservation covers selected upgraded colour plus conservative detail mips, not total GPU/VRAM. Mask/blend variants and the separately capped terrain pool are additional. Inferred colour and albedo-derived normals are not authored HD or recovered geometry.')
    (ROOT/'logs/environment-texture-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
