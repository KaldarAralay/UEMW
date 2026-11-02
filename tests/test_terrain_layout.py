import unittest
import numpy as np
from terrain_layout import native_tile

class TerrainLayoutTest(unittest.TestCase):
    def setUp(self):
        self.p=np.asarray([[x*128,y*128,x*y*7]for y in range(5)for x in range(5)],dtype=float)
        self.uv=self.p[:,:2]/512
        self.t=dict(rotation=np.eye(3).reshape(-1).tolist(),position=[0,0,0],scale=1)
    def test_loaded_native_tile_and_negative_cell(self):
        self.assertEqual(native_tile(self.p,self.uv,self.t),[0,0])
        self.t['position']=[-16384,-73728,0];original=self.p.copy()
        self.assertEqual(native_tile(self.p,self.uv,self.t),[-32,-144]);np.testing.assert_array_equal(self.p,original)
    def test_neighboring_cells_share_global_grid(self):
        self.t['position']=[-512,0,0];self.assertEqual(native_tile(self.p,self.uv,self.t),[-1,0])
        self.t['position']=[0,0,0];self.assertEqual(native_tile(self.p,self.uv,self.t),[0,0])
    def test_rotated_or_noncanonical_uv_uses_original_material(self):
        self.assertIsNone(native_tile(self.p,self.uv[:,::-1],self.t))
        self.t['rotation']=[0,-1,0,1,0,0,0,0,1];self.assertIsNone(native_tile(self.p,self.uv,self.t))
    def test_non_grid_props_and_invalid_buffers_are_not_terrain(self):
        self.t['position']=[256,0,0];self.assertIsNone(native_tile(self.p,self.uv,self.t))
        self.assertIsNone(native_tile(self.p[:3],self.uv[:3],self.t))
        self.p[0,0]=np.nan;self.assertIsNone(native_tile(self.p,self.uv,self.t))

if __name__=='__main__':unittest.main()
