"""Audit local optional character output against installed source conversions."""
import hashlib
import json
from pathlib import Path
from collections import Counter
import numpy as np
from PIL import Image
from texture_upscale import planned_bytes

ROOT=Path(__file__).resolve().parents[1]

def main():
    index=json.loads((ROOT/'local/texture-upgrades/index.json').read_text())
    baseline=ROOT/'local/baselines/water-reflection/texture-index.json'
    original=json.loads(baseline.read_text())if baseline.is_file()else None
    failures=[];categories=Counter();drift=[];planned=0;unchanged=0
    for key,value in index['entries'].items():
        planned+=planned_bytes(value['width'],value['height'])
        if original and key in original['entries']:
            if value!=original['entries'][key]:failures.append('Architecture entry changed: '+key)
            else:unchanged+=1
        if value.get('material')not in ('skin','hair','cloth','equipment'):continue
        categories[value['material']]+=1
        source=ROOT/'local/assets'/key;output=ROOT/'local/texture-upgrades'/value['file']
        if hashlib.md5(source.read_bytes()).hexdigest()!=value['source_md5']or hashlib.md5(output.read_bytes()).hexdigest()!=value['md5']:failures.append('Digest mismatch: '+key)
        with Image.open(source)as image:a=image.convert('RGBA')
        with Image.open(output)as image:b=image.convert('RGBA')
        if b.size!=(a.width*2,a.height*2)or not np.array_equal(np.asarray(b.getchannel('A')),np.asarray(a.getchannel('A').resize(b.size,Image.Resampling.NEAREST))):failures.append('Dimension/alpha mismatch: '+key)
        drift.append(float(np.mean(np.abs(np.asarray(a.convert('RGB'),dtype=float).mean((0,1))-np.asarray(b.convert('RGB'),dtype=float).mean((0,1))))))
    if original and unchanged!=len(original['entries']):failures.append('Architecture baseline was not preserved completely')
    if not drift:failures.append('No character upgrades')
    if planned!=index['planned_mip_bytes']or not planned<=index['budget_bytes']<=256*1024*1024:failures.append('Budget mismatch')
    result=dict(passed=not failures,character_images=sum(categories.values()),categories=dict(categories),architecture_unchanged=unchanged if original else None,planned_mip_bytes=planned,budget_bytes=index['budget_bytes'],failures=failures,mean_channel_drift_median=float(np.median(drift))if drift else None,mean_channel_drift_max=max(drift)if drift else None,scope='File/source/output digest, exact 2x dimensions and original alpha; no authored-HD or skin-detail accuracy claim')
    (ROOT/'logs/character-bake-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
