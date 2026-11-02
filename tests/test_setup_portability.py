import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import prepare_game
from audit_repository import audit,source_files
from live_probe import ROOT


class PrivatePreparationTests(unittest.TestCase):
    def fixture(self,base):
        source=base/'different steam library/steamapps/common/Morrowind';source.mkdir(parents=True)
        for name in prepare_game.ROOT_FILES:
            (source/name).write_bytes(b'[General]\nMax FPS=240\n[Game Files]\nGameFile0=bad.esp\n[Other]\nKeep=1\n'if name.endswith('.ini')else name.encode())
        (source/'Data Files').mkdir()
        for name in prepare_game.DATA_FILES:(source/'Data Files'/name).write_text(name)
        for folder,filename in(('Saves','old.ess'),('Data Files/Meshes','mod.nif'),('Data Files/Textures','mod.dds'),('Data Files/Sound','owned.wav')):
            path=source/folder/filename;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'owned fixture')
        steam=base/'Steam Client/steam.exe';steam.parent.mkdir();steam.write_bytes(b'owned fixture')
        return source,steam,base/'Project with spaces'

    def test_private_copy_handles_other_library_and_spaces_without_mods_or_saves(self):
        folder=ROOT/'local/test-temp';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder)as tmp:
            source,steam,project=self.fixture(Path(tmp));before={str(p):p.read_bytes()for p in source.rglob('*')if p.is_file()}
            with patch('prepare_game.EXPECTED',prepare_game.sha(source/'Morrowind.exe')):result=prepare_game.prepare(project,source,steam)
            private=project/'local/Morrowind';self.assertFalse((private/'Saves/old.ess').exists());self.assertFalse((private/'Data Files/Meshes').exists());self.assertFalse((private/'Data Files/Textures').exists())
            self.assertTrue((private/'Data Files/Sound/owned.wav').exists());self.assertEqual((private/'steam.exe').read_bytes(),steam.read_bytes())
            ini=(private/'Morrowind.ini').read_text();self.assertIn('Max FPS=60',ini);self.assertNotIn('bad.esp',ini);self.assertIn('[Game Files]\nGameFile0=Morrowind.esm',ini);self.assertIn('[Other]\nKeep=1',ini)
            for p,data in before.items():self.assertEqual(Path(p).read_bytes(),data)
            self.assertFalse(result['saves_copied'])

    def test_rerun_preserves_private_preferences_and_new_saves(self):
        folder=ROOT/'local/test-temp';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder)as tmp:
            source,steam,project=self.fixture(Path(tmp))
            with patch('prepare_game.EXPECTED',prepare_game.sha(source/'Morrowind.exe')):
                prepare_game.prepare(project,source,steam);private=project/'local/Morrowind'
                (private/'Morrowind.ini').write_text('private preference');(private/'Saves/new.ess').write_text('private save')
                self.assertTrue(prepare_game.prepare(project,source,steam)['reused'])
                self.assertEqual((private/'Morrowind.ini').read_text(),'private preference');self.assertEqual((private/'Saves/new.ess').read_text(),'private save')

    def test_unsupported_executable_and_partial_private_folder_are_not_overwritten(self):
        folder=ROOT/'local/test-temp';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder)as tmp:
            source,steam,project=self.fixture(Path(tmp))
            with self.assertRaisesRegex(ValueError,'Unsupported'):prepare_game.prepare(project,source,steam)
            self.assertFalse(project.exists())
            private=project/'local/Morrowind';private.mkdir(parents=True);sentinel=private/'keep.txt';sentinel.write_text('owned')
            with patch('prepare_game.EXPECTED',prepare_game.sha(source/'Morrowind.exe')):
                with self.assertRaisesRegex(ValueError,'left untouched'):prepare_game.prepare(project,source,steam)
            self.assertEqual(sentinel.read_text(),'owned')

    def test_repository_audit_rejects_tracked_private_files_and_personal_paths(self):
        folder=ROOT/'local/test-temp';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder)as tmp:
            root=Path(tmp);(root/'local').mkdir();(root/'local/save.ess').write_text('owned fixture')
            (root/'code.py').write_text('path = "'+'C:'+ '/Users/'+'example/private"')
            result=audit(root,['local/save.ess','code.py']);self.assertFalse(result['passed']);self.assertTrue(any('personal path'in x for x in result['errors']));self.assertTrue(any('Private/'in x for x in result['errors']))

    def test_source_export_audit_excludes_generated_and_private_trees(self):
        folder=ROOT/'local/test-temp';folder.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=folder)as tmp:
            root=Path(tmp)
            for name in ('README.md','bridge/source.py','source-manifest.json','local/config.json','ue/UEMorrowind/Content/generated.uasset','ue/UEMorrowind/Intermediate/generated.cpp','ue/UEMorrowind/Source/owned.cpp'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('owned fixture')
            self.assertEqual(source_files(root),['README.md','bridge/source.py','ue/UEMorrowind/Source/owned.cpp'])
            self.assertTrue(audit(root)['passed'])


if __name__=='__main__':unittest.main()
