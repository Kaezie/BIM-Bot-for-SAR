# Supabase setup for BIM-Bot

Supabase Auth handles Google sign-in. Recordings save to the laptop first and
sync to a private Supabase Storage bucket when internet is available.

## Project and Google sign-in

1. Open the team's Supabase project. For a separate installation, create a
   project in the [Supabase Dashboard](https://supabase.com/dashboard).
2. On the Supabase **Google** sign-in provider page, copy the project's callback
   URL. On a standard hosted project it is
   `https://YOUR-PROJECT-REF.supabase.co/auth/v1/callback`.
3. In Google Cloud, configure the OAuth consent screen and create a **Web
   application** OAuth client. Add the Supabase callback to **Authorized
   redirect URIs**. If Google restricts access to approved testers, check the
   app's audience settings.
4. Enable Google in Supabase and enter the Google client ID and client secret in
   the provider settings. [Supabase Google sign-in guide](https://supabase.com/docs/guides/auth/social-sign-in/auth-google)

## Local app redirect

Set `PORT=5050` in the app's local `.env` to match the examples in these
guides. In Supabase **Authentication → URL Configuration**, add the exact
`http://localhost:5050/` to **Redirect URLs**. The app requests the current
browser origin followed by `/` after Google sign-in. If Flask uses a different
port or hostname, allow that exact address with the trailing slash.

For a project used only with this local installation, use the same address as its
**Site URL**. For a shared project with a production Site URL, keep that default
and add the local address to the redirect list. [Supabase redirect URLs](https://supabase.com/docs/guides/auth/redirect-urls)

## Storage and local configuration

Create or reuse a private Storage bucket named `recordings`, or set
`SUPABASE_STORAGE_BUCKET` to its actual name. Flask uploads and signs links
using its server-side key. Camera clips use `<user-id>/<filename>.mp4` and
mission reports use `<user-id>/reports/<filename>.txt`. If the private bucket
restricts file types, allow `text/plain` alongside the existing video
types. [Supabase bucket restrictions](https://supabase.com/docs/guides/storage/buckets/creating-buckets)

**Save Report** in Mission tools writes JSON to the laptop first. The local
queue renders the saved content as plain text and retries the Supabase upload
when internet returns. The saved reports list shows upload confirmation and
lets the signed-in owner download the laptop JSON.

**Record screen** captures the display selected in the browser picker. Choose
**Entire Screen** and keep the dashboard visible to include detection banners.
Screen capture is video-only, continues across camera waiting states, and saves
to the laptop. Use **Stop** or the browser's stop-sharing control to finish.

Copy `.env.example` to `.env` on a new checkout. Use values from the same
Supabase project.

| Local variable | Value |
| --- | --- |
| `SUPABASE_URL` | Project URL from the Connect dialog |
| `SUPABASE_ANON_KEY` | Public `anon` key in Settings → API Keys |
| `SUPABASE_SERVICE_ROLE_KEY` | Privileged `service_role` key in Settings → API Keys |
| `SUPABASE_STORAGE_BUCKET` | Private bucket name, default `recordings` |
| `PORT` | `5050` for the examples in this guide |

This checkout's verified setup uses the legacy key pair. Supabase is
deprecating those keys. Keep the privileged key in the server's ignored
`.env` and use Supabase's rotation guidance if a key is exposed.
[Supabase API keys](https://supabase.com/docs/guides/getting-started/api-keys)

## Verify sign-in and recording

1. Follow [local setup](../README.md#run-locally) to start Flask.
2. While online, open `http://localhost:5050/login` and sign in with Google.
   Confirm the dashboard shows the signed-in account before joining robot Wi-Fi.
3. Follow the [offline workflow](OFFLINE_RECORDING.md) to verify a clip saves
   locally, remains downloadable and syncs when internet returns. Earlier
   cloud-only clips require internet and use signed links valid for one hour.

The local session lasts up to 12 hours. Sign out on the laptop to revoke it
immediately. While offline, an existing session cannot check for cloud account
revocation and may remain usable until it expires.
