# Conservative camera and sensor profile

The current app uses the `conservative-2` settings in the
[shared transport profile](../features/monitoring_profile.py). The timing
table below summarizes the current browser and backend behavior. The October
28–29 trials are dated evidence. For normal operation, use the
[camera setup](NIGHT_VISION_SETUP.md) and [thermal setup](THERMAL_SENSOR_SETUP.md).

## October 28–29 trial history

The October 29 spare upload was readback-verified with an 8 FPS target,
QVGA/JPEG quality 12, platform-default transmit power, and thermal enabled at
refresh code 3. The short October 30 capture recorded fresh thermal and DHT
samples. [Spare upload](verification/night_fresh2_upload_2026-10-29.json) ·
[Thermal and DHT restoration](verification/thermal_restoration_result_2026-10-30.json)

Latest operator accepts quality20 latency but still reports reconnection. In the
recorded180s, source generation/errors and browser releases do not change:
1265frames,172/174active samples fresh, but sampled pictureage reaches6054ms.
The5s freshness policy clears/resumes the SAME subscription during that gap.
Underlying frame-delivery pauses remain unresolved; keep quality/rates and image
expiry unchanged. This window does not exclude later actual reconnects. See
[quality20 result](verification/quality20_main_result_2026-10-29.json).

The October 29 readback confirmed original JPEG quality 20, framesize 6,
pixformat 4 and xclk 20. Flask's login and dashboard routes responded after
restart. See [readback and readiness](verification/original_quality20_and_dashboard_readiness_2026-10-29.json).

Latest sharing-off trial FAILED: operator corrects the result to "no improvement
at all". The 300 s trace records 909 frames and six new source errors, with no
invalid JPEGs. No valid concurrent ping comparison was captured. See
[sharing comparison](verification/peer_sharing_comparison_2026-10-29.json).

A volatile original-camera JPEG quality10→20 trial is prepared, keeping
QVGA/framesize6, JPEG/pixformat4 and xclk20. It is NOT yet confirmed applied:
last checked route is home192.168.68.73. The bounded helper verifies settings
before and after its sole control attempt; the temporary launcher starts the
isolated Main dashboard only after successful readback, with a180s automatic
trace.272Python checks pass;9focused safety checks pass after the final metadata
adjustment. No live acceptance from this trial yet. No firmware upload, serial
opening or persistent configuration change in this continuation. Separate
October29 firmware source edits remain unuploaded.

Latest five-minute live candidate2 run still fails (4source resets; no browser
viewer releases). A further parser-ordering defect is corrected and loaded:
complete recovered JPEGs parse before the incomplete-stream10s stall check.
263Python checks pass, including regressions that fail before correction.
Transport10s, picture5s and all rates remain unchanged. Corrected-parser live
acceptance and underlying source/radio/supply diagnosis are pending. See
[parser recovery evidence](verification/recovered_frame_parser_2026-10-28.json).

The `conservative-2` change raised the upstream socket read timeout from 5 to
10 seconds and kept picture freshness at 5 seconds. Software verification
included a six-second HTTP pause and a comparison with the old timeout.

The original on new robot batteries produced6 complete pictures/~40s and TCP,
header and body timeouts. On the visually checked USB base, it produced647
pictures/120s, but the diagnostic's3-second read limit still caused3body timeouts.
The normal dashboard then retained its viewer (no DELETEs) but its5-second source
read timeout caused one reader reset:115fresh of118active samples. These are
reception measurements, not optical latency or proof of a particular power fault.

Evidence:
- [New-battery original check](verification/fresh_battery_original_check_2026-10-28.json)
- [Original USB check](verification/original_usb_transport_check_2026-10-28.json)
- [USB dashboard failure](verification/original_usb_dashboard_failure_2026-10-28.json)
- [Follow-up and current stage](verification/camera_transport_followup_2026-10-28.json)

| Setting | Fixed value |
| --- | --- |
| Upstream socket read recovery |10s, changed from5s in candidate1 |
| Visible video delivery | Maximum about6FPS; source may be slower |
| Background monitor delivery | Maximum1FPS |
| Person/pose analysis | Latest image, at most2starts/s per camera |
| Thermal Wi-Fi grid reads | At most1/s; firmware acquisition unchanged |
| Thermal browser cache reads |1s visible,2s summary |
| DHT polling when configured | Existing2s |
| Device-status polling |3s |
| Viewer lease |8s; explicit/hidden/session cleanup stays immediate |
| Video / model-result freshness | Existing5s /2s |
| DHT / thermal freshness | Existing10s /5s |
| White light | Renewable lease requested while Night is in use, with manual On/Off controls |

An expired image clears and the UI says Waiting while its viewer remains.
Candidate2 additionally lets the source socket survive a pause beyond picture
expiry. The existing malformed/oversize/stalled-frame limits, explicit cleanup,
authorization checks and generation fences remain. No old image or detection is
made fresh to conceal a transport gap. Latest-only video and inference slots
prevent queued model work from holding video publication.

During the October 28 USB comparison: original camera on its USB base only, robot master
OFF, all FIVE original jumper leads detached; spare OFF with all SIX leads
detached. DHT and thermal are physically disconnected. Process-only SENSOR_URL,
NIGHTVISION_CAMERA_URL and THERMAL_DATA_URL are deliberately blank. Their missing
readings are expected during isolation. Motor command URLs stay blank and bridge
5054 stays stopped. No private.env rewrite, serial opening or firmware upload.

IMG7591/7592/7593 show expected base direction and both seated rows; the operator
completed the USB-only exercise. These are visual/operating observations, not a
voltage or continuity measurement. USB/DHT disconnect also changes load/contacts;
regulator failure is not established. Before eventual robot-power restoration,
remove USB and base, identify the exact retained power/DHT leads and actual pin
labels, and verify the connections. Never combine robot and USB power sources.

Original and spare firmware, camera source quality/FPS, model weights and SAR
rule thresholds remain unchanged. Main/Night and restored sensors require
separate real combined-load acceptance before the whole system is called stable.
