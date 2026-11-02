"""Audit local foliage output and retention of the preceding 748-image pack."""
import hashlib,json
from pathlib import Path
import numpy as np
from PIL import Image
from texture_upscale import ROOT,planned_bytes

def main():
    folder=ROOT/'local/texture-upgrades';baseline=ROOT/'local/baselines/texture-cleanup/texture-upgrades';index=json.loads((folder/'index.json').read_text());old=json.loads((baseline/'index.json').read_text());failures=[];coverage=[];iou=[];foliage=[];retained=0;total=0
    for key,v in index['entries'].items():
        target=folder/v['file'];total+=planned_bytes(v['width'],v['height'])
        if hashlib.md5(target.read_bytes()).hexdigest()!=v['md5']:failures.append('Output hash mismatch: '+key)
        if key in old['entries']:
            previous=old['entries'][key]
            if v!=previous or target.read_bytes()!=(baseline/previous['file']).read_bytes():failures.append('Existing image or metadata changed: '+key)
            else:retained+=1
            continue
        if v.get('material')!='foliage':failures.append('Unexpected extension category: '+key);continue
        foliage.append(key);source=ROOT/'local/assets'/key
        if hashlib.md5(source.read_bytes()).hexdigest()!=v['source_md5']:failures.append('Source hash mismatch: '+key)
        with Image.open(source)as image:a=image.convert('RGBA')
        with Image.open(target)as image:b=image.convert('RGBA')
        if b.size!=(a.width*2,a.height*2):failures.append('Not exact 2x: '+key)
        expected=np.asarray(a.getchannel('A').resize(b.size,Image.Resampling.NEAREST))>=85;actual=np.asarray(b.getchannel('A'))>=85
        error=abs(float(expected.mean())-float(actual.mean()));union=np.logical_or(expected,actual).sum();overlap=float(np.logical_and(expected,actual).sum()/union)if union else 1.
        coverage.append(error);iou.append(overlap)
        if error>.02 or overlap<.82:failures.append('Alpha coverage or shape changed excessively: '+key)
        zero=np.asarray(a.getchannel('A').resize(b.size,Image.Resampling.BILINEAR))==0
        if np.any(np.asarray(b.getchannel('A'))[zero]!=0):failures.append('Transparent hole acquired opacity: '+key)
    if retained!=len(old['entries']):failures.append('Preceding library coverage was lost')
    if not foliage or index['version']!=2 or total!=index['planned_mip_bytes'] or index['resident_budget_bytes']!=256*1024**2:failures.append('Library or scene reservation mismatch')
    report=dict(passed=not failures,foliage_images=len(foliage),previous_images_unchanged=retained,total_images=len(index['entries']),planned_library_mip_bytes=total,scene_upgrade_reservation_bytes=index['resident_budget_bytes'],alpha_coverage_error_max=max(coverage,default=0),cutout_mask_iou_min=min(iou,default=1),failures=failures,scope='File hashes, 2x dimensions, prior-image byte preservation, alpha-cutoff coverage and cutout overlap. Alpha is resampled original data; inferred colour is not authored HD. Scene reservation is colour/detail planning, not measured total VRAM.')
    (ROOT/'logs/foliage-texture-audit.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
