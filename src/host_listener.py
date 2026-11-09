"""
Host-side Serial Listener for Presto Touch HID
Listens on the USB serial port for JSON events from Presto and prints/handles them.
"""

import sys
import glob
import json
import subprocess
import serial

def find_presto_port():
    candidates = glob.glob("/dev/cu.usbmodem*")
    if candidates:
        return candidates[0]
    return None

def handle_action(action_id):
    """Executes actions on macOS based on button ID."""
    if action_id == "mute":
        print("[Host] Toggling system mute...")
        subprocess.run(["osascript", "-e", "set volume output muted not (output muted of (get volume settings))"])
    elif action_id == "play_pause":
        print("[Host] Sending Play/Pause media key...")
        subprocess.run(["osascript", "-e", 'tell application "Music" to playpause'])
    elif action_id == "terminal":
        print("[Host] Opening Terminal...")
        subprocess.run(["open", "-a", "Terminal"])
    elif action_id == "tests":
        print("[Host] Trigger tests action (example)...")
    else:
        print(f"[Host] Action not mapped: {action_id}")

def listen(port=None):
    if not port:
        port = find_presto_port()
    if not port:
        print("Error: No Presto USB modem found in /dev/cu.usbmodem*")
        sys.exit(1)

    print(f"Connecting to Presto on {port}...")
    try:
        ser = serial.Serial(port, baudrate=115200, timeout=1)
    except Exception as e:
        print(f"Failed to open port {port}: {e}")
        sys.exit(1)

    print("Connected! Listening for events from Presto (Ctrl+C to quit)...")
    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            
            # Try parsing JSON event
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    if data.get("event") == "press":
                        print(f"-> Button Pressed: {data.get('label')} (ID: {data.get('id')})")
                        handle_action(data.get("id"))
                    elif data.get("event") == "release":
                        print(f"<- Button Released: {data.get('id')}")
                except json.JSONDecodeError:
                    print(f"[Device Log] {line}")
            else:
                print(f"[Device Log] {line}")
        except KeyboardInterrupt:
            print("\nExiting listener.")
            break
        except Exception as e:
            print(f"Read error: {e}")
            break

if __name__ == "__main__":
    port_arg = sys.argv[1] if len(sys.argv) > 1 else None
    listen(port_arg)
