"""Generated joint trajectories, not real help-gesture accuracy."""
import unittest
from features.survivor_observations import SurvivorObservations


def joints(x=40, raised=True, shift=0):
    points = [[50 + shift, 80] for _ in range(17)]
    points[5], points[6] = [30 + shift, 60], [70 + shift, 60]
    points[9] = [x + shift, 20 if raised else 90]
    points[10] = [70 + shift, 90]
    return points


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.now = 1
        self.observations = SurvivorObservations(clock=lambda: self.now)

    def sample(self, x=40, **kwargs):
        self.now += .2
        return self.observations.update('one', (0, 0, 100, 140), joints(x, **kwargs), False, True)

    def test_repeated_raised_hand_reversals_produce_only_a_candidate(self):
        for x in (30, 50, 70, 50, 30, 50, 70):
            value = self.sample(x)
        self.assertEqual(value['gesture_state'], 'possible_wave')
        self.assertTrue(value['gesture_requires_verification'])

    def test_static_raised_hand_and_single_sweep_are_not_waves(self):
        for sequence in ((40,) * 8, (30, 35, 40, 45, 50, 55, 60)):
            self.observations.reset()
            for x in sequence:
                value = self.sample(x)
            self.assertEqual(value['gesture_state'], 'raised_hand')

    def test_body_translation_without_relative_motion_is_not_waving(self):
        for shift in (0, 10, 20, 10, 0, 10, 20):
            value = self.sample(40, shift=shift)
        self.assertNotEqual(value['gesture_state'], 'possible_wave')

    def test_old_wave_and_lowered_hand_clear(self):
        for x in (30, 50, 70, 50, 30, 50, 70):
            self.sample(x)
        for _ in range(8):
            value = self.sample(40, raised=False)
        self.assertEqual(value['gesture_state'], 'no_wave_observed')

    def test_independent_stillness_resets_on_missing_motion(self):
        self.sample()
        value = self.sample()
        self.assertAlmostEqual(value['immobility_seconds'], .2)
        other = self.observations.update('two', (0, 0, 100, 140), joints(), True, True)
        self.assertIsNone(other['immobility_seconds'])
        missing = self.observations.update('one', (0, 0, 100, 140), None, None, False)
        self.assertIsNone(missing['immobility_seconds'])
        self.assertEqual(missing['gesture_state'], 'unknown')
        self.observations.prune({'two'})
        self.assertNotIn('one', self.observations.people)

    def test_time_gap_clears_gesture_and_inactivity(self):
        self.sample();self.sample();self.now += 2
        value = self.sample()
        self.assertEqual(value['gesture_state'], 'unknown')
        self.assertEqual(value['immobility_seconds'], 0)


if __name__ == '__main__':
    unittest.main()
