


#!/bin/bash

# Check if the script is run as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

# 1. Cleanup old OMNeT++ specific components
echo "[*] Cleaning up existing OMNeT++ network..."
ip link delete vnet-omnet 2>/dev/null
# Force clear Port 9998 (UDP)
fuser -k 9998/udp 2>/dev/null

# 2. Create the dummy interface for OMNeT++
# Unusual IPs: 198.19.20.1 (Responder) and 198.19.20.2 (Collector)
echo "[*] Creating interface vnet-omnet (Subnet 198.19.20.x)..."
modprobe dummy
ip link add dev vnet-omnet type dummy
ip addr add 198.19.20.1/24 dev vnet-omnet
ip addr add 198.19.20.2/24 dev vnet-omnet
ip link set vnet-omnet up

echo "[+] OMNeT++ Digital Twin Network is UP."
ip addr show vnet-omnet | grep "inet "