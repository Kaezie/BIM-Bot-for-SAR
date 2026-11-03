# Two camera microphone channels

Latest October27: operator confirms a Bluetooth headset with microphone and
earpiece. Manual exact-input analysis, optional local YAMNet sound-event
classification and separate exact-device two-way routing are now prepared.
Real capture/audibility/range remain pending; no microphone was activated by
these software checks. See [current headset setup](HEADSET_SOUND.md),
[two-way setup](SURVIVOR_COMMUNICATION.md), and the
[in-app test guide](http://localhost:5050/testing). Earlier no-recognizer/no-output
statements below describe previous stages, not current software readiness.
No microphone module or new ESP32 audio wiring/firmware has been added.


October 27 update: the operator authorizes borrowed-headset **software** support
as a no-purchase alternative. Exact input selection and operator-confirmed robot
placement are now prepared; no device is available/paired/tested by this work.
This supplies at most one input and does not complete independent Original/Spare
audio, speech recognition or two-way communication. See
[current headset setup](HEADSET_SOUND.md). Earlier purchase/wiring proposals
below remain background research, not an instruction to buy or modify hardware.

## Current budget and defense requirement

October 25 update: the operator has no budget for additional hardware and the
final defense is in November 2026 (date not specified). Sound detection is
confirmed as part of the approved thesis requirements. Preserve that requirement;
the microphone purchase sequence below is background feasibility work, not the
current executable plan.

First inventory existing or borrowed audio inputs. A phone, headset or borrowed
microphone is a candidate to investigate, not a confirmed compatible solution.
Verify robot placement, connection, latency and actual samples before claiming
robot sound detection. Two independent camera-position views require two real
inputs; one source cannot be duplicated and labelled as two. The operator laptop
microphone alone measures sound at the operator, not at a remote robot. Label any
alternative source explicitly and establish whether it satisfies the required
scope. Do not access personal phone files or start audio capture merely to
inventory available hardware.

The operator confirms only the laptop is available; no phone is available to
mount on the robot. An optional **Laptop microphone** view is being prepared in
Sound, off by default with manual Start and browser permission. It does not
satisfy independent camera-position audio; the robot sound requirement remains
unresolved. No actual microphone has been activated by this work.

Original source is now located in the operator-supplied `pineappleapi/bimbot`
repository: `BIM-BOT_arduino_setup/ESPCAM.ino`, pinned release commit
`ff1947f6a2f6347de9d05d39ed44cab31698ceef`. It specifies the AI-Thinker camera,
AP mode and DHT11 on GPIO13, with no audio sampling/transport. See
[Original source audit](ORIGINAL_CAMERA_SOURCE.md). This supersedes the earlier
missing-source dependency below; no original firmware was uploaded.

Investigation updated October 25, 2026. The operator selected connecting one
microphone to each existing camera, rather than adding an audio controller.
This route is plausible but has not been wired or tested on the robot.

Before providing the repository link, the operator did not know the original
sketch location and asked to use the spare sketch as a base. The spare build
investigation below remains valid; the newly located original source now gives
us a reference for its AP, video and DHT roles. The station-mode spare sketch
must not be flashed unchanged onto the original. No microphone hardware is
currently available for either camera.

## Hardware actually identified

### October 25 purchase shortlist — no order placed

The operator now asks which module to buy and requests links. This authorizes
research, not a purchase; funding and owned hardware have not changed. Recommended
candidate: an **INMP441 standard I2S MEMS microphone breakout**, using 3.3 V.
Its digital audio samples can support real level/waveform analysis; recognition
of people, voice or tapping remains a separate unvalidated feature. Buy a board
with exposed VDD/GND/SCK/WS/SD/L/R connections, not the bare surface-mount chip.
Confirm whether headers are soldered and use short appropriate jumper wires.

Listings checked October 25, 2026; prices exclude shipping and can change:

| Seller/product | Listed unit price | Listed pair cost |
| --- | --- | --- |
| [PowerMav INMP441 breakout](https://powermavelectronics.com/shop/module/omnidirectional-microphone-module-inmp441/) | PHP190 | PHP380 |
| [Fu-labs INMP441 breakout](https://fulabs.ph/products/omnidirectional-microphone-module-i2s-interface-inmp441-mems-high-precision-low-power-ultra-small-volume-for-esp32) | PHP192 | PHP384 |

PowerMav's opened page says in stock, although a search excerpt says out of
stock. Fu-labs shows an in-stock count/Add to cart alongside a generic Sold out
label. Confirm actual stock, header assembly and delivery with the chosen seller;
neither listing is a guaranteed arrival before the defense. One first module
is the lower-cost bench-test step; two matching actual microphones are needed
for independent Original-position and Spare-position inputs. No microphone or
specific robot wiring has yet been tested.

New design candidate: the manufacturer documents two INMP441s sharing SCK/WS/SD
with opposite L/R selections, giving distinct stereo slots. Thus both microphones
could potentially be mounted at the two camera positions and read by I2S1 on
the **spare alone**, preserving the original's AP/video/DHT firmware. This is an
inference from the supported bus topology, not a tested robot implementation or
a confirmed change of architecture. It still needs the spare's boot/UART pin
audit, short-wire signal/power checks and combined camera/thermal/audio tests.
Use 64 BCLK cycles per stereo frame, 32-bit slots carrying each microphone's
24-bit sample. Check the breakout's decoupling and shared-data pull-down; the
manufacturer's reference uses 100 kOhm. No GPIO assignment is provided here.

The operator subsequently asks about purchasing **one** module and requests
Shopee options. One real input can serve a shared robot microphone; two
independent position readings still require two real inputs. No order or change
to the required thesis scope is confirmed.

- [Professional relay INMP441 Shopee listing](https://shopee.ph/INMP441-Omnidirectional-Microphone-Module-MEMS-High-Precision-Low-Power-Consumption-I2S-Interface-Support-ESP32-Module-i.292646376.41460859592): indexed PHP135/preorder, four variants. The opened copy is about two months old with stale delivery dates; current price, variant, stock and arrival are **not verified**.
- [MakerLab INMP441 Shopee listing](https://shopee.ph/Omnidirectional-Microphone-Module-I2S-Interface-INMP441-MEMS-for-ESP32-Micro-Controller-i.18252381.23647663205): indexed PHP319, opened copy says **Sold Out**. Do not recommend as confirmed in-stock.

**Shopee variation clarification, October 25:** enlarged seller images show
A = round with loose headers, B = round with soldered headers, C = rectangular
with loose headers, D = rectangular with soldered headers. All four images say
“compatible chip version,” without an exact part number. B is a convenient
assembly style, not proof of INMP441 identity or electrical/timing compatibility.
Obtain the actual chip model and confirmation of standard I2S/3.3 V operation
before checkout; do not equate the listing title with a verified part. The user's
screenshot shows a general PHP135 price and November1–5 preorder estimate, with
no A–D variant visibly selected. No order or hardware test is established.

Primary electrical reference:
[TDK INMP441 datasheet, especially I2S interface and stereo configuration](https://product.tdk.com/system/files/dam/doc/product/sw_piezo/mic/mems-mic/data_sheet/inmp441.pdf).
Do not follow a shop's generic ESP32 GPIO diagram: camera/thermal signals occupy
some pins used by those examples. The product type is recommended for testing;
end-to-end robot compatibility and audio capture remain unverified.

The operator identifies the camera with the sticker as **Original** and the
one without the sticker as **Spare**. The supplied front photographs are:

- [Original, IMG_7553.HEIC](/Users/christine/Downloads/IMG_7553.HEIC)
- [Spare, IMG_7552.HEIC](/Users/christine/Downloads/IMG_7552.HEIC)

They show the familiar ESP32-CAM/OV2640 layout and flash LED, with no visible
microphone. Only the fronts were photographed. The operator subsequently
confirmed having no separate microphone modules, only the shown hardware.
This supersedes the earlier assumption that microphones were already connected.
Hearing the robot during live viewing did not establish transmitted audio.

Both project checkouts currently record canvas video only. The working spare
firmware provides JPEG video, thermal data and light control, with no audio
sampling or transport. No personal recording was opened for this investigation.

## Feasibility and resources

Espressif documents two standard I2S controllers on this ESP32. Camera mode uses
I2S0; an external standard I2S microphone could use **I2S1**, explicitly selected
instead of automatic controller allocation. The current camera driver configures
I2S0 directly. Use the current standard I2S API consistently; the legacy and new
I2S drivers cannot coexist. This is a proposed software architecture, not proof
that the present board wiring and combined workload will operate reliably.

| Resource | Original camera | Spare camera |
| --- | --- | --- |
| Identity | Sticker; existing main video/hotspot | No sticker; working Night video |
| Camera, on matching ESP32-CAM pin map | GPIO0, 5, 18, 19, 21, 22, 23, 25, 26, 27, 32, 34, 35, 36, 39, confirmed in supplied source | Same set, verified in project source |
| PSRAM | Reserve GPIO16/17 for matching board; confirm original configuration | GPIO16/17 reserved |
| Existing sensors | DHT11/GPIO13 in supplied source, consistent with reported data wire | Thermal SDA14/SCL13, installed refresh profile4 |
| Flash light | Pin map defines GPIO4; separate server LED constant22 needs review, see source audit | GPIO4 reserved for working light control |
| microSD | Actual use still needs confirmation | Operator confirmed unused |
| Remaining header resources | Source located; exact live firmware and other connections still need verification before assignment | GPIO2/12/15 have boot restrictions; GPIO1/3 are programming/debug UART |

A standard digital I2S microphone needs three signal connections (BCLK, WS,
data) in addition to power and ground. The spare has no established set of three
unrestricted header GPIOs. Reusing its remaining header pins would require
checking boot levels and/or releasing a UART pin in software. GPIO12 is excluded
from the initial proposal because its reset level can select flash supply
voltage. Do not use PSRAM, camera, thermal or light pins to make room.
**No microphone pinout is assigned or approved by this document.**

An analog microphone on the exposed ADC2 pins is a poor fit for continuous
sampling alongside Wi-Fi; Espressif documents their shared hardware constraint.
Most ADC1 pins on this board are already camera signals or are not available on
the normal headers. A threshold-only sound module would supply an event, not
samples for a real waveform. Investigate standard I2S MEMS breakouts with 3.3 V
power/logic, documented timing, and no required MCLK connection. The exact
module's format, clock limits and reset output behaviour must be checked before
buying or wiring two matching modules. A generic I2S example is not sufficient
to qualify every microphone model.

## Software-only build evidence

A temporary copy of the complete spare source was built for
`esp32:esp32:esp32cam` with Arduino-ESP32 **3.3.12 / ESP-IDF 5.5.5**, thermal
enabled and refresh profile4. It includes an explicitly selected I2S1 receiver
using the standard API: allocation, mode initialization, enable, bounded read,
disable and deletion. All microphone GPIOs remain unassigned. Only placeholder
network credentials were used; the real secret header was excluded entirely.

- Compilation and linking passed: 1,066,105 bytes flash, 81,640 bytes static RAM.
- ELF symbols confirm both `esp_camera_init` and the above I2S functions were
  retained; the legacy `i2s_driver_install` symbol is absent.
- The artifact is a compile/link probe marked **NEVER FLASH**. It is not a
  microphone firmware release and has not been uploaded or run.
- No GPIO, USB/serial device, robot endpoint, Wi-Fi setting or microphone was
  accessed. Dynamic memory, actual I2S initialization, boot reliability, sound
  quality and camera/thermal performance under audio load remain unverified.

Local evidence: `/private/tmp/bimbot-audio-feasibility-5gzk0xnj/result.json`.
The temporary sources and placeholder binary may disappear with temporary-file
cleanup; the evidence above records only a software build result.

## Integration sequence and remaining input

1. Use the complete working project spare sketch for spare development, and the
   newly located repository original source to preserve original behaviour. The
   latter is a source reference, not an installed-binary verification or tested
   original build. Confirm complete pin use, AP configuration and live endpoint
   behaviour before any adaptation. A safe replacement/rollback procedure also
   remains to be established before an original upload. Do not
   extract credentials from flash, Keychain or private files to fill this gap.
   The previously supplied
   `NightVisionCamera.ino` is an incomplete spare-camera sample, not a verified
   replacement for the original firmware. Do not overwrite the original with
   the spare sketch or inspect credential values.
2. Review an exact microphone breakout model and its electrical/timing details;
   two modules are needed. Audit pins for each camera separately. Original
   microSD use and other signal wiring must be checked against source or a
   confirmed hardware inventory before assigning its pins; this does not block
   the spare's own pin audit.
3. Add a bounded sampler and small latest-result endpoint on the spare first,
   with audio disabled by default and camera allocation taking priority. Report
   real relative level and optional short sample windows; avoid a growing audio
   queue or continuous raw-audio transmission for a level display.
4. Bench-test reset/upload behaviour and concurrent video, thermal and light
   operation before accepting a pin map. Preserve the current verified firmware
   and rollback. Hardware handling/upload preparation must account for any new
   microphone leads; the earlier six-lead thermal workflow is not sufficient
   once a microphone is connected.
5. Integrate the original microphone with verified original source if available,
   or a separately reviewed adapted version of the spare base that preserves
   hotspot, video and DHT behaviour. Do not treat the spare's successful build or
   upload as validation of the original. Validate each input separately, then
   both together.
6. Present two independent sources in the existing Sound section: **Original
   camera microphone** and **Spare camera microphone**, each with real level,
   activity and freshness. Show missing/stale independently. Do not duplicate
   `SOUND_URL`, generate levels, or substitute the laptop microphone. A waveform
   needs actual samples; use relative units or dBFS without implying calibrated
   dB SPL. Voice/tapping recognition and audio recording/playback need separate
   implementation and validation.

## Optional laptop microphone view

`static/js/laptop_sound.js` performs browser-local waveform/RMS/peak analysis
and compares relative RMS signal level with an adjustable activity threshold.
It does not recognize speech, people or tapping. Relative percentages are not
calibrated sound-pressure dB. It has no audio server/storage path, does not add
audio to recordings, and does not replace remote `SOUND_URL` telemetry.

Both camera microphone cards stay unavailable. The laptop card explicitly says
it hears sound near the laptop. Start is deliberate in the visible Sound tab
of an authenticated dashboard; selecting Sound alone requests nothing. Stop,
leaving Sound, hiding/closing the page, session end, sign-out and input loss
release tracks and close analysis. A late permission grant after Stop is
discarded and its tracks stopped. No playback output is connected.

Software tests use generated oscillator audio with `getUserMedia` replaced before
application load. They do not establish live microphone operation or robot sound
detection. The existing video recorder is unchanged and remains video-only.

## Primary references

- [Espressif I2S, matching IDF 5.5.5](https://docs.espressif.com/projects/esp-idf/en/v5.5.5/esp32/api-reference/peripherals/i2s.html)
- [Espressif camera driver for ESP32](https://github.com/espressif/esp32-camera/blob/master/target/esp32/ll_cam.c)
- [Espressif GPIO restrictions](https://docs.espressif.com/projects/esp-idf/en/v5.5.1/esp32/api-reference/peripherals/gpio.html)
- [ESP32 datasheet, boot configuration and flash/PSRAM connections](https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf)
- [Manufacturer I2S microphone breakout guide](https://learn.adafruit.com/adafruit-i2s-mems-microphone-breakout?view=all)
