import os
import sqlite3
import math
from uuid import UUID, uuid4
import threading
import time
from datetime import datetime
from functools import wraps
from contextlib import contextmanager

from flask import Flask, Response, jsonify, request, render_template, g, redirect, url_for
from ultralytics import YOLO
import cv2
import numpy as np
import requests

from supabase import create_client
from features.telemetry import Telemetry
from features.missions import Missions
from features.routes import register as register_feature_routes
from features.nightvision import NightVision
from features.person_analysis import PersonAnalysis, draw_people
from features.live_camera import LiveCamera
from features.person_tracking import PersonTracker, match_boxes, valid_box, usable_keypoints, person_region_motion
from features.survivor_observations import SurvivorObservations
from features.sound_classifier import SoundClassifier
from features.system_diagnostics import save_check, collect_check, DashboardCheck, robot_network
from features.robot_connection import SpareDiscovery
from features.monitoring_profile import PROFILE as MONITORING_PROFILE
from features.nightvision_illumination import NightVisionIllumination
from features.offline_auth import OfflineSessions, same_origin_request, is_google_user, COOKIE_NAME
from features.local_recordings import LocalRecordings

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Small JPEG/blur operations should not each start a second CPU thread pool
# alongside both cameras' person/pose models.
cv2.setNumThreads(1)

# Load a .env file if python-dotenv is installed and one exists (optional —
# you can also just export these as real environment variables).
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except ImportError:
    pass

app = Flask(__name__)


@app.context_processor
def monitoring_profile_context():
    return {'monitoring_profile': dict(MONITORING_PROFILE)}

app.config['MAX_CONTENT_LENGTH'] = 513 * 1024 * 1024
_camera_http_lock = threading.Lock()
_camera_http_counts = {'main': {}, 'nightvision': {}}


@app.after_request
def count_camera_responses(response):
    source = request.path.rsplit('/', 1)[-1]
    if request.path == f'/api/camera-frame/{source}' and source in _camera_http_counts:
        key = f'{request.method}:{response.status_code}'
        with _camera_http_lock:
            values = _camera_http_counts[source]
            values[key] = values.get(key, 0) + 1
    return response


@app.errorhandler(413)
def recording_too_large(_error):
    return jsonify({'error': 'This request exceeds the 512 MB recording limit. Download the MP4 backup and record a shorter clip.'}), 413

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
camera_http = requests.Session()
camera_http.trust_env = False
nightvision_http = requests.Session()
nightvision_http.trust_env = False
sensor_http = requests.Session()
sensor_http.trust_env = False
sensor_health = {'error_code': None, 'last_attempt_at': None}
nightvision_illumination = NightVisionIllumination(NIGHTVISION_CAMERA_URL, CAMERA_URL)
# Temperature-grid JSON and the SAR thermal video stream are different inputs.
telemetry_http = requests.Session()
telemetry_http.trust_env = False
telemetry = Telemetry({kind: os.environ.get('THERMAL_DATA_URL' if kind == 'thermal' else f'{kind.upper()}_URL', '')
                       for kind in ('thermal', 'sound', 'position', 'robot', 'movement')}, telemetry_http)
last_detection_at = None

# ── GLOBAL STATE ──
thermal_cap = None
thermal_available = False
latest_detections = []
is_recording = False
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
def valid_environment_values(temp_c, rh):
    if isinstance(temp_c, bool) or isinstance(rh, bool) or temp_c is None or rh is None:
        raise ValueError('Temperature and humidity are required.')
    temp_c, rh = float(temp_c), float(rh)
    if not math.isfinite(temp_c) or not math.isfinite(rh) or not -40 <= temp_c <= 85 or not 0 <= rh <= 100:
        raise ValueError('Temperature or humidity is invalid.')
    return temp_c, rh


def calculate_heat_index(temp_c, rh):
    temp_c, rh = valid_environment_values(temp_c, rh)
    T = temp_c * 9 / 5 + 32.0
    R = rh
    # NWS screening avoids extrapolating the Rothfusz hot-weather polynomial
    # into cool conditions. This remains heat screening, not general safety.
    simple = .5 * (T + 61 + (T - 68) * 1.2 + R * .094)
    screened = (simple + T) / 2
    if screened < 80:
        return (screened - 32) * 5 / 9
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
    temp, hum = valid_environment_values(temp, hum)
    hi = calculate_heat_index(temp, hum)
    if hi >= 54 or temp >= 41:
        return "Severe Risk", 3, 0.95, {"low": 0.02, "moderate": 0.03, "severe": 0.95}, "Dangerously hot conditions"
    elif hi >= 41 or temp >= 35:
        return "Moderate Risk", 2, 0.80, {"low": 0.10, "moderate": 0.80, "severe": 0.10}, "Heat stress likely"
    else:
        return "Low Risk", 1, 0.90, {"low": 0.90, "moderate": 0.08, "severe": 0.02}, "Below heat-warning thresholds; other hazards are not assessed"

# ── SENSOR LISTENER ──
def wifi_sensor_listener():
    global latest_sensor_data, is_recording
    print(f"📡 Sensor listener started. Polling {SENSOR_URL}...")
    while True:
        response = None
        sensor_health['last_attempt_at'] = time.time()
        try:
            response = sensor_http.get(SENSOR_URL, timeout=(1, 2), allow_redirects=False)
            if response.status_code == 200:
                data = response.json()
                temp, hum = valid_environment_values(data.get('temp_c'), data.get('humidity'))
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
                sensor_health['error_code'] = None
                print(f"🌡️ {temp}°C | 💧{hum}% | {risk_label}")
            else:
                sensor_health['error_code'] = 'http_error'
                print(f"⚠️ Sensor status: {response.status_code}")
        except Exception as e:
            sensor_health['error_code'] = ('timeout' if isinstance(e, requests.Timeout) else
                                           'invalid_payload' if isinstance(e, ValueError) else 'transport_error')
            print(f"[Sensor] {sensor_health['error_code']}; retrying independently of video.")
        finally:
            if response is not None:
                response.close()
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

def classify_injury(keypoints, is_moving, pose, person_id, stationary_state=None):
    timers = stationary_timers if stationary_state is None else stationary_state
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
            if person_id not in timers:
                timers[person_id] = time.time()
            duration = time.time() - timers[person_id]
        else:
            timers.pop(person_id, None)
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
                      person_id=0, thermal_data=None, stationary_state=None):
    frame_h, frame_w = frame_shape[:2]
    x1, y1, x2, y2  = box
    box_h = y2 - y1

    age           = classify_age(box_h, frame_h)
    pose          = classify_pose(keypoints) if keypoints is not None else "unknown"
    # Missing temporal evidence is not observed immobility. The existing
    # condition rules remain unvalidated estimates when motion is available.
    consciousness = "Unknown" if is_moving is None else "Conscious" if is_moving else "Unconscious/Unresponsive"
    injury = "Unknown" if is_moving is None else classify_injury(keypoints, is_moving, pose, person_id, stationary_state)

    if is_moving is None:
        trapped = "Unknown"
    elif not is_moving and pose == "lying":
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
main_analysis = PersonAnalysis(cv2, classify_survivor, 'main')


def analyze_main_frame(frame):
    return main_analysis.analyze(frame, main_camera, detection_model, pose_model,
                                 thermal_frame=get_thermal_frame(), thermal_analyzer=analyze_thermal)


def render_main_frame(frame, detections, age):
    return draw_people(cv2, frame, detections, age)


def clear_main_result():
    global latest_detections, last_detection_at
    latest_detections, last_detection_at = [], None
    main_analysis.reset()


def accept_main_result(detections, received_at):
    global latest_detections, last_detection_at
    latest_detections, last_detection_at = list(detections), received_at
    return lambda: publish_survivor_reading(captured_at=received_at, detections=detections)


main_camera = LiveCamera(CAMERA_URL, camera_http, cv2, np,
                         analyze=analyze_main_frame, render=render_main_frame,
                         on_result=accept_main_result, on_clear=clear_main_result)
nightvision = NightVision(
    NIGHTVISION_CAMERA_URL, nightvision_http, cv2, np,
    lambda: YOLO(os.path.join(BASE_DIR, os.environ.get('YOLO_MODEL_PATH', 'best.pt'))),
    detection=os.environ.get('NIGHTVISION_DETECTION_ENABLED', 'true').lower() == 'true',
    pose_factory=lambda: YOLO(os.path.join(BASE_DIR, os.environ.get('POSE_MODEL_PATH', 'yolo11s-pose.pt'))),
    classifier=classify_survivor)


def apply_spare_address(host, camera_enabled, thermal_enabled):
    if camera_enabled:
        url = f'http://{host}:81/stream'
        nightvision.set_url(url)
        nightvision_illumination.camera_url = url
    if thermal_enabled:
        telemetry.set_url('thermal', f'http://{host}/thermal')


spare_discovery = SpareDiscovery(NIGHTVISION_CAMERA_URL, telemetry.urls.get('thermal'), apply_spare_address)


def generate_frames():
    yield from main_camera.frames()

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
from features.movement import MovementControl
movement = MovementControl(missions, telemetry, requests,
                           os.environ.get('MOVEMENT_COMMAND_URL', ''), os.environ.get('ROBOT_COMMAND_KEY', ''))
missions.external_motion_busy = lambda: movement.busy


# =========================================================
#  AUTH — Google-verified local sessions and existing Supabase access tokens
#
#  Google sign-in is verified online before this laptop receives an opaque,
#  bounded local session. Local camera/API access then works without internet.
#  Only session-token hashes are stored on disk, never Supabase refresh tokens.
# =========================================================

LOCAL_DATA_DIR = os.environ.get('LOCAL_DATA_DIR') or os.path.join(BASE_DIR, 'local_data')
offline_sessions = OfflineSessions(LOCAL_DATA_DIR)


def upload_local_recording(owner_id, filename, path):
    # The queue supplies the verified owner and one immutable, unique filename.
    # Retrying that same path is idempotent. The local source is always retained.
    with open(path, 'rb') as recording:
        supabase_admin_client.storage.from_(SUPABASE_STORAGE_BUCKET).upload(
            f'{owner_id}/{filename}', recording,
            {'content-type': 'video/mp4', 'upsert': 'true'},
        )


local_recordings = LocalRecordings(LOCAL_DATA_DIR, upload_local_recording)

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
        local_user = offline_sessions.current_user()
        if local_user is not None:
            if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not same_origin_request():
                return jsonify({'error': 'Same-origin request required.'}), 403
            g.user = local_user
            return f(*args, **kwargs)
        token = _extract_token()
        if not token:
            return jsonify({'error': 'Missing access token.'}), 401
        user = _verify_token(token)
        if user is None:
            return jsonify({'error': 'Invalid or expired session.'}), 401
        if not is_google_user(user):
            return jsonify({'error': 'A verified Google account is required.'}), 403
        g.user = user
        return f(*args, **kwargs)
    return wrapper


def verify_google_user_fresh(token):
    # Device-session issuance always verifies online, without the poll cache.
    result = supabase_auth_client.auth.get_user(token)
    return result.user if result else None


offline_sessions.register(app, verify_google_user_fresh)
local_recordings.register(app, require_auth)
nightvision_illumination.register(app, require_auth)
sound_classifier = SoundClassifier(os.path.join(BASE_DIR, 'local_data', 'models', 'yamnet'))
sound_classifier.register(app, require_auth)


# =========================================================
#  PAGES
#  Pages render locally and use the server-verified device session before any
#  cloud authentication call. API routes remain protected in both modes.
# =========================================================

@app.route('/login')
def login_page():
    return render_template(
        'login.html',
        supabase_url=SUPABASE_URL,
        supabase_anon_key=SUPABASE_ANON_KEY,
    )


@app.route('/signup')
def signup_page():
    return redirect(url_for('login_page'))


@app.route('/')
def dashboard():
    return render_template(
        'dashboard.html',
        supabase_url=SUPABASE_URL,
        supabase_anon_key=SUPABASE_ANON_KEY,
    )


@app.get('/testing')
def testing_guide():
    return render_template('testing.html', supabase_url=SUPABASE_URL, supabase_anon_key=SUPABASE_ANON_KEY)


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
    except Exception:
        return jsonify({'error': 'Cloud upload could not finish. Keep the local recording and retry when internet is available.'}), 502


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


def publish_survivor_reading(captured_at=None, detections=None):
    global last_detection_at, previous_detection_count
    if captured_at is None:
        last_detection_at = time.time()
    evidence = latest_detections if detections is None else detections
    missions.observe(evidence, latest_sensor_data)
    count = len(evidence)
    if count > 0 and count != previous_detection_count:
        add_alert('detection', f'{count} possible survivor(s) detected. Verify in the camera feed.')
    previous_detection_count = count


def authorized_camera_frames(frames):
    """Close local-session streams on expiry/revocation, including open clients."""
    if not getattr(g.user, 'local', False):
        return frames
    # Capture context before Flask returns the streaming response.
    token = request.cookies.get(COOKIE_NAME)
    owner, expires_at = g.user.id, g.user.expires_at

    def stream():
        next_check = 0
        try:
            for frame in frames:
                now = time.time()
                if now >= expires_at:
                    break
                if now >= next_check:
                    user = offline_sessions.resolve(token)
                    if user is None or user.id != owner:
                        break
                    next_check = now + 2
                yield frame
        finally:
            frames.close()
    return stream()


def require_camera_frame_auth(f):
    protected = require_auth(f)

    @wraps(f)
    def wrapper(*args, **kwargs):
        # The new fetch-based transport never verifies URL credentials.
        if 'access_token' in request.args:
            result = jsonify({'error': 'Use the session cookie or Authorization header.'}), 400
        else:
            result = protected(*args, **kwargs)
        # This includes failed auth and malformed viewer requests, which must
        # not be reused by an intermediary or the browser after a new sign-in.
        response = app.make_response(result)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Cookie, Authorization, X-Camera-Viewer'
        return response
    return wrapper


@app.route('/api/camera-frame/<source>', methods=['GET', 'DELETE'])
@require_camera_frame_auth
def camera_frame(source):
    """A bounded current-image request avoids an accumulating browser stream."""
    camera = {'main': main_camera, 'nightvision': nightvision}.get(source)
    if camera is None:
        return jsonify({'error': 'Unknown camera source.'}), 404
    viewer_id = request.headers.get('X-Camera-Viewer', '')
    try:
        if len(viewer_id) != 36 or str(UUID(viewer_id)) != viewer_id.lower():
            raise ValueError
        cursor = []
        for name in ('X-Camera-Sequence', 'X-Camera-Generation'):
            value = request.headers.get(name, '-1')
            if len(value) > 20:
                raise ValueError
            parsed = int(value)
            if parsed < -1 or parsed > 2 ** 63 - 1:
                raise ValueError
            cursor.append(parsed)
    except (ValueError, AttributeError):
        return jsonify({'error': 'Invalid camera viewer or frame cursor.'}), 400
    viewer = (str(g.user.id), viewer_id.lower())
    if request.method == 'DELETE':
        camera.close_snapshot(viewer, asynchronous=True)
        response = Response(status=204)
    else:
        _capture_on_camera_request()
        snapshot = camera.snapshot(viewer, sequence=cursor[0], generation=cursor[1])
        if getattr(g.user, 'local', False):
            # Recheck after the wait, just as open MJPEG streams check their
            # captured lease before emitting another image.
            user = offline_sessions.resolve(request.cookies.get(COOKIE_NAME))
            if user is None or str(user.id) != str(g.user.id) or time.time() >= g.user.expires_at:
                camera.close_snapshot(viewer, asynchronous=True)
                response = jsonify({'error': 'Invalid or expired session.'})
                response.status_code = 401
                return response
        state = snapshot['state']
        if state == 'frame':
            response = Response(snapshot['jpeg'], mimetype='image/jpeg')
            response.headers['X-Camera-Sequence'] = str(snapshot['sequence'])
            response.headers['X-Camera-Generation'] = str(snapshot['generation'])
            response.headers['X-Camera-Received-At'] = f"{snapshot['received_at']:.6f}"
            response.headers['X-Camera-Age-Ms'] = f"{snapshot['age_ms']:.3f}"
        elif state == 'pending':
            response = Response(status=204)
        else:
            response = jsonify({'connected': False, 'message': snapshot['message']})
            response.status_code = 429 if state == 'busy' else 503
            if state == 'busy':
                response.headers['Retry-After'] = '1'
    return response


@app.route('/video_feed')
@require_auth
def video_feed():
    frames = generate_frames()
    first = next(frames, None)
    if first is None:
        frames.close()
        return jsonify({'connected': False, 'message': main_camera.status()['message']}), 503

    def stream():
        try:
            yield first
            yield from frames
        finally:
            frames.close()

    response = Response(authorized_camera_frames(stream()),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    response.headers['Cache-Control'] = 'no-store'
    response.call_on_close(frames.close)
    return response

@app.route('/api/survivors')
@require_auth
def survivors():
    return jsonify(detection_snapshot())

@app.route('/api/sensor-data')
@require_auth
def sensor_data():
    retrying = sensor_health['error_code'] in ('timeout', 'transport_error')
    fresh = bool(latest_sensor_data.get('updated_at') and
                 0 <= time.time() - latest_sensor_data['updated_at'] < 10 and
                 (not sensor_health['error_code'] or retrying))
    response = jsonify({**latest_sensor_data, **sensor_health, 'fresh': fresh, 'retrying': retrying,
                        'message': 'Retrying DHT connection; showing the last recent reading.' if retrying and fresh else
                        'Fresh DHT readings.' if fresh else 'Waiting for the robot sensor. Check ESP32_CAM connectivity and robot power.'})
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/api/system-check')
@require_auth
def system_check():
    if not same_origin_request():
        return jsonify({'error': 'Same-origin request required.'}), 403
    try:
        report = save_check(LOCAL_DATA_DIR, {'main': main_camera, 'nightvision': nightvision},
                            latest_sensor_data.copy(), sensor_health.copy(), telemetry.get('thermal'))
    except (OSError, ValueError):
        return jsonify({'error': 'Could not save the internal diagnostic snapshot.'}), 503
    response = jsonify({'saved': True, 'report': report})
    response.headers['Cache-Control'] = 'no-store'
    return response


def _dashboard_diagnostic_snapshot():
    report = collect_check({'main': main_camera, 'nightvision': nightvision},
                            latest_sensor_data.copy(), sensor_health.copy(), telemetry.get('thermal'))
    with _camera_http_lock:
        report['camera_http'] = {source: values.copy() for source, values in _camera_http_counts.items()}
    report['spare_discovery'] = spare_discovery.status()
    return report


dashboard_check = DashboardCheck(LOCAL_DATA_DIR, _dashboard_diagnostic_snapshot,
                                 duration=max(30, min(300, int(os.environ.get('BIMBOT_CAPTURE_SECONDS', '180'))))
                                 if os.environ.get('BIMBOT_CAPTURE_ON_VIDEO') == '1' else 60)

_capture_enabled = os.environ.get('BIMBOT_CAPTURE_ON_VIDEO') == '1'
_capture_start_lock = threading.Lock()
_capture_started = False


def _capture_on_camera_request():
    """Include startup failures, without recording a home-network login check.

    Keep the existing opt-in launch flag. Only the authenticated, validated GET
    path calls this hook; recording itself never opens a camera connection.
    """
    global _capture_started
    if not _capture_enabled or _capture_started:
        return
    try:
        with _capture_start_lock:
            if _capture_started or robot_network().get('robot_subnet') is not True:
                return
            _capture_started = True
        dashboard_check.start()
    except Exception:
        pass  # Optional diagnostics must never interrupt a camera request.


@app.route('/api/system-check/recording', methods=['GET', 'POST'])
@require_auth
def system_check_recording():
    if request.method == 'POST':
        if not same_origin_request():
            return jsonify({'error': 'Same-origin request required.'}), 403
        if not dashboard_check.start():
            return jsonify({'error': 'A diagnostic recording is already running.'}), 409
    response = jsonify(dashboard_check.status())
    response.headers['Cache-Control'] = 'no-store'
    return response, 202 if request.method == 'POST' else 200

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
    if not nightvision.url:
        return jsonify({'connected': False, 'message': 'Night-vision camera is not installed yet.'}), 503
    frames = nightvision.frames()
    first = next(frames, None)
    if first is None:
        frames.close()
        return jsonify({'connected': False, 'message': nightvision.status()['message']}), 503

    def stream():
        try:
            yield first
            yield from frames
        finally:
            frames.close()

    response = Response(authorized_camera_frames(stream()), mimetype='multipart/x-mixed-replace; boundary=frame')
    response.headers['Cache-Control'] = 'no-store'
    response.call_on_close(frames.close)
    return response


@app.route('/api/nightvision')
@require_auth
def nightvision_status():
    return jsonify(nightvision.status())


@app.route('/api/device-status')
@require_auth
def device_status():
    return jsonify({'nightvision': bool(nightvision.url), 'nightvision_status': nightvision.status(),
                    'main_status': main_camera.status()})


@app.route('/api/thermal-data')
@require_auth
def thermal_data():
    response = jsonify(telemetry.get('thermal'))
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/sound-data')
@require_auth
def sound_data():
    return jsonify(telemetry.get('sound'))


def detection_snapshot():
    fresh = bool(detection_model is not None and last_detection_at and 0 <= time.time()-last_detection_at < LiveCamera.RESULT_TTL)
    return {'available': fresh, 'updated_at': last_detection_at,
            'survivors_found': len(latest_detections) if fresh else None,
            'detections': list(latest_detections) if fresh else []}


register_feature_routes(app, require_auth, missions, telemetry,
                        lambda: latest_sensor_data, detection_snapshot,
                        lambda: {'detector_loaded': detection_model is not None, 'pose_loaded': pose_model is not None,
                                 'person_class_id': 14,
                                 'condition_classifier': 'sar_heuristics',
                                 'preprocessing': False}, movement=movement)


def mission_listener():
    while True:
        try:
            missions.reconcile()
            missions.heartbeat()
        except Exception as exc:
            print(f'[Mission] {exc}')
        time.sleep(1)


def start_workers():
    spare_discovery.start()
    telemetry.start()
    local_recordings.start(interval=30)
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
