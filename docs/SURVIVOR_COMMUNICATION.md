# Proposed survivor communication

The team confirmed that survivors must communicate through the robot without a
phone, and that the robot has no speaker, buzzer or display. A visible LED has not
yet been confirmed.

The current system can receive camera images, which an operator can use to observe
gestures. It has no implemented robot output for conveying replies to survivors.
The feature outline proposes a microphone but no speaker or display; the current
integration notes also say sound hardware is pending. A sound-event label is not
an audio stream, transcript, or understood survivor answer.

## Proposed flow

Use a short-prompt, human-verified response loop, once an outbound channel is
confirmed. First stop the robot using the existing acknowledged Stop control;
verify that it is stationary. Deliver one prompt through the confirmed channel,
observe the response on the camera (or listen if real audio becomes available),
and document the actual response and uncertainty in the detection review.
Do not infer a medical condition from a missing response.

With no additional hardware, one possibility needs confirmation:

- If the installed ESP32-CAM has a usable visible LED, firmware could transmit
  simple acknowledgements. This needs verified board/pin/power details and a
  means of teaching the survivor the signal meanings. It does not support
  arbitrary spoken questions, and its use must be validated in the test setting.
  The night-vision infrared illuminators cannot convey a visible message.

Voice communication through the robot requires a microphone, a speaker and an
appropriate output driver/amplifier plus firmware audio transport. These are not
implemented or confirmed in this workspace, so full two-way voice cannot be
claimed using only the documented current equipment.

## Dashboard changes supplied now

The Survivor communication section states the proposal and integration limits.
“Add communication note” appends a dated observation template to an existing
detection review without replacing its notes. Saving uses the existing protected
review endpoint and SQLite storage; it sends no message to the robot or survivor.
The situational report includes these saved notes through its existing event data.
Existing review saves replace the previous review, so this is not an immutable
conversation audit log.

## Clarifications before transmission implementation

1. Does the installed ESP32-CAM have a working visible flash LED, and which exact
   board model is installed?
2. If so, which firmware endpoint and pin allocation are available to control it?

No hardware command, live cloud write, or deployment was performed for this change.
