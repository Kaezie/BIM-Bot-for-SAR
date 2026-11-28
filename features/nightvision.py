"""Independent spare-camera detections over the shared latest-frame pipeline."""
from .live_camera import LiveCamera
from .person_analysis import PersonAnalysis, draw_people


class NightVision(LiveCamera):
    def __init__(self, url, http, cv, np, model_factory, detection=True,
                 pose_factory=None, classifier=None, heat_risk=None):
        self.model_factory, self.detection, self.detector = model_factory, detection, None
        self.pose_factory, self.pose_model = pose_factory, None
        self.person_analysis = PersonAnalysis(cv, classifier, 'nightvision') if pose_factory and classifier else None
        self.heat_risk = heat_risk
        super().__init__(url, http, cv, np, analyze=self._detect if detection else None,
                         render=self._draw, source='nightvision',
                         on_clear=self.person_analysis.reset if self.person_analysis else None)

    def _detect(self, frame):
        if self.detector is None:
            self.detector = self.model_factory()
        if self.person_analysis is not None:
            # The spare view has no calibrated pixel registration to thermal.
            return self.person_analysis.analyze(frame, self, self.detector, self._estimate_pose)
        result = self.detector(frame, classes=[14], conf=0.25, verbose=False)[0]
        return [{'confidence': float(box.conf.item()),
                 'box': [float(v) for v in box.xyxy[0].tolist()],
                 'source': 'nightvision'} for box in result.boxes]

    def _estimate_pose(self, frame, *, conf):
        if self.pose_model is None:
            self.pose_model = self.pose_factory()
        return self.pose_model(frame, conf=conf)

    def _draw(self, frame, detections, age):
        return draw_people(self.cv, frame, detections, age, self.heat_risk() if self.heat_risk else None)

    def publish(self, jpeg, infer=False, generation=None, received_at=None):
        return super().publish(jpeg, infer=infer and self.detection, generation=generation,
                               received_at=received_at)

    def status(self):
        return {**super().status(), 'detection_enabled': self.detection,
                'person_analysis_enabled': self.detection and self.person_analysis is not None}
