"""Reused original addresses must not resurrect the previous cell's buffers."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from game_assets import Assets
from geometry_stream import Geometry

class Memory:
    cell=0x30000
    root=0x90000
    coordinate=0.
    revision=0
    def read(self,address,count):
        if address==self.cell+0x14:
            data=bytearray(0x1c);struct.pack_into('<I',data,0,self.root);struct.pack_into('<I',data,4,1);struct.pack_into('<I',data,0x18,0xA0000);return bytes(data)
        if address==0x50000:
            data=bytearray(0x48);struct.pack_into('<I',data,0x1c,0x60000);struct.pack_into('<IH',data,0x2c,7,self.revision);struct.pack_into('<I',data,0x3c,0x70000);return bytes(data)
        if address==0x60000:return struct.pack('<9f',self.coordinate,0,0,1,0,0,0,1,0)
        if address==0x70000:return struct.pack('<3H',0,1,2)
        raise AssertionError(f'Unexpected fake read: {address:#x}, {count}')

class Graph:
    def __init__(self,memory):self.memory=memory
    def collect(self):
        m=self.memory
        return dict(cell=f'room-{m.cell}',cell_ptr=hex(m.cell),roots=[hex(m.root),'0xa0000'],counts={},errors=[],
                    shapes=[dict(id='0x40000',model='0x50000',skin='0x0',texture='',vertex_count=3,triangle_count=1)])

class LifecycleTests(unittest.TestCase):
    def test_cell_and_root_changes_invalidate_reused_model_addresses_and_bound_caches(self):
        workspace=Path(__file__).resolve().parents[1];scratch=workspace/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        self.assertTrue(scratch.resolve().is_relative_to(workspace))
        memory=Memory()
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            out=Path(folder);self.assertTrue(out.resolve().is_relative_to(scratch.resolve()));(out/'meshes').mkdir();(out/'textures').mkdir()
            assets=Assets.__new__(Assets);assets.r=memory;assets.out=out;assets.meshes={};assets.textures={};assets.missing=[];assets.archives=[]
            with patch('geometry_stream.SceneReader',return_value=Graph(memory)),patch('geometry_stream.Assets',return_value=assets):
                geometry=Geometry(memory)
            epochs=set();digests=set()
            for index in range(12):
                # Reuse ALL geometry/model IDs and revisions; only scene roots
                # change. The backing vertex bytes represent the new room.
                memory.cell=0x30000+(index%2)*0x1000
                memory.root=0x90000+index*4;memory.coordinate=float(index)
                base=dict(world='0x10000',data='0x20000',cell_ptr=hex(memory.cell))
                geometry.refresh(base)
                epochs.add(geometry.epoch);digests.add(geometry.shapes[0]['asset'])
                self.assertEqual(len(assets.meshes),1)
                self.assertLessEqual(len(geometry.catalog_history),8)
                catalog=json.loads((out/geometry.catalog).read_text())
                self.assertEqual(len(catalog['meshes']),1)
            self.assertEqual(len(epochs),12);self.assertEqual(len(digests),12)
            self.assertEqual(len(list(out.glob('catalog-*.json'))),8)
            self.assertTrue(geometry.records)
            geometry.invalidate_scene()
            self.assertFalse(geometry.records)
            self.assertIsNone(geometry.pose_requests)
            self.assertFalse(geometry.skins)

    def test_refresh_prunes_old_revisions_within_same_loaded_scene(self):
        workspace=Path(__file__).resolve().parents[1];scratch=workspace/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        self.assertTrue(scratch.resolve().is_relative_to(workspace))
        memory=Memory()
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            out=Path(folder);self.assertTrue(out.resolve().is_relative_to(scratch.resolve()));(out/'meshes').mkdir();(out/'textures').mkdir()
            assets=Assets.__new__(Assets);assets.r=memory;assets.out=out;assets.meshes={};assets.textures={'retired.dds':'retired.png'};assets.missing=[];assets.archives=[]
            with patch('geometry_stream.SceneReader',return_value=Graph(memory)),patch('geometry_stream.Assets',return_value=assets):geometry=Geometry(memory)
            epochs=set();digests=set()
            for revision in range(12):
                memory.revision=revision;memory.coordinate=float(revision)
                geometry.refresh(dict(world='0x10000',data='0x20000',cell_ptr=hex(memory.cell)))
                epochs.add(geometry.epoch);digests.add(geometry.shapes[0]['asset'])
                self.assertEqual(len(assets.meshes),1)
            self.assertEqual(len(epochs),1) # no full cell reset for a local revision
            self.assertEqual(len(digests),12) # changed data was actually translated
            self.assertFalse(assets.textures) # retired texture not held indefinitely
            # Same-cell quickloads can reuse every cell/root/model address.
            # Replacing the original player must still retire cached bind data.
            memory.revision=0;memory.coordinate=50.
            geometry.refresh(dict(world='0x10000',data='0x20000',cell_ptr=hex(memory.cell),player_ref='0xb0000'))
            first_epoch=geometry.epoch;first_mesh=geometry.shapes[0]['asset']
            memory.coordinate=60.
            geometry.refresh(dict(world='0x10000',data='0x20000',cell_ptr=hex(memory.cell),player_ref='0xc0000'))
            self.assertNotEqual(geometry.epoch,first_epoch)
            self.assertNotEqual(geometry.shapes[0]['asset'],first_mesh)
            # Loading-menu generation also fences complete address reuse,
            # including the player reference itself.
            prior_epoch=geometry.epoch;prior_mesh=geometry.shapes[0]['asset'];memory.coordinate=70.
            geometry.refresh(dict(world='0x10000',data='0x20000',cell_ptr=hex(memory.cell),player_ref='0xc0000',load_serial=1))
            self.assertNotEqual(geometry.epoch,prior_epoch);self.assertNotEqual(geometry.shapes[0]['asset'],prior_mesh)

if __name__=='__main__':unittest.main()
