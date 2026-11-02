"""Read one local Steam shortcut for the isolated native bootstrap; never edit it."""
import argparse
import json
import os
from pathlib import Path
import struct


def decode_shortcuts(data):
    if not 1<=len(data)<=4*1024*1024:raise ValueError('Invalid Steam shortcut file size')
    position=0;items=0
    def take(count):
        nonlocal position
        if count<0 or position+count>len(data):raise ValueError('Truncated Steam shortcut file')
        value=data[position:position+count];position+=count;return value
    def string():
        nonlocal position
        end=data.find(b'\0',position,min(len(data),position+32769))
        if end<0:raise ValueError('Invalid Steam shortcut string')
        value=data[position:end].decode('utf-8');position=end+1;return value
    def object_(depth=0):
        nonlocal items
        if depth>16:raise ValueError('Steam shortcut nesting exceeds limit')
        result={}
        while True:
            kind=take(1)[0]
            if kind==8:return result
            name=string().casefold();items+=1
            if items>16384 or name in result:raise ValueError('Invalid or duplicate Steam shortcut key')
            if kind==0:value=object_(depth+1)
            elif kind==1:value=string()
            elif kind==2:value=struct.unpack('<I',take(4))[0]
            elif kind==7:value=struct.unpack('<Q',take(8))[0]
            else:raise ValueError('Unsupported Steam shortcut value type')
            result[name]=value
    result=object_()
    if position!=len(data):raise ValueError('Trailing Steam shortcut bytes')
    return result


def match_shortcut(data,bootstrap):
    rows=decode_shortcuts(data).get('shortcuts',{})
    if not isinstance(rows,dict):raise ValueError('Invalid Steam shortcut table')
    expected=os.path.normcase(str(Path(bootstrap).resolve()));matches=[]
    for row in rows.values():
        if not isinstance(row,dict)or not isinstance(row.get('exe'),str):continue
        candidate=os.path.normcase(str(Path(row['exe'].strip('"')).resolve()))
        if candidate!=expected:continue
        app=row.get('appid')
        if type(app)is not int or not 0x80000000<=app<=0xffffffff:raise ValueError('Invalid non-Steam shortcut app ID')
        # Confirmed against the game ID emitted by Steam's own launch log.
        matches.append(dict(game_id=str((app<<32)|0x02000000),name=row.get('appname',''),bootstrap=expected))
    if len(matches)!=1:raise ValueError('Expected exactly one Steam shortcut for local/bin/uemw-game-start.exe; add it using Steam > Add a Game > Add a Non-Steam Game.')
    return matches[0]


def resolve(root):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam')as key:steam=Path(winreg.QueryValueEx(key,'SteamPath')[0])
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Valve\Steam\ActiveProcess')as key:
        account=winreg.QueryValueEx(key,'ActiveUser')[0];pid=winreg.QueryValueEx(key,'pid')[0]
    target=root/'local/bin/uemw-game-start.exe'
    sources=[steam/'userdata'/str(account)/'config/shortcuts.vdf']if account else list((steam/'userdata').glob('*/config/shortcuts.vdf'))
    matches={}
    for source in sources:
        if not source.is_file():continue
        try:row=match_shortcut(source.read_bytes(),target)
        except ValueError as error:
            if account or 'exactly one'not in str(error):raise
            continue
        matches[row['game_id']]=row
    if len(matches)!=1:raise ValueError('Expected one registered private startup shortcut; see docs/SETUP.md')
    result=next(iter(matches.values()))
    return dict(result,steam_exe=str(steam/'steam.exe'),steam_pid=pid,uri='steam://rungameid/'+result['game_id'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);args=parser.parse_args()
    try:print(json.dumps(resolve(args.root.resolve())))
    except(OSError,ValueError,UnicodeError)as error:print(json.dumps(dict(error=str(error))));raise SystemExit(2)
