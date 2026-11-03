# Bluetooth headset sound and recognition

Updated October 27, 2026, Asia/Manila. The operator confirms an available
Bluetooth headset with microphone and earpiece. Its model, pairing, placement,
range and live sound performance remain unverified. One headset is one robot
input; the Original/Spare camera microphone cards remain unavailable.

Use the in-app [stationary testing guide](http://localhost:5050/testing#sound)
for the full operator sequence. Pair through Mac System Settings → Bluetooth,
then use Sound → Headset mounted on robot → Find microphones → select the exact
headset → confirm placement → Start microphone. Discovery releases its probe.
No input is opened on page load or tab selection. A missing/mismatched input
never falls back to the laptop.

Waveform and relative RMS/peak analysis stay in the browser. The optional
**Enable local YAMNet sound recognition** control is off until selected after
microphone startup. It sends bounded0.975-second mono16kHz float32 frames only
to this laptop's authenticated local server. Raw audio is not saved or sent to
cloud services. The AudioWorklet continuously resamples actual input; it does
not concatenate disconnected analyser snapshots. A silent output keeps the
worklet running without playing microphone audio.

The [official YAMNet model](https://www.tensorflow.org/hub/tutorials/yamnet)
classifies sound events. This integration reports possible speech, shout,
scream, crying and knock/tap candidates, other audio or uncertainty. It does
not transcribe the word help, locate a survivor, confirm human presence or
provide calibrated probabilities. Current0.35score gate is an unevaluated
software default. Live positive/negative tests and false-alarm measurements
remain pending. Generated silence and Google's public speech example are
model smoke checks only.

## Local model setup

The existing .venv-1 environment now contains ai-edge-litert2.3.0. Verified
Google model/label assets and TensorFlow source license are in ignored
local_data/models/yamnet with source URLs and SHA-256 hashes. No camera or
Uno firmware change is needed. To reproduce setup in the project environment:

```sh
python -m pip install -r requirements-sound.txt
python scripts/setup_sound_model.py
```

Setup is explicit. Dashboard startup never downloads a model or accesses audio.
Runtime checksum/shape validation and a single nonqueued inference lock bound
processing. The protected API accepts only62400bytes of finite float32 PCM at
16kHz; wrong formats fail. Late responses after Stop/source change are ignored;
results expire rather than remaining current. Recognition can be stopped while
leaving the waveform input active; stopping the input clears recognition too.

## Separate two-way audio mode

[Survivor communication](SURVIVOR_COMMUNICATION.md) routes headset input to the
operator output and operator input to the headset earpiece. It is manual and
mutually exclusive with sound analysis, including discovery. Permission denial,
wrong device, disconnection, hidden/closed page and sign-out stop the relevant
streams. This mode requires two distinct input devices and two distinct outputs
and a browser supporting exact output selection. Use Google Chrome if the
in-app browser lacks that capability. Actual simultaneous-input support and
audibility remain physical acceptance checks. Saved clips remain video-only.
