# Camera streaming and performance

Latest October29: Night firmware application has now been uploaded and
independently verified against flash, after a device-verified full4MB backup.
NewNight target8FPS,failedjoin retry3s,streamsendtimeout5s; QVGA/JPEG12 and existing
thermalenabled/refresh3 retained. Defaulttransmitpower retained (earlier8.5dBm
proposal removed BEFOREupload). Mainfirmware untouched. DashboardPID9960/5050
serves200 and300strace isarmed; runtimeprofile/livevideo acceptance PENDING on
ESP32_CAM. Sensors remain software-paused during this separate camera phase.
See [upload proof](verification/night_fresh2_upload_2026-10-29.json).
Earlier source-only/not-uploaded entries below describe historical stages.

Latest October28 status: conservative-1 is deployed and software-verified
(257Python checks,8browser suites); live acceptance remains pending. See
[the fixed camera/sensor profile](CONSERVATIVE_PROFILE.md) for exact settings,
source-expiry recovery and unchanged firmware/model boundaries. Current physical
comparison has original on robot battery and isolated spare on USB, all6spare
robot/thermal jumpers detached. Thermal reads are intentionally paused. Master
is ON with wheels raised; robot USB unplugged. Restore/test thermal separately
before accepting the full system. Earlier entries below describe prior stages.

Updated 2026-10-29. Applies to the active BIM-Bot-for-SAR checkout.

## October 29 power diagnosis and firmware source changes (not uploaded)

Operator-confirmed: both cameras take robot 5 V (P9/P5) through jumpers into
their 5V pins; the two 3.7 V cells are in series; the LM1085-5.0 gets hot after
about five minutes; during a freeze the picture stops while the Mac stays on
`ESP32_CAM`, both feeds freeze together and recovery takes 30 s to over a minute;
it happens whenever the robot is on. No power bank, meter, capacitors or budget.

Working diagnosis, not a measured result: the linear LM1085 drops the 7.4–8.4 V
battery to 5 V for both cameras and their sensors and turns the rest into heat,
so the shared 5 V likely sags under load. The original camera is also the hotspot
relaying every Night frame, so its trouble freezes both feeds. Its unpaced stream
also keeps the hotspot's send queue full, consistent with the 162 ms median local
ping on clean USB power. Night additionally waited 30 s after every failed join.

Source changes, compiled for `esp32:esp32:esp32cam` with Arduino-ESP32 3.3.12:

- Night (`firmware/nightvision_camera`): 8 fps pacing (was 15), 3 s rejoin after
  a reported failure (was 30 s), 8.5 dBm transmit power once joined, 5 s stream
  send timeout (was 2 s); status `startup_profile` `retry/2`, `stream_profile`
  `fresh/2`. Native tests pass; the thermal-enabled refresh-3 build compiles
  without warnings. Exact pre-change files: `firmware/source_archive/2026-10-29-nightvision-before-fix/`.
- Original (`firmware/original_camera`): hotspot-only Wi-Fi (removed the unused
  station static IP that enabled an idle station interface), 15 dBm hotspot
  transmit power, newest-frame capture (`CAMERA_GRAB_LATEST`) and stream pacing to
  about 8 fps. QVGA/quality 10, all endpoints and the DHT code are unchanged.
  Compile-checked with a stand-in DHT header only. The reviewed original remains
  in `firmware/source_archive/2026-10-27/`.

Neither board has been flashed. Before flashing the original: install Adafruit's
DHT library, back up its full flash, and identify the board. Firmware reduces
load; it cannot make an overheating regulator adequate. Moving at least the
original camera to a separate 5 V source remains the main fix to test.

## Earlier live diagnosis, October 28, about 16:45 Manila

**Connection stability remains unresolved.** The normal trace initially records
Mac `192.168.4.2`, which is also the configured spare address. The next run uses
Mac `.4.4` and freshly verifies the spare's `bimbot-nightvision/2` identity at
`.4.2`; address mismatch does not explain every failure. The latter run has
97 robot-subnet samples, 11 Main upstream errors, no invalid-JPEG count and
only 20 fresh thermal samples. Night has no active viewer in that recording,
so it is not a Night-video acceptance result.

A temporary Main/DHT-only run, with Night and thermal traffic disabled, still
has 29 upstream failures across 89 robot-subnet samples. With the entire app
stopped and the Mac about one metre away, direct `/capture` returns no complete
JPEGs in 21 requests. Separate `/status` reads also fail. The Mac's reported
signal is -40 dBm; the noise/rate fields are not validated quality measurements.
A normal master-switch power reset then yields 9 complete JPEGs in 20 requests,
with later timeouts returning. This reproduces a device/network failure outside
the dashboard. It does not distinguish supply instability, camera/AP firmware
or radio interference. No snapshot fallback was installed from these poor
results.

Operator confirms a single whole-robot switch, both cameras on the battery/power
board, and no multimeter currently available. Both camera LEDs went out with
master OFF while USB remained connected; all wheels were then securely raised
before master ON. Camera and motor supplies cannot be separated using nonexistent
switches. Movement work remains on hold and command URLs remain blank.
The full dashboard is restored; temporary isolated checks have finished.

`features/robot_connection.py` now resolves configured local spare endpoints
through bounded identity-checked GET `/status` requests. It excludes the Mac
and original AP, refuses ambiguous discovery or a changing network, preserves
disabled/custom endpoints and updates runtime targets only. A brief outage
retries the known address before neighbourhood discovery. Generation fences
reject replies from replaced endpoints. Camera diagnostics now record sanitized
transport categories and received byte/chunk/frame counts. Internal manual
capture remains 60 seconds; temporary auto capture can set
`BIMBOT_CAPTURE_SECONDS` within 30–300 seconds.

255 Python tests pass. The previous eight browser suites cover unchanged UI;
neither result establishes physical stability. No firmware/model/wiring or
persistent private-setting change occurred. Current evidence and next steps:
[connection diagnosis](verification/connection_diagnosis_2026-10-28.json).
Next identify current power test points from a clear connection photo, then
verify supply under load when a meter is available. Preserve the original
camera's video/DHT firmware and avoid speculative uploads.

## Current normal-dashboard stability work, October 28

The operator reports frequent reconnects in the normal dashboard, especially
on Thermal, and later reports disconnection during close/quick movement. The
earlier short two-feed acceptance does not establish this longer workflow.
Current software verification is in
[dashboard stability checks](verification/dashboard_stability_2026-10-28.json);
live movement-triggered acceptance remains pending.

Main and Night now retain their subscriptions across monitoring sections, with
an explicit Disconnect control for each camera. Background monitor-camera
delivery runs at a lower rate while keeping its reader/detection active; returning
to that view wakes delivery immediately. Hidden browser tabs pause non-recording
feeds/polls and resume requested connections when shown. Recording remains tied
to its original camera. Close older duplicate dashboard tabs before testing.

The player retries short transport/5xx failures within the same viewer instead
of deleting and recreating it after every failed request. Its original five-second
image deadline remains, as do strict auth/protocol failures. Startup grace allows
the server's own reconnect loop to recover without repeated browser teardown;
it adds no delay to successful images. An independent device-status poll no
longer tears down a frame stream that is supplying fresh images.

Thermal polling is bounded to four starts/second with the existing minimum100ms
pause after a completed slow source read. The visible Thermal view polls cache
at250ms; other views update its summary at1000ms. A reusable32×24pixel canvas
replaces768DOMcell updates while preserving all sensor pixels, the original hue
map, nearest-pixel scaling and4:3layout. Recent validated thermal/DHT acquisitions
survive brief transport failures with explicit retry labels and their original
5s/10s expiry. Invalid/stale data still clears. These changes supersede the earlier
immediate-invalidation and125ms-browser/100ms-source-pause-only descriptions.

A single damaged JPEG is now discarded without restarting the camera or renewing
the previous image's timestamp. A truncated multipart image can resynchronize at
the declared next boundary; persistent corruption still expires and reconnects.
Generated large/high-entropy JPEGs spanning64KiB/chunk boundaries and isolated
damaged/truncated frames are covered by regressions. No physical trigger is
attributed to corruption without recorded live evidence.

Final247Python tests and eight Chrome suites pass. The generated15FPS/120ms
delayed-decoder check paints36frames with max/p95189.4ms reception-to-paint,
one request at a time and no remaining viewers. These are software metrics,
not optical robot latency or a guarantee against physical Wi-Fi/power failure.
Firmware, installed camera quality/FPS, thermal acquisition, wiring, model
weights/input thresholds and the movement hold are unchanged.

Internal60second recording now saves partial cached-state history under
`local_data/diagnostics/normal_dashboard_check.json`, including source-error,
invalid-frame and HTTP-status counters. Summaries separate robot-subnet samples
from later home/internet samples. A temporary one-shot runtime flag
`BIMBOT_CAPTURE_ON_VIDEO=1` starts it after the next valid video frame; it starts
no camera itself and is not written to private configuration. The automatic
trigger is removed after starting. No images, identities or credentials are
saved. This is internal debug instrumentation, not a dashboard navigation item.

## Earlier October 28 recovery investigation

The operator reports delay in both cameras and lost DHT/thermal readings, while
reporting ESP32_CAM connected. Read-only checks on the execution Mac nevertheless
show 192.168.68.73 via 192.168.68.1 and timeouts for the original DHT, spare status
and thermal endpoints. The operator reports a 192.168.4.x address after renewing
DHCP; subsequent tool checks still observe the home route. Preserve both facts;
do not call the physical fault resolved from generated tests.

Detection now starts at most four times per second per camera, replacing pending
work throughout the pause and rejecting expired work before calling either model.
Video delivery remains independent. OpenCV's small-image CPU pool uses one thread
to avoid starting another pool alongside both detector/pose workers. Torch thread
benchmarking on generated images showed no material gain and no Torch override
was installed. Models, confidence/input settings, firmware, camera quality/FPS,
thermal acquisition rate and wiring are unchanged.

DHT now uses its own persistent direct session (`trust_env=False`), bounded
connect/read timeouts, redirect refusal and response cleanup. Errors invalidate
freshness and normal polling recovers after a successful reading. Browser DHT
requests are single-flight and cannot overwrite a newer session; unexpected poll
callback failures reschedule rather than permanently killing the loop. DHT and
thermal API responses explicitly disable caching. No camera connection gates
the sensor workers.

Verification: 239 Python checks and the camera-recovery, thermal-live, dashboard
and headset/guide Chrome suites pass. New checks cover recovery after a DHT
timeout, independent DHT/thermal updates during camera failures, repeating-worker
recovery, detection cooldown/latest-only replacement and stale-work rejection.
The generated 15 FPS source/120 ms delayed browser decoder paints 36 frames with
maximum reception-to-paint age 190.9 ms (p95 190.2 ms), skipping 31 old frames with
one request at a time. This confirms bounded localhost delivery, not a physical
speed improvement or robot-network latency. See
[verification](verification/recovery_latency_2026-10-28.json).

Internal diagnosis: while on robot Wi-Fi, use
[Save system diagnostic snapshot](http://localhost:5050/testing#diagnostics).
This authenticated, same-origin action stores only cached freshness, timing and
Mac IPv4 state under ignored `local_data/diagnostics/latest_system_check.json`.
It starts no device and saves no images, identities or credentials. It remains
available after returning to internet so live evidence does not depend on the
network used to send a chat reply. No guide link is added to product navigation.

The first operator-triggered live snapshot at 14:01:57 Asia/Manila confirms
Mac192.168.4.3, fresh DHT27.2°C/69% and fresh thermal sequence8483 with range
20.38–32.90°C. Thermal's measured HTTP exchange was458.3ms; this is not optical
latency. Both camera viewer counts were0 with no frames since this server start,
so that snapshot does not measure the camera complaint. See
[live sensor snapshot](verification/sensor_recovery_2026-10-28.json).

For a camera snapshot, the internal page now has a separate manual **Start both
camera test feeds** button. It opens the same authenticated current-frame
players in two visible canvases, sharing the production readers and analysis.
Wait for changing video and compare hand movement, then save while both feeds
remain open. Stop releases both viewers; hiding/leaving the page also stops
them. The test does not change illumination, start microphones or send motor
commands. It avoids losing camera viewers while switching to a separate guide
tab.

Follow-up at 14:14:08 Asia/Manila: the operator reports both videos responsive in
the brief manual test. DHT27.4°C/68% and thermal sequence11337/range22.02–32.61°C
are fresh in the saved snapshot after the exercise. Last model-analysis durations
are159.7ms Main/158.9ms Night. The final snapshot has zero camera viewers after
release, so it does not measure sustained dual-camera FPS or concurrent sensor
continuity. See [live follow-up](verification/dual_camera_recovery_2026-10-28.json).

Last-viewer release also detaches the transport once and the camera API closes
it asynchronously. A stalled network close cannot occupy the browser's release
request until its socket timeout, leaving request capacity available for sensors.
The regression test deliberately blocks close and verifies prompt release,
immediate stale-state clearing and one close call. Firmware and source video
quality/FPS remain unchanged. Sustained combined-load testing remains pending.

## Current dashboard delivery, October 21

After the firmware rollback the operator reports improved stability but
continued delay in both videos. The dashboard now renders each camera
onto a stable canvas using authenticated, sequential current-image requests.
It waits for transfer and decoding before requesting another image, so a slow
display skips superseded frames rather than consuming a growing MJPEG response.
The existing MJPEG routes remain supported.

`GET /api/camera-frame/main` and `/nightvision` return a current JPEG and its
sequence, connection generation, reception timestamp and age. A UUID viewer
header, scoped to the authenticated owner, renews a three-second lease on the
same shared upstream reader. The request waits at most750ms for a new frame;
204 means no new image, and never renews visible freshness. DELETE releases the
viewer; abandoned leases expire. Cookies or Authorization headers authenticate
these endpoints; query-string credentials are rejected and all responses use
no-store. Local session expiry/revocation is checked again after the bounded wait.

The player fences old requests/decodes on reconnect, closes decoded assets, and
accepts only increasing cursors within the current connection generation. Image
age plus request/decode time must remain below the existing five-second freshness
limit. Recording draws from the stable selected-camera canvas across tab changes.
Main connection intent, Night retries, light leases and DHT/inference behavior
are preserved. The restored spare JPEG12/15FPS firmware and wiring are unchanged.

All123 hardware-free Python checks pass, including auth, expiry, shared reader,
viewer lease renewal/expiry and stale-generation rejection. Six mocked Chrome
suites pass, including real MP4 recording, source retention, light controls,
recovery, offline sessions and page restoration.

`check_latest_frame_latency.cjs` exercises production snapshot selection and the
real browser player over localhost with generated320x240 JPEGs at15FPS and
120ms injected browser decoding delay. It paints36 images over4.50s, skips30
obsolete source images, and measures maximum reception-to-paint189.8ms
(p95186.2ms). First/last six-frame mean ages153.6/162.2ms show no accumulating
backlog. One request spans fetch/body/decode/paint; stop leaves zero leases and
clients. This fixture replaces ingestion with direct generated publication and
does not measure radio or physical exposure latency. The normal SAR server
PID32353 on5050 serves the exact player/dashboard/CSS with no-cache; readiness
routes return200 and the frame endpoint returns401/no-store without auth. This change
cannot remove pauses that already occur before a JPEG reaches the laptop; actual
robot-powered delay after deployment still needs operator confirmation.

## Current firmware rollback, October 21

The operator reports the lower-traffic update makes both videos much slower and
less stable when the spare is powered from P9, and explicitly requests the
previous update. Its earlier USB acceptance does not establish robot-powered
acceptance. Do not resume lower-traffic tuning from that USB result.

Canonical source is restored to the exact retained pre-update build: QVGA,
JPEG quality12,15FPS pacing, and the original512-byte status response. The new
profile helper, stream metrics and their locks/counters are removed. Startup
retry, thermal OFF, light leases, PSRAM latest buffers, staged packets and
TCP_NODELAY remain. Public source/pacing matches the saved build and all four
strict native pacing/startup/lease/packet checks pass. The saved previously
verified firmware artifact is used for the rollback, retaining its existing
private Wi-Fi settings without inspecting them. Rollback upload completed with verification: exit0, existing bootloader/partitions
verified, app0/application written and hash-verified, automatic reset reported.

The app now runs normally without the temporary per-frame wrappers or extra
status probes. Earlier dashboard reconnect fixes and the five-second read limit
are retained as they were before the rejected firmware experiment. Original
camera/DHT firmware and the separate UI checkout are unchanged. This rollback
restores the requested software; it is not a new power-capacity or latency test.

Historical trial: the rejected JPEG18/8FPS build passed native/build checks and
had a short USB capture with no source errors, but that did not predict the
robot-powered result. Its P9 capture subsequently showed send failures and
multiple source reconnections while uptime increased. The electrical/radio cause
was not established; those observations do not override the operator's rollback.

## Latest latency changes, October 19

The operator subsequently confirmed several seconds of lag persisted after
upload, restart and refresh. A second investigation reproduced accumulation
when JPEG validation/rendering runs more slowly than incoming images: receiving
and processing on the same thread leaves old HTTP chunks in the TCP stream.
Normal unloaded QVGA decoding measured about 0.3 ms here; the deliberately slow
decoder test identifies a remaining software path, not the physical bottleneck.

The reader now drains and parses upstream data independently of decoding and
rendering, using one replaceable pending JPEG. A separate publisher validates
and processes the latest waiting image. Original reception times are retained
for freshness and inference; expired video and work from an earlier connection
are rejected. Disconnecting the final viewer clears pending video and inference.
Status adds `video_processing_ms` (arrival-to-publication time) and
`skipped_video_frames` (pending images replaced during this connection). These
are laptop pipeline metrics, not exposure-to-screen measurements.

This follow-up passes all 107 Python tests, including disconnect during decoding,
reconnection fencing, invalid-JPEG reconnect and preserved arrival timestamps.
Real localhost chunked HTTP at 15 FPS with a deliberately 120 ms decoder produced
frame 20 at 1,200.1 ms old with synchronous processing. The revised path kept its
maximum age 186.8 ms and frame 20 age 131.5 ms, replacing 16 waiting images. A Chrome
rerun of actual production framing also passes: first image 13 ms, next image 13 ms
after sending. These are controlled software results. The operator subsequently
confirmed **“the latency is good now.”** The issue is resolved to the operator's
satisfaction; no numerical hardware delay/FPS or separate Main-connected
comparison result was supplied. Preserve the accepted configuration. No further
firmware, quality or frame-rate change was made.
The updated app is active as PID 22258/session 97507 on port 5050; root/login and
normal GET `/api/local-session` respond 200 without inspecting session data.

The browser stream now sends the next part's complete MIME headers immediately
after each JPEG. Real Chrome testing found that the previous framing waited for
the next exposure before painting the completed image. Adding `Content-Length`
or a boundary alone did not fix that wait. The new framing starts the next image
part without its unknown length, then sends its pixels when available. An
independent MIME parser validates consecutive images with different sizes.

`LiveCamera` also uses urllib3's available-byte `read1` API when supported. This
avoids waiting to fill a fixed 1024-byte receive block on plain multipart sources
and lets the parser discard complete older images together. Older HTTP adapters
retain the existing reader. ESP-IDF's chunked stream already flushed each HTTP
chunk in the old reader; this receive change alone does not establish a speedup
for the spare. JPEG validation, current-image overlays and detection settings
are retained.

The spare now copies each complete multipart frame into one reusable packet,
then returns its camera buffer before sending. This lets continuous capture
replace the waiting image while Wi-Fi is busy, rather than holding one of the
two camera buffers through a slow send. Storage prefers PSRAM, grows only as
needed and is bounded at 160 KiB. Allocation failure or an oversized frame falls
back to the original direct send. Each staged packet uses one HTTP chunk;
TCP_NODELAY avoids waiting to combine small writes. A blocked socket write now
times out after two seconds instead of five; this is not an end-to-end latency
limit. `/status` retains `bimbot-nightvision/2`, adds `stream_profile:"fresh/1"`
and reports `stream_staging_active` for the path currently in use.

QVGA, JPEG quality12, the 15 FPS pacing ceiling, automatic exposure, white-light
controls and thermal-OFF configuration are retained. These changes reduce
avoidable waits without forcing shorter, darker exposures. The original
camera's firmware and DHT wiring are unchanged.

### Measured software results

- All 101 Python tests pass, including framing, validation, freshness and
  inference isolation. Native packet tests check that returning/overwriting a
  camera buffer cannot change the staged image, storage reuse, allocation
  failure and bounds. Packet tests also pass under ASan/UBSan; existing pacing
  and light-lease tests pass.
- `scripts/check_browser_camera_latency.cjs` serves the actual production
  `LiveCamera.frames()` output to Chrome with generated images 900 ms apart.
  Previous framing painted the first image at 919 ms and the second 914 ms after
  sending. Updated framing painted at 11 ms and 5 ms after sending, respectively.
  This removes a roughly one-image wait in that controlled test. It is not a
  measurement of camera exposure, Wi-Fi or robot-to-screen delay.
- `scripts/check_camera_pipeline.py` measures plain multipart reception with the
  next exposure held 350 ms: fixed-block reading 352.0 ms versus available-byte
  reading 3.4 ms. ESP-style chunked reception was already immediate: 3.0 versus
  1.5 ms. Two viewers also receive changing frames during deliberately blocked
  inference, share one upstream and release it after closing.

The complete combined sketch compiled with Arduino-ESP32 3.3.12 without warnings:
thermal OFF using existing local settings, 1,029,657 bytes flash/59,144 bytes
globals; thermal ON using placeholder settings, 1,050,165/81,488 bytes. Existing
private values were not inspected or copied. The OFF build was uploaded with
verification to the same user-identified USB spare `/dev/cu.usbserial-110`:
exit0, four verified flash regions. Thermal remains OFF. The active SAR server
was restarted on port 5050 as PID21513 (exec session43988); root/login and normal
GET `/api/local-session` return HTTP200 without reading session response data.
Filtered startup after upload confirms thermal acquisition disabled and a fresh
join reporting `http://192.168.4.3:81/stream`, hotspot -63 dBm/channel1. This is a
successful startup/Wi-Fi result, separate from a decoded video or latency test.

The live comparison below remains necessary. During this work the Mac was at
`192.168.68.79` via `192.168.68.1`; public status requests at last-known spare
`.3` and prior `.2` timed out. No physical FPS or end-to-end timing was obtained.

## Implemented changes

Both cameras use `features/live_camera.py`: one lazy MJPEG reader per camera,
shared by viewers, with separate inference. The reader keeps current video
moving while a model works. There is one waiting inference frame, replaced by
newer input; complete images already superseded in a network batch are skipped.
The final subscriber closes the upstream response and invalidates pending work.
Reconnect generations prevent late results from a previous connection returning
as current evidence.

The main camera retains its existing SAR detector class 14/confidence 0.25, pose,
motion, thermal and condition-classification logic in `analyze_main_frame`.
`generate_frames` now subscribes to the shared stream instead of repeatedly
sending an old annotated image. Camera readings are timestamped when received
by the laptop. Inference results older than two seconds are discarded. Overlays
expire after one second and show their age; boxes are recent observations, not
pixel-aligned tracking of a moving subject. Frames use current image pixels.

Valid camera JPEGs pass through unchanged unless a recent overlay needs drawing.
This removes the previous unconditional decode/re-encode of every spare image
and avoids expanding a compact camera JPEG with OpenCV's default output quality.
JPEG decode validation remains required before a stream becomes live. Model
errors are reported separately and do not disconnect valid video.

The spare firmware retains QVGA/JPEG quality 12 and its existing light controls.
It targets approximately 15 FPS with a 67 ms interval including capture/send time,
instead of adding 100 ms after every frame. With PSRAM it requests two buffers and
`CAMERA_GRAB_LATEST`; without PSRAM it retains one buffer/`WHEN_EMPTY`. Wi-Fi sleep
is disabled. These settings follow the approaches in Espressif's
[camera driver](https://github.com/espressif/esp32-camera/blob/master/README.md) and
[Arduino camera example](https://raw.githubusercontent.com/espressif/arduino-esp32/master/libraries/ESP32/examples/Camera/CameraWebServer/CameraWebServer.ino).
They increase potential throughput and activity; USB supply stability and both
streams sharing the original hotspot must be checked. Original camera/DHT
firmware, camera resolution, model weights and confidence thresholds were not
changed.

The preceding performance sketch was compiled and uploaded with verification to the same
previously user-identified USB spare at `/dev/cu.usbserial-110`. Its public
`/status` includes `stream_target_fps:15` alongside the compatible v2 light API.
The latest status request to last-known 192.168.4.2 was unreachable; no actual
camera FPS, end-to-end delay, decoded hardware frame or optical LED result has
been established by this change.

## Verification

- All 94 Python tests pass, including slow inference with changing video, a
  latest-only pending input, stale result/connection rejection, current-image
  overlays, JPEG validation and subscriber cleanup.
- `python scripts/check_camera_pipeline.py` runs generated JPEGs over real
  localhost HTTP. Two viewers each received 10 changing frames while inference
  was deliberately blocked. Both shared one upstream and closing them released
  the response. It uses no robot configuration, credentials or cloud services.
- All four mocked Chrome suites pass: dashboard, night-light controls, Google
  sign-in and offline recording. Browser recording remains fixed to its selected
  source across tab changes.
- Native C++ light-lease and frame-pacing tests pass, including clock rollover.
  Arduino-ESP32 3.3.12 compiled the matching ESP32-CAM firmware successfully with
  both placeholder settings and existing local settings; upload with verification
  exited 0. Private values and raw device logs were not inspected.

## Live comparison still needed

Use both powered cameras on `ESP32_CAM`, refresh the signed-in dashboard and
compare a moving hand or clock with the real scene. Check the original feed,
DHT freshness and spare light while both streams are active, then record/play
one short clip from each source. Check reconnect behavior after a spare power
cycle. Preserve the last-known address until a new successful address is observed.

Authenticated status exposes `received_fps` and `inference_ms`; main status is in
`/api/device-status` under `main_status`, and spare status is at
`/api/nightvision`. Received FPS is an estimate at the laptop, not display FPS or
end-to-end latency. The 15 FPS firmware setting is a pacing target, not a measured
result. Wi-Fi contention, sensor exposure, light and processing load can reduce
it. A 30 FPS recording canvas cannot create 30 unique camera images from a slower
source. In low light, a longer sensor exposure can also lower frame rate; this
change does not force darker exposures or establish infrared capability.
