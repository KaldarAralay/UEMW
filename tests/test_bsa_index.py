import os,struct,tempfile,unittest
from pathlib import Path
from game_assets import Bsa
from live_probe import ROOT


class BsaIndexTests(unittest.TestCase):
    def test_cached_index_uses_independent_handles_and_invalidates_changed_archive(self):
        scratch=ROOT/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as tmp:
            path=Path(tmp)/'own.bsa';name=b'own.dds\0'
            def write(data):path.write_bytes(struct.pack('<6I',0x100,12+len(name),1,len(data),0,0)+name+bytes(8)+data)
            write(b'abcd');a=Bsa(path);b=Bsa(path)
            try:
                self.assertIs(a.entries,b.entries);self.assertIsNot(a.file,b.file);self.assertEqual(a.read('own.dds'),b'abcd');self.assertEqual(b.read('own.dds'),b'abcd')
                with self.assertRaises(TypeError):a.entries['other']=(0,0)
            finally:a.close();b.close()
            write(b'longer');c=Bsa(path)
            try:self.assertIsNot(c.entries,a.entries);self.assertEqual(c.read('own.dds'),b'longer')
            finally:c.close()


if __name__=='__main__':unittest.main()
