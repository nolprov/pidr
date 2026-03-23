import socket
import json
import os
import time
import subprocess
import sys
from datetime import datetime

# --- CONFIGURATION ---
GLOBAL_FREQ = 10  # 10Hz = 10 paquets par seconde
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Chemins relatifs (à ajuster selon votre structure de dossiers)
JSON_PATH = os.path.join(SCRIPT_DIR, "..", "simulations", "network_state.json")
IDS_LOG_PATH = os.path.join(SCRIPT_DIR, "..", "simulations", "sent_packet_ids.txt")

UDP_IP = "10.255.0.2"
UDP_PORT = 9999
INTERFACE = "veth-sender"

# Format : delay (latence + jitter), loss, rate (bande passante)
NETWORK_PROFILES = {
    "1": {
        "delay": "1ms", 
        "loss": "0%", 
        "rate": "1000mbit", 
        "desc": "Profil 1 : Idéal (1ms, 0ms jitter, 0% loss, 1Gbps)"
    },
    "2": {
        "delay": "10ms 2ms", 
        "loss": "0.1%", 
        "rate": "100mbit", 
        "desc": "Profil 2 : Très Bon (10ms, 2ms jitter, 0.1% loss, 100Mbps)"
    },
    "3": {
        "delay": "40ms 10ms", 
        "loss": "1%", 
        "rate": "20mbit", 
        "desc": "Profil 3 : Moyen / Normal (40ms, 10ms jitter, 1% loss, 20Mbps)"
    },
    "4": {
        "delay": "80ms 35ms", 
        "loss": "5%", 
        "rate": "5mbit", 
        "desc": "Profil 4 : Cellule Congestionnée (80ms, 35ms jitter, 5% loss, 5Mbps)"
    },
    "5": {
        "delay": "250ms 50ms", 
        "loss": "15%", 
        "rate": "1mbit", 
        "desc": "Profil 5 : Fortement Dégradé (250ms, 50ms jitter, 15% loss, 1Mbps)"
    },
    "6": {
        "delay": "20ms 5ms", 
        "loss": "0%", 
        "rate": "10mbit", 
        "desc": "Profil 6 : Lien Limité (20ms, 5ms jitter, 0% loss, 10Mbps)"
    }
}

def apply_network_conditions(config):
    """Applique les conditions réseau via Linux TC (Traffic Control)"""
    print(f"\n[TC] Application de la configuration : {config['desc']}")
    
    # Nettoyage des anciennes règles
    subprocess.run(f"sudo tc qdisc del dev {INTERFACE} root 2>/dev/null || true", shell=True)
    
    # Construction de la commande netem
    # Syntaxe : delay [LATENCY] [JITTER] loss [PERCENTAGE] rate [BANDWIDTH]
    cmd = f"sudo tc qdisc add dev {INTERFACE} root netem delay {config['delay']} loss {config['loss']} rate {config['rate']}"
    
    result = subprocess.run(cmd, shell=True)
    if result.returncode == 0:
        print(f"[TC] Succès : {config['desc']} activé sur {INTERFACE}")
    else:
        print("[TC] ERREUR : Échec de l'application des règles.")

def main():
    # Vérification des privilèges Root
    if os.getuid() != 0:
        print("\nCRITICAL: Ce script doit être lancé avec 'sudo' pour modifier les conditions réseau (tc).")
        sys.exit(1)

    # 1. Initialisation du fichier de log
    os.makedirs(os.path.dirname(IDS_LOG_PATH), exist_ok=True)
    with open(IDS_LOG_PATH, "w") as f:
        f.write("SnapshotID\tTimestampMS\tSimTimeInPacket\tStatus\n")

    # 2. Menu de sélection du profil
    print("\n" + "="*60)
    print("  EDGE SENDER - SIMULATEUR DE CONDITIONS RÉSEAU (10Hz)")
    print("="*60)
    for k, v in NETWORK_PROFILES.items():
        print(f" {k}. {v['desc']}")
    
    choice = input("\nChoisissez un profil (1-6) : ")
    
    if choice in NETWORK_PROFILES:
        apply_network_conditions(NETWORK_PROFILES[choice])
    else:
        print("Choix invalide. Sortie du script.")
        return

    # 3. Préparation du Socket UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    snapshot_id = 0

    print(f"\n[*] Envoi en cours vers {UDP_IP}:{UDP_PORT}")
    print(f"[*] Fréquence : {GLOBAL_FREQ}Hz (1 paquet toutes les {1.0/GLOBAL_FREQ}s)")
    print(f"[*] Fichier log : {IDS_LOG_PATH}")
    print("Appuyez sur Ctrl+C pour arrêter.\n")

    # 4. Boucle de transmission
    try:
        while True:
            start_time = time.time() # Pour le contrôle précis de la fréquence
            
            try:
                if os.path.exists(JSON_PATH):
                    with open(JSON_PATH, "r") as f:
                        content = f.read().strip()
                        if content:
                            # Gestion de sécurité si le JSON est mal terminé durant l'écriture concurrente
                            if not content.endswith("]"): 
                                content += "]"
                            
                            data = json.loads(content)
                            
                            if data:
                                # On récupère la dernière valeur disponible dans le JSON
                                last_snapshot = data[-1]
                                sim_time_val = last_snapshot.get("timestamp", 0)
                                
                                snapshot_id += 1
                                
                                # Création du paquet agrégé
                                packet = {
                                    "snapshot_id": snapshot_id,
                                    "sim_time": sim_time_val,
                                    "nodes": last_snapshot.get("nodes", []),
                                    "flows": last_snapshot.get("flows", [])
                                }
                                
                                # Envoi UDP (les conditions TC s'appliquent ici au niveau kernel)
                                message = json.dumps(packet).encode()
                                sock.sendto(message, (UDP_IP, UDP_PORT))
                                
                                # Logging
                                ts_ms = int(time.time() * 1000)
                                with open(IDS_LOG_PATH, "a") as log_f:
                                    log_f.write(f"{snapshot_id}\t{ts_ms}\t{sim_time_val}\tSENT\n")
                                
                                print(f" [TX] #{snapshot_id} | SimTime: {sim_time_val}s | Taille: {len(message)} octets")

            except Exception as e:
                # Erreur de lecture JSON probable si OMNeT++ écrit en même temps
                pass

            # CONTRÔLE DE LA FRÉQUENCE (10Hz)
            elapsed = time.time() - start_time
            sleep_time = (1.0 / GLOBAL_FREQ) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n[!] Arrêt par l'utilisateur.")
    finally:
        # Nettoyage optionnel des règles TC à la fermeture
        # subprocess.run(f"sudo tc qdisc del dev {INTERFACE} root 2>/dev/null", shell=True)
        print("[*] Script terminé.")

if __name__ == "__main__":
    main()