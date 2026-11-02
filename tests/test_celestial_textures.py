import unittest
import numpy as np
from PIL import Image
from celestial_textures import faithful_resize,decode

class CelestialArtwork(unittest.TestCase):
    def test_constellation_centres_flux_and_alpha_are_exact(self):
        a=np.zeros((16,16,4),dtype=np.uint8);a[:,:,3]=255;a[3,7]=[180,220,255,255];a[12,10]=[250,120,64,150];b=np.asarray(faithful_resize(Image.fromarray(a),True));np.testing.assert_array_equal(b,np.repeat(np.repeat(a,2,axis=0),2,axis=1));self.assertEqual(np.count_nonzero(b[:,:,:3].max(2)),8)
    def test_reconstruction_preserves_phase_alpha(self):
        a=np.zeros((8,8,4),dtype=np.uint8);a[:,:4]=[180,130,90,255];b=np.asarray(faithful_resize(Image.fromarray(a)));np.testing.assert_array_equal(b[:,:,3],np.repeat(np.repeat(a[:,:,3],2,axis=0),2,axis=1))
    def test_empty_new_moon_stays_completely_empty(self):
        b=np.asarray(faithful_resize(Image.new('RGBA',(8,8),(0,0,0,0))));self.assertFalse(b.any())

if __name__=='__main__':unittest.main()
