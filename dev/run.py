"""Run an opt-in diagnostic: python dev/run.py <module> [arguments]."""
import os
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parents[1]
if len(sys.argv)<2:raise SystemExit('Usage: python dev/run.py <diagnostic_name> [arguments]')
name=sys.argv[1]
if not name.replace('_','').isalnum():raise SystemExit('Use a diagnostic module name, without a path')
path=ROOT/'dev/diagnostics'/(name+'.py')
if not path.is_file():raise SystemExit('Unknown diagnostic: '+name)
paths=[str(ROOT/folder)for folder in('bridge','dev/diagnostics','tools')]
sys.path[:0]=paths;os.environ['PYTHONPATH']=os.pathsep.join(paths)
sys.argv=[str(path),*sys.argv[2:]]
runpy.run_path(str(path),run_name='__main__')
