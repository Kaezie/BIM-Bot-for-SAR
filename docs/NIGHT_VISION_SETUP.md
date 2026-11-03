# Night camera integration

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

Latest connection note, October 28: the spare is identity-verified at .4.2 in
one failing run with Mac .4.4, but .4.2 is the Mac itself in other runs. Active
SAR now performs bounded identity-checked DHCP rediscovery for configured local
spare stream/thermal endpoints, updating runtime targets only. This does not
resolve the shared camera/AP outages reproduced outside the dashboard. See
CAMERA_PERFORMANCE.md; retain the installed firmware and wiring.

## Current state

October 28 normal-dashboard stability update: after Night is connected, its
viewer now stays subscribed across Main/Thermal/Sound rather than reconnecting
on every return. The selected camera has explicit Connect/Disconnect controls;
Night's manual Disconnect is respected. Hidden browser tabs pause unused feeds
and resume requested ones when shown. Short request failures retry in the same
viewer within the original freshness deadline. White-light policy remains tied
to viewing/recording Night; keeping a background stream does not force its light
on. See [current connection work](CAMERA_PERFORMANCE.md). Operator reports of
close/quick-movement drops remain a separate live acceptance issue; do not treat
software tests or the earlier brief two-feed check as a sustained hardware pass.

October 28, 2026: the operator requests the original camera's person details in
Night vision too. Active SAR now runs the same shared person/pose/gesture
pipeline in `features/person_analysis.py` with independent Night models, tracks,
image-motion history, inactivity and injury-rule timers. The local
`NIGHTVISION_DETECTION_ENABLED` setting is enabled. Models load lazily on actual
viewing. The video overlay includes the estimated adult/child group,
consciousness-rule label and gesture; **View person details** opens a separate
Night-camera list in Mission tools & history. Main counts/reports remain sourced
from Main, and Night detections do not populate them. Stale/disconnected Night
results clear independently. This is software integration, not live accuracy.

There is no numerical-age model: the existing adult/child rule uses bounding-box
height and is unvalidated. Consciousness is also an unvalidated image-motion
rule; stillness does not establish unconsciousness. Candidate waving requires
temporal pose observations and operator confirmation. No thermal coordinates
are mapped onto the Night image. Test stationary one/two-person scenes, hand
gestures, reconnection and the intended lighting using the
[guided tests](http://localhost:5050/testing). Firmware, wiring and model weights
are unchanged; movement remains on hold.

Rollback requested, 2026-10-21: the operator rejects the latest JPEG18/8FPS
profile after returning the spare to P9 power; both videos are reported delayed
and unstable. Canonical source now exactly matches the preceding saved
JPEG12/15FPS firmware with its original status response. New profile/metrics
helpers are removed; automatic startup recovery, thermal OFF, light leases and
latest-frame transport remain. Four strict native checks pass. Rollback upload completed with verification: exit0, all four flash regions
verified and automatic reset reported. Temporary app stream wrappers and extra status probes
are stopped, and the normal app runs on port5050. Original camera/DHT firmware
and earlier dashboard reconnect fixes are preserved. Do not treat the rejected
trial's USB acceptance as robot-powered approval.

Latest USB video result, 2026-10-21: the operator confirms Night video now works
with the spare on USB after correcting active SAR to `192.168.4.2`. A read-only
local check independently verifies expected firmware/camera readiness across
29 HTTP200 status replies and decodes one 320x240 JPEG. Robot-powered startup
without RST after this address correction is the next physical test; thermal
remains disconnected/OFF. This does not establish permanent power capacity.

Latest 2026-10-21: the operator requests automatic robot-power startup without
USB-base RST after a Night-disconnected screenshot. The suspected reset dependence
is not a confirmed cause. Startup recovery is now prepared and compiled in the
canonical spare sketch; native retry/light checks and 16 illumination Python tests
pass, with no review issues. The thermal-OFF build was uploaded with verification
to the identified spare: exit 0, four verified regions. Filtered USB startup after
a normal EN reset confirms camera initialized/automatic startup ready and thermal
disabled. The completed 35-second capture reports Wi-Fi reasons 201/36 and ends
the 30-second no-IP attempt before retrying; no stream/control/thermal address.
The operator later confirms the robot/AP was OFF during USB no-AP debugging,
then powers it ON. Fresh UART reports camera ready, light initially OFF, thermal
OFF and `http://192.168.4.2:81/stream` plus `.2/status`. This **supersedes `.3`**;
active SAR's URL was corrected and restarted (dashboard/login/local-session HTTP200). This is USB
join/startup, not decoded-video or robot cold-boot proof. Original firmware unchanged.

Earlier 2026-10-19: with the robot confirmed powered on, a filtered normal-reset
check confirms the spare sees `ESP32_CAM` at -65 dBm/channel1, joins and reports
`http://192.168.4.3:81/stream`. Thermal remains disabled. This supersedes `.2`.
Active SAR now has a final nonsecret `.3` configuration override and was restarted
on port5050. The UI prototype was not changed. Laptop en0 still routes through
`192.168.68.1` from `192.168.68.79`, and `/status` at `.3` timed out; laptop video
and optical light checks await the robot network. Browser polling now retains
the Night tab's Disconnected/Retrying message after failure instead of replacing
it with Configured/Select-this-camera; refresh the page to load that fix.

The app supports a separate authenticated night-camera MJPEG feed, source-labelled
person detections, browser recording and white-light control with the updated
spare firmware. On 2026-10-18 the updated project sketch was compiled, uploaded
and verified on `/dev/cu.usbserial-110` after the operator confirmed that only the
spare was USB-connected. Original-camera firmware remains unchanged. The filtered
post-reset serial check reported hotspot-not-found reason201 and no stream/control
address within 35 seconds. Physical video and LED operation still need testing
after the spare joins the robot hotspot.
The new photographs identify an Ai-Thinker-style ESP32-CAM with an ESP32-S module
and AMS1117-3.3 regulator, an ESP32-CAM-MB USB programming base with IO0/RST
buttons, and a camera ribbon marked TY-OV2640-V1.0. The visible pin labels match
the reference layout. The exact board revision, infrared optics, IR illumination
wiring and power budget still need confirmation. Software cannot establish infrared sensitivity or supply missing
illumination. No thermal temperatures are inferred from the night camera.
The October 28 extension adds unvalidated SAR condition estimates as described
above; it does not establish infrared sensitivity or condition accuracy.

The original camera and temperature sensor remain on their existing firmware.
The latest operator serial screenshot identifies the hotspot as `ESP32_CAM`.
The new camera joins that hotspot in station mode; it must have its own IP address.
The laptop stays connected to the same hotspot. Joining an AP as a station is
documented in [Espressif's Wi-Fi API](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html).
Direct station-to-station access and dual-stream throughput must be verified on
the original hotspot. A camera feed does not require Arduino serial/GPIO wiring.
The robot hotspot does not establish internet access. Sign in while online to
establish the app's local session, then use the camera and laptop recording
offline. Cloud uploads wait for an internet route; see [Offline recording](OFFLINE_RECORDING.md).

## Hardware findings and missing information

Robot photos show the existing OV2640 camera, an Arduino-style motor shield,
and an LM1085-5.0 regulator. The Arduino model beneath the shield and available
regulator current/thermal headroom cannot be established from those photos.
The small blue emitter/receiver modules appear to be obstacle sensors, not
confirmed night-vision illuminators. The later new-camera photos show a white
flash LED but no separate infrared illuminator.
Two cells are labelled 3.7 V; holder output voltage must be measured. Cell capacity
does not establish the pack voltage or allowable camera/illumination load.

Before robot wiring, obtain:

1. Seller specification confirming the new camera optics/IR-cut configuration.
2. IR lamp/module specification: input voltage, current, wavelength and driver.
3. Battery-holder output measurement and a verified camera power supply.
4. A measured power budget with motors, both cameras and IR light operating.

Do not use a motor/sensor signal pin as a power supply. Do not connect battery
output directly to the camera or infer a connector's voltage from its wire colour.
The supplied RE1.2 board document specifies regulated 5 V input, 3.3 V GPIO and
at least a 1 A supply as a development starting point for that board alone.
This is not a verified requirement for a different camera board or the whole robot.
Do not assume the shield's regulator has spare capacity for the new camera and IR
lights. A dedicated regulated supply may be needed after measurements.
External IR lamps require their specified supply/driver; the sketch does not drive
them. Keep the new lens beside the original lens with both views unobstructed,
insulate exposed board pads and leave antenna/ventilation clearance.

## Firmware preparation (only for a matching pin map)

### Assemble and test using the photographed USB base

1. Disconnect all power. Remove the packing foam before operation.
2. Gently open the camera connector latch, insert the OV2640 ribbon fully with
   its copper contacts facing the connector contacts, and close the latch. Do
   not force it or choose orientation from the red protective-film tab alone.
3. Seat the ESP32-CAM on the matching ESP32-CAM-MB socket. Align the 5V/GND and
   serial pins; do not reverse it or offset it by a socket position. If the base
   labels cannot be read, verify its pin continuity with power disconnected.
4. Connect a micro-USB DATA cable to the base and laptop. Use this USB supply
   alone for the initial test; leave the robot battery disconnected from the new
   camera. If USB power causes resets, investigate supply/cable limitations rather
   than disabling brownout protection.
5. In Arduino IDE select the Espressif ESP32 board package, `AI Thinker ESP32-CAM`
   for the matching board, its new serial port and upload speed 115200. Open the
   reference sketch and prepare its private configuration as described below.
6. Click Verify before Upload. The reference is not a precompiled deliverable.
   If Upload stalls at Connecting, hold IO0, press/release RST, and release IO0
   once flashing starts. Afterwards release IO0 and press RST for normal boot.
   GPIO0 low at reset selects the bootloader, as documented in
   [Espressif's boot guide](https://docs.espressif.com/projects/esptool/en/latest/esp32/advanced-topics/boot-mode-selection.html).
7. Open Serial Monitor at 115200, power the original robot hotspot and copy the
   printed `http://<camera-ip>:81/stream` URL. Keep the original firmware intact.

### Permanent camera power and mounting

In the photographed front/card-socket view (ESP32-CAM lettering at the bottom),
the uppermost pin on the LEFT is marked `5V`, and the next one below is `GND`.
Use the printed labels as the authority, not position alone.

| Verified supply connection | New camera pin |
| --- | --- |
| Regulated +5 V output | 5V |
| Supply return/negative | GND |
| Data connection to Arduino | None; video goes over Wi-Fi |

Use one supply at a time: disconnect USB/base power before powering through the
header. Leave VCC, 3V3, IO0, RX and TX unconnected for normal camera operation.
The exact robot-side supply connector is NOT assigned yet: measure its voltage
and confirm capacity before wiring. A separate USB power bank through the MB
base is an option for initial mounted tests; its capacity must support the camera.
For shared robot power, regulator input range must cover the measured battery
range, its output must be verified at 5 V, and the source/return must be traced.
Do not use the motor output terminals as camera power.

Mount the camera/lens beside the original front camera using an insulated bracket
and standoffs, leaving the temperature sensor, obstacle sensors, wheels and
antenna unobstructed. Secure the board and cable without pulling on the ribbon.
Verify plain streaming first, then test infrared optics and illumination separately.
The white flash on GPIO4 starts off and can be enabled by the updated dashboard
using a short renewable lease. This is visible illumination. No IR-lamp wiring
can be assigned without the actual lamp's input/current specification.

`firmware/nightvision_camera/nightvision_camera.ino` is a source-only reference
using the supplied AI-ESP32-CAM RE1.2/Ai-Thinker-style pin map. It compiles with
Arduino-ESP32 3.3.12 for `esp32:esp32:esp32cam`, using placeholder credentials for
the compile check; physical Wi-Fi and camera operation still need testing. Board
confirmation is required before enabling its compile guard. It is not firmware for the original
camera or the motor controller.

1. Confirm the new board and pin map before following any wiring diagram.
2. Copy `wifi_secrets.example.h` to `wifi_secrets.h` in the same sketch folder.
3. Fill in the existing hotspot password locally. Keep this file out of Git.
4. Enable `NIGHTVISION_BOARD_CONFIRMED` only after hardware verification.
5. Install Espressif's Arduino ESP32 package and select the board matching the
   actual module. The supplied development package uses Arduino-ESP32 2.0.17;
   newer versions also require compiling and checking this sketch.
6. Verify/compile the sketch before uploading. Use the new board's verified USB
   programmer or 3.3 V logic UART procedure. Exact connector pins remain pending.
7. Test the new camera independently on a verified regulated supply. Power the
   original hotspot, then watch Serial Monitor at 115200 for the stream address.

The reference retains JPEG capture at QVGA. Since the October 29 stability
change it targets about 8 fps (previously 15), including capture/send time in its
pacing: the dashboard shows about 6 fps and the original camera's hotspot relays
every Night frame. With PSRAM it requests two latest-frame buffers; otherwise it
retains the one-buffer fallback. Wi-Fi sleep is disabled, and once joined the
transmit power drops to 8.5 dBm because the hotspot is on the same robot. The
stream now allows 5 s (was 2 s) for a stalled send before dropping the viewer.
The installed board keeps its previous build until this source is uploaded.
The performance update was compiled and uploaded with verification to the
previously identified spare; actual frame rate still needs a live test. It
provides `/stream` on port 81 and a separate control server
on port 80, reconnecting to the robot hotspot after a loss. The supplied newer
example only offers single JPEG capture and SD save; the older streaming sketch
has inconsistent camera-model macros, an invalid token and missing helper
definitions. These are why the app cannot simply use either sample unchanged.

### Uploaded sketch supplied for review

The operator supplied `/Users/christine/Documents/Arduino/NightVisionCamera/NightVisionCamera.ino`.
It matches the older `ESP32 CAM/Camera/Camera.ino` sample. It selects
`CAMERA_MODEL_YYH`, while the supplied pin header defines `CAMERA_MODEL_HONGKE`,
contains the invalid statement `char* AP_ssid;yyh`, starts its own Wi-Fi access
point, and prints the hotspot password to Serial. Its folder contains no supporting
header or server implementation. It cannot compile as that single-file folder
and does not implement the spare's station-mode network or light controls. The
earlier `Night stream:` output therefore does not establish that this saved file
is the program currently flashed. The supplied files were retained unchanged.

Use the complete project sketch at `firmware/nightvision_camera/nightvision_camera.ino`
for the spare. The supplied HONGKE camera pin map matches this project's existing
Ai-Thinker-style map; physical board identification and the compile guard still
apply before upload. Do not upload this sketch to the original camera.

### White-light control

After the updated sketch is uploaded to the spare, selecting **Night vision**
automatically requests its white LED. The panel also provides explicit **White
light on/off** controls. Switching away turns it off unless a spare-camera
recording still needs it. Hiding or leaving the page stops lighting requests.
The dashboard shows an acknowledged state; a failed request is shown as a light
error without blocking video viewing.

The firmware uses GPIO4 with PWM brightness 32/255 at 5 kHz, on a timer separate
from the camera clock. This starting brightness limits average LED load; it is
not a measured electrical or thermal power budget. No brightness slider or
external illumination driver is supplied. The LED starts off and turns off on
Wi-Fi loss or when its 15-second lease expires. The page renews the lease every
five seconds while needed, so an unreachable off command cannot leave the light
on indefinitely. Restarting Flask alone cannot add these controls to old firmware.

The control server runs independently of continuous MJPEG streaming:

| Camera route | Purpose |
| --- | --- |
| `GET http://<spare-ip>:80/status` | Reports firmware `bimbot-nightvision/2`, `white_led` capability and illumination state. |
| `POST http://<spare-ip>:80/light?enabled=1` | Enables the bounded white light or renews its lease. |
| `POST http://<spare-ip>:80/light?enabled=0` | Requests immediate light off. |
| `GET http://<spare-ip>:81/stream` | Existing MJPEG video feed. |

The browser uses authenticated `GET`/`POST /api/nightvision/light` on the laptop;
the backend derives the camera's control URL from the configured spare stream,
checks its firmware identity/capability, and refuses the configured original
camera host. Light control requires a private literal IPv4 stream address on port
81 with path `/stream`, without credentials, query or fragment; LAN hostname
aliases are not supported by this proxy. No Wi-Fi password is sent to the browser. The camera's raw LAN
control endpoints, like its stream, rely on the hotspot's network access control.

The spare needs the exact robot hotspot password locally to join it. Retain that
value only in the ignored `wifi_secrets.h`, not in the tracked `.ino`, example
header, logs or project memory. The updated sketch never prints the password.

For the physical check, keep the spare USB powered and its microSD slot unused
(GPIO4 is shared with SD on this board family). First confirm a changing scene
with room lights on. Select Night vision and verify both the visible LED and an
acknowledged light-on status. Compare the same close object with room lights off
and White light off/on; then switch to Main camera and confirm off. Disconnect
the laptop from the robot network and confirm automatic off within 15 seconds
of the last renewal. Confirm original video/DHT continuity throughout. If power
resets or instability occur, stop the light test and investigate USB power/cable
capacity. Passing these checks demonstrates white-light-assisted video only;
infrared-compatible optics and an IR illuminator are still separate prerequisites.

## Diagnosing a spare camera that cannot join

The installed startup fix removes the mandatory network scan before connection.
Earlier firmware marked exact scan matches with `configured robot hotspot`;
that is historical behavior. Check the configured SSID against the original
camera hotspot without displaying its password, keep that camera powered and
move the spare closer if needed.
Disconnect events print the ESP32 reason code with hints for unavailable APs,
authentication/handshake failures or a full hotspot. A hint is not proof of one
specific cause; keep the numeric code when reporting the failure.

Automatic reconnection is disabled so only the sketch controls retries. Each
attempt has 30 seconds to obtain an address, then is explicitly disconnected
before the next begins. This replaces ten-second `reconnect()` calls that could
run while the Wi-Fi stack was already connecting. Upload only to the identified
spare; filtered startup/disconnect output at 115200 can establish its join/address.
Arduino's cloud Offline banner is separate from the camera's local Wi-Fi status.

### Automatic startup and robot cold-boot check

The installed fix waits 500 ms, then retries failed camera initialization three
seconds after each attempt finishes, using a camera PWDN32 pulse (20/100 ms).
Wi-Fi/control startup proceeds independently with one Wi-Fi retry owner
(`wifi_retry.h`). It retries 3 s after an attempt reports failure, for example
when the original camera has not started its hotspot yet, and interrupts an
attempt that reports nothing only after 30 s. The previous source waited 30 s
after every failure, which kept Night offline after each power-on race or hotspot
hiccup. After a network join, status can report `camera_ready` false and
`startup_profile` `retry/2` (`retry/1` before October 29); stream/thermal task
startup waits for camera readiness.
Successful initialization ends these startup retries. This fixes the earlier
return before Wi-Fi; it cannot fix supply dips, loose camera connections or
GPIO0 held low in bootloader mode.

After verified upload, power off before restoring the previously tested P5-to-
spare 5V/GND trial, remove spare USB/base and keep thermal disconnected/OFF.
Raise wheels, stop motors and power the robot from off without RST. Join
`ESP32_CAM`, allow automatic retries and reconfirm the address if DHCP changes.
Check a moving Night image for about one minute with light OFF, then repeat a
full power-off/on cycle without RST; check original video/DHT separately. Stop
for repeated resets/dropout or overheating and power off before wiring changes.
These cold boots remain untested; software checks do not establish supply capacity.

## App configuration and verification

Latest filtered UART on 2026-10-21, after robot/AP power-on, reports the USB-powered
spare at `http://192.168.4.2:81/stream`; this supersedes `.3`. Active SAR received
only a nonsecret `.2` URL override and was restarted on port5050, health pending.
NEW-BIMBOT-UI's private setting was not changed in this correction.
Confirm the printed address again after a power cycle because it is assigned by DHCP.
This confirms the reported Wi-Fi connection; laptop video access remains a
separate check on the robot network.

Selecting **Night vision** automatically opens the configured spare stream.
Explicitly selecting **Main camera** with the mouse or keyboard connects the
original camera if needed, or reuses its existing live stream. Status refreshes
preserve manual Disconnect. Both boards must stay powered; selecting a tab does
not switch USB power or enable external infrared illumination. The updated spare
sketch adds white LED control, not an external IR-light control endpoint. An older
sketch can still stream, while the light panel reports that a firmware update is
needed.

1. Copy the IP printed by the new camera; do not assume it is 192.168.4.1.
2. With the laptop on the robot hotspot, test that camera's printed stream URL.
   Close this direct test before opening the app; firmware serves one stream.
3. Add the following to the local `.env`, substituting the actual address:

   ```dotenv
   NIGHTVISION_CAMERA_URL=http://ACTUAL_CAMERA_IP:81/stream
   NIGHTVISION_DETECTION_ENABLED=true
   ```

4. Restart Flask, sign in and select Night vision. Select Record to capture that
   feed. Stop completes the clip using the existing save/download workflow.
5. Disconnect night-camera power: its status should become disconnected, an
   active night recording should stop, and the page should retry connection.
6. Restore power and verify reconnection. If DHCP assigns another address, update
   `.env` and restart. A fixed address must be chosen after checking subnet/DHCP.
7. Check the main camera and temperature readings while night vision is active.
8. Follow the white-light check above for the currently available hardware. Test
   IR illumination off/on only after compatible optics and a real IR lamp are
   available; software brightness alone does not establish infrared night vision.
9. Evaluate person detections against known scenes at expected range and light.
   The existing SAR model's class 14/confidence .25 settings are reused with a
   separate lazily loaded model instance; that model is not validated on infrared
   images. Set detection to false for viewing/recording without model inference.

Night-camera detections are shown separately and do not increase main-camera
survivor counts or enter mission reports. This avoids counting the same person
twice and avoids applying main-camera condition heuristics to infrared frames.
Annotated inference frames are recorded as displayed; recording has one active
source and keeps that source if the user switches tabs. Clip names contain
`main` or `nightvision`. It is not simultaneous dual-camera recording.

The backend shares one upstream connection between viewers, bounds read time,
JPEG size and startup wait, drops stale detections and closes idle streams.
Its Flask routes still require authentication. The camera's raw local stream is
protected by the existing Wi-Fi network; it has no separate HTTP authentication.
Offline tests mock camera/model/browser data. They do not establish physical
wiring, IR range, inference accuracy, live cloud upload or hotspot capacity.
