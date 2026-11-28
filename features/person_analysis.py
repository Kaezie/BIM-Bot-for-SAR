"""Shared person analysis with independent temporal state for each camera."""
import logging
import math
import time

from .live_camera import LiveCamera
from .heat_alerts import HEAT_ALERTS
from .person_tracking import PersonTracker, match_boxes, valid_box, usable_keypoints, person_region_motion
from .survivor_observations import SurvivorObservations


logger = logging.getLogger(__name__)
POSTURE_LABELS = {'standing': 'Standing survivor', 'fallen': 'Fallen figure'}


def estimate_posture(box, points, confidence):
    """Classify visible posture using proportions, independent of image scale."""
    torso = usable_keypoints(points, confidence, required=(5, 6, 11, 12))
    if torso is None:
        return 'unknown'
    width, height = box[2] - box[0], box[3] - box[1]
    dx, dy = ((torso[11][axis] + torso[12][axis] - torso[5][axis] - torso[6][axis]) / 2
              for axis in (0, 1))
    if width >= 1.1 * height and abs(dx) >= max(1.3 * abs(dy), .15 * width):
        return 'fallen'
    if height <= width or dy < max(1.4 * abs(dx), .15 * height):
        return 'unknown'
    legs = usable_keypoints(points, confidence, required=(13, 14, 15, 16))
    if legs is not None and all(legs[end][1] - legs[start][1] >= .09 * height
                                for start, end in ((11, 13), (12, 14), (13, 15), (14, 16))):
        return 'standing'
    return 'unknown'


class PersonAnalysis:
    def __init__(self, cv, classifier, source):
        self.cv, self.classifier, self.source = cv, classifier, source
        self.prev_frame = self.motion_generation = None
        self.person_tracker = PersonTracker(max_gap=LiveCamera.RESULT_TTL)
        self.survivor_observations = SurvivorObservations()
        self.stationary_timers = {}
        self.reported_consciousness = {}
        self.pose_failed = False

    def reset(self):
        self.prev_frame = self.motion_generation = None
        self.person_tracker.reset()
        self.survivor_observations.reset()
        self.stationary_timers.clear()
        self.reported_consciousness.clear()

    def analyze(self, frame, camera, detector, pose_model, thermal_frame=None, thermal_analyzer=None):
        cv = self.cv
        generation = camera.analysis_generation
        generation = camera.generation if generation is None else generation
        received_at = camera.analysis_received_at
        gray = cv.cvtColor(frame, cv.COLOR_BGR2GRAY)
        gray = cv.GaussianBlur(gray, (21, 21), 0)
        det_results = detector(frame, classes=[14], conf=0.25)

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
        if people:
            try:
                pose_result = pose_model(frame, conf=0.25)[0]
                if pose_result.keypoints is not None and pose_result.boxes is not None:
                    points, confidence = pose_result.keypoints.xy, pose_result.keypoints.conf
                    for index, box in enumerate(pose_result.boxes):
                        bounds = bounded_box(box)
                        if bounds is None:
                            continue
                        joints = upper = None
                        posture = 'unknown'
                        if confidence is not None and index < len(points) and index < len(confidence):
                            xy, scores = points[index].tolist(), confidence[index].tolist()
                            joints = usable_keypoints(xy, scores)
                            upper = usable_keypoints(xy, scores, required=(5, 6, 9, 10))
                            posture = estimate_posture(bounds, xy, scores)
                        poses.append((bounds, joints, upper, posture))
            except Exception as exc:
                poses.clear()
                if not self.pose_failed:
                    logger.warning('%s pose analysis failed (%s). Keeping person boxes.',
                                   self.source, type(exc).__name__)
                self.pose_failed = True
            else:
                self.pose_failed = False
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
            now = time.monotonic()
            for track_id, (_, reported_at) in list(self.reported_consciousness.items()):
                if track_id not in visible_ids or now - reported_at >= 30:
                    self.reported_consciousness.pop(track_id)
            for track_id in list(self.stationary_timers):
                if track_id not in visible_ids:
                    self.stationary_timers.pop(track_id, None)
            detections = []
            for index, ((x1, y1, x2, y2), confidence) in enumerate(people):
                track = observations[index]
                _, keypoints, upper, posture = poses[pose_matches[index]] if index in pose_matches else (
                    None, None, None, 'unknown')
                observed = self.survivor_observations.update(track['id'], (x1, y1, x2, y2), upper,
                                                            moving[index], track['continuous'])
                if not track['continuous'] or observed['immobility_seconds'] in (None, 0) or keypoints is None:
                    self.stationary_timers.pop(track['id'], None)
                thermal_data = thermal_analyzer(thermal_frame, (x1, y1, x2, y2)) if thermal_analyzer else None
                status = self.classifier((x1, y1, x2, y2), frame.shape, keypoints,
                                         moving[index], person_id=track['id'], thermal_data=thermal_data,
                                         stationary_state=self.stationary_timers)
                reported = self.reported_consciousness.get(track['id'])
                detections.append({
                    'confidence': confidence, 'x': x1, 'y': y1, 'width': x2, 'height': y2,
                    'box': [x1, y1, x2, y2], 'source': self.source,
                    **status, **observed, 'posture': posture, 'track_id': track['id'], 'track_number': track['number'],
                    'pose_matched': keypoints is not None, 'motion_observed': moving[index],
                    'motion_scope': 'person_region_image', 'assessment_method': 'sar_heuristic_unvalidated',
                    'age_years': None, 'age_method': 'bounding_box_ratio_unvalidated',
                    'consciousness': reported[0] if reported else 'Unknown',
                    'consciousness_method': 'operator_reported' if reported else 'unverified',
                })
            return detections


def _draw_label(cv, frame, lines, color, box):
    height, width = frame.shape[:2]
    x, top, right, bottom = box
    font, scale, padding, line_height = cv.FONT_HERSHEY_SIMPLEX, .4, 3, 13
    label_width = max(cv.getTextSize(line, font, scale, 1)[0][0] for line in lines) + 2 * padding
    label_height = len(lines) * line_height + padding
    left = max(0, min(x, width - label_width))
    # Prefer outside the person box and keep space for the caption.
    y = top - label_height - 2
    if y < 0:
        if bottom + label_height + 17 <= height:
            y = bottom + 3
        else:
            y = top + 3
            if x >= label_width + 2:
                left = x - label_width - 2
            elif right + label_width + 3 <= width:
                left = right + 3
    y = max(0, min(y, height - label_height - 14))
    cv.rectangle(frame, (left, y), (left + label_width - 1, y + label_height - 1), (18, 18, 18), -1)
    for index, line in enumerate(lines):
        cv.putText(frame, line, (left + padding, y + 11 + index * line_height), font, scale, color, 1, cv.LINE_AA)


def draw_people(cv, frame, detections, age, heat_risk=None):
    """Render visual observations with the latest established heat category."""
    heat = HEAT_ALERTS.get(heat_risk, HEAT_ALERTS['unavailable'])
    for det in detections:
        box = det.get('box') or (det['x'], det['y'], det['width'], det['height'])
        x1, y1, x2, y2 = map(int, box)
        held_age = det.get('last_seen_seconds')
        if held_age is not None:
            color = (0, 190, 255)
            cv.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            _draw_label(cv, frame, [f'Person last seen {held_age:.1f}s ago'], color, (x1, y1, x2, y2))
            continue

        label = f"Track {det['track_number']}" if 'track_number' in det else 'Person'
        posture = det.get('posture')
        lying = posture == 'fallen' if posture is not None else det.get('pose') == 'lying'
        still = det.get('motion_observed') is False
        reported = det.get('consciousness') if det.get('consciousness_method') == 'operator_reported' else None
        alert = reported == 'Unconscious' or (lying and still) or heat['severity'] == 'alert'
        caution = lying or still or heat['severity'] == 'warning'
        title = f"{label} {det['confidence']:.0%}"
        if alert:
            title = 'ALERT | ' + title
        elif caution:
            title = 'CHECK | ' + title

        lines = [title]
        if posture in POSTURE_LABELS:
            lines.append(POSTURE_LABELS[posture])
        if lying and still:
            lines.extend(('Lying still. Check responsiveness.', 'Check for visible debris.'))
        elif lying:
            lines.append('Lying posture. Verify condition.')
        elif still:
            lines.append('Little image motion. Verify condition.')
            if det.get('trapped') == 'Possibly Trapped':
                lines.append('Check for visible debris.')
        elif det.get('motion_observed') is True:
            lines.append('Movement observed')
        if reported in ('Conscious', 'Unconscious'):
            lines.append(reported)
        lines.append(f"Heat: {heat['label']}")
        lines.append('Excavation: See area status')
        gesture = det.get('gesture')
        if gesture and gesture != 'Unknown':
            lines.append(f'Gesture: {gesture}')

        color = (150, 160, 255) if alert else (0, 190, 255) if caution else (245, 210, 120)
        cv.rectangle(frame, (x1, y1), (x2, y2), (40, 55, 255) if alert else color, 2)
        _draw_label(cv, frame, lines, color, (x1, y1, x2, y2))
    if any('last_seen_seconds' not in det for det in detections):
        cv.putText(frame, f'Detection age {age:.1f}s | Heat only | Verify hazards', (5, frame.shape[0] - 6),
                   cv.FONT_HERSHEY_SIMPLEX, .35, (0, 255, 255), 1)
    return frame
