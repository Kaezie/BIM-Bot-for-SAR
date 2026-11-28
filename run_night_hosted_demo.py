"""Run the integrated dashboard with the tested Night-hosted camera addresses."""

import os


CAMERA_ENDPOINTS = {
    'CAMERA_URL': 'http://192.168.4.2:81/stream',
    'SENSOR_URL': 'http://192.168.4.2/dht',
    'NIGHTVISION_CAMERA_URL': 'http://192.168.4.1:81/stream',
    'THERMAL_DATA_URL': 'http://192.168.4.1/thermal',
}
PORT = 5050


def main():
    # app.py reads the endpoints on import. Existing .env credentials,
    # model paths and local storage settings still load normally.
    os.environ.update(CAMERA_ENDPOINTS)
    from app import app, start_workers

    start_workers()
    print(f'Night-hosted BIM-Bot dashboard: http://localhost:{PORT}/login', flush=True)
    app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
