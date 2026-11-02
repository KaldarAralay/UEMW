import hashlib,json
import numpy as np
from PIL import Image
from texture_upscale import ROOT,planned_bytes

def main():
    folder=ROOT/'local/texture-upgrades';oldfolder=ROOT/'local/baselines/foliage-fidelity/texture-upgrades';index=json.loads((folder/'index.json').read_text());old=json.loads((oldfolder/'index.json').read_text());failures=[];retained=0;celestial=0;stars=0;total=0
    for key,v in index['entries'].items():
        output=folder/v['file'];total+=planned_bytes(v['width'],v['height'])
        if hashlib.md5(output.read_bytes()).hexdigest()!=v['md5']:failures.append('Output hash: '+key)
        if key in old['entries']:
            prior=old['entries'][key]
            if v!=prior or output.read_bytes()!=(oldfolder/prior['file']).read_bytes():failures.append('Existing image changed: '+key)
            else:retained+=1
            continue
        celestial+=1;source=ROOT/'local/assets'/key
        if v.get('material')!='celestial' or hashlib.md5(source.read_bytes()).hexdigest()!=v['source_md5']:failures.append('Source/category: '+key)
        with Image.open(source)as im:a=im.convert('RGBA')
        with Image.open(output)as im:b=im.convert('RGBA')
        expected=np.asarray(a.resize(b.size,Image.Resampling.NEAREST));actual=np.asarray(b)
        if b.size!=(a.width*2,a.height*2) or not np.array_equal(actual[:,:,3],expected[:,:,3]):failures.append('Phase alpha/size changed: '+key)
        if v['source_name'].rsplit('/',1)[-1].startswith('tx_stars'):
            stars+=1
            if not np.array_equal(actual,expected):failures.append('Constellation points or source flux changed: '+key)
        elif v['source_name'].rsplit('/',1)[-1].startswith(('tx_masser','tx_secunda')):
            zero=np.max(expected[:,:,:3],axis=2)==0
            if np.any(actual[:,:,:3][zero]!=0):failures.append('Lunar black background changed: '+key)
    if retained!=len(old['entries'])or not stars or not celestial or total!=index['planned_mip_bytes']or index['resident_budget_bytes']!=256*1024**2:failures.append('Coverage/reservation mismatch')
    result=dict(passed=not failures,prior_images_unchanged=retained,celestial_images=celestial,exact_source_star_images=stars,total_images=len(index['entries']),planned_library_mip_bytes=total,scene_reservation_bytes=index['resident_budget_bytes'],failures=failures,scope='Hashes, previous image retention, exact native phase alpha, lunar black support and exact replicated constellation texels. Higher resolution representation is not new authored star detail. Lunar colour alone uses the pinned offline model; runtime radiance interpretation is separate.')
    (ROOT/'logs/celestial-texture-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
