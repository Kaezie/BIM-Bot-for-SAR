# Bluetooth headset sound and recognition

Updated November 13, 2026, Asia/Manila. YAMNet starts automatically whenever
**Start microphone** successfully opens the selected input. There is no separate
recognition enable switch. Starting a microphone remains an explicit operator
action; page load, Sound selection and device discovery do not start recognition.
Stop, input changes/loss, leaving Sound, hidden page and session end cancel
recognition, including pending startup and late results. If the model is
unavailable or inference fails, a visible error directs the operator to stop and
restart the microphone after correcting the issue; levels remain available.

The operator confirms an available
Bluetooth headset with microphone and earpiece. Its model, pairing, placement,
range and live sound performance remain unverified. One headset is one robot
input; the Original/Spare camera microphone cards remain unavailable.

November 13 software verification: five sound-classifier and 50 dashboard
Python checks pass. The generated-audio headset and microphone browser suites
pass, including automatic startup, one pipeline per input session, cancellation
of delayed readiness/classification replies, model failures and cleanup. The
loud-sound suite passes 21 checks at each of 320/390/768/1440 pixels. The cached
YAMNet model loads successfully with checksum/shape validation. These checks
open no real microphone and do not establish live sound-event accuracy.

Use the in-app [stationary testing guide](http://localhost:5050/testing#sound)
for the full operator sequence. Pair through Mac System Settings → Bluetooth,
then use Sound → Headset mounted on robot → Find microphones → select the exact
headset → confirm placement → Start microphone. Discovery releases its probe.
No input is opened on page load or tab selection. A missing/mismatched input
never falls back to the laptop.

## Loud-sound alerts

While the selected microphone is listening, a signal at or above the
**Loud-sound alert threshold** shows a dismissible dashboard banner and saves
a **Sound alert** under Mission tools & history → Alert history. The default is
20% relative RMS signal; adjust it above the observed background level for the
selected input. This threshold is separate from the 3% activity indicator. It
is not a calibrated decibel limit or evidence of a survivor. Loud-sound alerts
use this threshold independently of YAMNet's sound-event classifications.

Continuous noise produces one alert. Another requires at least one second
below the loud threshold and at least ten seconds since the preceding alert.
The local history API also enforces a persistent ten-second cooldown across
dashboard tabs. Dismissing the banner retains its history entry. A failed save
is shown in the banner rather than reported as successful.

Only the source, relative level, threshold and server timestamp are saved in
the laptop's existing history database. Laptop demonstration and operator-
confirmed robot headset events retain distinct source labels. Stop, leaving
Sound, hiding the page, input loss or session expiry ends listening and prevents
new alerts. A visible banner includes the observation time; it is a past event,
not a continuing live measurement. Session expiry clears the banner.

Verification on November 3: 277 Python tests pass, including route validation,
authentication, same-origin checks, offline sessions and persistent cooldown.
`python tests/sound_alerts_ui.py` passes 21 generated-signal browser checks at
320, 390, 768 and 1440 pixels. These checks open no real microphone and do not
establish live headset accuracy, an appropriate field threshold or robot range.

Waveform and relative RMS/peak analysis stay in the browser. YAMNet recognition
starts automatically with the microphone, reusing that exact selected input.
It sends bounded0.975-second mono16kHz float32 frames only
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
results expire rather than remaining current. Stopping the microphone clears
recognition too. Restarting the microphone starts a fresh recognition session.

## Separate two-way audio mode

[Survivor communication](SURVIVOR_COMMUNICATION.md) routes headset input to the
operator output and operator input to the headset earpiece. It is manual and
mutually exclusive with sound analysis, including discovery. Permission denial,
wrong device, disconnection, hidden/closed page and sign-out stop the relevant
streams. This mode requires two distinct input devices and two distinct outputs
and a browser supporting exact output selection. Use Google Chrome if the
in-app browser lacks that capability. Actual simultaneous-input support and
audibility remain physical acceptance checks. Saved clips remain video-only.
