# Frontend integration support

October 27: [Headset input selection](HEADSET_SOUND.md) and the partner-proposed
[recorded movement display](MOVEMENT_INTEGRATION.md) are prepared in active SAR.
The operator subsequently supplies the full Uno/camera sources and confirms USB.
The updated Uno recorder/replay and localhost serial bridge are implemented;
see [Uno setup](UNO_MOVEMENT_SETUP.md). No live headset, serial device or GPS
source was connected by this update. See the [panel requirements audit](PANEL_REQUIREMENTS_AUDIT.md) for the
remaining gaps; the later hardware-purchase discussion is historical context.

The SAR backend owns camera, detection, pose, survivor classification, thermal
analysis, and heat-risk calculation. The UI consumes those results. See
`REPOSITORY_MERGE.md` for the corrected merge scope and removed overlapping code.

## Original SAR APIs

- `GET /video_feed`: SAR MJPEG stream and its original processing pipeline.
- `GET /api/survivors`: original classifications, plus availability and update time.
- `GET /api/sensor-data`: original readings/risk scores, plus freshness metadata.
- `GET /api/thermal`: original thermal-availability status.
- `POST /toggle_recording`: original start/stop recording status.

The dashboard uses a verified local session cookie after Google sign-in.
Protected APIs also support a verified Google-linked Supabase Bearer token.
The current camera-frame route uses the cookie or Authorization header.

## Additional UI support

- `/api/local-recordings`: local MP4 save, listing, download and sync queue.
  Existing cloud-only clips are listed through `/api/recordings` and opened
  through `/api/recordings/link`. [Recording workflow](OFFLINE_RECORDING.md)
- `/api/history`: persisted SAR sensor samples and risk/detection alerts.
- `/api/mission`, `/api/mission/start`, `/api/mission/stop`: mission controls with
  operator ownership and acknowledged robot commands.
- `/api/survivor-events` and `/api/survivor-events/<id>/review`: SAR snapshots and separate operator reviews.
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

### GPS and local robot position

October25 request: position indoors and outdoors; operator confirms no GPS/GNSS
module is owned. The software section at Mission tools & history → Robot position
and authenticated `/api/position-data` accept future global fixes or local metre
coordinates through `POSITION_URL`. Missing/no-fix/stale data clears current
coordinates. Global fixes require explicit fix validity and acquisition age plus
sample sequence. No laptop location is requested and maps load only on a manual
external-link click. Robot observation position is distinct from survivor
coordinates. Hardware acquisition, firmware bridge and indoor tracking remain
unimplemented/unverified. See [Position integration](POSITION_INTEGRATION.md).

### Sound sources

The Sound tab supports the selected laptop microphone or a headset mounted on
the robot. Local YAMNet recognition starts with the selected microphone when
its optional runtime and model are installed. The separate two-way audio
controls route the headset microphone and earpiece through the laptop.
Camera microphone cards require independent inputs, and the current ESP32
camera firmware supplies video and sensor data. Keep optional `SOUND_URL`
telemetry separate from laptop or headset audio. Saved clips are video-only.
[Headset setup](HEADSET_SOUND.md) · [Two-way audio](SURVIVOR_COMMUNICATION.md) ·
[Camera audio design notes](SOUND_INTEGRATION.md)

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
