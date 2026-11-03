# Updated Uno movement: saved files, USB setup and limits

October 27, 2026. The operator connected the Uno by USB and confirmed motor
power OFF. The recording-only Uno update is now uploaded and independently
readback-verified; the dashboard receives fresh USB telemetry. **IR command
recording and physical motor/sensor acceptance are still pending. Supervised
return remains disabled.** Neither ESP32 camera was uploaded or rewired.

## Verified Uno upload and current connection

- Identified target: Arduino Uno, USB VID `2341`, PID `0043`, device
  `/dev/cu.usbmodem1101`; build target `arduino:avr:uno`.
- Compared all motor pin/direction/PWM writes with the supplied original sketch.
  Existing source definitions are preserved; physical wheel directions remain
  unverified. Built only `robot_movement/`, with explicit
  `BIMBOT_SUPERVISED_RETURN=0`: 15,212 flash bytes, 1,163 static RAM bytes.
- Saved the installed 32,768-byte flash before uploading. All 15,212 application
  bytes match an independent post-upload read; the 512-byte bootloader is unchanged.
  Sources, flash backup, application, logs and hashes are retained under
  `local_data/firmware_backups/uno_2026-10-27_170238/` (Git-ignored).
- The attempted `preupload_eeprom.hex` and `postupload_eeprom.hex` reads are
  **not valid EEPROM backups**: this Optiboot returns flash data for EEPROM
  reads. Never restore those files to EEPROM. No EEPROM write or chip erase
  was requested; actual EEPROM preservation could not be independently checked.
- Real USB testing found the bridge ignored `bytearray` input. Decoding now
  accepts both bytes and bytearray, and startup waits silently for the expected
  boot banner before polling. Three regressions cover fragmented startup,
  missing/wrong firmware and the actual buffered read loop; all 190 Python
  tests pass. No second firmware upload was needed for these host fixes.
- `pyserial==3.5` is installed in the existing `.venv-1` Python environment.
  SAR's private movement endpoint is now `http://127.0.0.1:5054/movement`.
  The bridge runs without `--enable-return`; movement and mission command URLs
  remain blank. Fresh real Uno telemetry advances and reports stopped output,
  empty history and return disabled. No physical driving is established.
- Dashboard login responds on port 5050; protected movement data still requires
  sign-in. Open Mission tools & history → Recorded movement after signing in.
  Keep motor power OFF for the first IR `*`, brief Up, release and OK check.
  A recorded command/duration with unpowered motors verifies input and logging,
  not wheel motion, obstacle operation, distance or return accuracy.

## Where the nine supplied files were saved

Exact byte-for-byte originals, with SHA-256 manifest, are in
`firmware/source_archive/2026-10-27/` in BOTH local checkouts. Downloads were not
changed. The archive is ignored by Git because the camera sketch contains Wi-Fi
credentials. Never publish that archive or its private header.

Canonical working folders in **BIM-Bot-for-SAR**:

- `firmware/robot_movement/robot_movement.ino`: updated Uno sketch; with
  `MovementRecorder.h`, `IR_remote.cpp/.h` and `Keymap.cpp/.h` in the same folder.
- `firmware/original_camera/original_camera.ino`: separately saved original
  ESP32 camera source, with its camera headers and server. Credentials were moved
  into ignored `wifi_secrets.h`; the camera configuration struct is zero-initialized.
  Its isolated build uses placeholders. It is a source/reference backup, not a
  requested replacement of the currently working camera firmware. The supplied
  server's GPIO22 LED constant conflicts with the AI-Thinker PCLK map and needs
  separate review before any original-camera upload. No camera pin was reassigned.

Keep Uno and ESP32 sketches in separate Arduino sketch folders; they cannot be
combined into one Arduino program. The saved camera still provides its original
AP/video/DHT roles. Movement uses the Uno USB interface and does not require a
camera-to-Uno connection or an ESP32 `/return` endpoint.

For the Uno sketch, select **Arduino Uno** in Arduino IDE and install Adafruit's
**DHT sensor library** and **Adafruit Unified Sensor** through Library Manager.
Keep every file in `robot_movement/` together. Verification used AVR core1.8.8,
DHT1.4.6 and Adafruit Unified Sensor1.1.15 in an isolated build environment.

## Source-derived Uno wiring and controls

These are definitions from the supplied sketch, not newly traced physical wiring:

| Function | Supplied definition |
| --- | --- |
| Left motor direction / PWM | D2 / D5 |
| Right motor direction / PWM | D4 / D6 |
| Forward | D2 HIGH, D4 LOW, both PWM50 |
| Backward | D2 LOW, D4 HIGH, both PWM50 |
| Left turn | D2 LOW, D4 LOW, both PWM40 |
| Right turn | D2 HIGH, D4 HIGH, both PWM40 |
| IR receiver | D3 |
| Right / left obstacle input | A1 / A2, active LOW |
| Uno DHT | D9, DHT11 |
| Serial | 9600 baud |

The supplied ESP32 source separately defines DHT11/GPIO13. This does not establish
that two physical sensors are installed; each source's definitions are retained.
Dashboard environmental readings remain on the existing camera DHT endpoint.
The IR obstacle inputs are not an ultrasonic range sensor or rear/cliff coverage.

Use the supplied normal IR remote map:

1. With the robot stopped at the intended starting area and obstacle inputs clear,
   press **\***. This starts a new, operator-declared trace and clears old steps.
2. Drive with the arrow buttons. Release stops within the retained 250 ms manual
   timeout; **OK** also stops. Stop captures the final active segment.
3. Watch **Mission tools & history → Recorded movement** for command directions,
   durations and source freshness. This does not measure metres or GPS position.
4. Download a JSON record, or retain the USB bridge's automatic local archives
   under `local_data/movement/`. Archives are historical records; restarting the
   bridge never reuses a saved file as live telemetry.

Fixes include a bounded lookup for the 17 actual IR-map entries, consistent header
case, refusal of unsupported remote maps, and ignoring unknown keys for the
manual movement timeout. The original `key != 0` test could keep the timeout
alive on unknown/no-key readings. Motor pins and PWM values are preserved.

## Connect the dashboard through the available USB cable

First identify the **Uno's** actual serial device in Arduino IDE. Do not reuse the
spare ESP32 camera's old device name. Close its Serial Monitor before the bridge
opens the same port. Opening Uno USB serial can reset the Uno and clears its
volatile route. Initial upload/connection tests should have wheels raised and
an accessible motor power cutoff.

From the integrated project, install the optional serial dependency into your
normal project environment:

```sh
python -m pip install -r requirements-serial.txt
```

Start the bridge explicitly with the identified port; the name below is a
placeholder that must be replaced:

```sh
python scripts/uno_movement_bridge.py --port /dev/cu.REPLACE_WITH_IDENTIFIED_UNO
```

This listens only on `127.0.0.1:5054`. It does not scan ports, auto-select a board,
or open anything during dashboard startup. It uses the project's existing Flask,
requests and dotenv dependencies plus pyserial3.5. Normal execution reads the
private project `.env`; no key values are printed.

When ready to connect telemetry, set only the following in the existing private
project `.env` and restart the integrated app:

```text
MOVEMENT_URL=http://127.0.0.1:5054/movement
```

The initial code update left private runtime settings unchanged. During the
later live session, only the localhost MOVEMENT_URL above was configured. Without
the bridge or updated Uno firmware the panel remains unavailable. USB makes this a tethered
setup: the cable and laptop must remain connected. It does not supply wireless
robot movement telemetry, even though the camera remains on Wi-Fi.

## Supervised timed return

Timed reverse playback is implemented as a nonblocking state machine. It plays
F→B, B→F, L→R, R→L in reverse segment order at the supplied direction speeds,
with a 100 ms motors-off interval between segments. It supports IR OK/Stop,
obstacle stops and a three-second controller lease. Manual override cancels a
return, and playback is never appended to the recorded path. Overflow, oversized
segments, protocol faults and interrupted return invalidate replay readiness.

Return is **disabled by default**, with two explicit gates:

- Firmware `BIMBOT_SUPERVISED_RETURN` defaults to0. The build with value1 is
  prepared for a supervised clear-course test after checking actual motor
  direction, Stop, sensor polarity and lease expiry. Default firmware still
  records movement and supplies telemetry.
- The bridge additionally needs `--enable-return`, plus a nonempty private
  `ROBOT_COMMAND_KEY`. The dashboard's command adapter uses that same key.

After those controlled checks and deliberate enabling, configure the command URL:

```text
MOVEMENT_COMMAND_URL=http://127.0.0.1:5054/command
```

Start the bridge with its explicit return gate, keeping the key only in private
configuration:

```sh
python scripts/uno_movement_bridge.py --port /dev/cu.REPLACE_WITH_IDENTIFIED_UNO --enable-return
```

The existing dashboard requires a fresh complete stopped trace and no active
mission/return. It accepts matching controller acknowledgements, retains a
durable uncertain state after timeout, and renews only while the owning operator's
page is visible with fresh matching replay status. The controller must stop
after three seconds without renewals; hiding the page sends Stop best-effort.

This is a supervised open-loop demonstration. The two supplied IR sensors cannot
establish rear/side/cliff clearance. Wheel slip, turn differences and obstacles
can prevent arrival. `replay_complete` reports completion of motor commands,
**never confirmed arrival at base**. It is not GPS, autonomous exploration,
measured route reconstruction or survivor coordinates. Keep these limitations
in the panel requirement assessment.

## Verification and remaining physical checks

Software verification includes Uno AVR compilation for both return modes, an
isolated ESP32 camera build with placeholder credentials, native tests of the
recorder and the actual Uno serial/loop adapter, fake-serial bridge tests, backend
regressions and dashboard fixture tests. Native tests include time wraparound,
final-segment capture, replay cancellation, overflow, lease/obstacle stops,
matching acknowledgements and output backpressure. Unique request challenges
prevent buffered old telemetry or acknowledgements from becoming fresh.

Identification, the recording-only upload, independent flash readback and fresh
USB telemetry are complete. Still needed: verify real IR command recording and
all physical motor directions, check both obstacle inputs, test USB reset/loss
and stopping, then separately enable and evaluate supervised return and lease
expiry on a controlled course. Compile/readback success does not prove motor or
obstacle behavior.
