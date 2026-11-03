# October 30, 2026 integration review

This branch contains the integrated SAR updates for groupmate review and robot
integration testing. The operator authorizes publishing the review branch and
pull request. Merging into `main`, flashing firmware and declaring requirements
complete remain separate decisions. The groupmate will check the remaining
completion items and verify hardware/software interaction.

## Set up a separate review checkout

```sh
git clone --branch codex/robot-integration-review https://github.com/insignechristine16-glitch/BIM-Bot-for-SAR.git bimbot-review
cd bimbot-review
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Enter the required private configuration locally, following
[Supabase setup](SUPABASE_SETUP.md). Preserve any existing private configuration;
the copy command above is for a new checkout. Neither credentials nor local
recordings, session data, firmware backups or supplied raw sketches are included.
The original detector and pose files already tracked by the project are retained.
Compact verification summaries are shared; large raw captures remain local and
are identified in [the evidence index](verification/README.md).
Optional YAMNet assets are downloaded separately by `scripts/setup_sound_model.py`
after installing `requirements-sound.txt`; see [headset setup](HEADSET_SOUND.md).
Install `requirements-serial.txt` only for the later manually started Uno bridge.

For the normal application, use `PORT=5050 python app.py` and open
`http://localhost:5050`. Initial Google sign-in needs internet. Robot camera and
sensor access needs the robot network. Leave motor command/bridge settings blank
for stationary checks. The application does not flash firmware or start a serial
bridge merely because the branch was checked out.

## Changes supplied

- Shared Main/Night camera readers, independent inference, current-frame display,
  bounded freshness/recovery and metadata diagnostics.
- Main and Night person/pose association, temporary tracks, per-person image
  inactivity and candidate waving observations; existing model weights retained.
- Numeric MLX90640 heatmap, DHT validation and heat-only screening.
- Local MP4 storage and retry queue, offline sessions, mission evidence/reviews
  and reports.
- Exact selected-headset waveform input, optional local YAMNet sound events and
  separate two-way audio routing. Saved clips remain video-only.
- Uno movement recording, an explicitly launched USB bridge and disabled-by-
  default supervised return foundations. Position input remains an adapter.
- Firmware sources, native checks, backend/browser tests and setup/limitation
  records. The separate NEW-BIMBOT-UI prototype is not this review target.

## Installed state and source defaults

| Component | Last verified state | Review boundary |
| --- | --- | --- |
| Main camera | Original firmware retained; volatile JPEG quality 20 applied/read back | Power cycling can restore quality 10. Included original-camera source tuning has not been flashed. Do not upload it as a routine setup step. |
| Spare/Night camera | October 29 application upload and independent device verification; `retry/2`, `fresh/2`, target 8 FPS, thermal enabled with refresh code 3 | Source defaults deliberately keep thermal off and refresh code 2. Reproducing the installed thermal build requires explicit `BIMBOT_THERMAL_ENABLED=1` and `BIMBOT_THERMAL_REFRESH_RATE=3` build definitions after the documented hardware prerequisites. No upload is required to test an already configured robot. |
| Uno | Recording-only firmware uploaded/readback verified; fresh telemetry checked with motor power off | USB bridge currently stopped, physical route tests pending, `BIMBOT_SUPERVISED_RETURN=0`. Preserve the movement hold until the operator resumes with the remote. |
| DHT and thermal | Fresh real data restored in short October 29–30 checks | Calibration and sustained combined-load acceptance remain pending. |
| Headset | Bluetooth mic/earpiece availability operator-confirmed; software/model checks passed | Real pairing, robot mounting, source capture, range, recognition and two-direction audibility not yet accepted. |

Addresses retained in setup notes are last known, not guarantees after restart.
Do not guess pins or substitute the ultrasonic reference for the supplied Uno
sketch. Read the camera, thermal and Uno setup documents before hardware changes.

## Repeatable software checks

```sh
python -m unittest discover -s tests -p 'test_*.py'
python scripts/preview_ui.py
```

The preview on `http://127.0.0.1:5051` serves templates without robot workers.
In a second terminal, browser fixtures can use Playwright 1.62.1:

```sh
npm install --no-save --package-lock=false playwright@1.62.1
npx playwright install chromium
node tests/dashboard_ui.cjs
node tests/camera_recovery_ui.cjs
node tests/dashboard_stability_ui.cjs
node tests/night_light_ui.cjs
node tests/shared_monitoring_ui.cjs
node tests/thermal_live_ui.cjs
node tests/headset_audio_ui.cjs
node tests/laptop_sound_ui.cjs
node tests/movement_ui.cjs
node tests/position_ui.cjs
node tests/auth_ui.cjs
node tests/offline_ui.cjs
node tests/latest_frame_ui.cjs
```

The October 30 browser run uses installed Google Chrome; on macOS set
`CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"` when
using that browser. MP4 capture needs an encoder supported by the chosen browser.
The tests use mocked APIs/generated media, not real robot audio/video or cloud
writes. Localhost socket permission is necessary for transport/browser checks.
Native firmware checks use simulated hardware; they do not prove physical
navigation or electrical performance. Current review results are recorded in
[the software check summary](verification/review_readiness_2026-10-30.json).

## Groupmate acceptance before merge

- [ ] Confirm configuration and model availability on a clean review checkout.
- [ ] Observe both camera feeds and fresh DHT/thermal data together for at least
  five minutes; record stalls, errors and reconnect behavior on robot power.
- [ ] Check Main/Night/Thermal switching, manual disconnect and source loss.
- [ ] Check thermal visual response and compare sensors with reference readings.
- [ ] Evaluate person detection, pose, gestures and condition estimates against
  labeled examples; retain false alarms and misses.
- [ ] Verify the robot-mounted headset source, quiet/background and sound events,
  disconnect behavior and range; separately test audible communication both ways.
- [ ] Save/download/play a real clip, reload offline, then verify later cloud
  upload/retrieval while retaining the local copy.
- [ ] Once movement is explicitly resumed, check IR input, directions, Stop,
  obstacle response, lease/USB loss and actual route capture. Assess supervised
  return separately only after prerequisites; record drift rather than claiming
  guaranteed arrival.
- [ ] Resolve panel YOLOv8 wording versus current YOLOv12s detector/YOLO11s pose,
  GPS/map substitution, unclear Route wording and disaster-scenario scope.
- [ ] Record test conditions, pass/fail/untested status and evidence before merge.

No GPS/local tracker or validated hidden-human detector is installed. Movement
history is not measured position. Age, injury, consciousness and entrapment
outputs remain unvalidated heuristics. Training/evaluation results remain Pending;
software checks and short sensor restoration do not complete the panel checklist.
See [panel audit](PANEL_REQUIREMENTS_AUDIT.md) and
[implementation plan](IMPLEMENTATION_PLAN.md).
