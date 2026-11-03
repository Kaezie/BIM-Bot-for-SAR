# Person and pose association

Updated October 28, 2026, Asia/Manila.

The October 28 extension uses `features/person_analysis.py` for both Main and
Night vision, with independent model instances and all temporal state scoped
to its camera. Night adds the same unvalidated age-group/condition and temporal
gesture fields to its own API/overlay/details list. Its detections do not enter
Main counts or mission evidence. No numerical age is predicted or thermal image
registered to Night. See [Night setup](NIGHT_VISION_SETUP.md) and the
[October 28 verification](verification/night_person_analysis_2026-10-28.json).

The main-camera pipeline now matches pose boxes to person boxes spatially and
assigns temporary track IDs across nearby frames. Reordering the detector or
pose arrays no longer determines whose pose or immobility timer is used.
Movement tests remain on hold; this update requires no robot firmware change.

## Software behavior

- `features/person_tracking.py` uses mutual, unambiguous best box overlap for
  both pose matching and temporal association. A pose belongs to at most one
  detection. Missing, weak or ambiguous evidence remains unmatched.
- Required joints must have usable coordinates and confidence before the
  retained SAR pose rules receive them. A masked zero joint is not a body part.
- Detection responses expose `track_id`, `track_number`, `pose_matched`,
  `motion_observed`, `motion_scope` and `assessment_method`. The live overlay and
  details show Track numbers. Existing saved detections without these fields
  still render with the previous Detection label.
- IDs persist through unambiguous nearby frames, including detector-order
  changes. Missing tracks are retained briefly for association, but a missed
  frame immediately breaks motion/timer continuity. Resetting a stream, changing
  resolution, a stale acquisition or a long gap starts fresh observation state.
  Track numbers are not recycled during the running server process.
- Image motion is observed separately in each person's box. Pixels shared with
  another person's box are excluded. Insufficient exclusive area or widespread
  background change yields Unknown rather than a shared scene-motion boolean.
- The first observation, uncertain motion and lost association cannot establish
  immobility. Motion-dependent condition outputs are Unknown until temporal
  evidence is available; expired/missing tracks cannot lend their timers to a
  new person.
- The existing detector class14/confidence0.25, model weights, age/pose/injury
  rules and thermal input remain. `classify_survivor` now explicitly handles
  missing motion; the remaining condition rules still need independent
  evaluation. `assessment_method` states `sar_heuristic_unvalidated`.
- Camera-generation and acquisition-age checks prevent a disconnected or stale
  inference from committing tracking state. Inference and camera I/O remain
  outside the shared video-frame lock.

## Current software defaults

These are conservative implementation gates, not tuned research settings or
measured performance. Their suitability remains to be evaluated on real scenes.

| Gate | Current default |
| --- | --- |
| Minimum box overlap, intersection over union | 0.30 |
| Required separation from a second match | 0.10 overlap score |
| Required joint confidence | 0.50 for the joints consumed by SAR rules |
| Track time gap | Less than 2 seconds, aligned with result freshness |
| Missing observations retained for association | At most two missing frames |
| Person-region image change | At least 25 changed pixels and at least 2 percent of eligible region |
| Required exclusive person region | At least half the clipped box area |
| Background reference | At least 10 percent of image area |
| Widespread background-change gate | More than 20 percent of background pixels |

The original grayscale blur and pixel-difference threshold25 are retained.

## Verification and limits

The [software verification record](verification/person_tracking_2026-10-27.json)
records 209 passing Python tests, the two Chrome fixture suites, the model smoke
check and current dashboard asset/auth checks.

Generated tests cover reversed pose order, reordered person detections,
single-use and ambiguous associations, hidden/weak joints, brief missing frames,
time gaps, resolution/context changes, discarded tracks, stale acquisition and
disconnect generations. Separate masks verify that one moving region does not
mark a second person as moving, shared pixels do not leak between people, and
widespread background change remains unknown.

The actual application function is tested with generated images and model
outputs. Both existing local models also complete a smoke check through the
updated pipeline using two generated blank frames, with unchanged weight
hashes and no workers or hardware opened. Browser fixtures verify Track labels,
motion Unknown/Region changed, old saved-record compatibility, stale clearing,
recording UI and responsive shared-monitoring layout.

These are software results. Real crossing, occlusion, camera shake, lighting,
small/partial bodies, association accuracy and inference cadence remain
unmeasured. A temporary geometric track is not biometric identity, a count of
unique survivors, a location or proof of a medical condition. Image change does
not establish world motion, consciousness, injury or entrapment. The next October27 update adds candidate temporal waving/help observations and image-inactivity duration. See [current readiness](TESTING_READY.md); real gesture/condition accuracy remains pending.

## Next stationary check

Use the existing camera setup when it can be viewed with the robot stationary
and without resuming motor tests. Sign in, connect Main camera, and open Mission
tools and history to see the survivor details.

1. Start with one consenting person. Confirm a stable Track number in successive
   clear frames; initial motion evidence may be Unknown.
2. Show two consenting people separated in view. Have one move and the other
   remain still; check that their image-motion evidence is separate.
3. Change the detection order by changing relative positions while keeping
   people separated. Check matching pose and Track numbers against the video.
4. Briefly obscure one person, then test a cautious crossing. Record any ID
   change or unmatched pose as a limitation rather than forcing identity.
5. Disconnect/reconnect Main. Old identities and immobility evidence must not
   carry into the new connection.

Record actual observations separately from generated tests. Do not turn these
checks into a consciousness/injury/age/entrapment accuracy result.
