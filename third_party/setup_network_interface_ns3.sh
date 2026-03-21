#!/bin/bash

# Check if the script is run as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

# 1. Cleanup old NS-3 specific components
echo "[*] Cleaning up existing NS-3 network..."
ip link delete vnet-ns3 2>/dev/null
# Force clear Port 9999 (UDP)
fuser -k 9999/udp 2>/dev/null

# 2. Create the dummy interface for NS-3
# Unusual IPs: 198.19.10.1 (Responder) and 198.19.10.2 (Collector)
echo "[*] Creating interface vnet-ns3 (Subnet 198.19.10.x)..."
modprobe dummy
ip link add dev vnet-ns3 type dummy
ip addr add 198.19.10.1/24 dev vnet-ns3
ip addr add 198.19.10.2/24 dev vnet-ns3
ip link set vnet-ns3 up

echo "[+] NS-3 Digital Twin Network is UP."
ip addr show vnet-ns3 | grep "inet "