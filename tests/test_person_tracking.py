"""Generated geometry/masks only; no camera, model download or human data."""
import unittest

import numpy as np

from features.person_tracking import (
    PersonTracker, intersection_over_union, match_boxes, person_region_motion,
    usable_keypoints, valid_box,
)


LEFT = (10, 10, 70, 110)
RIGHT = (140, 10, 200, 110)


class AssociationTests(unittest.TestCase):
    def test_pose_order_does_not_determine_person_association(self):
        self.assertEqual(match_boxes([LEFT, RIGHT], [RIGHT, LEFT]), {0: 1, 1: 0})

    def test_one_pose_is_not_shared_and_ambiguous_overlap_abstains(self):
        self.assertEqual(match_boxes([LEFT, LEFT], [LEFT]), {})
        self.assertEqual(match_boxes([LEFT], [LEFT, LEFT]), {})
        self.assertEqual(match_boxes([LEFT, RIGHT], [LEFT]), {0: 0})

    def test_missing_far_and_invalid_boxes_do_not_match(self):
        for bad in ((0, 0, 0, 10), (1, 1, -1, 10), (float('nan'), 1, 9, 10), ('bad',)):
            self.assertIsNone(valid_box(bad))
            self.assertEqual(intersection_over_union(LEFT, bad), 0)
        self.assertEqual(match_boxes([LEFT], [RIGHT]), {})
        self.assertEqual(match_boxes([LEFT], []), {})

    def test_required_body_joints_need_confidence_and_real_coordinates(self):
        points = [[20., 30.]] * 17
        scores = [1.] * 17
        self.assertIsNotNone(usable_keypoints(points, scores))
        for bad in (None, [1.] * 16, [float('nan')] * 17, [.49] * 17):
            self.assertIsNone(usable_keypoints(points, bad))
        hidden = [list(point) for point in points]
        hidden[15] = [0., 0.]
        self.assertIsNone(usable_keypoints(hidden, scores))
        malformed = [list(point) for point in points]
        malformed[0] = [float('nan'), 1.]
        self.assertIsNone(usable_keypoints(malformed, scores))

    def test_gesture_joints_can_be_usable_when_ankles_are_occluded(self):
        points, scores = [[20., 30.] for _ in range(17)], [1.] * 17
        for index in (15, 16):points[index] = [0., 0.];scores[index] = 0
        self.assertIsNone(usable_keypoints(points, scores))
        self.assertIsNotNone(usable_keypoints(points, scores, required=(5, 6, 9, 10)))


class TrackingTests(unittest.TestCase):
    def test_ids_follow_people_when_detection_list_reorders(self):
        tracker = PersonTracker()
        initial = tracker.update([LEFT, RIGHT], context='main', at=1)
        second = tracker.update([(142, 10, 202, 110), (12, 10, 72, 110)], context='main', at=1.2)
        self.assertEqual([row['id'] for row in second], [initial[1]['id'], initial[0]['id']])
        self.assertTrue(all(row['continuous'] for row in second))

    def test_missing_frame_breaks_motion_continuity_without_stealing_id(self):
        tracker = PersonTracker()
        first = tracker.update([LEFT], at=1)[0]
        tracker.update([], at=1.1)
        reacquired = tracker.update([LEFT], at=1.2)[0]
        self.assertEqual(first['id'], reacquired['id'])
        self.assertFalse(reacquired['continuous'])

    def test_time_gaps_context_changes_reset_and_clock_reversal_use_new_ids(self):
        tracker = PersonTracker()
        previous = tracker.update([LEFT], context='main', at=1)[0]['id']
        for now, context in ((3, 'main'), (3.1, 'other-generation'), (3.2, ('other-generation', 320)), (2, 'main')):
            result = tracker.update([LEFT], context=context, at=now)[0]
            self.assertNotEqual(previous, result['id'])
            self.assertFalse(result['continuous'])
            previous = result['id']
        tracker.reset()
        self.assertNotEqual(previous, tracker.update([LEFT], at=4)[0]['id'])

    def test_ambiguous_crossing_does_not_transfer_previous_person_state(self):
        tracker = PersonTracker()
        old = tracker.update([(0, 0, 50, 100), (40, 0, 90, 100)], at=1)
        new = tracker.update([(20, 0, 70, 100), (20, 0, 70, 100)], at=1.1)
        self.assertTrue({row['id'] for row in old}.isdisjoint(row['id'] for row in new))
        self.assertTrue(all(not row['continuous'] for row in new))

    def test_missing_track_memory_is_bounded_by_missed_frames(self):
        tracker = PersonTracker()
        tracker.update([LEFT], at=1)
        for now in (1.1, 1.2, 1.3, 1.4):
            tracker.update([], at=now)
        self.assertFalse(tracker.tracks)


class PersonMotionTests(unittest.TestCase):
    def test_one_moving_region_does_not_mark_the_other_person_as_moving(self):
        mask = np.zeros((140, 240), np.uint8)
        mask[30:60, 20:50] = 255
        self.assertEqual(person_region_motion(mask, [LEFT, RIGHT], [True, True]), [True, False])

    def test_first_observation_missing_mask_and_camera_change_are_unknown(self):
        mask = np.zeros((140, 240), np.uint8)
        self.assertEqual(person_region_motion(mask, [LEFT], [False]), [None])
        self.assertEqual(person_region_motion(None, [LEFT], [True]), [None])
        mask[:] = 255
        self.assertEqual(person_region_motion(mask, [LEFT, RIGHT], [True, True]), [None, None])

    def test_heavy_overlap_is_unknown_and_shared_pixels_do_not_leak(self):
        mask = np.zeros((140, 240), np.uint8)
        self.assertEqual(person_region_motion(mask, [LEFT, LEFT], [True, True]), [None, None])
        boxes = [(10, 10, 70, 110), (50, 10, 110, 110)]
        mask[20:50, 50:70] = 255
        self.assertEqual(person_region_motion(mask, boxes, [True, True]), [False, False])

    def test_no_background_reference_does_not_claim_person_movement(self):
        mask = np.zeros((140, 240), np.uint8)
        self.assertEqual(person_region_motion(mask, [(0, 0, 240, 140)], [True]), [None])


if __name__ == '__main__':
    unittest.main()
