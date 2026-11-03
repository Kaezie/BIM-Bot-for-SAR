# BIM-Bot for SAR

BIM-Bot-for-SAR is the main codebase. The current NEW-BIMBOT-UI frontend is
integrated into its existing Flask backend. SAR owns camera capture, motion
analysis, YOLO detection, pose processing, survivor classification, thermal
analysis, heat-index calculation, and threshold risk assessment.

The [remaining implementation plan](docs/IMPLEMENTATION_PLAN.md) orders the
independent software work, stationary hardware checks and panel questions while
movement testing is on hold. The [panel audit](docs/PANEL_REQUIREMENTS_AUDIT.md)
records requirement evidence and remaining gaps.

For the October 30 review, start with the [groupmate handoff](docs/REVIEW_HANDOFF.md).
It records setup, the installed firmware versus source defaults, software checks,
and the hardware acceptance items that remain open before merging.

## Project layout

- `app.py`: original SAR processing functions plus UI routes/adapters.
- `best.pt`, `yolo11s-pose.pt`: original SAR detector and pose weights.
- `templates/`, `static/css/`, `static/js/`: the integrated UI and browser functions.
- `features/missions.py`, `features/telemetry.py`, `features/movement.py`, `features/routes.py`: support for
  the UI's additional mission/review/report/device panels; they consume SAR results.
- `scripts/preview_ui.py`: hardware-free template preview.
- `tests/`: offline backend and mocked browser checks.
- `docs/REPOSITORY_MERGE.md`: integration decisions and verification.

The main SAR classification logic is `analyze_main_frame`; `generate_frames`
streams current images through a shared reader while inference runs separately.
Both cameras keep a latest-only inference input so slow analysis does not queue
old video. See [Camera performance](docs/CAMERA_PERFORMANCE.md) for the verified
software checks, spare firmware settings and remaining live measurements.
The optional night camera has an independent person detector; its results do not
alter main-camera counts or condition classifications.
All four monitoring tabs keep the main-camera survivor count, ambient DHT readings,
environmental risk, thermal scene range and sound summary visible. Each source is
labelled, with unavailable or stale readings cleared. On another tab, **Connect
main detector** starts the original camera without leaving that view; an existing
main stream continues across tabs. Manual Disconnect is preserved. The sensor
readings use the original full-screen console: floating instruments flank the
image on desktop, with compact strips on phones. The dark teal theme, pill
controls and full-width bottom tabs are retained. Thermal and sound
still need their own configured hardware/data endpoints; showing their status
does not install them or align thermal readings with a camera image.
The alternative UI camera worker, heat-risk calculator, preprocessing/pose
matcher, ML hazard classifier, and duplicate HTML/backend copies were removed.
The old SAR `index.html` is replaced by the Jinja dashboard, with one frontend
script per page and shared auth initialization.

## Run locally

Create a virtual environment, install `requirements.txt`, and configure `.env`
using `.env.example` and [Supabase setup](docs/SUPABASE_SETUP.md). Then run:

```sh
python app.py
```

On this machine, the existing UI environment can run the integrated project:

```sh
cd /Users/christine/Documents/ChatGPT/BIM-BOT/BIM-Bot-for-SAR
/Users/christine/Desktop/BIMBOT/NEW-BIMBOT-UI/.venv-1/bin/python app.py
```

The VS Code workspace uses that existing environment for Run Python File and
the `BIM-BOT: Run Flask server` debug configuration. Set `PORT=5050` in `.env`
if macOS AirPlay Receiver occupies the default port 5000, then open
`http://localhost:5050`.

Both original model files must be available. SAR uses person class 14 and
confidence 0.25, as in its original detector call. Model paths resolve from the
project folder. The sensor listener starts with the server; camera inference
runs when the main camera feed is connected, matching the original SAR flow.

The dashboard shows SAR age, consciousness, injury, entrapment, pose, and thermal
fields as automatic estimates requiring verification. Its risk panel shows the
original threshold rules and preset scores rather than claiming a trained ML
hazard prediction. The existing algorithms are retained; the integration does
not validate classification or medical accuracy.

Google sign-in creates a verified local session that supports offline camera
access for up to 12 hours. Recordings save to this laptop first and queue for
Supabase until internet returns. The app must be running to sync; local copies
remain after upload. See [Offline recording](docs/OFFLINE_RECORDING.md) for the
field workflow, file location, and limits. The service-role key stays server-side.
The copied local `.env`, local recording/session data, and SQLite history are ignored by Git. The two original
SAR model files remain tracked; new model artifacts are ignored.

`THERMAL_URL` is SAR's future thermal video stream. `THERMAL_DATA_URL` is a separate
optional 24x32 temperature-grid JSON endpoint for the dashboard. Neither is
invented when hardware is unavailable. Other optional devices and mission control
use the contracts in [Frontend integration](docs/FEATURE_INTEGRATION.md).

## Verification and preview

See [Night camera setup](docs/NIGHT_VISION_SETUP.md) for the second-camera
network, viewing/recording/detection support, automatic white-light control and
pending hardware checks. The white light requires the updated spare firmware;
it provides visible illumination and does not establish infrared night vision.

```sh
python -m unittest discover -s tests -p 'test_*.py'
python scripts/check_camera_pipeline.py
python scripts/preview_ui.py
```

The preview runs at `http://127.0.0.1:5051/`. It serves templates only; browser tests
inject auth and API fixtures. To run them with Playwright installed:

```sh
node tests/dashboard_ui.cjs
node tests/night_light_ui.cjs
node tests/shared_monitoring_ui.cjs
node tests/laptop_sound_ui.cjs
node tests/movement_ui.cjs
node tests/position_ui.cjs
node tests/auth_ui.cjs
node tests/offline_ui.cjs
```

Set `CHROME_PATH` if using a local Chrome executable. These tests do not contact
robot hardware or upload recordings to the live Supabase bucket.

The Sound tab offers manually selected laptop or robot-headset input, waveform
and relative level, plus optional **local YAMNet sound-event recognition**.
The operator confirms a Bluetooth headset with mic/earpiece. Separate manual
**Survivor communication** controls route headset input to the operator output
and operator input to the earpiece, using exact devices with no fallback. Audio
is not saved or sent to cloud services; clips remain video-only. Real headset
capture, recognition accuracy, simultaneous inputs and audibility need testing.
See [headset setup](docs/HEADSET_SOUND.md) and
[two-way routing](docs/SURVIVOR_COMMUNICATION.md).

For internal testing only, open
[localhost:5050/testing](http://localhost:5050/testing) for ordered stationary
checks, readiness checks that start no devices, and downloadable operator
observations. The main-camera pipeline now adds temporary tracks, independent
image motion, image-inactivity duration and candidate waving/help gestures.
These observations do not validate age, injury, consciousness or entrapment.
Movement stays on hold and no firmware upload is required for this update.

The October 28 connection update retains Main/Night across monitoring sections,
retries brief image-request failures within one viewer and pauses unused hidden
browser tabs. Thermal preserves all32×24pixels on a lightweight canvas with
bounded polling. Recent readings retain their original expiry during a retry.
The current close/rapid-movement regression is tracked separately from earlier
brief acceptance; see [connection investigation](docs/CAMERA_PERFORMANCE.md).

Optional sound runtime and assets are set up separately using
`requirements-sound.txt` and `scripts/setup_sound_model.py`; verified assets
remain in ignored local_data/models/yamnet. Heat screening now rejects invalid
DHT values and uses NWS cool-weather screening before the retained Rothfusz
hot-weather equation. Existing risk cutoffs stay unchanged; low heat risk does
not establish general disaster safety.

Robot position is available under **Mission tools & history → Robot position**.
It supports a future outdoor GPS/GNSS bridge or a separate indoor local tracker.
No receiver or indoor tracker is connected; this is software preparation, not live
tracking. GPS alone does not provide reliable indoor room/floor location. See
[Position integration](docs/POSITION_INTEGRATION.md) for the fix/freshness contract.

**Mission tools & history → Recorded movement** prepares the partner-proposed
command/duration display, replay status and JSON export. Recording-only Uno
firmware was uploaded and independently readback-verified; fresh USB telemetry
was checked with motor power off. The bridge is now stopped during the movement
hold, and physical IR route recording remains pending. Optional bridge settings
are blank in the example. The full supplied Uno source is adapted in
`firmware/robot_movement/`; a localhost USB serial bridge and local trace archives
are implemented. Return remains disabled. See
[Uno USB setup](docs/UNO_MOVEMENT_SETUP.md) and [Movement feasibility](docs/MOVEMENT_INTEGRATION.md). Command history is not
GPS, measured displacement or verified return to base.

The [October 27 panel requirements audit](docs/PANEL_REQUIREMENTS_AUDIT.md)
lists every legible requested feature, current evidence and remaining gaps.
The complete requirements are not yet met; UI labels and software fixture tests
do not establish hardware or classifier acceptance.
