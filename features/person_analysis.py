"""Shared person analysis with independent temporal state for each camera."""
import math
import time

from .live_camera import LiveCamera
from .person_tracking import PersonTracker, match_boxes, valid_box, usable_keypoints, person_region_motion
from .survivor_observations import SurvivorObservations


class PersonAnalysis:
    def __init__(self, cv, classifier, source):
        self.cv, self.classifier, self.source = cv, classifier, source
        self.prev_frame = self.motion_generation = None
        self.person_tracker = PersonTracker(max_gap=LiveCamera.RESULT_TTL)
        self.survivor_observations = SurvivorObservations()
        self.stationary_timers = {}

    def reset(self):
        self.prev_frame = self.motion_generation = None
        self.person_tracker.reset()
        self.survivor_observations.reset()
        self.stationary_timers.clear()

    def analyze(self, frame, camera, detector, pose_model, thermal_frame=None, thermal_analyzer=None):
        cv = self.cv
        generation = camera.analysis_generation
        generation = camera.generation if generation is None else generation
        received_at = camera.analysis_received_at
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        gray = cv.GaussianBlur(gray, (21, 21), 0)
        det_results = detector(frame, classes=[14], conf=0.25)
        pose_results = pose_model(frame, conf=0.25)

        def bounded_box(box):
            value = valid_box(box.xyxy[0].tolist())
            if value is None:
                return None
            x1, y1, x2, y2 = value
            return valid_box((max(0, x1), max(0, y1), min(frame.shape[1], x2), min(frame.shape[0], y2)))

        people = []
        for box in det_results[0].boxes:
            bounds, confidence = bounded_box(box), float(box.conf)
            if bounds is not None and math.isfinite(confidence) and 0 <= confidence <= 1:
                people.append((bounds, confidence))
        poses = []
        pose_result = pose_results[0]
        if pose_result.keypoints is not None and pose_result.boxes is not None:
            points, confidence = pose_result.keypoints.xy, pose_result.keypoints.conf
            for index, box in enumerate(pose_result.boxes):
                bounds = bounded_box(box)
                if bounds is not None:
                    joints = (usable_keypoints(points[index].tolist(), confidence[index].tolist())
                              if confidence is not None and index < len(points) and index < len(confidence) else None)
                    upper = (usable_keypoints(points[index].tolist(), confidence[index].tolist(), required=(5, 6, 9, 10))
                             if confidence is not None and index < len(points) and index < len(confidence) else None)
                    poses.append((bounds, joints, upper))
        boxes = [item[0] for item in people]
        pose_matches = match_boxes(boxes, [item[0] for item in poses])

        # Inference stays outside the camera lock. A disconnect during inference
        # cannot repopulate that camera's cleared tracking/timer state.
        with camera.condition:
            if generation != camera.generation:
                return []
            if received_at is not None and not 0 <= time.time() - received_at < LiveCamera.RESULT_TTL:
                self.reset()
                return []
            if self.motion_generation != generation or self.prev_frame is not None and self.prev_frame.shape != gray.shape:
                self.reset()
            self.motion_generation = generation
            mask = None
            if self.prev_frame is not None:
                diff = cv.absdiff(self.prev_frame, gray)
                _, mask = cv.threshold(diff, 25, 255, cv.THRESH_BINARY)
            observations = self.person_tracker.update(boxes, context=(generation, tuple(frame.shape[:2])))
            moving = person_region_motion(mask, boxes, [item['continuous'] for item in observations])
            self.prev_frame = gray
            visible_ids = {item['id'] for item in observations}
            self.survivor_observations.prune(visible_ids)
            for track_id in list(self.stationary_timers):
                if track_id not in visible_ids:
                    self.stationary_timers.pop(track_id, None)
            detections = []
            for index, ((x1, y1, x2, y2), confidence) in enumerate(people):
                track = observations[index]
                keypoints = poses[pose_matches[index]][1] if index in pose_matches else None
                upper = poses[pose_matches[index]][2] if index in pose_matches else None
                observed = self.survivor_observations.update(track['id'], (x1, y1, x2, y2), upper,
                                                            moving[index], track['continuous'])
                if not track['continuous'] or observed['immobility_seconds'] in (None, 0) or keypoints is None:
                    self.stationary_timers.pop(track['id'], None)
                thermal_data = thermal_analyzer(thermal_frame, (x1, y1, x2, y2)) if thermal_analyzer else None
                status = self.classifier((x1, y1, x2, y2), frame.shape, keypoints,
                                         moving[index], person_id=track['id'], thermal_data=thermal_data,
                                         stationary_state=self.stationary_timers)
                detections.append({
                    'confidence': confidence, 'x': x1, 'y': y1, 'width': x2, 'height': y2,
                    'box': [x1, y1, x2, y2], 'source': self.source,
                    **status, **observed, 'track_id': track['id'], 'track_number': track['number'],
                    'pose_matched': keypoints is not None, 'motion_observed': moving[index],
                    'motion_scope': 'person_region_image', 'assessment_method': 'sar_heuristic_unvalidated',
                    'age_years': None, 'age_method': 'bounding_box_ratio_unvalidated',
                    'consciousness_method': 'image_motion_rule_unvalidated',
                })
            return detections


def draw_people(cv, frame, detections, age):
    """Render current-frame estimates identically for both cameras."""
    for det in detections:
        x1, y1, x2, y2 = map(int, (det['x'], det['y'], det['width'], det['height']))
        cv.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"Track {det['track_number']}" if 'track_number' in det else 'Person'
        cv.putText(frame, f"{label} {det['confidence']:.0%} | Est. {det['age']} | {det['consciousness']}",
                   (x1, max(12, y1 - 25)), cv.FONT_HERSHEY_SIMPLEX, .4, (0, 255, 0), 1)
        cv.putText(frame, f"{det['injury']} | {det['trapped']}",
                   (x1, max(24, y1 - 10)), cv.FONT_HERSHEY_SIMPLEX, .4, (0, 255, 255), 1)
        cv.putText(frame, f"Gesture: {det.get('gesture', 'Unknown')}",
                   (x1, min(frame.shape[0] - 18, y2 + 12)), cv.FONT_HERSHEY_SIMPLEX, .35, (0, 255, 255), 1)
    cv.putText(frame, f'Detection age {age:.1f}s | estimates need verification', (5, frame.shape[0] - 6),
               cv.FONT_HERSHEY_SIMPLEX, .35, (0, 255, 255), 1)
    return frame
