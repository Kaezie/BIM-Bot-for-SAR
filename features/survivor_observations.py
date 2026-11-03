"""Temporal visual observations; no medical diagnosis or proof of intent."""
from collections import deque
import time


class SurvivorObservations:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.people = {}

    def reset(self):
        self.people.clear()

    def prune(self, visible):
        self.people = {key: value for key, value in self.people.items() if key in visible}

    def update(self, track_id, box, points, moving, continuous):
        now = self.clock()
        previous = self.people.get(track_id)
        if not continuous or previous and not 0 < now - previous['at'] <= 1:
            previous = None
        history = previous or {'hands': {9: deque(maxlen=32), 10: deque(maxlen=32)}, 'still_at': None}
        history['at'] = now
        if moving is False and continuous:
            if history['still_at'] is None:
                history['still_at'] = now
            still = max(0, now - history['still_at'])
        else:
            history['still_at'] = None
            still = None
        result = {'gesture': 'Unknown', 'gesture_state': 'unknown',
                  'immobility_seconds': round(still, 2) if still is not None else None,
                  'gesture_requires_verification': True}
        if points is None or moving is None or not continuous:
            for values in history['hands'].values():
                values.clear()
            self.people[track_id] = history
            return result
        center = (points[5][0] + points[6][0]) / 2
        span = max(abs(points[6][0] - points[5][0]), .15 * (box[2] - box[0]), 1)
        raised_seen, enough = False, False
        for wrist, shoulder in ((9, 5), (10, 6)):
            raised = points[wrist][1] < points[shoulder][1] - .1 * (box[3] - box[1])
            values = history['hands'][wrist]
            values.append((now, (points[wrist][0] - center) / span, raised))
            while values and now - values[0][0] > 3:
                values.popleft()
            if len(values) < 3 or now - values[0][0] < .4:
                continue
            enough = True
            raised_seen |= raised
            if len(values) < 5 or now - values[0][0] < .6 or not raised:
                continue
            elevated = [entry for entry in values if entry[2]]
            if len(elevated) < .75 * len(values):
                continue
            signs, last_change = [], None
            anchor = elevated[0][1]
            for at, x, _ in elevated[1:]:
                delta = x - anchor
                if abs(delta) >= .12:
                    signs.append(1 if delta > 0 else -1)
                    anchor, last_change = x, at
            reversals = sum(a != b for a, b in zip(signs, signs[1:]))
            amplitude = max(entry[1] for entry in elevated) - min(entry[1] for entry in elevated)
            if reversals >= 2 and amplitude >= .35 and last_change is not None and now - last_change <= .75:
                result.update(gesture='Possible waving/help gesture', gesture_state='possible_wave')
                break
        if result['gesture_state'] != 'possible_wave' and enough:
            result.update(gesture='Raised hand observed' if raised_seen else 'No wave observed',
                          gesture_state='raised_hand' if raised_seen else 'no_wave_observed')
        self.people[track_id] = history
        return result
