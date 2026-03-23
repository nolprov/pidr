import socket
import json
import os
import time
import subprocess
import sys
from datetime import datetime

# --- CONFIGURATION ---
GLOBAL_FREQ = 10  # 10Hz
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(SCRIPT_DIR, "..", "simulations", "network_state.json")
IDS_LOG_PATH = os.path.join(SCRIPT_DIR, "..", "simulations", "sent_packet_ids.txt")

UDP_IP_DEST = "10.255.0.2"
UDP_IP_SRC = "10.255.0.1"
UDP_PORT = 9999
INTERFACE = "veth-sender"

NETWORK_PROFILES = {
    "1": {"delay": "1ms", "loss": "0%", "rate": "1000mbit", "desc": "Profil 1 : Idéal"},
    "2": {"delay": "10ms 2ms", "loss": "0.1%", "rate": "100mbit", "desc": "Profil 2 : Très Bon"},
    "3": {"delay": "40ms 10ms", "loss": "1%", "rate": "20mbit", "desc": "Profil 3 : Moyen"},
    "4": {"delay": "80ms 35ms", "loss": "5%", "rate": "5mbit", "desc": "Profil 4 : Congestionné"},
    "5": {"delay": "250ms 50ms", "loss": "15%", "rate": "1mbit", "desc": "Profil 5 : Fortement Dégradé"},
    "6": {"delay": "20ms 5ms", "loss": "0%", "rate": "10mbit", "desc": "Profil 6 : Lien Limité"}
}

def apply_network_conditions(config):
    print(f"\n[TC] Application : {config['desc']}")
    subprocess.run(f"sudo tc qdisc del dev {INTERFACE} root 2>/dev/null || true", shell=True)
    cmd = f"sudo tc qdisc add dev {INTERFACE} root netem delay {config['delay']} loss {config['loss']} rate {config['rate']}"
    result = subprocess.run(cmd, shell=True)
    if result.returncode == 0:
        print(f"[TC] Succès sur {INTERFACE}")
    else:
        print("[TC] ERREUR : Échec TC.")

def main():
    if os.getuid() != 0:
        print("\nCRITICAL: Lancez avec 'sudo' pour modifier le réseau (tc).")
        sys.exit(1)

    os.makedirs(os.path.dirname(IDS_LOG_PATH), exist_ok=True)
    with open(IDS_LOG_PATH, "w") as f:
        f.write("SnapshotID\tTimestampMS\tSimTimeInPacket\tStatus\n")

    print("\n" + "="*60)
    for k, v in NETWORK_PROFILES.items():
        print(f" {k}. {v['desc']}")
    
    choice = input("\nChoisissez un profil (1-6) : ")
    if choice in NETWORK_PROFILES:
        apply_network_conditions(NETWORK_PROFILES[choice])
    else:
        print("Choix invalide."); return

    # Configuration Socket avec Forçage d'Interface
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # On attache le socket à l'IP source et à l'interface physique virtuelle
        sock.bind((UDP_IP_SRC, 0)) 
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, INTERFACE.encode())
    except Exception as e:
        print(f"Erreur bind interface: {e}")

    snapshot_id = 0
    print(f"\n[*] TX via {INTERFACE} ({UDP_IP_SRC}) -> {UDP_IP_DEST}:{UDP_PORT}")

    try:
        while True:
            start_time = time.time()
            try:
                if os.path.exists(JSON_PATH):
                    with open(JSON_PATH, "r") as f:
                        content = f.read().strip()
                        if content:
                            if not content.endswith("]"): content += "]"
                            data = json.loads(content)
                            if data:
                                last_snapshot = data[-1]
                                sim_time_val = last_snapshot.get("timestamp", 0)
                                snapshot_id += 1
                                
                                packet = {
                                    "snapshot_id": snapshot_id,
                                    "sim_time": sim_time_val,
                                    "nodes": last_snapshot.get("nodes", []),
                                    "flows": last_snapshot.get("flows", [])
                                }
                                
                                message = json.dumps(packet).encode()
                                sock.sendto(message, (UDP_IP_DEST, UDP_PORT))
                                
                                ts_ms = int(time.time() * 1000)
                                with open(IDS_LOG_PATH, "a") as log_f:
                                    log_f.write(f"{snapshot_id}\t{ts_ms}\t{sim_time_val}\tSENT\n")
                                
                                print(f" [TX] #{snapshot_id} | SimTime: {sim_time_val}s | Latence active: {NETWORK_PROFILES[choice]['delay']}")
            except Exception:
                pass

            elapsed = time.time() - start_time
            sleep_time = (1.0 / GLOBAL_FREQ) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[!] Arrêt.")
    finally:
        print("[*] Script terminé.")

if __name__ == "__main__":
    main()