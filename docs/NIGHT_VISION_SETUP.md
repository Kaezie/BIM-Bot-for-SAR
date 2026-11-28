# Night camera integration

## Use the installed spare camera

The original ESP32-CAM hosts `ESP32_CAM` and supplies Main video and DHT
readings. The spare joins that hotspot and supplies Night video, the GPIO4
white light and, when enabled, thermal data. Both cameras stay powered while
the dashboard switches views.

Sign in to the running app while online, then join `ESP32_CAM` using the same
laptop and browser. Confirm the spare's current address from its serial output
or an identity-checked status response. The last verified example was
`192.168.4.2`. DHCP can change it, and the laptop can receive the same address in
another session. See [configuration and verification](#app-configuration-and-verification)
and [the offline workflow](OFFLINE_RECORDING.md).

The October 29 upload was readback-verified on the spare. Its installed build
used QVGA/JPEG quality 12, an 8 FPS target, platform-default Wi-Fi transmit
power, and thermal enabled at refresh code 3. The public sketch defaults to
thermal off at refresh code 2. The operator reported on November 16 that the
cameras and sensors worked on the intended robot supply without laptop USB
power. Sustained simultaneous operation and supply margin still require
measurement. [October 29 upload record](verification/night_fresh2_upload_2026-10-29.json) ·
[Live thermal and DHT record](verification/thermal_restoration_result_2026-10-30.json)

The dashboard keeps active feeds connected across monitoring sections and
honors manual Disconnect. Night's optional person, pose and gesture analysis
uses independent tracks and clears stale results. Use **View person details**
for the Night list. Main counts and mission evidence stay Main-only. The adult
or child estimate uses bounding-box height, and the consciousness label uses
image motion. Both need evaluation. Check low-light performance using
[the guided test page](http://localhost:5050/testing). The white LED provides
visible light. External infrared illumination requires verified optics and
hardware.

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

Use one supply at a time. Disconnect USB/base power before powering through the
header. Keep VCC, IO0, RX and TX free during normal operation. For a connected
thermal module, follow its documented 3V3 wiring. See the
[power guide](SPARE_CAMERA_POWER.md) for the previously used supply and alternative
bench setup. Measure voltage and confirm capacity before changing supplies.
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

The complete spare sketch is
[`firmware/nightvision_camera/`](../firmware/nightvision_camera/). It compiles
with Arduino-ESP32 3.3.12 for `esp32:esp32:esp32cam` (AI Thinker ESP32-CAM).
Use the existing installed program for routine testing. These preparation
steps apply only when a spare-camera firmware installation is needed.

1. Confirm the spare board, its camera pin map and its current USB programmer.
2. In the sketch folder, copy `wifi_secrets.example.h` to `wifi_secrets.h` if
   needed. Set the exact robot hotspot name and password privately.
3. Enable `NIGHTVISION_BOARD_CONFIRMED` only after board identification.
4. Keep the entire sketch folder, including `src/`. Verify the sketch for the
   matching board and serial port before any upload. Use the USB base procedure
   above. Keep the original ESP32-CAM and controller firmware as installed.
5. Power the original hotspot and watch the spare's serial output at 115200
   baud for its stream address.

The spare uses QVGA JPEGs at quality 12 and targets about 8 FPS. It requests two
latest-frame buffers with PSRAM, with a single-buffer fallback. Wi-Fi sleep
is disabled, the radio uses platform-default transmit power, and a stalled
stream send times out after five seconds. Port 81 serves video and port 80
serves status and controls. See [camera performance](CAMERA_PERFORMANCE.md)
for dated trials and [thermal setup](THERMAL_SENSOR_SETUP.md) for build options.

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

To check a cold boot with the installed setup, raise the wheels and keep motors
stopped. Power the robot from off without pressing RST. Join `ESP32_CAM`, allow
automatic retries and confirm the spare address if DHCP changes. Check a changing
Night image with the white light off, then verify Main video and fresh DHT in the
same session. If you need to isolate supply or thermal load, follow the
[power guide](SPARE_CAMERA_POWER.md) with all power off before moving jumpers.

## App configuration and verification

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

4. Restart Flask after editing `.env`. Sign in while online, join the robot
   network, then select Night vision. Select Record to capture that feed. Stop
   saves the clip through the [local recording workflow](OFFLINE_RECORDING.md).
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
source and keeps that source if the user switches tabs. New clip names include
`Main` or `NightVision`.

The backend shares one upstream connection between viewers, bounds read time,
JPEG size and startup wait, drops stale detections and closes idle streams.
Its Flask routes still require authentication. The camera's raw local stream is
protected by the existing Wi-Fi network; it has no separate HTTP authentication.
Offline tests mock camera/model/browser data. They do not establish physical
wiring, IR range, inference accuracy, live cloud upload or hotspot capacity.
