"""Inspect configured local model identities without running the application.

Loads only existing checkpoint files. Does not train, run inference, start
workers, open cameras or serial devices, or modify model weights.
"""
import argparse
from datetime import datetime
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_model(path):
    from ultralytics import YOLO

    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Local checkpoint missing: {path.name}; no download attempted.')
    before = sha256(path)
    model = YOLO(str(path))
    names = model.names
    names = dict(enumerate(names)) if isinstance(names, list) else dict(names)
    config = getattr(model.model, 'yaml', {}) or {}
    checkpoint = model.ckpt or {}
    training = checkpoint.get('train_args') or {}
    after = sha256(path)
    if before != after:
        raise RuntimeError(f'Checkpoint changed during inspection: {path.name}')
    return {
        'file': str(path),
        'sha256': before,
        'weights_unchanged': True,
        'task': model.task,
        'class_count': len(names),
        'class_names': names,
        'architecture_config': Path(str(config.get('yaml_file', ''))).name,
        'training_model_name': Path(str(training.get('model', ''))).name,
        'checkpoint_ultralytics_version': checkpoint.get('version'),
        'module_types': sorted({type(layer).__name__ for layer in model.model.modules()}),
        'keypoint_shape': config.get('kpt_shape'),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Save the identity report as JSON.')
    args = parser.parse_args()
    from dotenv import dotenv_values

    config = dotenv_values(PROJECT_ROOT / '.env')
    report = {
        'inspected_at': datetime.now(ZoneInfo('Asia/Manila')).isoformat(),
        'scope': 'Local checkpoint identity only; no accuracy measurement or training.',
        'runtime': {name: version(name) for name in ('ultralytics', 'torch')},
        'models': {},
        'accuracy_evaluation': 'pending',
        'panel_model_version_alignment': 'pending',
    }
    for role, setting, default in (
        ('detector', 'YOLO_MODEL_PATH', 'best.pt'),
        ('pose', 'POSE_MODEL_PATH', 'yolo11s-pose.pt'),
    ):
        configured = os.environ.get(setting, config.get(setting) or default)
        path = Path(configured)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        report['models'][role] = inspect_model(path)
    detector = report['models']['detector']
    pose = report['models']['pose']
    checks = {
        'detector_task_is_detect': detector['task'] == 'detect',
        'detector_person_class_14_matches_app': detector['class_names'].get(14) == 'person',
        'pose_task_is_pose': pose['task'] == 'pose',
        'pose_person_class_is_0': pose['class_names'].get(0) == 'person',
        'pose_has_17_keypoints': bool(pose['keypoint_shape'] and pose['keypoint_shape'][0] == 17),
    }
    report['identity_checks'] = checks
    report['identity_checks_passed'] = all(checks.values())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['identity_checks_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
