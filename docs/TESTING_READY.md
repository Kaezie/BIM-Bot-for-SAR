# Stationary software readiness and testing

Open [the guided test page](http://localhost:5050/testing) directly. The
instructions are visible before sign-in. To run readiness checks, sign in with
Google while online and then join `ESP32_CAM` when ready to test the cameras and
sensors. The readiness button reads status without starting a camera or
microphone. Download your observations before reloading the page.

Use the installed wiring and firmware for stationary checks. The October 30
capture recorded fresh thermal and DHT samples during a short robot-network
window. On November 16 the operator reported that the cameras and sensors
worked on robot power without laptop USB power. Calibration and sustained
operation remain separate checks. [Thermal and DHT result](verification/thermal_restoration_result_2026-10-30.json)

For a connection problem, use **Save system diagnostic snapshot** while
connected to `ESP32_CAM`. It saves cached timing, sensor freshness and the
laptop's network address in
`local_data/diagnostics/latest_system_check.json` without recording images or
audio. To check both camera readers, select **Start both camera test feeds**
with room lights on, then stop the feeds when the check is complete.
Use **Record 60-second dashboard check** to record connection health while
switching between Main, Night and Thermal on the normal dashboard.
That check writes `local_data/diagnostics/normal_dashboard_check.json`.
[Camera connection evidence](CAMERA_PERFORMANCE.md)

## Ready for controlled testing

| Feature | Software supplied | Still needed |
| --- | --- | --- |
| People and pose | Spatial pose association, temporary IDs, exclusive-region image motion and source resets | Real stationary tracking/pose accuracy, crossing/occlusion/camera motion |
| Night-camera person details | Same person/pose/gesture pipeline with separate models, tracks and timers; independent details list and overlay; detection enabled locally | Actual low-light performance, adult/child/condition/gesture evaluation, real dual-feed cadence |
| Visual help gesture | Per-track temporal raised-hand/waving candidates, upper-body confidence gates and expiring history | Real positive/negative clips and missed-event/false-alarm evaluation; intent is operator verified |
| Image inactivity | Continuous per-track duration, reset on missing/uncertain motion or an observation gap; retained injury timer resets with it | Actual-scene evaluation; this does not establish consciousness or injury |
| Robot sound | Exact selected input; local YAMNet inference starts automatically with the microphone and processes short actual PCM frames | Real headset capture/source check, noise/range and labeled recognition evaluation |
| Two-way audio | Exact two-input/two-output local routing, manual start/stop and fail-closed cleanup | Real concurrent-input support and intelligible audio in both directions |
| Environmental screening | Required finite DHT values, boundary checks, cool-weather screening and heat-only interpretation | Reference-instrument calibration, sensor continuity and disaster-scenario clarification |
| Recording/report workflow | Existing local video save/download, offline session, retry queue, review/report UI | User-created real clip, offline playback and actual cloud sync/retrieval |

Age, injury, consciousness and entrapment classification remain unvalidated SAR
heuristics. New observations do not turn them into trained or medically reliable
classifiers. GPS/automatic victim coordinates, panel model-version alignment,
ambiguous handwriting and disaster-scenario scope remain separate open items.
Movement/obstacle/return work stays **on hold**. No USB bridge is started, motor
command sent or firmware upload needed for this software update.

For Night, select its tab, then **View person details**. Repeat the person and
gesture tests against that camera. It estimates an adult/child group from image
size; it does not estimate age in years. Night results never add to Main counts
or Main mission evidence. Thermal is not registered to the Night image. See
[Night integration](NIGHT_VISION_SETUP.md) and the
[October 28 verification](verification/night_person_analysis_2026-10-28.json).

## Sound implementation and setup

`features/sound_classifier.py` uses the official local YAMNet model with the
LiteRT CompiledModel CPU API. Follow [headset setup](HEADSET_SOUND.md#local-model-setup)
to install the optional runtime and model. Model/label/license files are stored under
ignored `local_data/models/yamnet`; URLs, sizes and SHA-256 hashes are retained.
Startup never downloads a model. Runtime checksums and input/output dimensions
are checked before inference.

The model classifies AudioSet events rather than words. It reports possible
speech/shout/scream/cry/knock/tap, background, other events or uncertainty.
The 0.35 top-score gate is an unevaluated implementation default, not a calibrated
probability or a research result. Source:
[TensorFlow YAMNet tutorial](https://www.tensorflow.org/hub/tutorials/yamnet).
See [headset setup](HEADSET_SOUND.md) for sources and limitations.

Recognition is separately enabled after the selected microphone starts.
An AudioWorklet resamples continuous audio to mono16kHz and sends at most one
in-flight62400-byte/15600-float PCM frame to the authenticated local API. Raw
audio is not saved or sent to a cloud service. Busy requests do not queue.
Stop/source change/sign-out cancels requests and discards late replies; scores
expire after loss of fresh results. Recognition output is not aliased into
Original/Spare microphone telemetry or treated as calibrated decibels.

Two-way mode is independent of recognition. The headset mic routes to the
operator output; the operator mic routes to the headset output. It refuses
default aliases, duplicate roles and returned-device/sink mismatches. Discovery
is brief and manual. Cancellation, permission denial, missing/muted device,
output error, hidden/closed page and sign-out stop streams without a fallback.
Sound analysis and two-way mode stop each other before capture/discovery.
Real output volume/range and simultaneous capture are not software assertions.
See [communication setup](SURVIVOR_COMMUNICATION.md).

## Temporal gesture defaults

`features/survivor_observations.py` uses a maximum three-second/32-sample
per-hand history. A candidate requires at least five samples over0.6seconds,
two meaningful horizontal reversals, wrist amplitude0.35of shoulder span,
raised-hand evidence in at least75percent of samples and a recent change.
Shoulder-relative coordinates reduce whole-body translation effects. A static
raised hand and a single sweep are different observations. Missing upper-body
joints, unreliable image motion or a gap over one second reset the history.
These are prototype defaults awaiting real-scene validation, not selected ML
training parameters or evidence that a person is asking for help.

## Environmental correction

Missing values no longer become zero readings. Boolean/nonfinite/out-of-range
temperature or humidity is rejected without refreshing history. Cool-weather
screening prevents extrapolating the hot-weather Rothfusz polynomial. Existing
35/41°C and41/54°C heat-index warning cutoffs remain; low risk now explicitly
refers only to heat thresholds. Preset rule scores remain uncalibrated.
Reference: [NWS heat-index equation](https://www.weather.gov/ctp/heat).
Numerical/boundary tests do not establish actual DHT accuracy or general safety.

## Evidence

The current verification record is
[stationary software checks](verification/stationary_readiness_2026-10-27.json).
Generated tests cover gesture positives/negatives, independent tracking/timers,
PCM bounds/auth/busy behavior, environmental validation/boundaries, browser
device selection, permission cancellation/denial, wrong input/output, hidden
page, sign-out, disconnect and stale/late result cleanup. The real local model
recognizes Google's public speech example and generated silence in smoke checks;
this is not robot recognition accuracy. No real microphone or speaker was opened
by these tests. Local and cloud recording acceptance remain operator checks.
