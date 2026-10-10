from flask import Flask, Response, jsonify, request, send_from_directory
from ultralytics import YOLO
import cv2
import numpy as np
import threading
import time
import math
import requests

app = Flask(__name__)

# ── MODELS ──
detection_model = YOLO('best.pt')
pose_model = YOLO('yolo11s-pose.pt')  # ← changed from yolov12s-pose.pt

# ── URLS ──
CAMERA_URL  = 'http://192.168.4.1:81/stream'
SENSOR_URL  = 'http://192.168.4.1/dht'
THERMAL_URL = 'http://192.168.4.1:82/stream'  # future

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

# ── ROUTES ──
@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/video_feed')
def video_feed():
    return Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )

@app.route('/api/survivors')
def survivors():
    return jsonify({
        'survivors_found': len(latest_detections),
        'detections':      latest_detections
    })

@app.route('/api/sensor-data')
def sensor_data():
    return jsonify(latest_sensor_data)

@app.route('/api/thermal')
def thermal_status():
    return jsonify({
        'available': thermal_available,
        'message':   'Thermal camera not yet connected' if not thermal_available else 'Thermal camera active'
    })

@app.route('/toggle_recording', methods=['POST'])
def toggle_recording():
    global is_recording
    data = request.get_json()
    is_recording = data.get('action') == 'start'
    return jsonify({'is_recording': is_recording})

# ── START ──
if __name__ == '__main__':
    sensor_thread = threading.Thread(target=wifi_sensor_listener)
    sensor_thread.daemon = True
    sensor_thread.start()
    print("🚀 BIM-BOT Server Running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)