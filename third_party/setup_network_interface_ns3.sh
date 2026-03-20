#!/bin/bash

# Check if the script is run as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root (use sudo)"
   exit 1
fi

# Configuration: Using Benchmark IPs (198.19.x.x)
# Subnet for ns-3
NS3_R_IP="198.19.10.1"
NS3_C_IP="198.19.10.2"
NS3_INT="vnet-ns3"

# Subnet for Simu5G
S5G_R_IP="198.19.20.1"
S5G_C_IP="198.19.20.2"
S5G_INT="vnet-simu5g"

echo "[*] Loading dummy network module..."
modprobe dummy

# 1. Create NS-3 Virtual Interface
echo "[*] Creating interface $NS3_INT ($NS3_R_IP)..."
ip link add dev $NS3_INT type dummy
ip addr add $NS3_R_IP/24 dev $NS3_INT
ip addr add $NS3_C_IP/24 dev $NS3_INT
ip link set $NS3_INT up

# 2. Create Simu5G Virtual Interface
echo "[*] Creating interface $S5G_INT ($S5G_R_IP)..."
ip link add dev $S5G_INT type dummy
ip addr add $S5G_R_IP/24 dev $S5G_INT
ip addr add $S5G_C_IP/24 dev $S5G_INT
ip link set $S5G_INT up

echo "[+] Done! Unusual network interfaces are ready."
echo "------------------------------------------------"
echo "NS-3 Config:"
echo "   Responder: $NS3_R_IP | Collector: $NS3_C_IP"
echo "Simu5G Config:"
echo "   Responder: $S5G_R_IP | Collector: $S5G_C_IP"
echo "------------------------------------------------"