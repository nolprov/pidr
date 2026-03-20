import socket
import time
import os
import json
from datetime import datetime

# --- CONFIGURATION ---
SENDER_IP = "198.19.10.1"
SENDER_PORT = 9999
CLIENT_IP = "198.19.10.2"
OUTPUT_JSON_FILE = "dt_collected_history.json"
INTERVAL_REQ_TIME = 0.5

def save_to_json_history(new_data, filename):
    """Appends a single JSON object into a valid JSON array file."""
    file_exists = os.path.isfile(filename)
    
    if not file_exists:
        # Create new file with the start of an array
        with open(filename, 'w') as f:
            f.write("[\n  " + json.dumps(new_data, indent=2))
    else:
        # Open in read/write mode to handle the closing bracket
        with open(filename, 'rb+') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            
            # If the file has content, we need to go back before the last ']'
            # to add a comma and the new object
            # This is a simple logic assuming the last char is ']' or a newline
            f.seek(max(0, size - 5), os.SEEK_SET)
            content = f.read().decode()
            
            if "]" in content:
                # Find position of ']' and overwrite from there
                f.seek(size - (len(content) - content.rfind("]")), os.SEEK_SET)
                f.write(b",\n  ")
                f.write(json.dumps(new_data, indent=2).encode())
            else:
                # If no bracket found (file just started), just append
                f.write(b",\n  ")
                f.write(json.dumps(new_data, indent=2).encode())
    
    # Always ensure the array is closed
    with open(filename, 'a') as f:
        f.write("\n]")

def main():
    # Fresh start: delete old history
    if os.path.exists(OUTPUT_JSON_FILE):
        os.remove(OUTPUT_JSON_FILE)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((CLIENT_IP, 0))
    sock.settimeout(2.0)

    packet_id_counter = 1
    print(f"[*] Collector active. Saving history to {OUTPUT_JSON_FILE}...")

    while True:
        try:
            # 1. Send Request
            request_data = {"id": packet_id_counter, "cmd": "GET_STATE"}
            sock.sendto(json.dumps(request_data).encode(), (SENDER_IP, SENDER_PORT))

            # 2. Receive JSON Data
            data, _ = sock.recvfrom(65535)
            reception_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
            
            # Parse the received snapshot
            received_json = json.loads(data.decode())

            # 3. Add extra metadata as requested
            received_json["collector_reception_time"] = reception_time
            received_json["collector_packet_id"] = packet_id_counter

            # 4. Construct the long JSON file
            save_to_json_history(received_json, OUTPUT_JSON_FILE)
            
            print(f"Logged ID {packet_id_counter} | Time: {reception_time}")
            packet_id_counter += 1

        except socket.timeout:
            print("[!] Timeout: No response.")
        except Exception as e:
            print(f"[!] Error: {e}")

        time.sleep(INTERVAL_REQ_TIME)

if __name__ == "__main__":
    main()