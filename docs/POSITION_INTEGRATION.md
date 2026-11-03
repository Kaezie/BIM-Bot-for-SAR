# Robot position: outdoor GNSS and indoor local tracking

October 27 update: the operator asks to follow the partner's proposal to display
recorded movement instead of a live map. The separate [movement history](MOVEMENT_INTEGRATION.md)
display is prepared, awaiting actual Uno telemetry; it never invents coordinates.
The operator subsequently supplies the full sketch and USB option; the updated
recorder and bridge are implemented but not uploaded or tested on hardware.
No receiver/tracker is added, and panel approval to substitute movement history
for GPS is not established. The position adapter below remains future support.

Updated October 25, 2026. The operator puts microphone work on hold and asks to
incorporate GPS for **both indoor and outdoor** use. They confirm having **no
GPS/GNSS module**. No receiver, antenna, local tracker or live position fix is
verified. This document and the software support are preparation, not completion
of robot tracking. The earlier no-additional-budget constraint and November
defense remain relevant; no order or model selection is implied.

## Distinct positioning methods

Outdoor GNSS can supply latitude and longitude with suitable satellite
reception. GNSS alone is unreliable inside buildings and cannot reliably name
rooms or floors. A separate local tracker is needed indoors, with a defined
origin, scale and any floor-plan registration. Camera-based tracking, markers
or wheel odometry may be candidates, but none is implemented/validated by this
change. Do not label an operator-entered area name as an automatic position.

The manufacturer explains the reception problem and the need for alternatives
in [u-blox indoor GNSS guidance](https://www.u-blox.com/en/indoor-detection-technology).
A receiver should not be purchased with the expectation that it will solve
indoor room/floor tracking by itself.

## What the software now provides

In the active **BIM-Bot-for-SAR** checkout, **Mission tools & history → Robot
position** presents global or local coordinates, source, freshness, and receiver
quality if supplied. Missing/unconfigured/invalid/stale states clear coordinates
and the map link. A connected receiver with no fix has its own state. The
existing camera console and its thermal layout remain unchanged.

`GET /api/position-data` requires the existing verified-user authentication and
returns `Cache-Control: no-store`. It reuses the optional `POSITION_URL` bridge.
It never requests browser/laptop geolocation or contacts a GPS receiver directly.
No private environment values are changed by this work.

When an operator clicks the map link for a fresh non-simulated global fix,
OpenStreetMap receives the displayed coordinates. No map tiles or external
location requests are sent automatically. Local coordinates have no geographic
map link until an explicit registration/conversion system is implemented.

Mission evidence already stores a **fresh robot observation position** when
available. It does not calculate the coordinates of a detected person. No-fix
or stale receiver data must not enter that field as a current position.

## Proposed bridge contract

The receiving microcontroller/bridge must provide genuine device samples.
There is no robot firmware implementation or GPS pin assignment yet. The
examples below are protocol illustrations, not recorded locations.

Global fix (WGS84):

```json
{
  "frame": "wgs84",
  "source": "robot_gnss",
  "fix_valid": true,
  "latitude": 0.0,
  "longitude": 0.0,
  "sample_age_ms": 100,
  "sequence": 42,
  "satellites": 8,
  "horizontal_accuracy_m": 4.5
}
```

- `fix_valid` must be an explicit boolean. Never use zero-filled coordinates as
  a substitute for a missing fix. Zero latitude/longitude are valid numbers only
  when accompanied by a genuinely valid fix and sample metadata.
- `sample_age_ms` measures time since the receiver's actual position sample,
  not the HTTP response time. It must be finite, nonnegative and below 5000 ms.
- `sequence` is a nonnegative integer advanced for each new position sample,
  including when stationary. Do not advance it just to answer an HTTP request.
- Latitude/longitude must be finite and within ±90/±180 degrees. Satellite
  count is optional, integer0–255; horizontal accuracy is an optional finite,
  nonnegative receiver estimate in metres. HDOP must not be relabelled as metres.
- The host includes the entire HTTP exchange in a conservative sample-age
  estimate, expires samples after five seconds, and prevents a repeated sequence
  from becoming younger. A new frame/source has a separate sequence history.
- `simulated:true` must identify any demonstration data; UI labels it and hides
  the external map link. No simulator is configured by this change.

Receiver connected without a fix:

```json
{"frame":"wgs84","source":"robot_gnss","fix_valid":false,"satellites":2}
```

This replaces the earlier fix and discards any coordinates left in the payload.
The receiver can be connected while its position remains unavailable.

Local tracker sample, in metres from its defined origin:

```json
{"frame":"local_meters","source":"robot_local_tracker","x":1.25,"y":-2.5,"sample_age_ms":100,"sequence":42}
```

Use the same sample-age/sequence rules for new local trackers. Legacy
`local_meters` producers without this metadata retain their existing ten-second
HTTP-receipt freshness rule for compatibility. That older interface alone cannot
prove a moving tracker is still acquiring samples. No indoor tracker is connected.

## Hardware and validation remaining

1. Select a receiver/antenna appropriate to the available budget and outdoor
   demonstration; verify exact model, breakout supply/logic and antenna before
   selecting a serial port. Preserve camera, PSRAM, DHT, thermal and light pins.
2. Decide and validate the indoor tracking method against a known test layout.
   Do not infer local metres, room/floor identity or automatic area coverage from
   camera detections, mission labels or GNSS alone.
3. Implement the robot-side bridge, then test outdoors for first fix, sample
   timing, stationary/moving behaviour, loss/recovery and combined sensor load.
4. Test the local tracker separately and verify coordinate-system changes are
   explicit. Losing GNSS must not silently invent an indoor location.

No USB/serial access, wiring change, firmware upload, personal location query or
live GPS measurement occurred in this preparation. Software tests use generated
coordinates, mocked receivers and clocks. Real indoor/outdoor tracking acceptance
is pending actual hardware and a validated local tracker.
