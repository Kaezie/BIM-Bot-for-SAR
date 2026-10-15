# Setting Up Supabase for BIM-Bot

BIM-Bot now uses Supabase for two things:
1. **Auth** — employees sign in with Google, handled by Supabase Auth
2. **Storage** — recordings are uploaded to a private Supabase Storage bucket instead of Google Drive

You still need a Google Cloud OAuth client for the "Sign in with Google" button — Supabase hosts
the login flow, but Google is still who actually authenticates the employee. The difference from
before is that your Flask app never talks to Google directly anymore; Supabase sits in between.

## Part A — Create the Supabase project

1. Go to https://supabase.com/ → **New project**
2. Pick an organization, name it (e.g. `bimbot-sar`), set a database password (you won't need
   to touch the database directly for this feature, but Supabase requires one), choose a region
3. Wait for it to finish provisioning (~2 minutes)

## Part B — Google Cloud OAuth client (for the Google button)

1. Go to https://console.cloud.google.com/ → create a project (or reuse one)
2. **APIs & Services → OAuth consent screen** → set it up (External is fine; add your
   employees' Gmail addresses as test users while unverified)
3. **APIs & Services → Credentials → + Create Credentials → OAuth client ID**
   - Application type: **Web application**
   - **Authorized redirect URIs** — this is the important part: it must be **Supabase's**
     callback URL, not your app's:
     ```
     https://YOUR-PROJECT-REF.supabase.co/auth/v1/callback
     ```
     (find `YOUR-PROJECT-REF` in your Supabase project's URL / Settings → API)
4. Click **Create** → copy the **Client ID** and **Client Secret** (you'll paste these into
   Supabase next, not into your app)

## Part C — Enable Google in Supabase Auth

1. In your Supabase project: **Authentication → Providers → Google**
2. Toggle it on, paste in the **Client ID** and **Client Secret** from Part B
3. **Authentication → URL Configuration**:
   - **Site URL**: `http://localhost:5000` (or wherever you actually run the app)
   - **Redirect URLs**: add `http://localhost:5000/*` so Supabase is allowed to send the
     browser back to your app after login

## Part D — Create the Storage bucket

1. **Storage → New bucket**
2. Name it `recordings` (or whatever you set `SUPABASE_STORAGE_BUCKET` to)
3. Leave it **private** (not public) — the Flask backend uses your service role key to read and
   write it directly, and hands employees a time-limited signed link to their own file. No
   Storage policies are required for this to work, since the service role key bypasses them.

## Part E — Get your keys

In Supabase: **Settings → API**. You need three values:
- **Project URL** → `SUPABASE_URL`
- **anon / public key** → `SUPABASE_ANON_KEY` (safe to expose to the browser — it's what the
  frontend uses to talk to Supabase Auth)
- **service_role key** → `SUPABASE_SERVICE_ROLE_KEY` (**secret** — this bypasses all access
  rules; it must only ever live on the server, never sent to the browser or committed to git)

Copy `.env.example` to `.env` and fill these in:

```bash
cp .env.example .env
# then edit .env with the values above
```

## Part F — Run it

```bash
pip install -r requirements.txt
python app.py
```

Visit `http://localhost:5000` → you'll land on `/login` → click **Sign in with Google**. First
time any employee does that, Supabase creates their account automatically. Recordings saved
afterward go straight into the `recordings` bucket, organized as `recordings/<employee-id>/...`.

## Notes / things to know

- Because the service role key can read and write *anything* in your Supabase project, keep
  `.env` out of version control (add it to `.gitignore`) and never send that key to the browser.
- The Flask backend verifies each employee's session by asking Supabase's Auth API "is this
  token still valid?" — it's cached for 30 seconds per token to avoid hammering that API on
  every 1–2 second dashboard poll. If you revoke someone's access in Supabase, it takes effect
  within that window.
- To restrict who's allowed to sign in at all (beyond Google's own test-user list while
  unverified), you'd check `g.user.email` against an allow-list inside `require_auth` in
  `app.py` and reject anyone not on it.
- Links returned immediately after uploading expire after 7 days. Links opened from
  the recordings library expire after 1 hour. Both durations are set in `app.py`.
