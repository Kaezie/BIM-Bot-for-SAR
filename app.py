from flask import Flask, Response, jsonify, request, send_from_directory
from ultralytics import YOLO
import cv2
import threading
import time
import math
import requests

app = Flask(__name__)

# Load your trained model
model = YOLO('best.pt')

# ESP32 Camera stream URL
CAMERA_URL = 'http://192.168.4.1:81/stream'
SENSOR_URL = 'http://192.168.4.1/dht'

cap = cv2.VideoCapture(CAMERA_URL)

latest_detections = []
is_recording = False

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

def calculate_risk(temp, hum):
    hi = calculate_heat_index(temp, hum)
    if hi >= 54 or temp >= 41:
        return "Severe Risk", 3, 0.95, {"low": 0.02, "moderate": 0.03, "severe": 0.95}, "Dangerously hot conditions"
    elif hi >= 41 or temp >= 35:
        return "Moderate Risk", 2, 0.80, {"low": 0.10, "moderate": 0.80, "severe": 0.10}, "Heat stress likely"
    else:
        return "Low Risk", 1, 0.90, {"low": 0.90, "moderate": 0.08, "severe": 0.02}, "Conditions are safe"

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
            import traceback
            traceback.print_exc()
        time.sleep(2)

frame_count = 0
last_results = None

def generate_frames():
    global latest_detections, frame_count, last_results
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_count += 1

        # Only run YOLO every 3rd frame to reduce lag
        if frame_count % 3 == 0:
            results = model(frame, classes=[0], conf=0.10)
            last_results = results
            latest_detections = []

            for result in results:
                for box in result.boxes:
                    latest_detections.append({
                        'confidence': float(box.conf),
                        'x': float(box.xyxy[0][0]),
                        'y': float(box.xyxy[0][1]),
                        'width': float(box.xyxy[0][2]),
                        'height': float(box.xyxy[0][3])
                    })

        # Draw boxes on frame (use last results if available)
        if last_results is not None:
            annotated_frame = last_results[0].plot()
        else:
            annotated_frame = frame

        # Encode frame as JPEG
        ret, buffer = cv2.imencode('.jpg', annotated_frame)
        frame_bytes = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' +
               frame_bytes + b'\r\n')

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
        'detections': latest_detections
    })

@app.route('/api/sensor-data')
def sensor_data():
    return jsonify(latest_sensor_data)

@app.route('/toggle_recording', methods=['POST'])
def toggle_recording():
    global is_recording
    data = request.get_json()
    is_recording = data.get('action') == 'start'
    return jsonify({'is_recording': is_recording})

if __name__ == '__main__':
    sensor_thread = threading.Thread(target=wifi_sensor_listener)
    sensor_thread.daemon = True
    sensor_thread.start()
    print("🚀 BIM-BOT Server Running on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=False)