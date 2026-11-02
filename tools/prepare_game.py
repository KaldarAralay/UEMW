"""Prepare only a local vanilla copy. Never edit the Steam installation/saves."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
import uuid

EXPECTED='eac72e1b3524ee0012d080d3c2e2e00e401464e41ee54f9afd6aaaadf2c221f5'
ROOT_FILES=('Morrowind.exe','Morrowind.ini','binkw32.dll')
DATA_FILES=tuple(name+ext for name in('Morrowind','Tribunal','Bloodmoon')for ext in('.esm','.bsa'))
AUDIO_FOLDERS=('Fonts','Music','Sound','Splash','Video')


def sha(path):
    with path.open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def source_files(source):
    paths=[source/name for name in ROOT_FILES]+[source/'Data Files'/name for name in DATA_FILES]
    for path in paths:
        if not path.is_file():raise ValueError('Missing installed game file: '+str(path))
    for name in AUDIO_FOLDERS:
        folder=source/'Data Files'/name
        if folder.is_dir():
            for base,dirs,files in os.walk(folder,followlinks=False):
                for item in(*dirs,*files):
                    path=Path(base)/item
                    if path.is_symlink()or path.is_junction():raise ValueError('Linked/modded game files are unsupported: '+str(path))
                paths.extend(Path(base)/item for item in files)
    if any(p.is_symlink()or p.is_junction()for p in paths):raise ValueError('Linked game files are unsupported')
    return paths


def private_ini(data):
    text=data.decode('cp1252');newline='\r\n'if'\r\n'in text else'\n'
    text=re.sub(r'(?im)^GameFile\d+=.*(?:\r?\n|$)','',text)
    text=re.sub(r'(?im)^Max FPS=.*$', 'Max FPS=60',text)
    # Insert masters in their own section, independent of INI section order.
    marker=re.search(r'(?im)^\[Game Files\]\s*\r?$',text)
    files=newline.join('GameFile%d=%s.esm'%(i,name)for i,name in enumerate(('Morrowind','Tribunal','Bloodmoon')))+newline
    if marker:text=text[:marker.end()]+newline+files+text[marker.end():].lstrip('\r\n')
    else:text=text.rstrip()+newline+'[Game Files]'+newline+files
    return text.encode('cp1252')


def prepare(project,source,steam_exe):
    project=project.resolve();source=source.resolve();steam_exe=steam_exe.resolve()
    destination=project/'local/Morrowind';manifest=project/'local/game-preparation.json'
    if destination==source or destination in source.parents or source in destination.parents:raise ValueError('Source and private destination must be separate')
    files=source_files(source)
    if sha(source/'Morrowind.exe')!=EXPECTED:raise ValueError('Unsupported Steam executable; nothing was copied')
    if not steam_exe.is_file():raise ValueError('The registered Steam executable is missing')
    if destination.exists():
        required=[destination/name for name in ROOT_FILES]+[destination/'Data Files'/name for name in DATA_FILES]
        if any(not p.is_file()for p in required)or sha(destination/'Morrowind.exe')!=EXPECTED:raise ValueError('Existing private folder is incomplete/unsupported; it was left untouched. Move it aside before preparing a new copy.')
        if manifest.is_file():
            saved=json.loads(manifest.read_text())
            if saved.get('version')!=1 or saved.get('exe_sha256')!=EXPECTED:raise ValueError('Invalid private preparation manifest')
            return dict(saved,reused=True)
        # Adopt a preexisting valid private copy without replacing its INI,
        # wrapper, saves or local changes. Verify the immutable vanilla data.
        for name in DATA_FILES:
            if sha(source/'Data Files'/name)!=sha(destination/'Data Files'/name):raise ValueError('Existing private master/archive differs from installed vanilla data: '+name)
        adopted=True
    else:
        adopted=False;staging=project/'local'/('prepare-'+uuid.uuid4().hex)
        assert staging.resolve().is_relative_to(project/'local')
        staging.mkdir(parents=True)
        (staging/'Saves').mkdir()
        for path in files:
            target=staging/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        ini=staging/'Morrowind.ini';shutil.copy2(ini,staging/'Morrowind.original.ini');ini.write_bytes(private_ini(ini.read_bytes()))
        for i,name in enumerate(('Morrowind','Tribunal','Bloodmoon')):
            stamp=time.mktime((2002+i,1,1,12,0,0,0,0,-1));os.utime(staging/'Data Files'/(name+'.esm'),(stamp,stamp))
        shutil.copy2(steam_exe,staging/'steam.exe');(staging/'steam_appid.txt').write_text('22320\n',encoding='ascii')
        staging.rename(destination)
    result=dict(version=1,exe_sha256=EXPECTED,source=str(source),steam_exe=str(steam_exe),private=str(destination),adopted=adopted,reused=False,
        copied_files=len(files),saves_copied=False,loose_meshes_textures_plugins_copied=False)
    manifest.parent.mkdir(parents=True,exist_ok=True);manifest.write_text(json.dumps(result,indent=2),encoding='utf-8');return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--game',type=Path,required=True);parser.add_argument('--steam',type=Path,required=True);args=parser.parse_args()
    try:print(json.dumps(prepare(args.root,args.game,args.steam),indent=2))
    except(OSError,ValueError)as error:raise SystemExit(str(error))
