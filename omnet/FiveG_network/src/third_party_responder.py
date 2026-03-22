import socket
import json
import os

# --- PT CONFIGURATION ---
LISTEN_IP = "198.19.20.1"
LISTEN_PORT = 8000 
# VERIFIE BIEN CE CHEMIN :
SOURCE_JSON_FILE = "../simulations/network_state.json" 

def get_last_snapshot(filepath):
    try:
        if not os.path.exists(filepath):
            print(f"[!] Erreur: Le fichier {filepath} n'existe pas.")
            return None
        
        # Vérifier si le fichier est vide
        if os.path.getsize(filepath) == 0:
            print(f"[!] Erreur: Le fichier {filepath} est totalement vide (0 octets).")
            return None

        with open(filepath, 'r') as f:
            data = json.load(f)
            
            # Cas 1 : C'est une liste [{}, {}] -> on prend le dernier
            if isinstance(data, list):
                if len(data) > 0:
                    return data[-1]
                else:
                    print("[!] Erreur: La liste JSON est vide [].")
                    return None
            
            # Cas 2 : C'est un objet unique {} -> on le prend directement
            elif isinstance(data, dict):
                return data
            
            else:
                print(f"[!] Erreur: Format JSON inconnu ({type(data)}).")
                return None

    except json.JSONDecodeError:
        print(f"[!] Erreur: Le fichier {filepath} contient du texte qui n'est pas du JSON valide.")
        return None
    except Exception as e:
        print(f"[!] Erreur de lecture: {e}")
        return None

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # Option pour libérer le port immédiatement en cas de crash
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        sock.bind((LISTEN_IP, LISTEN_PORT))
        print(f"[*] PT Responder listening on {LISTEN_IP}:{LISTEN_PORT}...")
    except Exception as e:
        print(f"[!] Erreur de Bind: {e}")
        return

    while True:
        data, addr = sock.recvfrom(65535)
        print(f"[?] Requête reçue de {addr}") # Debug trace
        try:
            request = json.loads(data.decode())
            if request.get("cmd") == "GET_STATE":
                snapshot = get_last_snapshot(SOURCE_JSON_FILE)
                if snapshot:
                    snapshot["request_id"] = request.get("id")
                    sock.sendto(json.dumps(snapshot).encode(), addr)
                    print(f"[PT >] Snapshot envoyé pour ID: {request.get('id')}")
                else:
                    # Envoyer une erreur au collector au lieu de rien
                    sock.sendto(json.dumps({"error": "no_data"}).encode(), addr)
        except Exception as e:
            print(f"[!] Erreur boucle: {e}")

if __name__ == "__main__":
    main()