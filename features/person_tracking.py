"""Conservative main-camera associations, not biometric or global identity.

These gates are software defaults, not measured accuracy or training settings.
Ambiguous overlap deliberately starts a new track or leaves a pose unmatched.
"""
import math
import time
from uuid import uuid4


def valid_box(value):
    try:
        box = tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if len(box) != 4 or not all(math.isfinite(v) for v in box):
        return None
    return box if box[2] > box[0] and box[3] > box[1] else None


def intersection_over_union(a, b):
    a, b = valid_box(a), valid_box(b)
    if a is None or b is None:
        return 0.0
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - overlap
    return overlap / union


def match_boxes(boxes, candidates, minimum_iou=.3, ambiguity_margin=.1):
    """Return mutual unambiguous best matches; never reuse a candidate."""
    scores = [[intersection_over_union(box, other) for other in candidates] for box in boxes]

    def best(values):
        ranked = sorted(enumerate(values), key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] < minimum_iou:
            return None
        if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < ambiguity_margin:
            return None
        return ranked[0][0]

    row_best = [best(row) for row in scores]
    col_best = [best([row[col] for row in scores]) for col in range(len(candidates))]
    return {row: col for row, col in enumerate(row_best) if col is not None and col_best[col] == row}


def usable_keypoints(points, confidence, minimum_confidence=.5, required=(5, 6, 7, 8, 9, 10, 13, 14, 15, 16)):
    """Require confidence on joints used by the retained SAR pose rules.

    Unknown joints remain unknown; a detector's masked (0, 0) point must not
    become a body part. Missing confidence cannot establish usable evidence.
    """
    try:
        if len(points) != 17 or len(confidence) != 17:
            return None
        result = [[float(v) for v in point] for point in points]
        if any(len(point) != 2 or not all(math.isfinite(v) for v in point) for point in result):
            return None
        for index in required:
            x, y = result[index]
            score = float(confidence[index])
            if not all(math.isfinite(v) for v in (x, y, score)) or not 0 <= score <= 1:
                return None
            if score < minimum_confidence or (x == 0 and y == 0):
                return None
        return result
    except (TypeError, ValueError, IndexError):
        return None


class PersonTracker:
    def __init__(self, max_gap=2, clock=time.monotonic):
        self.max_gap, self.clock = max_gap, clock
        self.session = uuid4().hex[:12]
        self.next_number = 1
        self.tracks = {}
        self.context = None
        self.last_at = None
        self.frame_number = 0

    def reset(self):
        self.tracks.clear()
        self.context = self.last_at = None
        self.frame_number = 0
        # Numbers are never recycled during this server process.

    def update(self, boxes, context=None, at=None):
        at = self.clock() if at is None else at
        if (context != self.context or self.last_at is not None and
                (at <= self.last_at or at - self.last_at >= self.max_gap)):
            self.reset()
        self.context, self.last_at = context, at
        self.frame_number += 1
        self.tracks = {key: value for key, value in self.tracks.items()
                       if at - value['at'] < self.max_gap and self.frame_number - value['frame'] <= 3}
        keys = list(self.tracks)
        matches = match_boxes(boxes, [self.tracks[key]['box'] for key in keys])
        observations = []
        for index, box in enumerate(boxes):
            previous = self.tracks[keys[matches[index]]] if index in matches else None
            if previous is None:
                number = self.next_number
                self.next_number += 1
                track_id = f'{self.session}-{number}'
            else:
                number, track_id = previous['number'], previous['id']
            observations.append({'id': track_id, 'number': number, 'box': tuple(box), 'at': at,
                                 'frame': self.frame_number,
                                 'continuous': bool(previous and previous['frame'] == self.frame_number - 1)})
        # A missing/ambiguous track is retained briefly for association only;
        # its immobility timer is cleared by the application immediately.
        for item in observations:
            self.tracks[item['id']] = item
        return observations


def person_region_motion(mask, boxes, continuous):
    """Observe image change within exclusive person regions, never health state.

    Widespread background change, heavy box overlap, a first observation or a
    missing frame returns None. This cannot establish world motion or account
    for every camera movement, illumination change or partial occlusion.
    """
    import numpy as np

    unknown = [None] * len(boxes)
    if mask is None or len(mask.shape) != 2:
        return unknown
    height, width = mask.shape

    def pixels(box):
        return (max(0, min(width, math.floor(box[0]))), max(0, min(height, math.floor(box[1]))),
                max(0, min(width, math.ceil(box[2]))), max(0, min(height, math.ceil(box[3]))))

    regions = [pixels(box) for box in boxes]
    background = np.ones((height, width), dtype=bool)
    for x1, y1, x2, y2 in regions:
        background[y1:y2, x1:x2] = False
    background_pixels = int(np.count_nonzero(background))
    # No useful background reference: do not call a full-frame change a person
    # response. These are conservative gates awaiting real-scene calibration.
    if background_pixels < .1 * height * width:
        return unknown
    if np.count_nonzero(mask[background]) > .2 * background_pixels:
        return unknown
    for index, (x1, y1, x2, y2) in enumerate(regions):
        if not continuous[index] or x2 <= x1 or y2 <= y1:
            continue
        exclusive = np.ones((y2 - y1, x2 - x1), dtype=bool)
        for other, (a, b, c, d) in enumerate(regions):
            if other != index:
                left, top, right, bottom = max(x1, a), max(y1, b), min(x2, c), min(y2, d)
                if right > left and bottom > top:
                    exclusive[top - y1:bottom - y1, left - x1:right - x1] = False
        area = int(np.count_nonzero(exclusive))
        if area < .5 * exclusive.size:
            continue
        changed = int(np.count_nonzero(mask[y1:y2, x1:x2][exclusive]))
        unknown[index] = changed >= max(25, .02 * area)
    return unknown
