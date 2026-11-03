# SAR base with the integrated UI

October 30 review handoff: the original UI merge is already present in shared
`main` at `9c24366407dadb078360bf11d776e9b605103c4e` (PR #1). The subsequent
camera, sensor, audio, tracking and movement-recorder updates are being prepared
on `codex/robot-integration-review` for groupmate confirmation. They do not
establish completed hardware acceptance. See [review handoff](REVIEW_HANDOFF.md).
The source/import notes below describe the earlier integration stage.

## Sources

- Main repository: `https://github.com/Kaezie/BIM-Bot-for-SAR.git`, commit
  `0e73906a02f582a8f070041da12c754aa324a7e2` (SAR ver 2).
- Frontend source: `/Users/christine/Desktop/BIMBOT/NEW-BIMBOT-UI`, including its
  current local files. `MERGE_SOURCES.json` records the 44 initially imported
  source fingerprints; some imported backend files were subsequently removed.
- Integrated copy: `/Users/christine/Documents/ChatGPT/BIM-BOT/BIM-Bot-for-SAR`,
  branch `codex/merge-ui-sar`. Changes are local and uncommitted; nothing is pushed.
- The original UI checkout and original SAR model weights remain unchanged.

## Corrected integration direction

The user's confirmed direction is to keep the existing SAR camera, detection,
classifiers, and processing, integrate the UI functions, and remove overlapping
implementations from the UI import.

At the initial merge the following SAR function bodies matched the original repository: `calculate_heat_index`,
`calculate_risk`, `classify_age`, `classify_pose`, `classify_injury`, `classify_survivor`,
`get_thermal_frame`, and `analyze_thermal`. `wifi_sensor_listener` and
`generate_frames` also match after excluding their added UI publication hook.
Those hooks only timestamp/persist the original results and notify UI history.
They do not recalculate detections or classifications.

At that point camera reconnection, motion threshold, every-third-frame inference, class 14,
pose-array matching, stationary timers, annotation labels, and cached annotated
frames all retain SAR behavior. Inference remains tied to the camera stream.
The two original model weights are unchanged.

October27 follow-up, authorized as the next panel task: main-camera association
now uses spatial pose matching and temporary tracks rather than array indices.
Per-person image regions replace shared scene motion, and missing temporal
evidence explicitly produces Unknown for motion-dependent estimates. The SAR
models, detector class/confidence, risk rules and camera/thermal firmware remain.
See [Person and pose association](PERSON_TRACKING.md) for software checks and
pending real-scene validation. The original `classify_survivor` body therefore
now includes an unknown-motion guard; the initial body-match statement above is
historical, not a claim that this follow-up retained every function verbatim.

The subsequent October27 continuation adds per-track visual gesture/inactivity
observations, local opt-in YAMNet inference, manual headset two-way routing and
a public instruction page with protected readiness APIs. Heat-index/risk and
DHT parsing now include input validation, cool-weather screening and heat-only
wording; original warning cutoffs and rule-score interpretation remain. These
are authorized follow-ups, so the initial verbatim function comparison above
is historical. Model weights and installed firmware remain unchanged.

The new dashboard renders SAR fields using one shared frontend renderer for live
and saved detections. Age/consciousness/injury/entrapment/pose/thermal output stays
visible as SAR automatic estimates; operator reviews remain separate.
The risk panel displays the original threshold results and preset scores.

## Removed overlap

- The imported UI `camera_worker`, frame-condition/cache loop, and configurable
  detector/class-selection implementation.
- `features/environment.py`: competing heat-index and risk assessment.
- `features/vision.py`: competing preprocessing and pose matching.
- `features/ml.py`, `features/model_config.py`, hazard metadata, and optional ML
  requirements: additions from the broader first merge.
- Duplicate `legacy/app.py` and `legacy/index.html` copies and the old root
  `index.html`; original SAR files remain available in Git history.
- Tests and configuration specific to those removed implementations.

## UI additions that remain

Jinja templates, CSS, login/signup/Google auth, browser recording/save/retry,
recording library, history/charts, and the mission/review/report/device panels
remain connected through their required support APIs. Original SAR API paths
are retained and protected by the UI's verified-user authentication.

The new routes consume SAR results. Optional telemetry and mission support add
capabilities without defining a second SAR processing pipeline. Thermal stream
configuration remains `THERMAL_URL`; dashboard grid JSON uses `THERMAL_DATA_URL`
to avoid treating video bytes as temperature data.

The local `.env` was copied privately and history copied using SQLite backup.
Both stay ignored. No cloud settings, live data, or original UI files were changed.
`ngrok_tunnel.py` remains from SAR and is not started during verification.

## Verification

- 22 offline backend tests pass, including original SAR camera/classification
  responses, sensor/threshold/history integration, API auth, and UI support routes.
- The 10 SAR processing function bodies were compared against the base Git commit,
  excluding only the two publication calls.
- Dashboard and account browser suites verify the integrated UI and SAR response
  fields, recordings, reviews, responsive layout, login, and signup.
- Real model/camera-generator smoke check uses a synthetic frame and mocked capture;
  it opens no hardware connection. Model weights and original UI fingerprints
  are checked for preservation.

These checks do not establish survivor-classification accuracy or verify physical
camera, robot movement, live OAuth, or cloud uploads. Run instructions are in the
root README.
