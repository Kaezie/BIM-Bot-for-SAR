"""Explicit operator-started USB/serial movement bridge; never scans for devices."""
import argparse
import os
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from features.serial_movement import SerialMovementBridge, create_bridge_app


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True,help='Operator-identified Uno serial device; no automatic selection')
    parser.add_argument('--http-port',type=int,default=5054)
    parser.add_argument('--enable-return',action='store_true',help='Supervised clear-course return only; firmware must separately enable it')
    parser.add_argument('--record-dir',default=str(Path(__file__).resolve().parents[1]/'local_data/movement'))
    args=parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1]/'.env')
    key=os.environ.get('ROBOT_COMMAND_KEY','')
    if args.enable_return and not key:
        parser.error('Supervised return requires ROBOT_COMMAND_KEY in the private project configuration.')
    import serial
    # Opening a Uno USB port may reset it. This occurs only on explicit CLI run,
    # never on dashboard startup, package import, tests or device discovery.
    port=serial.Serial(args.port,9600,timeout=.05,write_timeout=.5)
    bridge=SerialMovementBridge(port,allow_return=args.enable_return,record_directory=args.record_dir)
    thread=threading.Thread(target=bridge.run,daemon=True);thread.start()
    print('Uno serial bridge started on localhost. Command recording is not GPS. No device or key value is printed.')
    print('Supervised return gate enabled.' if args.enable_return else 'Return remains disabled; telemetry only.')
    try:
        create_bridge_app(bridge,key).run(host='127.0.0.1',port=args.http_port,threaded=True,use_reloader=False)
    finally:
        bridge.close();thread.join(timeout=1)


if __name__=='__main__': main()
