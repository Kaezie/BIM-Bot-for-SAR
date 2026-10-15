import os
import sqlite3
import math
from uuid import uuid4
import threading
import time
from datetime import datetime
from functools import wraps
from contextlib import contextmanager

from flask import Flask, Response, jsonify, request, render_template, g
from ultralytics import YOLO
import cv2
import numpy as np
import requests

from supabase import create_client
from features.telemetry import Telemetry
from features.missions import Missions
from features.routes import register as register_feature_routes

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Load a .env file if python-dotenv is installed and one exists (optional —
# you can also just export these as real environment variables).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

app = Flask(__name__)

# =========================================================
#  SUPABASE CONFIG
#  See docs/SUPABASE_SETUP.md for where each of these comes from.
# =========================================================

SUPABASE_URL = os.environ['SUPABASE_URL']
SUPABASE_ANON_KEY = os.environ['SUPABASE_ANON_KEY']
SUPABASE_SERVICE_ROLE_KEY = os.environ['SUPABASE_SERVICE_ROLE_KEY']
SUPABASE_STORAGE_BUCKET = os.environ.get('SUPABASE_STORAGE_BUCKET', 'recordings')

# Used to verify whatever access token the browser sends us on each request.
supabase_auth_client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
# Used server-side only, to read/write Storage regardless of the per-user
# session — this key must never be sent to the browser.
supabase_admin_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# SAR models and streams. The original processing functions below are authoritative.
detection_model = YOLO(os.path.join(BASE_DIR, os.environ.get('YOLO_MODEL_PATH', 'best.pt')))
pose_model = YOLO(os.path.join(BASE_DIR, os.environ.get('POSE_MODEL_PATH', 'yolo11s-pose.pt')))
CAMERA_URL = os.environ.get('CAMERA_URL', 'http://192.168.4.1:81/stream')
SENSOR_URL = os.environ.get('SENSOR_URL', 'http://192.168.4.1/dht')
THERMAL_URL = os.environ.get('THERMAL_URL', 'http://192.168.4.1:82/stream')
NIGHTVISION_CAMERA_URL = os.environ.get('NIGHTVISION_CAMERA_URL')
# Temperature-grid JSON and the SAR thermal video stream are different inputs.
telemetry = Telemetry({kind: os.environ.get('THERMAL_DATA_URL' if kind == 'thermal' else f'{kind.upper()}_URL', '')
                       for kind in ('thermal', 'sound', 'position', 'robot')}, requests)
last_detection_at = None

# ── GLOBAL STATE ──
cap = None
thermal_cap = None
thermal_available = False
prev_frame = None
latest_detections = []
is_recording = False
frame_count = 0
last_results = None
stationary_timers = {}

latest_sensor_data = {
    "temperature": 0.0,
    "humidity": 0.0,
    "heat_index": 0.0,
    "risk_level": "Initializing...",
    "risk_score": 0,
    "confidence": 0.0,
    "probabilities": {"low": 0.0, "moderate": 0.0, "severe": 0.0},
    "method": "threshold",
    "timestamp": "Waiting for Robot...",
    "is_recording": False,
    "interpretation": "--",
}

# ── HEAT INDEX ──
def calculate_heat_index(temp_c, rh):
    if temp_c is None or rh is None:
        return 0.0
    T = temp_c * 9 / 5 + 32.0
    R = rh
    HI_f = (-42.379 + 2.04901523*T + 10.14333127*R - 0.22475541*T*R
            - 0.00683783*T**2 - 0.05481717*R**2 + 0.00122874*T**2*R
            + 0.00085282*T*R**2 - 0.00000199*T**2*R**2)
    if R < 13 and 80 <= T <= 112:
        adj = ((13-R)/4) * ((17-abs(T-95.0))/17)**0.5
        HI_f -= adj
    elif R > 85 and 80 <= T <= 87:
        adj = ((R-85)/10) * ((87-T)/5)
        HI_f += adj
    return (HI_f - 32.0) * 5 / 9

# ── RISK LEVEL ──
def calculate_risk(temp, hum):
    hi = calculate_heat_index(temp, hum)
    if hi >= 54 or temp >= 41:
        return "Severe Risk", 3, 0.95, {"low": 0.02, "moderate": 0.03, "severe": 0.95}, "Dangerously hot conditions"
    elif hi >= 41 or temp >= 35:
        return "Moderate Risk", 2, 0.80, {"low": 0.10, "moderate": 0.80, "severe": 0.10}, "Heat stress likely"
    else:
        return "Low Risk", 1, 0.90, {"low": 0.90, "moderate": 0.08, "severe": 0.02}, "Conditions are safe"

# ── SENSOR LISTENER ──
def wifi_sensor_listener():
    global latest_sensor_data, is_recording
    print(f"📡 Sensor listener started. Polling {SENSOR_URL}...")
    while True:
        try:
            response = requests.get(SENSOR_URL, timeout=3)
            if response.status_code == 200:
                data = response.json()
                temp = float(data.get('temp_c', 0))
                hum  = float(data.get('humidity', 0))
                hi   = calculate_heat_index(temp, hum)
                current_time = time.strftime("%Y-%m-%d %H:%M:%S")
                risk_label, risk_score, confidence, probs, interpretation = calculate_risk(temp, hum)
                latest_sensor_data = {
                    "temperature":    round(temp, 2),
                    "humidity":       round(hum, 2),
                    "heat_index":     round(hi, 2),
                    "risk_level":     risk_label,
                    "risk_score":     risk_score,
                    "confidence":     round(confidence, 3),
                    "probabilities":  probs,
                    "method":         "threshold",
                    "timestamp":      current_time,
                    "is_recording":   is_recording,
                    "interpretation": interpretation,
                }
                publish_sensor_reading()
                print(f"🌡️ {temp}°C | 💧{hum}% | {risk_label}")
            else:
                print(f"⚠️ Sensor status: {response.status_code}")
        except Exception as e:
            print(f"[Sensor] Error: {e}")
        time.sleep(2)

# ── CLASSIFICATION FUNCTIONS ──
def classify_age(box_h, frame_h):
    ratio = box_h / frame_h
    return "Child" if ratio < 0.35 else "Adult"

def classify_pose(keypoints):
    try:
        left_shoulder_y  = keypoints[5][1]
        right_shoulder_y = keypoints[6][1]
        left_ankle_y     = keypoints[15][1]
        right_ankle_y    = keypoints[16][1]
        shoulder_y = (left_shoulder_y + right_shoulder_y) / 2
        ankle_y    = (left_ankle_y + right_ankle_y) / 2
        vertical_diff = abs(ankle_y - shoulder_y)
        return "lying" if vertical_diff < 50 else "upright"
    except:
        return "unknown"

def classify_injury(keypoints, is_moving, pose, person_id):
    if keypoints is None:
        return "Unknown"
    try:
        left_wrist_y    = keypoints[9][1]
        right_wrist_y   = keypoints[10][1]
        left_knee_y     = keypoints[13][1]
        right_knee_y    = keypoints[14][1]
        left_elbow_y    = keypoints[7][1]
        right_elbow_y   = keypoints[8][1]

        arm_asymmetry   = abs(left_wrist_y - right_wrist_y)
        leg_asymmetry   = abs(left_knee_y - right_knee_y)
        elbow_asymmetry = abs(left_elbow_y - right_elbow_y)

        high_asymmetry = (
            arm_asymmetry > 100 or
            leg_asymmetry > 100 or
            elbow_asymmetry > 100
        )

        if not is_moving:
            if person_id not in stationary_timers:
                stationary_timers[person_id] = time.time()
            duration = time.time() - stationary_timers[person_id]
        else:
            stationary_timers.pop(person_id, None)
            duration = 0

        if pose == "lying" and not is_moving and duration > 30:
            return "Likely Injured — Immobile > 30s"
        elif pose == "lying" and not is_moving and duration > 10:
            return "Possibly Injured — Immobile > 10s"
        elif pose == "lying" and not is_moving:
            return "Possibly Injured — Immobile"
        elif pose == "lying" and is_moving:
            return "Possibly Injured — Limited Mobility"
        elif high_asymmetry and not is_moving:
            return "Possibly Injured — Asymmetric Posture"
        elif high_asymmetry and is_moving:
            return "Possible Injury — Abnormal Limb Position"
        else:
            return "No Visible Injury Indicators"
    except:
        return "Unknown"

def classify_survivor(box, frame_shape, keypoints, is_moving,
                      person_id=0, thermal_data=None):
    frame_h, frame_w = frame_shape[:2]
    x1, y1, x2, y2  = box
    box_h = y2 - y1

    age           = classify_age(box_h, frame_h)
    pose          = classify_pose(keypoints) if keypoints is not None else "unknown"
    consciousness = "Conscious" if is_moving else "Unconscious/Unresponsive"
    injury        = classify_injury(keypoints, is_moving, pose, person_id)

    if not is_moving and pose == "lying":
        trapped = "Possibly Trapped"
    elif not is_moving and pose == "upright":
        trapped = "Possibly Trapped"
    elif is_moving:
        trapped = "Free"
    else:
        trapped = "Unknown"

    thermal_status = thermal_data if thermal_data else {
        'alive_indicator':  'No thermal camera',
        'injury_indicator': 'No thermal camera'
    }

    return {
        "age":            age,
        "consciousness":  consciousness,
        "injury":         injury,
        "trapped":        trapped,
        "pose":           pose,
        "thermal_alive":  thermal_status['alive_indicator'],
        "thermal_injury": thermal_status['injury_indicator']
    }

# ── THERMAL ──
def get_thermal_frame():
    global thermal_cap, thermal_available
    if not thermal_available:
        return None
    try:
        if thermal_cap is None or not thermal_cap.isOpened():
            thermal_cap = cv2.VideoCapture(THERMAL_URL)
        ret, frame = thermal_cap.read()
        if ret:
            return frame
    except Exception as e:
        print(f"[Thermal] Error: {e}")
    return None

def analyze_thermal(thermal_frame, detection_box):
    if thermal_frame is None:
        return {
            'alive_indicator':  'No thermal camera',
            'injury_indicator': 'No thermal camera'
        }
    try:
        x1, y1, x2, y2 = [int(v) for v in detection_box]
        roi = thermal_frame[y1:y2, x1:x2]
        if roi.size == 0:
            return {'alive_indicator': 'Unknown', 'injury_indicator': 'Unknown'}
        gray_roi  = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        avg_heat  = float(gray_roi.mean())
        max_heat  = float(gray_roi.max())
        alive     = avg_heat > 100
        high_heat = max_heat > 200
        return {
            'alive_indicator':  'Alive (heat detected)' if alive else 'No heat detected',
            'injury_indicator': 'Possible inflammation' if high_heat else 'Normal heat signature'
        }
    except:
        return {'alive_indicator': 'Unknown', 'injury_indicator': 'Unknown'}

# ── CAMERA + YOLO ──
def generate_frames():
    global latest_detections, frame_count, last_results, prev_frame, cap

    while True:
        if cap is None or not cap.isOpened():
            cap = cv2.VideoCapture(CAMERA_URL)
            if not cap.isOpened():
                blank = np.zeros((480, 640, 3), dtype=np.uint8)
                ret, buffer = cv2.imencode('.jpg', blank)
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' +
                       buffer.tobytes() + b'\r\n')
                time.sleep(1)
                continue

        ret, frame = cap.read()
        if not ret:
            cap = None
            continue

        frame_count += 1

        if frame_count % 3 == 0:
            # Motion detection
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (21, 21), 0)
            is_moving = False
            if prev_frame is not None:
                diff = cv2.absdiff(prev_frame, gray)
                _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                motion_pixels = cv2.countNonZero(thresh)
                is_moving = motion_pixels > 1000
            prev_frame = gray

            # Get thermal frame
            thermal_frame = get_thermal_frame()

            # Run detection and pose
            det_results  = detection_model(frame, classes=[14], conf=0.25)
            pose_results = pose_model(frame, conf=0.25)

            latest_detections = []

            for i, box in enumerate(det_results[0].boxes):
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                confidence = float(box.conf)

                thermal_data = analyze_thermal(
                    thermal_frame, (x1, y1, x2, y2)
                )

                keypoints = None
                if (pose_results[0].keypoints is not None and
                        i < len(pose_results[0].keypoints.xy)):
                    keypoints = pose_results[0].keypoints.xy[i].tolist()

                status = classify_survivor(
                    (x1, y1, x2, y2),
                    frame.shape,
                    keypoints,
                    is_moving,
                    person_id=i,
                    thermal_data=thermal_data
                )

                latest_detections.append({
                    'confidence':     confidence,
                    'x': x1, 'y': y1,
                    'width': x2, 'height': y2,
                    'age':            status['age'],
                    'consciousness':  status['consciousness'],
                    'injury':         status['injury'],
                    'trapped':        status['trapped'],
                    'pose':           status['pose'],
                    'thermal_alive':  status['thermal_alive'],
                    'thermal_injury': status['thermal_injury']
                })

            publish_survivor_reading()

            # Draw annotations
            annotated_frame = det_results[0].plot()

            for det in latest_detections:
                x1, y1 = int(det['x']), int(det['y'])
                label  = f"{det['age']} | {det['consciousness']}"
                label2 = f"{det['injury']} | {det['trapped']}"
                cv2.putText(annotated_frame, label,
                            (x1, y1 - 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
                cv2.putText(annotated_frame, label2,
                            (x1, y1 - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

            last_results = annotated_frame

        display_frame = last_results if last_results is not None else frame
        ret, buffer = cv2.imencode('.jpg', display_frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               buffer.tobytes() + b'\r\n')

# Local mission history survives page reloads and server restarts.
HISTORY_DB = os.environ.get('HISTORY_DB', os.path.join(BASE_DIR, 'mission_history.sqlite3'))
history_lock = threading.Lock()
previous_risk = None
previous_detection_count = 0


@contextmanager
def history_database():
    db = sqlite3.connect(HISTORY_DB)
    try:
        with db:
            yield db
    finally:
        db.close()


def init_history():
    with history_database() as db:
        db.execute("CREATE TABLE IF NOT EXISTS samples (at REAL PRIMARY KEY, temperature REAL, humidity REAL, heat_index REAL)")
        db.execute("CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, at REAL, kind TEXT, message TEXT)")


def add_alert(kind, message):
    with history_lock, history_database() as db:
        db.execute("INSERT INTO alerts (at, kind, message) VALUES (?, ?, ?)", (time.time(), kind, message))
        db.execute("DELETE FROM alerts WHERE id NOT IN (SELECT id FROM alerts ORDER BY id DESC LIMIT 10000)")


init_history()
missions = Missions(history_database, telemetry, requests,
                    os.environ.get('ROBOT_COMMAND_URL', ''), os.environ.get('ROBOT_COMMAND_KEY', ''))


# =========================================================
#  AUTH — verifying Supabase-issued JWTs on each request
#
#  There's no server-side session here on purpose: the employee's browser
#  holds the Supabase session (via supabase-js) and sends the access token
#  with every request — as an Authorization header for normal API calls, or
#  as an ?access_token= query param for things loaded as <img>/<video> src
#  (which can't set custom headers). This route just checks that token is
#  still valid for each request; Supabase itself is the source of truth.
# =========================================================

# Small cache so we're not hitting Supabase's Auth API on every single
# 1-second poll from every employee's dashboard.
_token_cache = {}
TOKEN_CACHE_TTL_SECONDS = 30


def _verify_token(token):
    now = time.time()
    cached = _token_cache.get(token)
    if cached and cached[1] > now:
        return cached[0]

    try:
        result = supabase_auth_client.auth.get_user(token)
        user = result.user if result else None
    except Exception:
        user = None

    if user is not None:
        _token_cache[token] = (user, now + TOKEN_CACHE_TTL_SECONDS)
    return user


def _extract_token():
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header.split(' ', 1)[1]
    return request.args.get('access_token')


def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        token = _extract_token()
        if not token:
            return jsonify({'error': 'Missing access token.'}), 401
        user = _verify_token(token)
        if user is None:
            return jsonify({'error': 'Invalid or expired session.'}), 401
        g.user = user
        return f(*args, **kwargs)
    return wrapper


# =========================================================
#  PAGES
#  These render unconditionally — the pages themselves check for a valid
#  Supabase session client-side (via supabase-js) and redirect to /login if
#  there isn't one. The API routes below are what's actually protected.
# =========================================================

@app.route('/login')
@app.route('/signup')
def login_page():
    return render_template(
        'login.html',
        signup=request.path == '/signup',
        supabase_url=SUPABASE_URL,
        supabase_anon_key=SUPABASE_ANON_KEY,
    )


@app.route('/')
def dashboard():
    return render_template(
        'dashboard.html',
        supabase_url=SUPABASE_URL,
        supabase_anon_key=SUPABASE_ANON_KEY,
    )


# =========================================================
#  RECORDINGS → SUPABASE STORAGE
# =========================================================

@app.route('/api/upload-to-storage', methods=['POST'])
@require_auth
def upload_to_storage():
    if 'video' not in request.files:
        return jsonify({'error': 'No video file was received.'}), 400

    video_file = request.files['video']
    filename = request.form.get('filename') or f'bimbot_{uuid4().hex}.webm'
    if '/' in filename or '\\' in filename or not filename.endswith(('.webm', '.mp4')):
        return jsonify({'error': 'Invalid recording filename.'}), 400
    # One folder per employee inside the bucket, named by their Supabase user id.
    storage_path = f"{g.user.id}/{filename}"

    try:
        file_bytes = video_file.read()
        supabase_admin_client.storage.from_(SUPABASE_STORAGE_BUCKET).upload(
            storage_path,
            file_bytes,
            {"content-type": video_file.mimetype or "video/webm", "upsert": "true"},
        )
        # Bucket is private, so hand back a time-limited link rather than a
        # public URL. 7 days is plenty to review/download a recording.
        signed = supabase_admin_client.storage.from_(SUPABASE_STORAGE_BUCKET).create_signed_url(
            storage_path, 60 * 60 * 24 * 7
        )
        link = signed.get('signedURL') or signed.get('signedUrl') or signed.get('signed_url')

        return jsonify({'success': True, 'path': storage_path, 'link': link})
    except Exception as e:
        return jsonify({'error': f'Upload failed: {e}'}), 500


@app.route('/api/recordings')
@require_auth
def recordings():
    try:
        offset = max(0, request.args.get('offset', 0, type=int))
        files = supabase_admin_client.storage.from_(SUPABASE_STORAGE_BUCKET).list(
            str(g.user.id), {'limit': 50, 'offset': offset, 'sortBy': {'column': 'created_at', 'order': 'desc'}}
        )
        return jsonify({'recordings': [{'name': f['name'], 'created_at': f.get('created_at'),
                         'size': (f.get('metadata') or {}).get('size', 0)} for f in files if f.get('id')],
                        'has_more': len(files) == 50})
    except Exception:
        return jsonify({'error': 'Could not load recordings. Please retry.'}), 502


@app.route('/api/recordings/link')
@require_auth
def recording_link():
    name = request.args.get('name', '')
    if not name or '/' in name or '\\' in name:
        return jsonify({'error': 'Invalid filename.'}), 400
    try:
        signed = supabase_admin_client.storage.from_(SUPABASE_STORAGE_BUCKET).create_signed_url(f'{g.user.id}/{name}', 3600)
        return jsonify({'link': signed.get('signedURL') or signed.get('signedUrl') or signed.get('signed_url')})
    except Exception:
        return jsonify({'error': 'Could not open this recording. Please retry.'}), 502


@app.route('/api/history')
@require_auth
def history():
    with history_database() as db:
        db.row_factory = sqlite3.Row
        alerts = [dict(row) for row in db.execute('SELECT * FROM alerts ORDER BY at DESC LIMIT 100')]
        samples = [dict(row) for row in db.execute('SELECT * FROM samples WHERE at > ? ORDER BY at', (time.time() - 3600,))]
    return jsonify({'alerts': alerts, 'samples': samples})


# UI adapters record SAR results; they do not run a second processing pipeline.
def publish_sensor_reading():
    global previous_risk
    latest_sensor_data['updated_at'] = time.time()
    with history_lock, history_database() as db:
        db.execute('INSERT INTO samples VALUES (?, ?, ?, ?)',
                   (latest_sensor_data['updated_at'], latest_sensor_data['temperature'],
                    latest_sensor_data['humidity'], latest_sensor_data['heat_index']))
        db.execute('DELETE FROM samples WHERE at < ?', (time.time() - 86400,))
    risk = latest_sensor_data['risk_level']
    if risk != previous_risk and risk != 'Low Risk':
        add_alert('risk', risk + ': ' + latest_sensor_data['interpretation'])
    previous_risk = risk


def publish_survivor_reading():
    global last_detection_at, previous_detection_count
    last_detection_at = time.time()
    missions.observe(latest_detections, latest_sensor_data)
    count = len(latest_detections)
    if count > 0 and count != previous_detection_count:
        add_alert('detection', f'{count} possible survivor(s) detected. Verify in the camera feed.')
    previous_detection_count = count


@app.route('/video_feed')
@require_auth
def video_feed():
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/api/survivors')
@require_auth
def survivors():
    return jsonify(detection_snapshot())

@app.route('/api/sensor-data')
@require_auth
def sensor_data():
    return jsonify({**latest_sensor_data, 'fresh': bool(latest_sensor_data.get('updated_at') and time.time() - latest_sensor_data['updated_at'] < 10)})

@app.route('/api/thermal')
@require_auth
def thermal_status():
    return jsonify({
        'available': thermal_available,
        'message':   'Thermal camera not yet connected' if not thermal_available else 'Thermal camera active'
    })

@app.route('/toggle_recording', methods=['POST'])
@require_auth
def toggle_recording():
    global is_recording
    data = request.get_json()
    is_recording = data.get('action') == 'start'
    return jsonify({'is_recording': is_recording})

@app.route('/nightvision_feed')
@require_auth
def nightvision_feed():
    if not NIGHTVISION_CAMERA_URL:
        return jsonify({'connected': False, 'message': 'Night-vision camera is not installed yet.'}), 503

    def generate_nv_frames():
        nv_cap = cv2.VideoCapture(NIGHTVISION_CAMERA_URL)
        try:
            while True:
                ret, frame = nv_cap.read()
                if not ret:
                    break
                ret, buffer = cv2.imencode('.jpg', frame)
                yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        finally:
            nv_cap.release()

    return Response(generate_nv_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/device-status')
@require_auth
def device_status():
    return jsonify({'nightvision': bool(NIGHTVISION_CAMERA_URL)})


@app.route('/api/thermal-data')
@require_auth
def thermal_data():
    return jsonify(telemetry.get('thermal'))


@app.route('/api/sound-data')
@require_auth
def sound_data():
    return jsonify(telemetry.get('sound'))


def detection_snapshot():
    fresh = bool(detection_model is not None and last_detection_at and time.time()-last_detection_at < 10)
    return {'available': fresh, 'updated_at': last_detection_at,
            'survivors_found': len(latest_detections) if fresh else None,
            'detections': list(latest_detections) if fresh else []}


register_feature_routes(app, require_auth, missions, telemetry,
                        lambda: latest_sensor_data, detection_snapshot,
                        lambda: {'detector_loaded': detection_model is not None, 'pose_loaded': pose_model is not None,
                                 'person_class_id': 14,
                                 'condition_classifier': 'sar_heuristics',
                                 'preprocessing': False})


def mission_listener():
    while True:
        try:
            missions.reconcile()
            missions.heartbeat()
        except Exception as exc:
            print(f'[Mission] {exc}')
        time.sleep(1)


def start_workers():
    telemetry.start()
    for worker in (wifi_sensor_listener, mission_listener):
        threading.Thread(target=worker, daemon=True).start()


# =========================================================
#  MAIN
# =========================================================

if __name__ == '__main__':
    start_workers()
    port = int(os.environ.get('PORT', '5000'))
    print(f"BIM-BOT Server running on http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)
