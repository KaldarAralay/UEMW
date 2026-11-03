"""Source-owned active particles must survive translation without simulation."""
import struct
import unittest
import numpy as np
from live_probe import SceneReadChanged
from native_particles import capture,expand

class ParticleTests(unittest.TestCase):
    def test_corner_and_texture_orientation_matches_the_vanilla_draw_path(self):
        sample=(1,1,1.,struct.pack('<3f',0,0,0),None,None,(1.,1.,1.,1.))
        points,_=expand(sample,[1,0,0,0,1,0,0,0,1,0,0,0,1],dict(forward=[0,1,0],up=[0,0,1]))
        # The native DX8 writer places UV(0,0) at camera-right/down.
        np.testing.assert_array_equal(np.asarray(points).reshape(4,3),[[1,0,-1],[-1,0,-1],[-1,0,1],[1,0,1]])
    def test_retiring_emitter_does_not_drop_an_independent_current_emitter(self):
        class Memory:
            def read(self,p,n):
                if p==0x10000:raise OSError('Retired native allocation')
                if p==0x20000:
                    h=bytearray(0x44);struct.pack_into('<H',h,8,1);struct.pack_into('<H',h,0x3c,1)
                    struct.pack_into('<f',h,0x38,2);struct.pack_into('<I',h,0x1c,0x30000);return bytes(h)
                if p==0x30000:return struct.pack('<3f',7,8,9)
                raise AssertionError((p,n))
        shapes=[dict(particles=True,particle_capacity=1,model=hex(p),id=hex(p+0x40000))for p in(0x10000,0x20000)]
        current=capture(Memory(),shapes,tolerate=True)
        self.assertEqual(set(current),{0x60000})
        self.assertEqual(struct.unpack('<3f',current[0x60000][3]),(7,8,9))
        with self.assertRaises(OSError):capture(Memory(),shapes)

    def test_emissive_native_particle_material_is_not_translated_to_black(self):
        class Memory:
            def read(self,p,n):
                if p==0x10000:
                    h=bytearray(0x44);struct.pack_into('<H',h,8,2);struct.pack_into('<H',h,0x3c,1)
                    struct.pack_into('<f',h,0x38,1);struct.pack_into('<I',h,0x1c,0x20000);return bytes(h)
                if p==0x20000:return struct.pack('<3f',1,2,3)
                if p==0x30028:
                    h=bytearray(0x2c);struct.pack_into('<3f',h,0x18,1,.2,.3);struct.pack_into('<f',h,0x28,.5);return bytes(h)
                raise AssertionError((p,n))
        value=capture(Memory(),[dict(particles=True,particle_capacity=2,model='0x10000',id='0x40000',material='0x30000')])[0x40000]
        np.testing.assert_allclose(value[-1],[1,.2,.3,.5])
    def test_actual_centers_sizes_and_colors_translate_and_inactive_slots_collapse(self):
        sample=(2,1,2.,struct.pack('<3f',3,4,5),bytes((0,128,255,128)),struct.pack('<f',.5),(1.,1.,1.,.5))
        points,colors=expand(sample,[1,0,0,0,1,0,0,0,1,10,20,30,2],dict(forward=[0,1,0],up=[0,0,1]))
        points=np.array(points).reshape(2,4,3);colors=np.array(colors).reshape(2,4,4)
        np.testing.assert_allclose(points[0].mean(axis=0),[16,28,40])
        np.testing.assert_allclose(points[0].max(axis=0)-points[0].min(axis=0),[4,0,4])
        np.testing.assert_allclose(points[1],np.tile([10,20,30],(4,1)))
        np.testing.assert_allclose(colors[0][0],[1,128/255,0,128/255*.5],atol=.0001)
        self.assertFalse(colors[1].any())

    def test_recycled_particle_buffer_is_rejected_before_publication(self):
        class Memory:
            calls=0
            def read(self,p,n):
                if p==0x10000:
                    self.calls+=1;h=bytearray(0x44);struct.pack_into('<H',h,8,2);struct.pack_into('<H',h,0x3c,1)
                    struct.pack_into('<f',h,0x38,1);struct.pack_into('<I',h,0x1c,0x20000 if self.calls==1 else 0x30000);return bytes(h)
                if p==0x20000:return struct.pack('<3f',1,2,3)
                raise AssertionError((p,n))
        with self.assertRaises(SceneReadChanged):capture(Memory(),[dict(particles=True,particle_capacity=2,model='0x10000',id='0x40000')])

    def test_nonfinite_native_values_are_rejected(self):
        with self.assertRaises(ValueError):expand((1,1,1,struct.pack('<3f',float('nan'),0,0),None,None,(1,1,1,1)),[1,0,0,0,1,0,0,0,1,0,0,0,1],dict(forward=[0,1,0],up=[0,0,1]))

    def test_reused_data_type_cannot_retain_particle_identity(self):
        class Memory:
            def read(self,p,n):
                h=bytearray(0x44);struct.pack_into('<I',h,0,0x99999);return bytes(h)
        with self.assertRaises(SceneReadChanged):capture(Memory(),[dict(particles=True,particle_capacity=2,model='0x10000',id='0x40000',particle_data_vtable=0x88888)])

if __name__=='__main__':unittest.main()
