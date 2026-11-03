# Recorded movement and return feasibility

Reviewed October 27, 2026, Asia/Manila, before movement firmware editing. The
operator subsequently supplied the complete Uno/camera/support files and asked
to proceed, superseding the earlier hold. All nine originals are archived in
both checkouts. The supplied Uno defines the actual source pin map and IR
control; USB is operator-confirmed available. The updated Uno recorder/replay
and localhost serial bridge are now implemented. See
[current setup](UNO_MOVEMENT_SETUP.md). No firmware was uploaded, serial device
opened or motor command sent; physical wiring/operation remains unverified.

## What the partner's proposal can provide

The supplied chat proposes displaying the robot's recorded movement rather than
a live map. This update adds a **Recorded movement** section in Mission tools &
history. It displays validated forward/back/left/right command durations, current
command, source and reverse-playback progress, and can export the current record
as JSON. Fresh movement context also enters new mission detection evidence and
the situational report when a recorder is eventually connected.

This is a command history, not a measured route. Wheels may slip, turns may have
different radii, and collisions or battery changes alter distance. It supplies
neither GPS coordinates nor survivor coordinates and does not continuously locate
the robot. No route is fabricated from elapsed time. The existing GPS/local
position adapter remains a separate, unavailable input until genuine data exists.
Panel acceptance of movement history as a change to a GPS requirement is not
established by the partner's suggestion.

## Review of the supplied fragment

Timed reverse playback is feasible as limited automation on a controlled test
course. It is not autonomous search, path planning, obstacle-aware navigation,
or verified return to the physical starting point. Problems to resolve in the
full sketch before integration:

1. `returnToBase()` does not flush the still-active final move. It can omit the
   latest travel unless an external Stop/change already recorded it.
2. `delay(path[i].duration)` blocks normal command processing. Emergency Stop,
   connection-loss handling and obstacle updates must continue during playback.
   Use a `millis()` state machine; see Arduino's
   [nonblocking timing example](https://docs.arduino.cc/built-in-examples/digital/BlinkWithoutDelay/).
3. `isReturning` is set, but the supplied `recordMove()` never checks it. Playback
   must not be recorded or interleaved with new movement commands.
4. When 200 entries fill, the fragment silently stops saving new movements but
   keeps driving. That leaves an incomplete return route. Stop or explicitly
   invalidate replay on overflow; budget the complete sketch's RAM. The
   [Uno R3 datasheet](https://docs.arduino.cc/resources/datasheets/A000066-datasheet.pdf)
   lists only 2 kB SRAM for that model; this does not identify the user's exact
   Uno revision. The new bridge contract starts with a conservative
   80-segment limit; this is not proof of the unknown sketch's memory fit.
5. Direction inverses depend on the actual motor functions. L/R inversion works
   for suitable in-place turns; a turning arc may need a different inverse.
6. Reversing cannot rely on a front-only ultrasonic reading to establish rear
   clearance. Verify each movement's clearance and physical Stop arrangement.
7. `STATUS:AT_BASE` asserts more than timed playback proves. Publish
   `replay_complete`; require a separate observation/measurement to confirm base.
8. The proposed ESP32 handler runs the entire return before sending its HTTP
   response. Long routes exceed the backend's five-second timeout; the browser's
   fixed three-second reset is also unrelated to completion. Accept commands
   promptly and poll actual controller state instead.
9. A standard Uno has no built-in Wi-Fi. `server.on()` belongs on a confirmed
   network bridge, not directly in the Uno sketch. `192.168.4.1/return` is an
   unverified endpoint from the example, not an existing robot feature. Do not
   overwrite the working original camera/AP/DHT firmware to create it.
10. Capture failures, power resets, interrupted replay and lease loss invalidate
    the assumed path. Do not clear the trace and claim arrival after a failure.

## Prepared dashboard and bridge interface

No private runtime settings were changed. `.env.example` adds blank entries:

```text
MOVEMENT_URL=
MOVEMENT_COMMAND_URL=
```

The bridge is implemented in `features/serial_movement.py` and launched explicitly
with `scripts/uno_movement_bridge.py`. No device was opened and no private runtime
settings changed. With blank URLs, the UI remains Not configured. The operator
must upload the Uno update and start its identified USB connection before live
telemetry exists. Default firmware records only; supervised return requires both
firmware and bridge gates. See [setup and limitations](UNO_MOVEMENT_SETUP.md).

`GET /api/movement-data` uses the existing verified-user authentication and
no-store responses. The configured bridge's telemetry must contain an actually
acquired controller sample, for example (illustrative values only):

```json
{
  "source": "uno_movement_bridge",
  "trace_id": "unique-boot-and-recording-id",
  "command_id": null,
  "sequence": 42,
  "sample_age_ms": 100,
  "state": "stopped",
  "current_move": "S",
  "active_duration_ms": 0,
  "trace_complete": true,
  "return_ready": false,
  "returned_steps": 0,
  "segments": [
    {"direction": "F", "duration_ms": 1200},
    {"direction": "L", "duration_ms": 450}
  ]
}
```

Use a new trace ID after a reset or a new path recording. A complete trace begins
at an operator-declared starting point, retains every actual accepted motor
command, and includes the last segment on Stop. Mark it incomplete after any
lost segment, unrecorded movement, buffer overflow or interrupted return. A
bridge that resets must establish that it still has the correct Uno trace.

Accepted states: `idle`, `recording`, `stopped`, `returning`, `replay_complete`,
`cancelled`, `fault`. Directions are F/B/L/R, with S allowed only as current
command. Up to 80 completed segments, each 1–60000 ms and total at most 10 min;
an active duration is 0–60000 ms. A completed trace has no automatic geographic
meaning. `return_ready` must remain false until controller interlocks and the
actual return implementation are validated. Returning also requires nonempty,
complete, stopped, fresh, nonsimulated telemetry and no active mission or return.

Sample age includes the full HTTP exchange. A repeated sequence for the same
trace/source cannot become fresh through repolling. Status expires within five
seconds of acquisition; polling uses a single request per source, with a 500 ms
pause between movement requests. Preserve cached command history as history,
but clear current-motion claims and disable Return when data is stale.

The prepared authenticated `POST /api/return_to_base` accepts `trace_id`,
`segment_count` and `total_duration_ms` for the reviewed trace. The backend
creates a command ID and sends the configured bridge:

```json
{"action":"return", "command_id":"32-character-command-id", "trace_id":"unique-boot-and-recording-id"}
```

`stop` and `heartbeat` use the same identifiers. If configured, the existing
`ROBOT_COMMAND_KEY` is sent as `X-Robot-Key`; never save its value in docs. Require
a matching `{acknowledged:true,command_id,trace_id,state}` reply, where state is
`returning` for return/heartbeat or `stopped` for Stop. A timeout or malformed
reply creates persistent `command_uncertain`, blocks duplicate Return and new
missions, and keeps Stop available to the return owner. It never retries a
movement command automatically. Only matching terminal telemetry reconciles a
return; server restart preserves uncertain commands.

The updated controller implements a three-second replay lease, checks Stop and
both supplied IR obstacle inputs, and halts if renewals stop. Dashboard polling renews
only for the owning authenticated operator while the page is visible and fresh
matching `returning` telemetry exists. Hidden pages request Stop best-effort;
page closure, lost authentication and network failure must be covered by the
controller lease. These behaviors pass native software checks but still need
physical testing; the dashboard alone cannot enforce them. The older generic
ultrasonic reference is not the supplied robot's installed pin map.

## Physical integration still required

The full source and USB option are now available. Source pin assignments are
preserved in the updated sketch; confirm their correspondence to the actual Uno.
First verify nonblocking replay, final-segment capture, overflow handling,
Stop/lease expiry and per-direction clearance with wheels raised. Then run a
short controlled course, compare the actual start/end position, and record
drift, stopping behavior and camera/thermal continuity separately from software
tests. USB is tethered; no network-to-Uno connection is assumed or added.

Software checks use generated traces and mocked acknowledgements. No live
movement recording, replay accuracy or autonomous navigation has been validated.
