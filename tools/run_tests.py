"""Run owned-data tests without Steam, Morrowind assets or Unreal Engine."""
import os
import argparse
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
for folder in ('bridge','dev/diagnostics','tools','tests'):sys.path.insert(0,str(ROOT/folder))
os.environ['PYTHONPATH']=os.pathsep.join(str(ROOT/folder)for folder in('bridge','dev/diagnostics','tools','tests'))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--pattern',default='test_*.py');args=parser.parse_args()
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=args.pattern)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful()else 1)
