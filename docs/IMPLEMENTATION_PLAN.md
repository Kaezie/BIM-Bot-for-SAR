# BIM Bot remaining implementation plan

Updated October 28, 2026, Asia/Manila.

Night-camera extension: the same person/pose, adult/child size estimate,
unvalidated condition rules, temporal gesture and inactivity software is now
available for Night with separate tracks, timers and details. Repeat stationary
Tests 1–2 on Night during Test 5; live low-light and condition accuracy remain
pending. Main counts and mission evidence retain their own source. No numerical
age model, firmware upload or movement work is included. See
[Night integration](NIGHT_VISION_SETUP.md).

Continue the panel requirements that can progress while the robot stays still.
Movement testing remains on hold because the operator does not have the IR
remote. The Uno telemetry bridge is stopped and supervised return is disabled.
Use the integrated **BIM-Bot-for-SAR** checkout for this work; the separate
**NEW-BIMBOT-UI** checkout is not synchronized automatically.

Open the [guided stationary tests](http://localhost:5050/testing) for setup, ordered checks and operator observations. [Current software readiness](TESTING_READY.md) separates tested implementation from pending hardware/accuracy acceptance.

This is the execution order. The [panel audit](PANEL_REQUIREMENTS_AUDIT.md)
retains the original requirement readings and implementation evidence. An item
is complete only for the stated check: passing software checks does not complete
physical validation or establish research accuracy.

## What the movement hold affects

| Work | Effect of the hold | Remaining dependency |
| --- | --- | --- |
| Person detection, pose processing, gesture software and evaluation preparation | Can proceed on the laptop or stationary images/video. | Representative authorized labeled examples for accuracy claims. |
| Main and Night video, DHT and thermal | Stationary operation can be checked independently. | Robot camera/sensor power and a reachable robot network; previous accepted operation is retained. |
| Sound recognition software | Can be prepared without driving. | Actual audio model/data and a real robot audio input for acceptance. |
| Two-way audio | Software preparation can proceed without driving. | A verified input and an audible robot output; neither is established by an activity meter. |
| Local recordings, reports and cloud synchronization | Can be checked without a driven mission. | Signed-in session, a real clip, and internet for cloud acceptance. |
| Physical obstacle avoidance, driven command recording and return | On hold. | Remote availability and explicit operator resumption. |
| Motor-noise audio, vibration effects and combined driving endurance | On hold for the moving portion. | Validated motor control and the relevant camera/audio devices. |
| GPS and automatic victim coordinates | Unfulfilled independently of the hold. | A real positioning method or an explicitly accepted scope change. |
| Complete autonomous mission | Cannot be claimed complete. | The paused movement checks and all other required components. |

## Software order while movement is on hold

Work through this sequence without changing firmware or activating audio devices.
Live camera/audio checks are separate from laptop checks.

| Order | Focus | Current state | Completion evidence |
| --- | --- | --- | --- |
| 1 | Confirm the existing detector and pose model identities | Identity check complete. Configured `best.pt` reports `yolov12s.yaml`, 20 classes, person at class14. Pose reports `yolo11s-pose.yaml`, person at class0 and 17 keypoints. Weights unchanged. Panel version alignment and accuracy are pending. | [Identity report](verification/vision_models_2026-10-27.json) and repeatable `scripts/check_vision_models.py`. No model replacement or new experiment settings. |
| 2 | Associate each pose with the correct person and maintain person identity over time | Software foundation implemented and checked with generated cases: spatial one-to-one matching, temporary IDs, per-region image motion, unknown states and stream resets. Next: stationary real-scene acceptance. | [Behavior and checks](PERSON_TRACKING.md). Real association accuracy, occlusion/crossing and camera-motion behavior remain pending. This does not validate condition labels. |
| 3 | Evaluate lying/immobility and the four condition estimates | Per-track image-inactivity duration and conservative unknown states are prepared for observation. Age/injury/consciousness/entrapment remain unvalidated heuristics. | Labeled evaluation and real reference truth remain pending; do not infer a clinical condition from stillness. |
| 4 | Add and evaluate waving/help gestures | Temporal raised-hand/waving candidates implemented with per-track histories, shoulder-relative motion and confidence/missing-data gates. | Generated cases pass; real positive/negative clips and false-alarm/missed-event evaluation remain pending. See TESTING_READY.md. |
| 5 | Complete robot sound recognition software | Exact headset input plus optional local YAMNet sound-event inference prepared. Real model smoke checks pass on public speech/generated silence. Bluetooth headset availability confirmed. | Actual headset capture/source/range and labeled event accuracy pending. Does not transcribe help or confirm a survivor; one headset is one robot input. |
| 6 | Implement and validate two-way communication | Manual exact two-input/two-output local routes, source/sink verification, cancellation and disconnect/hidden/sign-out cleanup implemented. | Generated stream/stub output checks pass. Real simultaneous-input operation, two-direction audibility and range remain pending. |
| 7 | Verify risk calculation and its scope | Invalid/missing DHT rejection, NWS cool-weather screening, retained warning-cutoff boundary checks and heat-only wording implemented. | Numerical tests pass. Real calibration and disaster-scenario scope remain pending; preset scores are not calibrated probabilities. |
| 8 | Verify evidence, recording and retrieval | Local MP4, retry queue, reviews and JSON reports exist in software. | Real local save/download/playback, offline reload, later cloud upload/retrieval, correct source labels and retained local copy. Audio is currently absent from saved clips. |

Continue dataset and evaluation preparation alongside the relevant software item.
Do not invent training settings, scores or completed field tests. The actual
training/evaluation work and the separate ML2 course submissions remain tracked
in [Project Memory](../../Project%20Memory/MACHINE_LEARNING_2.md).

## Stationary hardware checks

These do not require confirmation of driving, but need their own devices and
operator setup. They are not a request to turn on motor power during the hold.

| Component | Retained result | Still required |
| --- | --- | --- |
| Original camera and DHT | Existing video and environmental-data integration. | Fresh video and readings together on the intended network. Preserve original firmware and wiring. |
| Spare Night view | Operator previously confirmed working video and acceptable latency. | Sustained stationary dual-camera continuity, reconnection and lighting checks as needed. No new upload is scheduled. |
| MLX90640 thermal | Operator accepted faster display; a short live check measured about four complete thermal images per second. | Temperature/reference calibration, noise, longer combined operation and tested use of human heat patterns. RGB association remains unvalidated; the heatmap does not establish hidden-victim detection. |
| Robot audio input | User confirms a Bluetooth headset with microphone and earpiece; exact-input/recognition software prepared. | Actual device model, pairing, placement, source/range/noise and disconnect acceptance pending. One robot input does not provide two independent camera microphones. |
| Robot audio output | Bluetooth headset earpiece is operator-confirmed available; software routing prepared. | Real browser sink availability, audibility, two-input support and range pending. |
| Position source | No GPS/GNSS or validated local tracker is connected. | Decide a feasible approved method; automatic position remains incomplete. |

## Movement work remains on hold

The recording-only Uno upload is independently readback-verified. Fresh USB
telemetry was verified with motor power off. These results do not establish an
IR-command trace or physical movement.

Resume only when the operator has the remote and explicitly resumes movement:

1. Check IR `*`, brief Up, release and OK with motor power off.
2. Verify real directions and Stop with a controlled physical setup.
3. Check actual obstacle inputs and physical stopping/connection-loss behavior.
4. Separately enable and assess supervised timed return and lease expiry.
5. Measure return drift and then run the combined driving endurance checks.

Do not restart the USB bridge, upload firmware, send motor commands or re-enable
return as part of the independent software work above.

## Panel and scope questions

| Question | Why it stays separate from implementation |
| --- | --- |
| Panel photo says YOLOv8; manuscript says YOLOv12; current detector metadata says YOLOv12s | Preserve the working model while confirming the required version. Inspection does not establish panel approval. |
| Can recorded commands plus manual area labels replace GPS/map? | Operator preference does not establish adviser/panel acceptance. They do not provide automatic robot or survivor coordinates. |
| What do the underlined Route phrase and the word below Pose estimation say? | Their exact readings remain unconfirmed; do not replace them with invented requirements. |
| Are fire, earthquake, flood/slide and explosion operating scenarios or automatic recognition categories? | The photos do not clearly require five automatic event classifiers. |
| Which audio events and communication directions must be demonstrated? | Sound activity, recognized events and live two-way communication need different implementations and acceptance evidence. |

## Requirement completion checklist

- [x] Identify the configured local detector/pose metadata and verify person-class mappings.
- [ ] Validate person detection on representative labeled scenes.
- [ ] Resolve the required YOLO version with the adviser/panel.
- [x] Implement and software-check one-to-one pose matching, temporary tracks and independent image-motion evidence.
- [ ] Validate per-person pose matching and temporal tracking on actual stationary camera scenes.
- [ ] Evaluate lying/immobility, injury, entrapment, child/adult and consciousness estimates separately.
- [x] Implement and software-check candidate temporal waving/help gestures.
- [ ] Evaluate waving/help gestures against real labeled positive/negative cases.
- [ ] Calibrate and evaluate thermal human-heat use and any RGB association.
- [x] Prepare local YAMNet sound-event inference and manual exact-headset input.
- [ ] Validate real robot sound capture and required event accuracy; word-level help recognition remains separate.
- [x] Implement and software-check manual exact-device two-way audio routing.
- [ ] Establish live two-way audibility and range on the actual headset/laptop.
- [ ] Validate heat-risk screening and resolve the disaster-scenario scope.
- [ ] Complete real recording, offline playback, cloud synchronization and retrieval acceptance.
- [ ] Establish an approved position/location method; retain the ambiguous Route requirement for clarification.
- [ ] Resume and validate navigation/obstacle/return behavior after the operator lifts the movement hold.
