# Windows setup and robot rehearsal

Open PowerShell in the integrated `BIM-Bot-for-SAR` checkout. Use its existing
Windows Python environment if it works. For a fresh checkout with Python 3.12
installed, create the environment and install dependencies while online.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The repository includes `best.pt` and `yolo11s-pose.pt`. Keep both beside
`app.py`. The commands run the virtual environment's interpreter directly.
If reusing an environment from another checkout, substitute its absolute
`python.exe` path and keep PowerShell in this checkout.

## Start the Night-hosted dashboard

Use your existing team `.env` beside `app.py`. On a fresh checkout, copy your
working Windows `.env` locally or start from `.env.example` and fill in the
team configuration. In File Explorer, show file extensions to verify the
name is `.env`. Keep that file and its keys private. For this rehearsal, use
the installed robot firmware and the IR remote, with the optional Uno USB
bridge stopped. [Supabase setup](SUPABASE_SETUP.md)

Close your previous dashboard terminal with Ctrl+C if it uses port 5050.
Start this launcher while the laptop is online.

```powershell
& .\.venv\Scripts\python.exe -X utf8 .\run_night_hosted_demo.py
```

Open `http://localhost:5050/login` in Chrome or Edge, sign in with Google, and
verify the dashboard shows your account. Leave the terminal and tab open,
join `BIMBOT_NIGHT_TEST` in Windows Wi-Fi settings, and return to the same
`localhost:5050` tab. See the [rehearsal steps](NIGHT_HOSTED_DEMO.md) and
[offline sign-in guide](OFFLINE_RECORDING.md).

## Troubleshoot sign-in

- **The browser opens `your-project-ref.supabase.co`.** Replace the example
  URL in `.env` with the team's Project URL and restart with Ctrl+C and the
  launcher above. If it persists, confirm the working folder and check
  whether Windows sets `SUPABASE_URL` in the process environment. An existing
  environment value takes precedence over the file.
- **Google returns to `localhost:3000` or another unavailable port.** Check
  the port Flask printed. In Supabase, allow the exact return URL such as
  `http://localhost:5050/` or `http://localhost:5000/`. Correct a stale
  default Site URL on a local-only project. For a shared project, keep its
  production Site URL and add your local URL to the redirect list. Start again
  from `/login` on the same hostname and port while Flask is running. Keep
  callback fragments private because they can contain login tokens.
- **Google shows `redirect_uri_mismatch`.** In the Google OAuth client, use
  the callback shown in the Supabase Google provider settings. The local
  Flask URL belongs in Supabase's redirect list.
  [Supabase Google sign-in](https://supabase.com/docs/guides/auth/social-sign-in/auth-google)
- **Google says access is limited to approved testers.** Check the app's
  audience and test-user settings.
  [Google audience rules](https://support.google.com/cloud/answer/15549945)

An HTTP 200 from `/api/local-session` can contain a null session. Verify that
the dashboard displays your signed-in account before changing networks.

## If video stalls

Confirm Windows is still connected to `BIMBOT_NIGHT_TEST`. While the affected
feed is selected, use `http://localhost:5050/testing#diagnostics` to collect
the dashboard check. The Main camera is expected at `192.168.4.2` and Night
Vision at `192.168.4.1`. Keep the report local until you review it.
