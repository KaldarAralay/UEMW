import unittest
from native_motion_fixture import select_edge


class MotionFixtureTests(unittest.TestCase):
    def test_uses_declared_edge_and_leaves_player_behind_actor_on_ground(self):
        points=[(1000,1000,100),(1300,1000,108)]
        r=select_edge(points,[[1],[0]],(800,1000,600),(0,0))
        self.assertEqual((r['start_index'],r['destination_index']),(0,1))
        self.assertEqual(r['actor_position'],[1000,1000,108])
        self.assertEqual(r['player_position'],[880.,1000.,116])
    def test_never_invents_connections_or_uses_water_or_platform_height(self):
        for points,edges in [([(1000,1000,100),(1300,1000,100)],[[],[]]),
                             ([(1000,1000,0),(1300,1000,0)],[[1],[0]]),
                             ([(1000,1000,600),(1300,1000,600)],[[1],[0]])]:
            with self.assertRaises(RuntimeError):select_edge(points,edges,(800,1000,600),(0,0))
    def test_malformed_links_and_points_fail_before_generating_commands(self):
        with self.assertRaises(ValueError):select_edge([(1000,1000,100)],[[12]],(800,1000,600),(0,0))
        with self.assertRaises(ValueError):select_edge([(float('nan'),1000,100)],[[]],(800,1000,600),(0,0))


if __name__=='__main__':unittest.main()
