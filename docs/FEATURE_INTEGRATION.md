# Frontend integration support

The SAR backend owns camera, detection, pose, survivor classification, thermal
analysis, and heat-risk calculation. The UI consumes those results. See
`REPOSITORY_MERGE.md` for the corrected merge scope and removed overlapping code.

## Original SAR APIs

- `GET /video_feed`: SAR MJPEG stream and its original processing pipeline.
- `GET /api/survivors`: original classifications, plus availability and update time.
- `GET /api/sensor-data`: original readings/risk scores, plus freshness metadata.
- `GET /api/thermal`: original thermal-availability status.
- `POST /toggle_recording`: original start/stop recording status.

All require the UI user's verified Supabase token. Browser API calls send a Bearer
header; image streams send `access_token` in the query string.

## Additional UI support

- `/api/upload-to-storage`, `/api/recordings`, `/api/recordings/link`: per-user
  recording uploads/library/signed links using the existing private bucket.
- `/api/history`: persisted SAR sensor samples and risk/detection alerts.
- `/api/mission`, `/api/mission/start`, `/api/mission/stop`: mission controls with
  operator ownership and acknowledged robot commands.
- `/api/survivor-events` and `/<id>/review`: SAR snapshots and separate operator reviews.
- `/api/situational-report`: current SAR results and mission evidence as JSON.
- `/api/device-status`, `/nightvision_feed`, `/api/thermal-data`, `/api/sound-data`:
  optional frontend device panels.

## Device configuration

`THERMAL_URL` keeps the original SAR video-stream role. `THERMAL_DATA_URL` is the
optional dashboard JSON endpoint and must return a 24-row by 32-column `grid` of
finite temperatures in degrees C. It is not passed to SAR's video capture.
`SOUND_URL` returns `db_level`, `classification` (`unknown`, `ambient`,
`voice_detected`, or `tapping_detected`) and confidence from 0 to 1.
`POSITION_URL` can report the robot's observation position; it is not a survivor
coordinate estimate. Missing endpoints remain unavailable.

`ROBOT_URL` returns current status, for example:

```json
{"state":"idle","navigation_ready":true,"mission_id":null}
```

`ROBOT_COMMAND_URL` accepts `start`, `stop`, and `heartbeat` with a `mission_id`.
The acknowledgement must contain `acknowledged: true`, the same mission ID, and
`searching` or `stopped` as appropriate. `ROBOT_COMMAND_KEY`, if set, is sent as
`X-Robot-Key`. Commands use a three-second timeout, heartbeat is renewed every
second while searching, and loss of acknowledgement marks the mission uncertain.
A physical controller must stop when its command lease expires.

The simulator (`scripts/simulate_robot.py`, local port 5052) supports these contracts.
Use `THERMAL_DATA_URL=http://127.0.0.1:5052/thermal` for its simulated grid. It does
not supply camera detections or validate the SAR classifiers.
The ultrasonic firmware is a reference requiring pin assignments and calibration.

SAR classifications are automatic heuristic outputs. The integrated UI preserves
them and stores them as evidence; operator reviews do not overwrite the original
classification fields. No trained hazard classifier is added by this merge.
