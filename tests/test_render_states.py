"""Compact hot path preserves complete membership and captured native poses."""
import json
import struct
from types import SimpleNamespace
import unittest
from geometry_stream import Geometry
from live_probe import SceneReadChanged
import numpy as np

class StateTests(unittest.TestCase):
    def fixture(self):
        geometry=Geometry.__new__(Geometry)
        identity=(0x60000,0x70000);raw={}
        transform=(1,0,0,0,1,0,0,0,1,0,10,0,1)
        for ptr in (0x40000,0x41000,0x42000):
            data=bytearray(0xac);struct.pack_into('<4f',data,0x1c,0,10,0,1);struct.pack_into('<13f',data,0x40,*transform)
            struct.pack_into('<2I',data,0x98,*identity);raw[ptr]=data
        struct.pack_into('<H',raw[0x41000],0x14,1)
        struct.pack_into('<4f',raw[0x42000],0x1c,0,-1000,0,1)
        class Skin:
            shape=0x40000;root=0x40000;bones=(0x40000,)
            def palette(self,worlds):
                if set(worlds)!={0x40000}:raise AssertionError('Late/uncaptured pose')
                return np.array([[[1,0,0,1],[0,1,0,2],[0,0,1,3]]],dtype='<f4')
        geometry.records=[(p,identity,(p,),Skin()if p==0x40000 else None,0)for p in raw]
        geometry.skins={'original':Skin()};geometry.transform_cache={};geometry.cell_definitions=[dict(key='exterior:0,0')]
        geometry.terrain_count=2;geometry.epoch='epoch';geometry.catalog='catalog';geometry.membership_hash='membership';geometry.catalog_history=[]
        geometry.assets=SimpleNamespace(meshes={},textures={})
        geometry.shapes=[];geometry.native_attributes={}
        geometry.cell='0x30000';geometry.r=SimpleNamespace(u32=lambda p:0x20000 if p==0x7c67e0 else 0x30000)
        geometry.prepare=lambda base:None
        camera=dict(position=[0,0,0],forward=[0,1,0],up=[0,0,1],frustum=[-1,1,1,-1,1,100],fov=90)
        geometry.capture_pose=lambda base:({'camera':camera},raw,{},{}, {'pose_attempts':1})
        return geometry,raw

    def test_hidden_and_culled_rows_stay_in_order_visible_pose_is_original(self):
        geometry,_=self.fixture();result=geometry.snapshot({})
        rows=result['instance_states']
        self.assertEqual(rows[1:],[(False,),(False,)])
        np.testing.assert_array_equal(rows[0][2]['palette'][0,:,3],[1.,2.,3.]);self.assertEqual(rows[0][1][10],10)
        self.assertEqual(result['stream_cells'][0]['visible'],1)
        self.assertEqual(result['geometry_stats']['instances'],3)
        self.assertEqual(result['geometry_stats']['frustum_culled'],1)
        self.assertEqual(set(geometry.transform_cache),{0x40000})

    def test_hidden_address_reuse_still_invalidates_the_whole_pose(self):
        geometry,raw=self.fixture();struct.pack_into('<I',raw[0x41000],0x98,0xdeadbeef)
        with self.assertRaisesRegex(SceneReadChanged,'identity changed'):geometry.snapshot({})

if __name__=='__main__':unittest.main()
