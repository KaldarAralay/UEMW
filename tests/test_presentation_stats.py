import unittest
from presentation_stats import summarize

def row(t,frame,refresh=None,hr=0,sync=None):
    refresh=frame if refresh is None else refresh
    return [t,hr,frame,refresh,refresh if sync is None else sync,t,0,frame+2,4]

class PresentationStatsTests(unittest.TestCase):
    def test_queried_device_latency_is_optional_and_cannot_invent_present_counts(self):
        old=row(1000,60);new=row(1017,61)+[1];r=summarize([old,new])
        self.assertEqual(r['samples'],2);self.assertEqual(r['maximum_frame_latency_values'],[1]);self.assertEqual(r['observed_display_changes'],1)
        self.assertEqual(summarize([old,row(1017,61)+[0]])['maximum_frame_latency_values'],[])
        for value in(-1,17,1.5,True,float('nan')):
            self.assertEqual(summarize([old,row(1017,61)+[value]])['samples'],1)
    def test_actual_display_counter_is_separate_from_present_calls(self):
        r=summarize([row(1000,60),row(1000+1000/60,61),row(1000+2000/60,61,61,sync=62),row(1050,62,63)])
        self.assertTrue(r['supported']);self.assertEqual(r['repeated_display_observations'],1)
        self.assertAlmostEqual(r['display_change_hz_lower_bound'],40)
        self.assertAlmostEqual(r['refresh_hz_estimate'],60)
        self.assertEqual(r['consecutive_display_intervals'],2)
        self.assertAlmostEqual(r['consecutive_display_interval_ms']['median'],25,places=2)

    def test_id_gap_is_not_fabricated_into_intermediate_display_frames(self):
        r=summarize([row(1000,60),row(1000+1000/60,63,61),row(1000+2000/60,64,62)])
        self.assertEqual(r['skipped_present_ids'],2);self.assertEqual(r['observed_display_changes'],2)
        self.assertEqual(r['consecutive_display_intervals'],1)

    def test_disjoint_breaks_interval_and_no_statistics_means_unknown(self):
        r=summarize([row(1000,60),row(1017,61,hr=0x887a000b),row(1034,62)])
        self.assertFalse(r['supported']);self.assertIsNone(r['display_change_hz_lower_bound'])
        self.assertEqual(r['consecutive_display_intervals'],0)
        self.assertIsNone(summarize([])['submitted_present_hz'])

    def test_reset_and_bad_rows_cannot_create_large_display_rate(self):
        r=summarize([row(1000,60),row(1017,1),[1],row(float('nan'),2),row(1034,2)])
        self.assertEqual(r['counter_resets'],1);self.assertEqual(r['observed_display_changes'],1)
        self.assertEqual(r['samples'],3)

    def test_duplicate_submission_timestamps_remain_unknown(self):
        a=row(1000,60);b=row(1000,61);c=row(1017,62);c[6]=1
        self.assertIsNone(summarize([a,b,c])['submitted_present_hz'])

if __name__=='__main__':unittest.main()
