import struct
import unittest
from pathlib import Path
from steam_startup import decode_shortcuts,match_shortcut

def field(kind,name,value):return bytes([kind])+name.encode()+b'\0'+value
def shortcut(exe,app=2475896635):
    row=field(2,'appid',struct.pack('<I',app))+field(1,'AppName',b'private\0')+field(1,'Exe',('"'+str(exe)+'"').encode()+b'\0')+b'\x08'
    return field(0,'shortcuts',field(0,'0',row)+b'\x08')+b'\x08'

class SteamStartupTests(unittest.TestCase):
    def setUp(self):self.target=Path.cwd()/'local/bin/uemw-game-start.exe'
    def test_exact_target_and_game_id_match_observed_steam_launch(self):
        self.assertEqual(match_shortcut(shortcut(self.target),self.target)['game_id'],'10633895075635003392')
    def test_an_installed_game_is_never_substituted(self):
        with self.assertRaisesRegex(ValueError,'exactly one'):match_shortcut(shortcut(self.target.parent/'Morrowind.exe'),self.target)
    def test_truncated_and_unbounded_strings_are_rejected(self):
        for data in(shortcut(self.target)[:-2],b'\x01'+b'a'*32769):
            with self.assertRaises(ValueError):decode_shortcuts(data)
    def test_duplicate_shortcut_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'duplicate'):decode_shortcuts(field(1,'x',b'1\0')+field(1,'X',b'2\0')+b'\x08')
    def test_duplicate_targets_are_not_launched_ambiguously(self):
        row=decode_shortcuts(shortcut(self.target))['shortcuts']['0'];encoded=field(2,'appid',struct.pack('<I',row['appid']))+field(1,'exe',row['exe'].encode()+b'\0')+b'\x08'
        data=field(0,'shortcuts',field(0,'0',encoded)+field(0,'1',encoded)+b'\x08')+b'\x08'
        with self.assertRaisesRegex(ValueError,'exactly one'):match_shortcut(data,self.target)
    def test_invalid_native_app_id_and_trailing_data_are_rejected(self):
        with self.assertRaisesRegex(ValueError,'app ID'):match_shortcut(shortcut(self.target,22320),self.target)
        with self.assertRaisesRegex(ValueError,'Trailing'):decode_shortcuts(shortcut(self.target)+b'bad')

if __name__=='__main__':unittest.main()
