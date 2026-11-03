"""Explicit setup of official YAMNet assets. No microphone, audio or cloud upload."""
import hashlib
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1] / 'local_data/models/yamnet'
ASSETS = {
    'yamnet.tflite': ('https://storage.googleapis.com/mediapipe-models/audio_classifier/yamnet/float32/1/yamnet.tflite',
                       '4d8b4a53282dc83ef04e3e7dbc4fbc98082e34e44ed798e16c3a0cdd4c584faf'),
    'yamnet_class_map.csv': ('https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv',
                            'cdf24d193e196d9e95912a2667051ae203e92a2ba09449218ccb40ef787c6df2'),
    'LICENSE': ('https://raw.githubusercontent.com/tensorflow/models/master/LICENSE',
                '5b17814bf0de8cf65069bc6d7cc38cff19fcaa864d243423ad3ef3db01b52385'),
}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.trust_env = False
    manifest = {}
    for name, (url, expected) in ASSETS.items():
        path = ROOT / name
        data = path.read_bytes() if path.is_file() else None
        if data is None or hashlib.sha256(data).hexdigest() != expected:
            with session.get(url, stream=True, timeout=30) as response:
                response.raise_for_status()
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise RuntimeError('Sound asset exceeded its download limit.')
                    chunks.append(chunk)
                data = b''.join(chunks)
            if hashlib.sha256(data).hexdigest() != expected:
                raise RuntimeError(f'{name} differs from the verified asset. Review the official source before updating.')
            if name.endswith('.tflite') and data[4:8] != b'TFL3':
                raise RuntimeError('Not a TFLite model.')
            temporary = path.with_suffix(path.suffix + '.part')
            temporary.write_bytes(data)
            temporary.replace(path)
        manifest[name] = {'source': url, 'sha256': expected, 'bytes': len(data)}
        print(f'Verified {name}: {len(data)} bytes')
    (ROOT / 'sources.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Assets ready for local sound-event testing. No audio input was opened.')


if __name__ == '__main__':
    main()
