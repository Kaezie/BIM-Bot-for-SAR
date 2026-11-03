# Survivor communication with the available headset

Updated October 27, 2026, Asia/Manila. The operator confirms a Bluetooth headset
with a microphone and earpiece. Local two-way routing software is prepared and
checked using generated streams/stubbed speakers. Real audibility, simultaneous
capture, microphone identity, range and motor-noise performance remain pending.
No standalone robot speaker/driver or ESP32 audio firmware has been added.

Use [the guided test](http://localhost:5050/testing#communication). Pair the
headset directly to the laptop. In Mission tools & history → Survivor
communication, press Find audio devices, select all four named roles, confirm
placement/low volume and press Start two-way audio.

| Role | Select | Route |
| --- | --- | --- |
| Robot microphone | Bluetooth headset microphone | Heard through operator output |
| Operator microphone | Laptop microphone or separate operator mic | Heard through robot earpiece |
| Robot output | Bluetooth headset earpiece | Receives operator speech |
| Operator output | Laptop speaker or separate headphones | Receives robot-side sound |

Default aliases and duplicate inputs/outputs are refused. The browser must
confirm exact microphone IDs and output sink IDs; mismatches fail closed.
Both routes are opened before playback begins. Cancelling a pending permission
request discards/stops a late grant. Disconnect, unavailable input/output,
hiding/closing the dashboard or sign-out stops both routes with no fallback.
Use Google Chrome at localhost:5050 if output selection is unavailable. Live
camera viewing can continue while two-way audio is active; leaving the browser
page hidden stops audio. Sound analysis and two-way mode stop each other.

Start close to the robot at low volume. Verify each direction separately, then
test the intended separation. Earpiece off-ear sleep, low volume and Bluetooth
quality/range can prevent acceptance even when the software opens correctly.
Software cannot prove physical mounting. No audio is recorded or uploaded to a
cloud service. A sound-event label does not interpret a survivor answer.

Communication notes remain separate: Add communication note in an operator
review records what actually happened without sending dashboard text to the
robot. Unclear or absent response remains unknown. Stillness does not establish
unconsciousness. The earlier visible-LED proposal is historical; this update
does not upload camera firmware or implement coded light messages.
