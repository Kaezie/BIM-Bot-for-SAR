# GY-MCU90640 thermal sensor beside the main camera

Latest October29 restoration: Main/DHT andNightnowoperator-confirmedonrobotpower;
Nightfirmwareretry/2,fresh/2,target8,thermalenabled/refresh3 retained. Restorethe
previous4sensorleadswhilemasterOFF/USBabsent, preservingcamera5V/GNDpowerpair and
originalPS→P5GND route. Exactcurrentmap andstageconstraints are recorded in
[restoration evidence](verification/thermal_restore_ready_2026-10-29.json).
DashboardPID17585/5050 now polls the alreadyidentifiedNight.2/thermal at1Hz; only
validatedfreshdata canpopulate theview. Actualthermalframes remainPENDING. Use
productioncachedsequence/freshnesshistory forinitialverification; do not run a
secondpoller or secondvideo reader simultaneously. Earlierstandalone-first steps
below describe prior workflows. No newfirmwareupload needed for thisrestore.

Updated 2026-10-24, Asia/Manila.

## Current status and resuming the live check

The October22 diagnostic did receive two real, advancing 24x32 thermal frames
from the identified spare at last-known `192.168.4.2`: sequences1461/1464,
ages157/774ms, scene ranges26.18–27.67C and26.22–27.67C. Installed spare firmware
reported thermal enabled/fresh/ready and camera ready. Dashboard integration
stopped at `production_telemetry_not_fresh`, with configuration unsaved and no
decoded Night JPEG verified. This brief result does not establish sustained
operation or temperature accuracy. See the [current project memory](../../Project%20Memory/README.md).

The confirmed wiring is spare3V3→thermalVIN, spare free labelledGND→thermalGND,
yellow thermalSDA→spareIO14, blue thermalSCL→spareIO13, and P5GND→thermalPS.
The white P9GND→spareGND-beside5V jumper is the spare power ground.
Do not change these connections or repeat the older firmware-OFF procedure
solely to resume software testing. If wiring changed, resolve that before power.

For the current debugging session, use the local-only check page at
`http://localhost:5053`. Keep it open, join `ESP32_CAM`, then press **Check
thermal and Night** when the page detects a robot-network address. Wait for
**Done** before returning to home Wi-Fi. It runs locally without an internet
connection or a pre-armed countdown, shows filtered results, and saves only
independently verified public endpoints. The session launcher is
`/private/tmp/bimbot-thermal-local-page.py`; the diagnostic runner is
`/private/tmp/bimbot-direct-debug.py`. It pauses only the dashboard launched
for this session after identifying the spare, so a direct Night JPEG check
has no competing app reader, then restores that dashboard. Original firmware,
wiring and motor controls are untouched. This temporary page is a diagnostic
tool; its availability is independent of the dashboard on port5050.

The firmware pin audit finds no conflict: spare thermal GPIO14/13, camera
SCCB26/27 and flash4 are distinct; the original DHT's GPIO13 is on a separate
board. The Oct22 frames support the mapping, but current connector contact,
power and network state still require live evidence. An unconfigured thermal
endpoint is an application setting, not a sensor pin diagnostic.

For the command-line fallback:

1. Confirm the wiring above is still intact. Keep the spare USB/base unplugged,
   boards secured on an insulating support, and motors stopped.
2. Start the integrated SAR dashboard on port5050 with its normal private
   configuration. Sign in with Google while the Mac still has home internet;
   the existing local session then supports robot-only Wi-Fi.
3. Arm the checker before switching networks. From the integrated SAR checkout,
   use the existing Python environment to run:

   ```sh
   python scripts/check_thermal_sensor.py --wait-network 180
   ```

4. Power the unchanged robot normally and connect the Mac to `ESP32_CAM`.
   The checker skips the laptop and original AP, identifies matching spare
   firmware, and compares direct frames with the actual `Telemetry` class.
   It changes no Wi-Fi, firmware, light, motor or application setting.
5. Read the filtered result in `local_data/thermal_check.json`. `verified`
   requires two fresh advancing real frames and a fresh production poll.
   `configured:false` means this diagnostic has not saved the URL or verified
   the authenticated dashboard. After a pass, save the verified endpoint as
   `THERMAL_DATA_URL`, restart the owned dashboard, and check its Thermal tab.
   Night video and sustained combined operation require separate verification.

The checker reports only static error categories and numeric HTTP status codes;
it does not print response bodies, exception messages or credentials. Return
to home Wi-Fi to report the result if robot Wi-Fi has no internet. Stop and
power off if the robot repeatedly resets or becomes unusually hot.

The remaining sections retain historical setup notes. Their proposed wiring,
thermal-OFF and unverified-reading statements describe earlier stages and are
superseded by the current status above and the project memory.

## Identified hardware

The photographed board is marked GY-MCU90640 / MLX90640, with VIN, GND, RX,
TX, SCL, SDA, NC and PS header labels and a SET I2C solder jumper. This is an
MLX90640 module with an additional controller, not an AMG8833 8x8 board.
The operator confirmed owning MLX90640BAA on 2026-10-19. Its nominal field of view
is 110° horizontally by 75° vertically. Newly supplied `IMG_7387.HEIC` and
`IMG_7388.HEIC` on 2026-10-21 confirm the current GY-MCU90640 controller carrier
and matching manual layout. With the lens up in the front view, left
top-to-bottom is VIN/GND/RX/TX; right is SCL/SDA/NC/PS. SET I2C's two gold pads
appear open; no electrical continuity test has been performed. Further carrier
identity photos are no longer pending.

The module manual lists 3-5 V module input and explains that PS grounded at power
up selects direct MLX90640 I2C access. The bare Melexis chip requires 3.3 V nominal;
module VIN and bare-chip supply are different. The six-page manual lists 42 mA
working current, not a maximum or direct-I2C-mode current, and supplies no
regulator schematic/dropout or I2C pull-up rail specification. NC is internal and
must remain unconnected. Pages 5–6 describe PS-to-GND before power cycling for
direct I2C, disabling the controller's activity. Do not infer the module's serial
protocol or voltage from a generic four-pin MLX90640 breakout tutorial.

Sources:
- [GY-MCU90640 module manual (public mirror)](https://github.com/vvkuryshev/GY-MCU90640-RPI-Python/blob/master/GY_MCU9064%20user%20manual%20v1.pdf)
- [Melexis MLX90640 product specification](https://www.melexis.com/en/product/MLX90640/far-infrared-thermal-sensor-array)
- [Espressif Ai-Thinker camera pin map](https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/camera_pins.h)

## Recommended next path: spare reads thermal, laptop combines sources

### Current ordinary-jumper option, October 21

The operator now confirms the spare is on its USB base and has ordinary jumper
wires only, with no breadboard or ground splitter. The base occupies camera pins;
unplug USB and remove the camera from the base before this proposed robot-powered
arrangement. Restore only the previous P9-to-spare5V/GND power pair with all power
disconnected; original-camera wiring stays in place.

With the battery/USB disconnected and thermal not attached, verify zero DC voltage
then power-off continuity between labelled P5GND and the free spareGND (fourth
down on the camera's3V3 side). A stable beep plus near-zero resistance comparable
to shorted probe tips establishes a common ground. Disconnect probes before
changing meter modes. If this check fails, do not use this PS route.

After that check, the proposed five female-to-female sensor leads are:

| Spare/robot label | Thermal label | Suggested color |
| --- | --- | --- |
| Spare free GND | GND | Black |
| Spare3V3 | VIN | Red |
| Verified common P5GND | PS | Black |
| SpareIO14 | SDA | Yellow |
| SpareIO13 | SCL | Blue |

P5VCC/SDA/SCL remain unused. This makes PS common with module ground without
putting two plugs onto one header. Both existing P9 camera-power leads remain.
PS must be grounded before the subsequent power-up, per the matching manual.
Leave SET I2C pads, RX,TX,NC alone and microSD empty.

Initially leave the IO14/IO13 data leads disconnected. Briefly power stationary,
white lightOFF, and measure module VIN versus GND in DC mode, then idle SDA and
SCL each versus GND. Use accessible labelled solder pads/test points, not probes
forced behind occupied sockets. Expect a supply around3.3V and compatible idle
signals around3.3V, never5V. The earlier unloaded3.28V result does not establish
thermal-loaded supply or internal chip VDD. Power off again before adding the
two data wires. Loaded supply, signal levels, continuity and actual installation
remain untested. Thermal-enabled firmware upload follows these checks; current
firmware staysOFF. This option avoids buying a splitter but depends on verified
common ground. Do not extrapolate the separate USB-base extension below into a
simultaneously connected USB-and-robot supply.

The operator now reports night vision accomplished and requests the next feature.
Preserve the original camera's video/DHT program and keep the spare's working
video/light program. Read thermal with the spare, then send its independent
numeric grid over robot Wi-Fi to the laptop. The thermal readout can appear
with Main camera regardless of which board reads the sensor. Mount the thermal
aperture beside the Main lens, with the spare nearby for a short I2C cable.

For the matching Ai-Thinker spare, **if microSD is unused and both GPIOs are
free**, the new candidate is:

| Thermal carrier label | Proposed spare-side connection |
| --- | --- |
| SDA | GPIO14 |
| SCL | GPIO13 |
| GND | Spare GND and supply ground |
| VIN | Verified suitable 3.3 V source with enough capacity; spare 3V3 only after capacity is established |
| PS | GND before power-up, only if the recorded GY-MCU90640 manual matches the carrier |
| RX, TX, NC/internal-use pin | Unconnected in direct I2C mode |

These are **label-to-label connections, not physical header order**. Spare GPIO13
belongs to a different board from original DHT GPIO13. Original DHT wires remain
unchanged. Spare GPIO4 remains assigned to its white light. The older original
14/15 proposal below avoided its occupied DHT13; spare14/13 avoids GPIO15's boot
strap. Neither thermal mapping has been physically tested.

Check I2C pull-ups are appropriate for 3.3 V ESP32 signals. Chip supply,
module VIN and robot battery/5 V are different nodes. P5 VCC was measured at
4.98 V DC on 2026-10-21 with operator-confirmed probe placement; its spare
capacity remains untested. Do not assign P5 VCC, a motor output or a battery
terminal as the proposed 3.3 V thermal source. Keep the
spare's existing USB power during bench work and use one board power source at
a time. Power off before changing wires and use a distribution connector for
shared grounds rather than forcing multiple plugs onto one header pin.

On 2026-10-21 `IMG_7480.MOV` shows stable **3.280 V DC** at the operator-reported
spare 3V3-to-GND pair while USB-powered, with thermal disconnected. Labels/contact
are obscured, so the pair attribution is operator-reported. This completes the
voltage check but does not establish spare 3.3 V current capacity or thermal
headroom. Carrier identity/manual are now confirmed above; supply capacity and
3.3 V signal pull-ups remain unverified. Keep thermal disabled; no thermal
reading or new upload is established.

### USB-only module power: access constraint

The operator confirms on 2026-10-21 that the spare's 3V3/GND pins are occupied
while stacked on its ESP32-CAM-MB USB base. The earlier direct stacked-base
jumper procedure is retracted because those contacts cannot take both plugs.
Subsequent `IMG_7483.HEIC`/`IMG_7484.HEIC` show power jumpers physically fitted:
camera red at 3V3 and black at GND (fourth pin, IO16/IO0 between), module red at
VIN and black at GND. This is label/contact photo evidence, not end-to-end
continuity or a powered thermal voltage test. Camera EN is not GND. Keep the
camera off the base and USB unplugged pending the extension mapping; keep robot
P5 disconnected.

A possible alternative under review removes the camera from the base and uses
two power extensions from verified base 5V/GND to labelled camera 5V/GND, leaving
camera 3V3 and a labelled common GND accessible. `IMG_7485.HEIC`/`IMG_7486.HEIC`
now show camera front/microSD-up 5V at top-left, GND immediately below. With the
empty base front/USB at bottom (IO0 bottom-left, RST bottom-right), the matching
[MB reference schematic](https://www.olimex.com/Products/IoT/ESP32/ESP32-CAM/resources/ESP32-CAM-MB-S001.jpg)
supports candidate **top-left socket 5V, second-left GND**. This is USB-derived
nominal 5 V through a diode, not a guaranteed exact 5.00 V. Actual base voltage
and polarity still require measurement; wire ends and availability of suitable
male-to-female leads are unconfirmed. No further photo is needed to identify
the candidate socket pair.

The isolated-base check below is presently blocked: the operator confirms no
male-to-female jumper leads are available. It remains unperformed: USB unplugged,
fit two additional suitable
leads to that pair, with camera/thermal not powered from the base. Power only
the base by USB and measure DC across free lead ends (red-to-candidate-5V,
black-to-candidate-GND), recording voltage and sign. USB off before changes.
This option has not been tested; do not connect camera to an unverified base
extension.

The **next proposed assessment is a brief stationary camera-only P5 load trial**
using existing female-to-female thermal power wires. All power off: detach
thermal at both ends, remove camera USB/base, then P5 VCC-to-camera 5V and P5
GND-to-adjacent-camera GND (front/microSD-up, first two left pins). Raise wheels,
keep motors stopped, briefly power the robot and read free opposite camera
3V3-to-fourth-pin-GND in DC mode near 3.3 V. Do not back-probe the occupied
5V/GND. Power off after reading, or stop for resets, dropout or overheating.
Keep thermal disconnected and firmware OFF; preserve original camera/DHT wiring.
This trial has not been wired or tested and does not establish permanent supply
capacity.
The eventual thermal power-only
test would leave SDA/SCL/PS/RX/TX/NC unconnected. A VIN of 3.280 V is within
the module's documented 3–5 V input range, but does not prove that internal MLX
VDD is 3.3 V or that the spare regulator has current headroom. Check those
remaining supply/pull-up conditions before adding SDA14/SCL13 or the PS mode
connection. Keep `BIMBOT_THERMAL_ENABLED` at 0 during this power-only test.

## Latest staged thermal-enabled upload, October21

The operator confirms the isolated spare on its USB base with robot power and
all four thermal leads removed. Fresh USB discovery identifies the sole CH340
VID1A86/PID7523 atUSB110. The prepared enabled build (canonical source with
`compiler.cpp.extra_flags=-DBIMBOT_THERMAL_ENABLED=1`) uploads with exit0, all four
regions written/hash-verified, and automatic RTS reset. Build usage is1,049,305
flash/81,480globals with zero warnings; application binary is1,049,456bytes.
The installed firmware is now thermal-enabled while the public default remains0
until physical checks. No private values were inspected and no camera profile
or original-camera/DHT changes were made.

Filtered12-second USB startup after a normal reset confirms bootreason1 and
camera initialization/automatic readiness, then three sensor-unavailable reports.
No disabled message or thermal grid is observed. This is the expected staged
result with the module unplugged, not a verified sensor or robot-powered result.
The user has confirmed the module PS pin is empty. Verify shared ground, add PS,
and check loaded VIN/idle SDA/SCL before data attachment and connected-sensor
power testing. USB/base removal precedes restoring the same previous P9 pair.
Last-known spare `.2` has not been verified in this run, and THERMAL_DATA_URL
has not yet been configured from a working sensor endpoint.

## Combined spare firmware and upload status

`firmware/nightvision_camera/nightvision_camera.ino` now includes thermal
acquisition alongside stream port 81, control port 80 and GPIO4 light leases.
It has been compiled for `esp32:esp32:esp32cam` with Arduino-ESP32 3.3.12 in both
thermal-enabled and disabled modes using placeholder Wi-Fi settings. On
2026-10-19 the operator then identified the USB-connected spare and requested
upload: the canonical sketch compiled with existing local Wi-Fi settings kept
private and was **uploaded with verification, thermal disabled**, to the only
detected USB serial device `/dev/cu.usbserial-110`. Both commands exited 0.
Filtered startup confirmed thermal disabled and Wi-Fi retries (reasons 201/36),
with no new address within 35 seconds. Actual thermal acquisition remains
untested; the enabled branch has only software/compile verification.

Thermal acquisition is OFF by default in `firmware/nightvision_camera/thermal_config.h`:

```cpp
#define BIMBOT_THERMAL_ENABLED 0
```

Change 0 to 1 only after confirming the spare board, unused/empty microSD slot,
SDA14/SCL13, matching GY carrier mode and suitable power/pull-up levels. This
switch is public nonsecret configuration. Do not change or display private Wi-Fi
values. The operator reconfirmed on 2026-10-19 that the spare remains USB-powered
because the robot-side output was then unmeasured; that does not confirm thermal
wiring, thermal supply verification or the microSD condition.

In the next reply, the operator confirmed microSD is unused and thermal
connection/supply checks are still undone, tentatively planned for 2026-10-20.
Keep `BIMBOT_THERMAL_ENABLED` at 0 until those remaining checks are complete.

The combined sketch bundles a pinned official Melexis calculation library under
`src/mlx90640` and a bounded transport in `thermal_sensor.cpp`; it does not require
installing Adafruit MLX90640. Keep the entire sketch folder, including `src/`,
headers and the existing private `wifi_secrets.h`, together when opening it in
Arduino IDE. Preserve the original camera's firmware and the unrelated saved
factory sketch in the user's Arduino folder.

The sensor uses the I2C controller opposite camera SCCB, with explicit SDA14 and
SCL13. The installed core puts camera SCCB on controller 1, so thermal uses
controller 0; do not blindly select `Wire1`. Default ESP32 pins 21/22 are camera
signals here. Chess mode, 18-bit resolution and two subpages per second produce
approximately one complete image per second. A separate yielding worker reads
two distinct subpages with a 3-second operation deadline and bounded transfers.
Only complete finite 768-value frames within -40 to 300 °C are published.
Failures invalidate the cache and retry initialization without waiting in camera,
light-lease or HTTP handlers. If spare power or streaming headroom is inadequate,
a dedicated ESP32 sensor bridge is the fallback.

### First live test after physical checks

1. With power off, verify the label-to-label connections above. Keep the original
   camera/DHT wiring intact. Use the spare's existing USB power and keep the
   original robot hotspot available.
2. Enable thermal in `thermal_config.h`, select the matching AI Thinker ESP32-CAM
   and the freshly identified spare's serial port, then Verify and Upload the
   **complete combined sketch**. Identify the spare again before every upload.
3. At 115200 baud, look for `MLX90640 initialized` followed by `Thermal frame` with
   a 24x32 scene range. `Thermal acquisition disabled` means the switch is still
   off; `Thermal sensor unavailable` means no valid sensor initialization.
4. Use the freshly printed IP on the laptop's robot network. Last-known example:
   `http://192.168.4.3/status` and `http://192.168.4.3/thermal` (latest serial
   address on 2026-10-19; DHCP can change it). The status object
   reports `thermal.enabled`, `fresh` and `state`. `/thermal` returns HTTP 200
   only for a complete frame younger than 5000 ms, with `frame_age_ms`, `sequence`
   and `grid`; otherwise it returns HTTP 503 with no grid. Responses are not cached.
5. Check night video and light on/off, then verify the original video and fresh
   DHT readings while thermal is running. A changing warm target should change
   the heat pattern; this is a relative-response test, not temperature calibration.
6. Configure `THERMAL_DATA_URL` in active SAR only after the endpoint works, as
   described below. The backend retains the sensor acquisition age and expires
   metadata-bearing thermal readings after five seconds rather than refreshing
   an old grid's timestamp at each poll.
7. Remove power before disconnecting the thermal module, then power the spare
   again: thermal must show unavailable while camera/light remain usable. Restore
   wiring with power off and verify recovery. Do not hot-plug jumper wires.

Sources: [Espressif GPIO restrictions](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/gpio.html),
[I2C custom pins/pull-ups](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/i2c.html),
[camera SCCB driver](https://github.com/espressif/esp32-camera/blob/master/driver/sccb.c).

## Information required before wiring to the original camera

The operator reports the temperature/humidity sensor's yellow data wire goes to
IO13 (interpreted as GPIO13), red to 3V3 and black to GND. Leave these unchanged.
MicroSD is believed unused but must be confirmed. Obtain the currently flashed
main ESP32-CAM sketch and confirmation of the 3.3 V supply capacity
and signal pull-up voltages. Existing firmware must be updated to read this
sensor; plugging in wires cannot create a thermal HTTP endpoint. A programming
cable/programmer is required to install that firmware, unless an existing known
OTA update mechanism is available. Do not replace the main camera firmware with
the standalone night-camera sketch: that would remove its temperature endpoint.

## Earlier original-camera candidate (alternative, NOT released for connection)

Revised plan: GPIO13 is occupied by the existing DHT sensor. For an Ai-Thinker
ESP32-CAM without microSD and with GPIO14/15 confirmed free:

| Suggested new wire color | Thermal module | ESP32-CAM candidate connection |
| --- | --- | --- |
| Red | VIN | Verified 3.3 V supply / 3V3, subject to capacity check |
| Black | GND | GND |
| Yellow | SDA | GPIO14, only if unoccupied |
| Blue | SCL | GPIO15, only if unoccupied |
| Black | PS | GND, selecting I2C mode before power-up |
| None | RX, TX, NC | Unconnected for direct I2C mode |

This sensor's red wire represents 3.3 V; the previous camera-power guide used red
for 5 V. Wire colors identify the new connections but do not establish voltage.
Do not connect the two red power wires interchangeably. Power down before wiring.
Do not solder SET I2C just to experiment; the documented removable PS-to-GND
connection can select mode after confirming the manual applies to the board.
ESP32 GPIO must not be exposed to 5 V pull-ups. Do not use GPIO21/22 by default:
they are camera signals on this board, despite being common I2C pins on other
ESP32 development boards. GPIO14/15 are also SD-related, hence the checks above.
GPIO15 is a strapping pin: verify normal boot with the I2C sensor connected and
keep signal levels within ESP32 limits. Use a breadboard or proper distribution
connector for shared power/ground; do not jam multiple jumpers onto one pin.
If no usable pin pair exists, use a separate ESP32 sensor bridge with a verified
pin map rather than changing unknown motor/sensor wiring.

Mount the thermal sensor beside the Main visible lens on rigid insulated
standoffs, pointing in the same direction; both should move on the same bracket
if the camera pans. Keep its broad field of view clear of bracket edges and its
aperture open. Ordinary glass is not a suitable thermal window; any protective
cover requires verified long-wave IR transmission. Keep it away from
motor/regulator/light heat, secure wiring with strain relief, and leave the
DHT exposed to circulating air. Similar direction
does not establish pixel alignment: different fields of view, offset and distance
require calibration before mapping temperature onto an individual person's box.

## Required firmware and app data path

### Standalone reference: do not upload to either working camera

`firmware/thermal_bench_test/thermal_bench_test.ino` is a standalone sensor test
for a SPARE ESP32-CAM. It is not a reconstruction of the unknown original sketch.
It uses the planned SDA14/SCL15 connections, initializes the sensor at address
0x33 with Adafruit MLX90640, starts at 1 Hz, rejects failed/invalid frames and
prints 24x32 temperature grids and scene min/max through Serial at 115200 baud.
It has no camera, DHT or Wi-Fi server. Both available cameras now have roles;
do not upload it to either the working Main or Night camera. Uploading it would
replace the current camera program. Its pins also differ from the new spare
proposal. Use only on an explicitly identified, otherwise unused test board after
adjusting wiring and source together.

For a separately identified test board, install Adafruit MLX90640 and its
required dependencies in Arduino IDE, select the matching ESP32-CAM board/port,
confirm the spare board's wiring/power/no-SD conditions, uncomment the bench-test
guard, click Verify, then Upload. This planning session did not compile or run
this standalone source. Observe readings first in Serial Monitor;
this test alone does not expose a thermal HTTP endpoint for Flask.

The recommended spare-host implementation is now in the combined night-camera
source as described above. An original-host alternative
would first require its actual source and preserve its DHT/video logic. Do not
merge this standalone setup/loop as a replacement. Dashboard/backend integration
remains separate from board firmware.

The ESP32 reads MLX90640 frames using an appropriate I2C library (default sensor
address 0x33), converts them into 24 rows of 32 Celsius values and exposes a JSON
endpoint such as `/thermal`. Initialization must report failure; disconnected or
stale sensor data must not be returned as a fresh success response. Start with a
low refresh rate and check that camera and temperature-sensor performance remain
acceptable. This module also has a documented UART mode, but do not wire both
UART and I2C or mix their firmware drivers.

Example HTTP shape, not real readings:

```json
{"grid": [["32 numeric Celsius readings per row; 24 rows total"]]}
```

The original-host alternative cannot be merged safely without the actual Main
source. The recommended spare-host path can use the existing complete spare
source. Once the chosen host's endpoint is verified on hardware, set the
active SAR local configuration (operator enters values locally):

```dotenv
THERMAL_DATA_URL=http://ACTUAL_CONTROLLER_IP/thermal
```

The route may be hosted by the spare, original camera or a separate sensor bridge on
the same robot Wi-Fi. Do not point THERMAL_URL at this JSON endpoint: THERMAL_URL
belongs to the old thermal video adapter, while THERMAL_DATA_URL is the numeric
sensor input. Restart Flask after configuration.

The backend already validates grid size, rejects nonfinite/out-of-range values,
calculates minimum/maximum and publishes `/api/thermal-data`. The main-camera
view now shows this surface-temperature range and freshness state. The Thermal
tab shows the grid. Stale or missing input removes the numeric reading.
An inset heatmap in Main view remains a proposed UI addition, followed by
calibrated fusion only after field-of-view/orientation/parallax checks. The
numeric path is not connected to the legacy thermal-video classifier.
Thermal data does not replace the humidity/ambient-temperature sensor or heat
index calculation. The main view is a UI readout, not temperature text burned into
the recorded video or calibrated fusion. No body temperature, life status or
injury classification is derived from the displayed scene range.

## Verification sequence after firmware is available

1. Verify supply and mode selection before connecting; scan for I2C address 0x33.
2. Confirm a complete 768-value frame with finite plausible temperatures.
3. Check camera streaming and the existing temperature/humidity endpoint.
4. Open the thermal endpoint from a laptop on the robot Wi-Fi.
5. Configure Flask and verify scene range beside the main feed and the Thermal grid.
6. Disconnect the thermal sensor and verify missing/stale values are not displayed
   as live. Restore the connection and verify recovery.
7. Test relative response to a known warm/cool scene. Accuracy and emissivity
   require separate checks; do not treat this as a clinical body-temperature test.
