# Change history

This document preserves earlier update notes. Descriptions below reflect the app
at the time of each update. See [the README](../README.md) for the current file
layout and run instructions, and [Supabase setup](SUPABASE_SETUP.md) for setup.

## Workspace organization — October 1, 2026

- Shared and page-specific CSS lives in `static/css/`; browser code lives in `static/js/`.
- Dashboard markup is divided into section templates under `templates/dashboard/`.
- Setup and historical notes live in `docs/`; manual utility scripts live in `scripts/`.
- The storage check runs only when explicitly launched, so importing it cannot upload files.

## Initial authentication and storage update

## 1. Login — Google sign-in via Supabase Auth
- `/login` is a "Sign in with Google" page. The button calls Supabase Auth's OAuth flow
  (`supabase.auth.signInWithOAuth`) — Google still authenticates the employee, but your Flask
  code never talks to Google directly anymore; Supabase handles that exchange.
- There's no server-side session in Flask. The browser holds the Supabase session (via the
  supabase-js SDK) and sends it with every request — as an `Authorization: Bearer <token>`
  header for normal API calls, or as `?access_token=...` for things loaded as `<img src>`
  (which can't carry custom headers), like the camera feed.
- Flask verifies that token on each protected route (`require_auth` in `app.py`) by asking
  Supabase's Auth API whether it's still valid — cached for 30 seconds so it isn't hit on every
  poll.
- No local user database anymore — Supabase's own `auth.users` table is the record of who
  exists. Nothing employee-related is stored in SQLite.

## 2. Recordings → Supabase Storage (not Google Drive)
- After stopping a recording, the panel now offers **☁️ Save to Cloud Storage**, **⬇️ Download
  to Device**, or **Discard**.
- "Save to Cloud Storage" uploads to a private Supabase Storage bucket (`recordings` by
  default), under a folder named by that employee's Supabase user ID —
  `recordings/<employee-id>/<filename>.webm`.
- The backend uses your Supabase **service role key** to do the upload (bypassing Storage access
  rules entirely) and hands back a signed, time-limited link (7 days) the employee can open
  or share.
- See `SUPABASE_SETUP.md` for the one-time setup: creating the Supabase project, wiring up the
  Google OAuth client for Supabase Auth, and creating the Storage bucket.

## 3. Redesigned Dashboard with New Feature Sections
Same as before — the single fullscreen camera view is one tab among four, switchable from a
bottom tab bar:

| Tab | Status |
|---|---|
| 📷 Main Cam | Fully working — same YOLO survivor detection + hazard HUD as before |
| 🌙 Night Vision | UI + backend route ready (`/nightvision_feed`); shows "not installed yet" until you set `NIGHTVISION_CAMERA_URL` in `app.py` once the second ESP32-CAM is wired |
| 🌡️ Thermal | UI + backend route ready (`/api/thermal-data`); shows "not installed yet" until you set `THERMAL_SENSOR_ENABLED = True` in `app.py` and feed real MLX90640 grid data into it |
| 🔊 Sound | UI + backend route ready (`/api/sound-data`); shows "not implemented yet" until you set `SOUND_DETECTION_ENABLED = True` and wire up a sound pipeline |

## Where things live now

```
app.py                       ← Flask backend
best.pt                      ← your trained YOLO model (unchanged — keep it here)
templates/
  login.html                 ← "Sign in with Google" page (Supabase Auth)
  dashboard.html             ← main dashboard (was: index.html)
.env                         ← YOU create this from .env.example (see SUPABASE_SETUP.md)
requirements.txt
SUPABASE_SETUP.md
```

## Quick start

```bash
cp .env.example .env     # then fill in your Supabase project's keys
pip install -r requirements.txt
python app.py
```

Then visit `http://localhost:5000` — you'll be sent to `/login` first. Click "Sign in with
Google"; the first time any employee does that, their account is created automatically.

## Things worth deciding later
- The `SUPABASE_SERVICE_ROLE_KEY` in `.env` can read/write anything in your Supabase project —
  keep `.env` out of version control.
- Right now anyone with a Google account can sign in and get a BIM-Bot account created for them,
  limited only by Google's test-user list while your OAuth app is unverified. For a real
  allow-list later, check `g.user.email` in `require_auth` (`app.py`) before treating a token
  as valid.
- The hazard classifier, YOLO detection, and DHT sensor logic are untouched from your original
  `app.py` — only auth and storage were swapped out around them.


## Field-rescue dashboard refresh — September 30, 2026

- Clean green-accented layout for phone, tablet, and desktop, with priority survivor and environmental risk cards.
- Camera controls sit outside the feed. Unavailable hardware keeps a visible, labeled tab.
- Freshness is checked against the robot's last successful update. Missing/stale readings show unavailable assessments instead of old values or zero detections.
- Recordings automatically upload after stopping. Failed uploads retain the clip while this page stays open, with retry, backup download, and explicit discard actions. Leaving or signing out with an unsaved clip is guarded.
- Each user's recording library reads only their verified account folder, with private signed links issued when opening a recording.
- Alert history persists locally in `mission_history.sqlite3` (latest 10,000 events retained; latest 100 displayed). Trends show the last hour; sensor samples are retained for 24 hours. History starts collecting after this update and uses real observations only. Back up the database when moving the server.
- Detections still require the trained `best.pt` model and a connected camera. Night vision, thermal, and sound still require their physical hardware/data pipelines.

Validation: `python -m unittest discover -s tests -v`. Browser checks use `python scripts/preview_ui.py` and `node tests/dashboard_ui.cjs` with Playwright available. Set `CHROME_PATH` for an installed browser if needed. These browser tests use fixture data and do not write to live cloud storage.
