import math
import unittest
import numpy as np
from render_culling import View

def camera():
    return dict(position=(0,0,0),forward=(0,1,0),up=(0,0,1),frustum=(-.75,.75,.56,-.56,1,1000))

class CullingTests(unittest.TestCase):
    def test_batch_matches_scalar_for_rotated_cameras_invalid_bounds_and_sphere_edges(self):
        rng=np.random.default_rng(149)
        bounds=np.column_stack((rng.uniform(-2000,2000,(1000,3)),rng.uniform(.1,400,1000)))
        bounds=np.vstack((bounds,[(0,0,0,0),(0,0,0,-1),(math.nan,0,0,1),(math.inf,0,0,1)]))
        for forward in ((0,1,0),(1,0,0),(.6,.8,0)):
            cam=camera();cam['forward']=forward;view=View(cam)
            np.testing.assert_array_equal(view.includes_many(bounds),[view.includes(b)for b in bounds])
        self.assertTrue(View({}).includes_many(bounds).all())
    def test_frustum_intersection_margin_and_distance(self):
        view=View(camera())
        for sphere in ((0,100,0,1),(100,100,0,1),(0,0,0,1),(0,1010,0,1)):
            with self.subTest(sphere=sphere):self.assertTrue(view.includes(sphere))
        for sphere in ((200,100,0,1),(-200,100,0,1),(0,100,200,1),(0,100,-200,1),(0,-100,0,1),(0,1100,0,1)):
            with self.subTest(sphere=sphere):self.assertFalse(view.includes(sphere))
        self.assertTrue(view.includes((200,100,0,100))) # sphere intersects side

    def test_rotated_translated_camera(self):
        cam=camera();cam.update(position=(500,100,50),forward=(1,0,0))
        view=View(cam)
        self.assertTrue(view.includes((600,100,50,1)))
        self.assertFalse(view.includes((400,100,50,1)))
        self.assertFalse(view.includes((600,300,50,1)))

    def test_invalid_camera_or_source_bounds_fail_open(self):
        for changes in ({'frustum':(0,0,0,0,0,0)},{'forward':(0,0,0)},{'up':(0,1,0)},{'position':(math.nan,0,0)}):
            cam=camera();cam.update(changes)
            self.assertTrue(View(cam).includes((99999,0,0,1)))
        for bound in ((0,0,0,0),(0,0,0,-1),(math.nan,0,0,1),(math.inf,0,0,1)):
            self.assertTrue(View(camera()).includes(bound))

if __name__=='__main__':unittest.main()
