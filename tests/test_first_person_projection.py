import unittest
import numpy as np
from check_first_person_motion import projected_axes


class ForegroundProjectionTests(unittest.TestCase):
    def test_witness_checks_every_native_axis_in_camera_coordinates(self):
        camera=dict(position=[-9544,-72436,183],forward=[0,1,0],up=[0,0,1])
        # Native columns include scale, shear and mirroring. A component-origin
        # test cannot distinguish this shape from a decomposed rigid placement.
        axes=np.asarray([[-2,0,0],[.3,1,0],[.7,0,.5]])
        np.testing.assert_allclose(projected_axes(axes,camera),[[-2,0,0],[.3,0,1],[.7,.5,0]])
        rigid=axes.copy();rigid[1,0]=rigid[2,0]=0
        self.assertGreater(np.max(np.abs(projected_axes(axes,camera)-projected_axes(rigid,camera))),.6)

    def test_camera_translation_cannot_change_a_direction_witness(self):
        a=dict(position=[0,0,0],forward=[1,0,0],up=[0,0,1])
        b=dict(a,position=[400000,-400000,1234])
        np.testing.assert_array_equal(projected_axes(np.eye(3),a),projected_axes(np.eye(3),b))
        np.testing.assert_allclose(projected_axes(np.eye(3),a),[[0,0,1],[-1,0,0],[0,1,0]])
