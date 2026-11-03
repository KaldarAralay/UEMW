"""Audit exactly what Git would publish, or a source export without .git."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
PUBLIC_DIRS={'bridge','dev','docs','native','shaders','tests','tools','.github','ue'}
PRIVATE_DIRS={'local','logs','third_party','.git','.venv','venv','.vs','.vscode','__pycache__','.pytest_cache'}
GENERATED={'Binaries','Intermediate','Saved','DerivedDataCache'}
FORBIDDEN={'.bsa','.esm','.esp','.ess','.nif','.dds','.umesh','.uskin','.uuv','.uasset','.umap','.pak','.exe','.dll','.obj','.lib','.exp','.ilk','.pdb','.dmp','.utrace','.mkv','.mp4','.zip','.pth','.pt','.onnx','.safetensors'}


def source_files(root=ROOT):
    if(root/'.git').exists():
        result=subprocess.run(['git','-c','core.quotepath=false','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root,capture_output=True,check=True)
        return sorted(set(p.decode('utf-8')for p in result.stdout.split(b'\0')if p))
    result=[]
    for base,dirs,files in os.walk(root):
        parent=Path(base).relative_to(root)
        dirs[:]=[d for d in dirs if d not in PRIVATE_DIRS|GENERATED and (parent.parts or d in PUBLIC_DIRS)and not(parent.parts==('ue','UEMorrowind')and d in('Content','Build'))]
        for name in files:
            p=Path(base)/name
            if not parent.parts and name=='source-manifest.json':continue
            if p.suffix not in('.pyc','.pyo'):result.append(p.relative_to(root).as_posix())
    return sorted(result)


def audit(root=ROOT,files=None):
    files=source_files(root)if files is None else files;errors=[]
    for name in files:
        p=root/name;parts=Path(name).parts
        if name=='source-manifest.json':errors.append('Release manifest belongs in the generated archive, not Git: '+name)
        if any(x in PRIVATE_DIRS|GENERATED for x in parts)or parts[:3]in(('ue','UEMorrowind','Content'),('ue','UEMorrowind','Build')):errors.append('Private/generated path: '+name)
        if p.suffix.lower()in FORBIDDEN:errors.append('Game/binary/generated artifact: '+name)
        if not p.is_file():errors.append('Missing source file: '+name);continue
        if p.stat().st_size>2*1024*1024:errors.append('Unexpected large source file: '+name);continue
        data=p.read_bytes()
        try:text=data.decode('utf-8-sig')
        except UnicodeDecodeError:errors.append('Non-text source file: '+name);continue
        if b'\0'in data:errors.append('Binary content: '+name)
        if re.search(r'(?i)[a-z]:[\\/]+Users[\\/]+[^\\/\s"\']+',text):errors.append('Hard-coded personal path: '+name)
        if re.search(r'\b(?:gh[pousr]_[A-Za-z0-9]{25,}|AKIA[0-9A-Z]{16})\b',text):errors.append('Possible credential: '+name)
        if p.suffix=='.ini'and re.search(r'(?im)^SecurityToken=\S+',text):errors.append('Generated service token belongs outside source: '+name)
        if p.suffix=='.md':
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',text):
                target=target.split('#',1)[0].strip('<>')
                if not target or re.match(r'^[a-z][a-z0-9+.-]*:',target,re.I):continue
                if not(p.parent/target).exists():errors.append('Broken documentation link: '+name+' -> '+target)
    return dict(passed=not errors,source_files=len(files),files=files,errors=errors)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--list-json',action='store_true');args=parser.parse_args()
    result=audit()
    print(json.dumps(result['files']if args.list_json and result['passed']else result,indent=2))
    raise SystemExit(0 if result['passed']else 1)
