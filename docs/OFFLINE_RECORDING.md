# Google sign-in and offline recordings

This workflow is implemented in the integrated `BIM-Bot-for-SAR` application.
The separate `NEW-BIMBOT-UI` checkout does not automatically receive these changes.

## Before joining the robot network

1. Start the SAR Flask app, then open `http://localhost:5050` on this laptop.
2. With internet available, choose **Sign in with Google**. Google is the only
   sign-in option; the old `/signup` address redirects to `/login`.
3. After the dashboard opens, join the robot's **ESP32_CAM** Wi-Fi. Keep using
   the same browser and address. `localhost` and `127.0.0.1` use different cookies.

The server verifies the Google account online and grants a local session lasting
up to 12 hours. Camera viewing, telemetry, mission review, local recording, and
local downloads use that session without an internet connection. Reloading the
page or restarting the Flask app does not erase the session. Signing out revokes
it locally. After expiry, sign in online again; starting a new Google sign-in
while offline cannot create a session.

The browser stores an opaque HttpOnly, SameSite=Strict cookie. The local database
stores its hash and expiry, not Google or Supabase access/refresh tokens. A local
session's fixed lifetime is independent of cloud token refresh. Account revocation
in Supabase cannot be checked while offline, so an already issued local session
may remain usable until its expiry or local sign-out. Changes to browser storage,
the server's data folder, or the laptop clock can affect the offline session.

Dashboard JavaScript, styles, icons, and fonts require no external requests. The
Supabase JavaScript SDK is loaded only for online sign-in or its callback.

## Record and save

Select **Main camera** or **Night vision**, wait for a live image, and start a
recording. The camera selected when recording begins remains the recording source
when tabs change. On **Stop**, the browser creates an MP4 and sends it to the local
Flask server on the laptop; this requires no internet. The supported browser must
provide MP4/H.264 MediaRecorder support. This workflow has been checked in Chrome.

The save dialog confirms success only after the MP4 and queue metadata are on
local disk. **Done** then allows another recording even when Supabase is offline.
The recordings library shows each local clip as queued or uploaded, and provides
an offline **Download MP4** link. Earlier cloud-only clips have a separate button
that requires internet.

If local saving fails, keep the page open and use **Retry local save** or
**Download MP4 backup**. The unsaved video is held in that browser page's memory;
closing it can lose the clip. A browser backup alone does not add the clip to the
automatic cloud queue. Local-session expiry stops camera access, but preserves
an unsaved clip's backup controls.

The local endpoint allows at most 512 MiB per recording. Record manageable clips;
the browser must hold a recording in memory until it reaches disk. Recording is
performed by the dashboard, so keep its tab open and the laptop awake until Stop
and the local-save confirmation.

## Where files live

Default on this laptop:

```text
/Users/christine/Documents/ChatGPT/BIM-BOT/BIM-Bot-for-SAR/local_data/
  recordings/<supabase-user-id>/<unique-id>_bimbot_<main-or-nightvision>_....mp4
  recordings.sqlite3
  sessions.sqlite3
```

Set `LOCAL_DATA_DIR` to an absolute folder in `.env` to choose another location.
Use the same folder after restarting; keep both MP4 files and the queue database.
The folder is private application data and ignored by Git. Local clips are scoped
to their verified owner in the dashboard and stay on this laptop after upload.
Files and queue metadata consume laptop storage; there is no automatic deletion.

## Supabase sync

A background worker tries due uploads approximately every 30 seconds while the
Flask app runs. Failures back off up to five minutes and remain pending in SQLite
across restarts. **Sync queued recordings** requests another attempt without
blocking recording. A Wi-Fi connection or browser `online` event alone does not
mean Supabase is reachable.

Each upload uses the verified owner's folder in the configured private bucket:
`<user-id>/<unique-local-filename>.mp4`. Retries reuse that path to avoid duplicate
cloud objects. The local copy is retained after Supabase confirms an upload.
The worker uses server-side credentials; no refresh/access token is stored with
queued clips. If a user signs out, already queued clips continue to sync under
their original owner.

Uploads use the existing Supabase Python Storage client with its bounded network
timeout. A failed upload retries the whole file; byte-level resumable upload is
not implemented. Bucket/project file-size limits or service errors can keep a
large clip queued even after internet returns. The local copy remains available.

Supabase cannot receive recordings over an internet-free ESP32_CAM connection.
The recommended workflow is local recording on the robot network, followed by
automatic sync after switching back to internet Wi-Fi. If simultaneous live
robot access and cloud upload are required, add a second internet connection
such as Ethernet or USB tethering, with routing that keeps `192.168.4.x` reachable
through robot Wi-Fi. That two-network arrangement has not been tested here.

## Verification scope

Automated tests cover Google-only authorization, persisted offline sessions,
local-save/download integration, owner isolation, MP4 validation, concurrent
queue handling, retry idempotency, and mocked cloud failures. Browser tests cover
Google-only UI, cookie-first reload, MP4 capture, local-save failure/backup,
pending/synced states, and camera/tab behavior. They do not authenticate an actual
Google account, upload to the live bucket, or prove either physical camera works.

Supabase references: [Google OAuth](https://supabase.com/docs/reference/javascript/auth-signinwithoauth),
[Python Storage upload](https://supabase.com/docs/reference/python/storage-from-upload).
