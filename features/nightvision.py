"""Independent spare-camera detections over the shared latest-frame pipeline."""
from .live_camera import LiveCamera
from .person_analysis import PersonAnalysis, draw_people


class NightVision(LiveCamera):
    def __init__(self, url, http, cv, np, model_factory, detection=True,
                 pose_factory=None, classifier=None):
        self.model_factory, self.detection, self.detector = model_factory, detection, None
        self.pose_factory, self.pose_model = pose_factory, None
        self.person_analysis = PersonAnalysis(cv, classifier, 'nightvision') if pose_factory and classifier else None
        super().__init__(url, http, cv, np, analyze=self._detect if detection else None,
                         render=self._draw, source='nightvision',
                         on_clear=self.person_analysis.reset if self.person_analysis else None)

    def _detect(self, frame):
        if self.detector is None:
            self.detector = self.model_factory()
        if self.person_analysis is not None:
            if self.pose_model is None:
                self.pose_model = self.pose_factory()
            # The spare view has no calibrated pixel registration to thermal.
            return self.person_analysis.analyze(frame, self, self.detector, self.pose_model)
        result = self.detector(frame, classes=[14], conf=0.25, verbose=False)[0]
        return [{'confidence': float(box.conf.item()),
                 'box': [float(v) for v in box.xyxy[0].tolist()],
                 'source': 'nightvision'} for box in result.boxes]

    def _draw(self, frame, detections, age):
        if self.person_analysis is not None:
            return draw_people(self.cv, frame, detections, age)
        for detection in detections:
            x1, y1, x2, y2 = map(int, detection['box'])
            self.cv.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 1)
            self.cv.putText(frame, f"Person {detection['confidence']:.0%}",
                            (x1, max(12, y1 - 4)), self.cv.FONT_HERSHEY_SIMPLEX,
                            .4, (0, 255, 0), 1)
        self.cv.putText(frame, f'Detection age {age:.1f}s', (5, frame.shape[0] - 6),
                        self.cv.FONT_HERSHEY_SIMPLEX, .35, (0, 255, 255), 1)
        return frame

    def publish(self, jpeg, infer=False, generation=None, received_at=None):
        return super().publish(jpeg, infer=infer and self.detection, generation=generation,
                               received_at=received_at)

    def status(self):
        return {**super().status(), 'detection_enabled': self.detection,
                'person_analysis_enabled': self.detection and self.person_analysis is not None}
