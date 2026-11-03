# Panel requirements audit

October 27, 2026, Asia/Manila. Reviewed the integrated **BIM-Bot-for-SAR**
checkout, its project memory, the pasted movement fragment, the partner's chat
screenshot and the three supplied red-pen photographs. This is a source/software
audit, not a new live robot acceptance test. Subsequent supplied complete sketches
and the USB confirmation are incorporated below. The separate **NEW-BIMBOT-UI**
prototype is not automatically synchronized with this checkout.

Current testing guide: [localhost:5050/testing](http://localhost:5050/testing). Software readiness and pending live checks: [readiness record](TESTING_READY.md).

Current execution order and movement hold: [BIM Bot remaining implementation plan](IMPLEMENTATION_PLAN.md).

**The full set of panel requirements is not yet met.** A displayed field or a
heuristic output does not establish reliable field performance. Prior
operator-confirmed Night/thermal operation remains recorded in Project Memory;
no additional live camera, audio, GPS or motor measurement was made for this audit.

## Interpretation of the photographs

The first photo names victim detection with condition classification (injury,
entrapment, child/adult, consciousness), YOLOv8, pose/lying or motionless/waving
for help, thermal integration and hazard categories. The second and third overlap:
debris/obstacle navigation, return to base, victim location/GPS/map or route
history, detecting victims not visible using help/scream audio, two-way
communication, risk level and record storage. A few handwritten phrases are
unclear: the exact route wording, one pose/body line and some hazard sublabels.
Those are provisional readings, not invented acceptance criteria. The third
photo does not add a separate implementation just because it repeats a feature.

The partner proposes showing recorded movement instead of a live map. The
operator authorizes that display, but neither this chat nor the screenshot
establishes panel approval to replace a mandatory GPS requirement.

### Photo recheck, October 27

The day-priority plan was a subset, not a complete item-by-item transcription.
Reopened all three original JPEGs and inspected enlarged regions without
changing the originals. Explicitly retain YOLOv8, thermal human-in-debris use,
measured high/low risk and both directions of communication in the checklist.
Do not read handwritten check marks as proof of software completion.

Two phrases remain unconfirmed: the word directly below "Pose estimation"
(possibly a bounding-box/body note), and the underlined line after "Route".
The latter must not be silently equated with command-history reconstruction;
its exact meaning could require more. Bounding boxes exist in the detector and
`render_main_frame`, but that does not resolve the handwritten word.

Scope correction: the disaster list appears to include fire, earthquake, a
flood-related item, a slide-related item and explosion. The exact flood/slide
wording and the heading are partly unclear. The notes do not unambiguously
require an automatic classifier for every disaster. Earlier audit wording was
too broad on that point. Record the listed scenarios and ask whether the panel
expects operating/test contexts, automatic recognition categories, or both.
No dedicated automatic classifiers were found, but a missing implementation
should not be called a mandatory gap until that scope is confirmed.

## Evidence and gaps

| Requirement read from photo | Current evidence in code/hardware notes | Status and what is lacking |
| --- | --- | --- |
| Camera-based human/victim detection | `app.py:analyze_main_frame` runs the configured detector on class 14 and displays detections/confidence. | Local checkpoint inspection now confirms person is class14 in the configured detector. Accuracy remains unverified; representative labeled tests across lighting, distance and occlusion are still required. |
| Unclear word below Pose estimation: possible bounding-box/body note | Detection coordinates and `render_main_frame` rectangle overlays exist. | Transcription/scope unconfirmed. Do not invent an additional body-analysis requirement or mark it satisfied without confirming the word. |
| YOLOv8 | Detector defaults to local `best.pt`; pose defaults to `yolo11s-pose.pt`. Both files exist. | Local metadata verified: best.pt uses yolov12s.yaml and training-model name yolov12s.pt; pose uses yolo11s-pose.yaml, person class0 and17keypoints. Weights unchanged. This differs from the photo's YOLOv8 wording; resolve panel/manuscript alignment. Accuracy and new experiment results remain pending. See verification/vision_models_2026-10-27.json. |
| Injured victim classification | `classify_injury` uses pose asymmetry, lying posture and stationary timers. | Partial heuristic only. No validated injury classifier. Camera evidence cannot substantiate a medical diagnosis from these rules. |
| Trapped victim classification | `classify_survivor` uses motion and pose to label Possibly Trapped/Free. | Partial heuristic only. No verified physical entrapment recognition or debris-context evaluation. |
| Child/adult classification | `classify_age` compares bounding-box height with frame height using 0.35. | Partial heuristic only. Distance, occlusion and posture confound this rule; no validated age-group model/test. |
| Conscious/unconscious classification | Retained SAR rule now receives per-person region image-change evidence; first/missing/ambiguous observations produce Unknown. Shared scene motion no longer labels all people together. | Still unvalidated. Region image change/stillness does not establish consciousness or a response. Operator review remains separate; labeled evaluation and appropriate condition logic are pending. |
| Pose / lying / immobility | Spatial one-to-one pose matching, confidence-gated joints, temporary box tracks, exclusive person-region image motion and track-keyed timers now replace array-index association/shared scene motion. | Software foundation verified with generated cases and actual-model blank-image smoke. 209 Python tests and two browser suites pass. Real stationary tracking/pose/motion accuracy remains pending; temporary geometric IDs may change after occlusion/crossing. See PERSON_TRACKING.md. |
| Waving or help gesture | Per-track temporal wrist motion relative to shoulders, distinct static-raised-hand state, confidence/missing-data gates and expiring histories now supply candidates. | Software prototype checked with generated positive/negative trajectories. Real labeled clips, false alarms/misses and intent verification remain pending; it does not prove a request for help. |
| Thermal camera integration | Real MLX90640 24×32 temperatures and heatmap are integrated; prior operator feedback confirms thermal/Night continuity. | Core display implemented and previously checked. Calibration, longer combined-load testing and human-specific detection remain unverified. |
| Human under debris / victim not visible | No validated hidden-human detector. Original `analyze_thermal` thresholds grayscale video ROI brightness; it is separate from the new temperature-grid endpoint. | Not met. No thermal/RGB registration or validated person association. Thermal imaging cannot see through opaque debris; a surface heat pattern is not proof of a buried victim. |
| Navigate debris / avoid collapsed objects | Complete supplied Uno source uses two active-low IR inputs on A1/A2 and IR manual driving. Updated sketch stops movement on asserted obstacles. | Source integration is prepared and software-tested. No live obstacle-course validation, rear/side/drop-off protection or autonomous area coverage. The earlier ultrasonic reference is not proof of installed ultrasonic hardware. |
| Return to base | Updated supplied Uno sketch implements nonblocking inverse command playback, Stop, overflow invalidation and a three-second lease; USB bridge forwards matching acknowledgements. | Recording-only Uno build uploaded and independently flash-readback verified; return remains disabled. Fresh USB telemetry is verified with motor power off. Exact return, safe rear clearance and arrival measurement remain unverified. |
| Victim GPS/location/map | Global/local-position adapter exists, but no GPS receiver or local tracker is owned/connected. | Not met as automatic position. Manual mission area labels identify an operator-reported area. Movement command history is neither robot coordinates nor survivor coordinates. |
| Underlined Route phrase; partner-proposed movement display | Updated Uno recorder plus USB serial bridge feed the Recorded movement section, with direction/duration, freshness, JSON export/report context and local trace archives. | Movement display checked with fixtures; live advancing Uno USB telemetry and the dashboard adapter now verified with motor power off. Real IR route capture and physical movement remain pending. Exact panel Route phrase remains unconfirmed and may require more than this display. No spatial map/distance estimate is fabricated. |
| Sound activity at robot | Exact selected headset input/mount confirmation plus waveform/activity UI. User confirms an available Bluetooth headset with microphone and earpiece. | Software and generated audio checks pass. Real pairing/mounting/capture/source/range/noise acceptance remains pending; one headset is one independent robot input. |
| Voice / help / scream recognition | Optional local official YAMNet sound-event model now processes actual short PCM frames and reports possible speech/shout/scream/cry/knock events, other audio or uncertainty. | Real model smoke on public example speech and generated silence passes; real robot event accuracy and false alarms remain pending. It does not transcribe the word help or confirm a person. Raw audio is not saved/cloud-uploaded. |
| Two-way communication | Manual exact headset→operator and operator→headset local audio routes, explicit device/sink checks, no fallback and failure cleanup are implemented. | Generated input/stub speaker checks pass. Real simultaneous inputs, intelligibility, earpiece audibility, Bluetooth range and input/output acceptance remain pending. |
| Risk levels, high/low or measured risk | Required finite DHT validation, NWS cool screening, retained heat warning cutoffs and heat-only low-risk wording; rule-score UI retained. | Numerical/input/boundary checks pass. Sensor calibration and broader disaster-scenario scope remain pending. Preset scores are not validated probabilities or general structural safety. |
| Disaster/scenario list: fire, earthquake, flood-related, slide-related, explosion | No dedicated automatic event classifiers found. Heat thresholds are not an event classifier. | Scope needs confirmation: these may be intended operating/test scenarios rather than five mandatory automatic detectors. Exact heading and two sublabels are unclear. Do not treat handwritten check marks as implementation evidence. |
| Record portal / storage | Authenticated recordings UI, local MP4 saves, queued Supabase synchronization, mission events, operator reviews and JSON situational reports exist. | Implemented software. Real cloud upload/retrieval and retention acceptance remain unverified. Browser clips are video-only; sound analysis is not recorded or uploaded. |

Thermal limitation is documented by the manufacturer:
[FLIR: thermal cameras show surface temperature differences, not through opaque objects](https://flir.custhelp.com/app/answers/detail/a_id/3025).
This does not prevent using the array for visible exposed heat patterns, but
that narrower capability must be tested and described accurately.

## What can be demonstrated with the available setup

- Existing video/Night view and thermal heatmap, with fresh-source labels.
- Existing DHT/heat-risk display, described as threshold-based heat screening.
- Camera detections and pose estimates, described as unvalidated estimates with
  separate operator assessment; avoid presenting motion as proven consciousness.
- Manual observation-area labels and saved evidence/reviews/recordings.
- Headset analysis after a compatible borrowed device is actually available and
  verified. Until then only generated software tests and the optional local
  laptop demonstration are established.
- Fresh stopped Uno USB telemetry was verified with motor power off. The bridge
  is now stopped for the operator's movement hold; actual IR command history and
  physical driving still await the remote.

## Priority before defense

1. Follow the independent software order in IMPLEMENTATION_PLAN.md. Model
   identity and the pose/person association foundation are software-checked.
   Next validate stationary real scenes before evaluating condition/help gestures.
2. Sound-event recognition and exact-device two-way routing are now software-checked.
   User confirms a Bluetooth headset with mic/earpiece; proceed with the guided
   real source, audibility and range checks without activating audio automatically.
3. Verify heat-risk rules, recording/report behavior and available stationary
   camera/thermal operation. Keep live device and cloud acceptance separate from
   generated software checks.
4. Resolve YOLOv8 versus current YOLOv12s, GPS substitution, ambiguous handwriting
   and disaster-scenario scope with the adviser/panel. Uncertainty does not
   authorize removing requirements or inventing additional classifiers.
5. Keep movement work ON HOLD until the operator explicitly resumes with the
   remote. Preserve the verified Uno firmware, stopped USB bridge and disabled
   return. Resume the documented IR/physical motor/obstacle/return checks later.

See [Headset setup](HEADSET_SOUND.md), [Uno USB setup](UNO_MOVEMENT_SETUP.md),
[movement feasibility](MOVEMENT_INTEGRATION.md), [position limitations](POSITION_INTEGRATION.md),
and [survivor communication](SURVIVOR_COMMUNICATION.md). Software verification
results for this change are recorded in Project Memory; they do not establish
that all panel requirements are met.
