# Original camera source reference

Reviewed October 25, 2026, after the operator supplied
[pineappleapi/bimbot](https://github.com/pineappleapi/bimbot) as the repository
containing the original camera sketch. Its default branch at review was
`release`, commit `ff1947f6a2f6347de9d05d39ed44cab31698ceef`.

The relevant folder is `BIM-BOT_arduino_setup`, containing:

| File | Blob SHA | Reviewed role |
| --- | --- | --- |
| `ESPCAM.ino` | `8f5c1ab3a7618a31e8da778a5b709058049e024d` | Main camera, Wi-Fi AP, DHT handler |
| `camera_pins.h` | `34085086769079f05dd3ac030b2c121d69a45955` | Selected AI-Thinker camera pin map |
| `app_httpd.cpp` | `9f78de594b75123e2ef1de1a8b55a0c5ac7656fb` | Camera HTTP/control/JPEG stream |
| `camera_index.h` | `040f1ec5267cbbb20f408ef38b3edb69eaaea0bf` | Embedded camera web interface; not opened for this source audit |

## Findings from source, not a new hardware test

- The sketch selects `CAMERA_MODEL_AI_THINKER`, matching the known camera pin
  family. It initializes JPEG capture and selects QVGA after initialization.
- It calls `WiFi.softAP(...)`, preserving the architectural distinction from
  the spare's station-mode firmware. Its station `WiFi.config(...)` addresses
  do not establish the AP's actual live address. Keep addresses as last known.
- It declares **DHT11, GPIO13**, initializes the sensor and registers `/dht` on
  the main HTTP server. Response fields include `temp_c`, `temp_f` and `humidity`;
  error responses include `ok`/`error`. This corroborates the prior operator-
  reported DHT data wire. DHT11 is the source configuration, not a new physical
  model identification or calibration.
- The server registers camera routes on its default port80 and `/stream` on
  port81. The selected map reserves GPIO0, 5, 18, 19, 21, 22, 23, 25, 26, 27,
  32, 34, 35, 36 and39; camera flash is defined as GPIO4.
- The reviewed sketch and server contain **no microphone sampling or audio
  transport**. They do not establish microphone availability. No SD
  initialization was found in the reviewed files; slot use remains a separate
  hardware check.
- Before adaptation, review initialization and compatibility: `camera_config_t
  config` is not zero-initialized, and the server's separate LED constant is
  GPIO22, which is camera PCLK on the selected map. The main sketch does not call
  `setupLedFlash`. Do not activate that path blindly or infer a present fault.

The source is now located and can guide preservation of original behaviour.
It has not been compiled, uploaded or compared with the installed binary in
this audit. The operator identifies it as the original source; exact identity
with flashed firmware is not independently verified. Do not overwrite the
original with the spare sketch or assume the original build/toolchain matches
the spare's successful Arduino3.3.12 build.

Only relevant repository metadata and the three source files above were
inspected. Credential literals were filtered from review output and are not
copied here. No personal recording, microphone, serial port or camera endpoint
was accessed. No remote repository or deployed firmware was changed.

## Pinned source links

- [Main sketch](https://github.com/pineappleapi/bimbot/blob/ff1947f6a2f6347de9d05d39ed44cab31698ceef/BIM-BOT_arduino_setup/ESPCAM.ino)
- [Camera pin map](https://github.com/pineappleapi/bimbot/blob/ff1947f6a2f6347de9d05d39ed44cab31698ceef/BIM-BOT_arduino_setup/camera_pins.h)
- [Camera HTTP server](https://github.com/pineappleapi/bimbot/blob/ff1947f6a2f6347de9d05d39ed44cab31698ceef/BIM-BOT_arduino_setup/app_httpd.cpp)
# October 27 supplied source backup

The operator supplies the complete camera sketch/server/headers alongside the
Uno movement source. Exact originals are archived in both checkouts under
`firmware/source_archive/2026-10-27/` with hash manifests and Git exclusions for
credentials. A separate `firmware/original_camera/` working reference isolates
credentials in an ignored header and zero-initializes camera configuration.
Its placeholder-credential ESP32 build passes; no original camera was flashed.
The supplied server's LED22 constant conflicts with AI-Thinker PCLK22, so this
reference is not an instruction to replace working firmware. Movement uses a
separate Uno USB bridge; camera AP/video/DHT roles and live wiring are unchanged.
See [Uno setup](UNO_MOVEMENT_SETUP.md) for current implementation and test scope.

## October 29 stability changes in the working reference

The operator authorized changing the original camera's Wi-Fi setup to fix the
freezes. `firmware/original_camera/` now differs from the archived original only
by: hotspot-only mode (the unused station static IP is removed; `WiFi.config()`
had enabled an idle station interface), 15 dBm hotspot transmit power,
`CAMERA_GRAB_LATEST` with explicit frame-buffer locations, and stream pacing to
about 8 fps (`STREAM_FRAME_INTERVAL_MS` in `app_httpd.cpp`). QVGA/quality 10, the
camera routes and the DHT11/GPIO13 `/dht` handler are unchanged. Changed lines
are marked `FIX:`. The LED22 call is a no-op on Arduino-ESP32 3.3.12 because
`ledcWrite()` ignores pins never attached to LEDC, and nothing attaches GPIO22.

`/status` reporting `framesize` 6 is QVGA (320×240): the camera library bundled
with Arduino-ESP32 3.3.12 inserted 128×128 and 320×320 into the size list. It
does not indicate a different flashed sketch; the operator confirms none was used.

Not flashed yet. Before any upload: identify the board, back up its full flash
with esptool, and install Adafruit's DHT sensor library. The October 29 compile
check used a stand-in DHT header and must not be flashed.
