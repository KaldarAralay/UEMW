import unittest
import numpy as np
from PIL import Image
from foliage_textures import fill_hidden_rgb,upscale_alpha,CUT

class FoliageEdges(unittest.TestCase):
    def test_hidden_black_cannot_bleed_into_green_leaf(self):
        a=np.zeros((24,24,4),dtype=np.uint8);a[5:19,8:16]=[24,160,16,255];b=np.asarray(fill_hidden_rgb(Image.fromarray(a)))
        np.testing.assert_array_equal(a[5:19,8:16],b[5:19,8:16]);np.testing.assert_array_equal(a[:,:,3],b[:,:,3]);self.assertGreater(b[12,7,1],140);self.assertLess(b[12,7,0],35)
    def test_thin_stems_and_leaf_coverage_survive(self):
        a=np.zeros((32,32,4),dtype=np.uint8);a[2:30,15:17]=[32,160,24,255];a[4:13,7:23]=[32,160,24,255];a[18:26,10:26]=[32,160,24,255];image=Image.fromarray(a)
        b=np.asarray(upscale_alpha(image,(64,64)));native=np.asarray(image.getchannel('A').resize((64,64),Image.Resampling.NEAREST))>=CUT;mask=b>=CUT
        self.assertLess(abs(mask.mean()-native.mean()),.012);self.assertGreater(np.logical_and(mask,native).sum()/np.logical_or(mask,native).sum(),.90);self.assertTrue(mask[28:36,31:33].all());self.assertTrue((b[:3]==0).all())
    def test_uniform_alpha_remains_exact(self):
        for alpha in (0,255):
            image=Image.new('RGBA',(8,8),(24,160,16,alpha));self.assertTrue((np.asarray(upscale_alpha(image,(16,16)))==alpha).all())

if __name__=='__main__':unittest.main()
