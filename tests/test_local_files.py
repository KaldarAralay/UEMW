import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import local_files

class LocalFileTests(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parents[1]/'local/test-temp';root.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(dir=root);self.folder=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_handle_is_closed_before_decode_and_copy_survives_replacement(self):
        target=self.folder/'state.json';target.write_text('{"sequence":1}')
        newer=self.folder/'new.json';newer.write_text('{"sequence":2}')
        decode=json.loads
        def replace_during_decode(text):
            os.replace(newer,target)
            return decode(text)
        with patch.object(local_files.json,'loads',side_effect=replace_during_decode):
            self.assertEqual(local_files.read_json(target),{'sequence':1})
        self.assertEqual(local_files.read_json(target),{'sequence':2})
    def test_invalid_oversized_and_nonobject_files_fail_closed(self):
        p=self.folder/'state.json'
        for data in (b'[]',b'{',b' '*(1024*1024+1)):
            p.write_bytes(data)
            with self.subTest(length=len(data)),self.assertRaises(ValueError):local_files.read_json(p)

if __name__=='__main__':unittest.main()
