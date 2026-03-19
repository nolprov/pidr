import socket
import json
import os
import time
import subprocess
import sys
from datetime import datetime

# --- CONFIGURATION ---
GLOBAL_FREQ = 10  # This ensures 10 packets per second (0.1s interval)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(SCRIPT_DIR, "..", "simulations", "network_state.json")
IDS_LOG_PATH = os.path.join(SCRIPT_DIR, "..", "simulations", "sent_packet_ids.txt")

UDP_IP = "127.0.0.1"
UDP_PORT = 9999
INTERFACE = "lo"

NETWORK_PROFILES = {
    "1": {"delay": "1ms", "loss": "0%", "rate": "1000mbit", "desc": "Ideal Link"},
    "2": {"delay": "10ms", "loss": "2%", "rate": "100mbit", "loss": "10%", "desc": "Standard 5G"},
    "3": {"delay": "200ms", "loss": "15%", "rate": "1mbit", "desc": "Congested Link"}
}

def apply_network_conditions(config):
    subprocess.run(f"sudo tc qdisc del dev {INTERFACE} root 2>/dev/null || true", shell=True)
    cmd = f"sudo tc qdisc add dev {INTERFACE} root netem delay {config['delay']} loss {config['loss']} rate {config['rate']}"
    subprocess.run(cmd, shell=True)
    print(f"\n[TC] Applied: {config['desc']} (Delay: {config['delay']}, Loss: {config['loss']})")

def main():
    if os.getuid() != 0:
        print("CRITICAL: Run with 'sudo' for tc commands."); sys.exit(1)

    # 1. Initialize Log File with Headers
    with open(IDS_LOG_PATH, "w") as f:
        f.write("SnapshotID\tTimestampMS\tSimTimeInPacket\tStatus\n")

    print("\n" + "="*50 + "\n  EDGE SENDER: STRICT 10Hz MODE\n" + "="*50)
    for k, v in NETWORK_PROFILES.items(): print(f" {k}. {v['desc']}")
    
    choice = input("\nSelect Profile: ")
    if choice in NETWORK_PROFILES:
        apply_network_conditions(NETWORK_PROFILES[choice])
    else:
        print("Invalid choice. Exiting."); return

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    snapshot_id = 0

    print(f"[*] Logging to: {IDS_LOG_PATH}")
    print(f"[*] Frequency: {GLOBAL_FREQ}Hz (1 packet every {1.0/GLOBAL_FREQ}s)")

    while True:
        start_time = time.time() # Start clock for frequency control
        
        try:
            if os.path.exists(JSON_PATH):
                with open(JSON_PATH, "r") as f:
                    content = f.read().strip()
                    if content:
                        # Fix JSON if OMNeT++ is currently writing to it
                        if not content.endswith("]"): content += "]"
                        data = json.loads(content)
                        
                        if data:
                            # ALWAYS TAKE THE LAST VALUE FOUND
                            last_snapshot = data[-1]
                            sim_time_val = last_snapshot.get("timestamp", 0)
                            
                            snapshot_id += 1
                            
                            # CREATE THE SINGLE AGGREGATED PACKET
                            packet = {
                                "snapshot_id": snapshot_id,
                                "sim_time": sim_time_val,
                                "nodes": last_snapshot.get("nodes", []),
                                "flows": last_snapshot.get("flows", [])
                            }
                            
                            # SEND VIA UDP (Subject to TC conditions)
                            message = json.dumps(packet).encode()
                            sock.sendto(message, (UDP_IP, UDP_PORT))
                            
                            # LOG PACKET ID TO TXT (As requested)
                            ts_ms = int(time.time() * 1000)
                            with open(IDS_LOG_PATH, "a") as log_f:
                                log_f.write(f"{snapshot_id}\t{ts_ms}\t{sim_time_val}\tSENT\n")
                            
                            print(f" [TX] Packet #{snapshot_id} | Data SimTime: {sim_time_val}s | Size: {len(message)} bytes")

        except Exception as e:
            # If JSON is being updated by OMNeT++, we might get a read error
            # We just skip that specific millisecond and continue
            pass

        # CONTROL FREQUENCY: Calculate how much time to sleep to stay at 10Hz
        elapsed = time.time() - start_time
        sleep_time = (1.0 / GLOBAL_FREQ) - elapsed
        if sleep_time > 0:
            time.sleep(sleep_time)

if __name__ == "__main__":
    main()
