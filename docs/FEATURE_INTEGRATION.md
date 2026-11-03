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

### Separate Original and Spare sound views

Microphone procurement and hardware work are on hold at the operator's October25
request while GPS/position support is prepared. Existing optional laptop analysis
remains off unless the operator starts it.

Current constraint, October 25: no budget for additional hardware, with a
November 2026 defense. The operator confirms sound detection is required in the
approved thesis scope. Inventory existing or borrowed real audio inputs first;
no purchase, source substitution or removal of the requirement is authorized by
this constraint. Candidate phone/headset inputs remain unverified. Any alternative
must identify its actual location/source, and two views require independent inputs.

Requested October 25: the Sound section should show the original camera's
microphone and the spare camera's microphone as separate visual sources.
This is a requirement awaiting added microphone hardware, not implemented live
dual-camera audio. The current `SOUND_URL` contract is a single optional sensor
endpoint and must not be duplicated or relabelled as two real microphones.

After the front-photo review, the operator identifies the sticker camera as
Original and the camera without a sticker as Spare, and confirms having no
separate microphones beyond the shown hardware. Neither photographed board has
a visible microphone. The earlier report of hearing robot sound during live
viewing does not establish an audio input. The current recorder in
`static/js/dashboard.js` uses only `recordCanvas.captureStream(30)`; neither
checkout requests or adds a microphone track. The current spare firmware
publishes JPEG video and thermal data, with no audio acquisition or transport.
No personal recording or new microphone capture was used for this audit.

Once microphone hardware is added and verified, implement two labelled channels:

- Original camera microphone: independent activity/level and freshness.
- Spare camera microphone: independent activity/level and freshness.
- Draw a waveform only when actual audio samples are available. A digital
  sound-trigger module alone cannot provide a genuine waveform.
- Show unavailable/configuration-pending states independently; one missing
  source must not be replaced by the other source or by generated activity.
- Label uncalibrated amplitude as relative level; claim sound-pressure dB only
  with an appropriate calibration. Voice/tapping recognition needs separate
  implementation and validation.

The operator selected investigating microphones on the existing cameras. A
software-only build combining the complete spare source, enabled thermal
profile4 and explicit I2S1 receiver APIs passes with placeholder credentials.
It assigns no microphone pins and was not uploaded. Three signal GPIOs are
needed, and the spare's remaining header pins have boot or UART restrictions.
Original source is now located in the operator-supplied `pineappleapi/bimbot`
repository: `BIM-BOT_arduino_setup/ESPCAM.ino`, release commit
`ff1947f6a2f6347de9d05d39ed44cab31698ceef`. It specifies AP mode and DHT11 on
GPIO13, with no microphone/audio path. See [Original source audit](ORIGINAL_CAMERA_SOURCE.md).
No exact installed-firmware comparison or original upload was made. See
[Sound integration investigation](SOUND_INTEGRATION.md) for the resource audit,
build evidence, hardware criteria and remaining inputs. Preserve original
camera/DHT and spare camera/thermal/light operation. Leave existing wiring
unchanged until the exact microphone model and the selected camera's pin use
are checked.
Only the laptop is available under the current budget. The optional Laptop
microphone view is labelled as a local demonstration and requires manual Start
and browser permission. Analysis stays in the browser: no audio upload, saving
or addition to video recordings. Camera inputs remain unavailable and local
sound must not become remote telemetry. Page load/tab selection requests no
microphone. Raw audio recording/playback is a separate feature; the robot-
position sound requirement remains unresolved.

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
