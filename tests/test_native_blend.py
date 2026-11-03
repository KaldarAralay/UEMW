import tempfile
from pathlib import Path
import unittest
from native_blend import classify,alpha_test
from game_assets import Assets


class BlendTests(unittest.TestCase):
    def test_alpha_comparison_is_independent_of_rgb_blending(self):
        for function in range(8):
            flags=self.flags(6,7)|0x200|(function<<10)
            self.assertEqual(classify(flags)['mode'],'translucent')
            self.assertEqual(alpha_test(flags,137),dict(version=1,function=function,reference=137))
        self.assertIsNone(alpha_test(self.flags(0,0),255))
        for flags,ref in ((0,-1),(0,256),(True,0),(0,False)):
            with self.assertRaises(ValueError):alpha_test(flags,ref)
    def test_alpha_reference_inherits_from_the_actual_property(self):
        from scene_reader import SceneReader
        class Memory:
            def read(self,p,n):
                return {0x10088:__import__('struct').pack('<2I',0x30000,0),0x20088:bytes(8),0x30014:bytes((0xed,0x12,0,0,137))}[p]
        graph=SceneReader(Memory());graph.ancestry=lambda p:['NiAlphaProperty']
        props=graph.render_properties(0x10000,(0,0,0,2))
        self.assertEqual(props[1],0x12ed);self.assertEqual(props[-1],137)
        self.assertEqual(graph.render_properties(0x20000,props),props)
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
