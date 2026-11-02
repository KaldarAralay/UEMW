import tempfile
from pathlib import Path
import unittest
from native_blend import classify
from game_assets import Assets


class BlendTests(unittest.TestCase):
    def flags(self,source,destination):return 1|(source<<1)|(destination<<5)
    def test_native_rgb_factor_pairs_select_distinct_cooked_policies(self):
        cases=[(6,7,'translucent',True),(6,0,'additive',True),(0,0,'additive',False),
               (0,7,'premultiplied',True),(4,1,'modulate',False),(1,2,'modulate',False)]
        for source,destination,mode,opacity in cases:
            with self.subTest(pair=(source,destination)):
                result=classify(self.flags(source,destination));self.assertEqual(result['mode'],mode)
                self.assertIs(result['native_opacity'],opacity);self.assertIsNone(result['fallback'])
        self.assertEqual(classify(0)['mode'],'opaque');self.assertEqual(classify(0x200)['mode'],'masked')
    def test_unknown_factors_are_reported_and_invalid_flags_are_rejected(self):
        result=classify(self.flags(8,9));self.assertEqual(result['fallback']['source'],8)
        self.assertEqual(result['fallback']['destination'],9)
        for value in(-1,65536,True,'1'):
            with self.assertRaises(ValueError):classify(value)
    def test_particle_mesh_cache_keeps_distinct_opacity_policies_with_shared_real_topology(self):
        scratch=Path(__file__).resolve().parents[1]/'local/test-temp';scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch)as folder:
            assets=Assets.__new__(Assets);assets.out=Path(folder);(assets.out/'meshes').mkdir();assets.meshes={};assets.texture=lambda name:''
            shape=dict(particle_capacity=2,texture='',alpha_mode='additive')
            a=assets.particle_mesh({**shape,'blend_native_opacity':True})
            b=assets.particle_mesh({**shape,'blend_native_opacity':False})
            self.assertIs(a['blend_native_opacity'],True);self.assertIs(b['blend_native_opacity'],False)
            self.assertEqual(a['file'],b['file']);self.assertEqual(len(assets.meshes),2)

if __name__=='__main__':unittest.main()
