# SAR base with the integrated UI

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

The following SAR function bodies match the original repository: `calculate_heat_index`,
`calculate_risk`, `classify_age`, `classify_pose`, `classify_injury`, `classify_survivor`,
`get_thermal_frame`, and `analyze_thermal`. `wifi_sensor_listener` and
`generate_frames` also match after excluding their added UI publication hook.
Those hooks only timestamp/persist the original results and notify UI history.
They do not recalculate detections or classifications.

Camera reconnection, motion threshold, every-third-frame inference, class 14,
pose-array matching, stationary timers, annotation labels, and cached annotated
frames all retain SAR behavior. Inference remains tied to the camera stream.
The two original model weights are unchanged.

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
