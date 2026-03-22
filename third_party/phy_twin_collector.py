import socket
import time
import os
import json
from datetime import datetime

# --- PT CONFIGURATION ---
TARGET_IP = "198.19.20.1"
TARGET_PORT = 8000
BIND_IP = "198.19.20.2"
OUTPUT_HISTORY_FILE = "physical_twin_history.json"
INTERVAL = 0.5

def save_to_json_history(new_data, filename):
    """Appends data while maintaining a valid JSON array format"""
    if not os.path.exists(filename):
        with open(filename, 'w') as f:
            f.write("[\n  " + json.dumps(new_data, indent=2) + "\n]")
        return

    with open(filename, 'rb+') as f:
        f.seek(0, os.SEEK_END)
        pos = f.tell()
        # Move back to find the closing ']'
        while pos > 0:
            pos -= 1
            f.seek(pos)
            if f.read(1) == b']':
                f.seek(pos)
                f.write(b",\n  " + json.dumps(new_data, indent=2).encode() + b"\n]")
                break

def main():
    if os.path.exists(OUTPUT_HISTORY_FILE):
        os.remove(OUTPUT_HISTORY_FILE)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((BIND_IP, 0))
    sock.settimeout(2.0)

    p_id = 1
    print(f"[*] PT Collector started. Saving to {OUTPUT_HISTORY_FILE}...")

    while True:
        try:
            # 1. Request
            req = {"id": p_id, "cmd": "GET_STATE"}
            sock.sendto(json.dumps(req).encode(), (TARGET_IP, TARGET_PORT))

            # 2. Receive
            data, _ = sock.recvfrom(65535)
            recv_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            
            # 3. Process
            payload = json.loads(data.decode())
            payload["pt_reception_time"] = recv_time
            payload["pt_packet_id"] = p_id

            # 4. Save to historical file
            save_to_json_history(payload, OUTPUT_HISTORY_FILE)
            
            print(f"[PT Log] Saved ID {p_id} at {recv_time}")
            p_id += 1

        except socket.timeout:
            print("[!] PT Responder Timeout...")
        except Exception as e:
            print(f"[!] PT Collector Error: {e}")

        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()