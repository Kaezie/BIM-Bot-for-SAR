# BIM Bot Night Vision Hotspot Demo Guide

Use this guide with the integrated `BIM-Bot-for-SAR` checkout and the robot’s current camera firmware. Night Vision hosts `BIMBOT_NIGHT_TEST` and serves Night video and the thermal grid. Main joins as a client and serves Main video and DHT temperature and humidity. Use the robot’s charged batteries and the team’s saved hotspot password.

## Before the demo

1. Use the actual demo laptop and browser. Open a terminal in `BIM-Bot-for-SAR`. Use the same Python environment, `.env`, and vision-model files that run the regular dashboard. For a new laptop, follow the [main setup](../README.md) or [Windows setup](WINDOWS_SETUP.md) first.
2. Close any earlier BIM-Bot server using port 5050. While the laptop is still online, start the Night-hosted launcher with the project’s Python interpreter.

   **macOS**, from the activated project environment

   ```sh
   python run_night_hosted_demo.py
   ```

   **Windows PowerShell**, using the project’s `.venv`

   ```powershell
   & .\.venv\Scripts\python.exe -X utf8 .\run_night_hosted_demo.py
   ```

3. Open `http://localhost:5050/login`. Sign in with Google and wait for the signed-in dashboard. Keep the terminal, browser, and `localhost:5050` address open when switching networks. See [offline sign-in](OFFLINE_RECORDING.md) for session details.
4. Place the robot in a clear area and turn it on. Join `BIMBOT_NIGHT_TEST` from the laptop’s Wi-Fi menu. Stay on it if the laptop reports that it has no internet. Return to the signed-in dashboard tab.
5. With the robot stationary, check **Main** and **Night Vision** in turn. Confirm that each image responds to movement in front of that camera. Confirm a fresh **DHT** reading and open **Thermal** to check that the temperature grid updates. Opening **Night Vision** automatically requests the white light. To repeat the logged light-off conditions, turn the light off before timing and verify the camera confirms **White light: off**. Re-entering Night Vision requests the light again.
6. Before driving, verify the crew can stop the robot with the IR remote’s **OK** button in a clear area. Keep a spotter with the remote during the driving segment. Begin the moving demonstration after the stationary checks and Stop check pass.

## Run the demo

1. With the robot stationary and Main live, keep the two standing figures and one fallen figure fully in frame. A side view of the fallen figure shows more of the torso. Check for **2 Standing survivors** and **1 Fallen figure**. The totals describe visible posture, and unclear results require operator review.
2. After the manual Night Vision check, return to Main. Confirm the white light is off and let Main see a bright scene for about five seconds to rearm automatic switching. Keep Main live on the visible dashboard and darken the scene. Check that Night Vision opens automatically, shows **White light: on**, and provides a usable image. Verify the physical LED as well.
3. Show DHT temperature and humidity and the live Thermal grid. Use a person or a hand in the thermal sensor’s field of view to demonstrate a change in the grid.
4. Drive the planned short route with the spotter watching the robot. Show the responses to the course and stop with IR **OK**. Use the remote to stop if video or control becomes unreliable. Include automatic return only after rehearsing it on the same robot.
5. At the end, stop the robot and switch it off. Rejoin normal Wi-Fi when internet access is needed. End the dashboard server with `Ctrl+C` when finished.

## Recover from a connection loss

1. Stop the robot using the IR remote and keep it stationary. Check whether the laptop is still on `BIMBOT_NIGHT_TEST`. If it switched networks, rejoin the robot network and return to the same dashboard tab. If several known networks compete, disable automatic joining of the competing network for the rehearsal.
2. If the laptop drops the hotspot again, check whether a phone can still see `BIMBOT_NIGHT_TEST` and whether the Night camera’s power indicator is on. Note the time. If the hotspot is missing, check power and battery connections with the robot off, then restart the robot and repeat the stationary checks.
3. If the hotspot is present and the laptop is connected, reload the dashboard once. Check **Night Vision**, **Main**, **DHT**, and **Thermal** for fresh updates. If the session expired, return to an internet connection, sign in again at the same local address, and rejoin the robot network. Use the stationary demonstration if fresh video cannot be restored.

## Test and service reference

| Dashboard input | Tested address |
| --- | --- |
| Main video | `http://192.168.4.2:81/stream` |
| Main DHT | `http://192.168.4.2/dht` |
| Night Vision video | `http://192.168.4.1:81/stream` |
| Night Vision thermal grid | `http://192.168.4.1/thermal` |

The launcher applies these four addresses to its own Flask process. The team’s `.env` continues to provide credentials and unrelated settings. The dashboard listens on the laptop only. Use `python app.py` for a setup that should follow its normal `.env` camera configuration.

For rehearsal, try the guided checks at `http://localhost:5050/testing` and save a diagnostic snapshot if a stream stalls. Record the test duration, robot movement, lighting, interruptions, and recovery. The November 26 stationary robot-power test logged both cameras and both sensors for 30 minutes with the white light off. The 47-minute 48-second laptop network-address window included time before and after that formal capture.
