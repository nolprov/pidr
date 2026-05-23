#include "debug-functions.h"
#include <iostream>
#include "metrics-calc.h"

/**
 * Implementation of debugging traces for the 5G Simulation.
 * These functions print to the console only if g_debugMode is set to true.
 */

void TraceIpDrop(const Ipv4Header &header, Ptr<const Packet> packet, Ipv4L3Protocol::DropReason reason, Ptr<Ipv4> ipv4, uint32_t interface) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] IP-DROP: Packet destined for " << header.GetDestination() 
              << " was dropped by the UE! (Reason Code: " << (int)reason << ")" << std::endl;
}

void TracePhyRxBegin(Ptr<const PacketBurst> pb) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] PHY-GNB: gNB antenna is capturing a radio signal (Uplink)!" << std::endl;
}

void TraceAppTx(Ptr<const Packet> packet) {
    if (!g_debugMode) return;
    std::cout << "[DEBUG-APP] UE Application sends a packet (" << packet->GetSize() 
              << " bytes) at " << Simulator::Now().GetSeconds() << "s" << std::endl;
}  

void TraceIpSend(const Ipv4Header &header, Ptr<const Packet> packet, uint32_t interface) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] IP-SEND: IP layer finished processing and is sending the packet to the lower layer (Interface: " << interface << ")" << std::endl;
}

void TraceUePhyTx(Ptr<const PacketBurst> pb) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] PHY-UE: UE antenna is transmitting a radio signal (Uplink)!" << std::endl;
}

void TraceNetDeviceTx(Ptr<const Packet> packet, Ptr<NetDevice> device, uint16_t protocol, const Address& dest) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] NET-DEVICE: IP packet arrived at the 5G network card (Destination: " << dest << ")" << std::endl;
}

void TraceQueueEnqueue(Ptr<const QueueDiscItem> item) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] TRAFFIC-CONTROL: Packet entered the UE transmission queue." << std::endl;
}

void TraceQueueDrop(Ptr<const QueueDiscItem> item, const char* reason) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X-DROP] TRAFFIC-CONTROL: Packet was DROPPED! Reason: " << reason << std::endl;
}

void TraceArpDrop(Ptr<const Packet> packet) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X-DROP] ARP: A packet was dropped by ARP! The UE is likely trying to resolve a MAC address on a 5G link (which is not allowed/impossible)." << std::endl;
}

void TraceArpTx(Ptr<const Packet> packet, Ipv4Address destination) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] ARP-TX: UE is sending an ARP request to find: " << destination << " !!" << std::endl;
}

void TraceNasTx(Ptr<const Packet> packet) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] NAS-UE: Packet entered the NAS layer (5G Tunnel is ready!)" << std::endl;
}

void TraceGnbMacRx(uint16_t rnti, Ptr<const Packet> packet) {
    if (!g_debugMode) return;
    std::cout << "[GNB-RECEPTION] gNB captured a radio packet from UE (RNTI: " 
              << rnti << ", Size: " << packet->GetSize() << " bytes)" << std::endl;
}

void CheckInterfaceStatus(Ptr<Node> node) {
    if (!g_debugMode) return;
    Ptr<Ipv4> ipv4 = node->GetObject<Ipv4>();
    bool isUp = ipv4->IsUp(1); // Interface 1 (5G NR)
    bool isForwarding = ipv4->IsForwarding(1);
    Ipv4Address addr = ipv4->GetAddress(1, 0).GetLocal();
    
    std::cout << "[STEP-X] UE-STATUS: Interface 1 is " << (isUp ? "UP" : "DOWN") 
              << " | IP: " << addr 
              << " | Forwarding: " << (isForwarding ? "YES" : "NO") 
              << " at " << Simulator::Now().GetSeconds() << "s" << std::endl;
}

void CheckNeighborCache(Ptr<Node> node) {
    if (!g_debugMode) return;
    // In this setup, Interface 0 is loopback, Interface 1 is 5G NR.
    Ptr<NetDevice> dev = node->GetDevice(1); 

    std::cout << "[STEP-X] VERIFICATION:" << std::endl;
    if (dev) {
        bool needsArp = dev->NeedsArp();
        std::cout << "  - Does the 5G network card require ARP? " << (needsArp ? "YES (ERROR)" : "NO (OK)") << std::endl;
        std::cout << "  - Device Type: " << dev->GetInstanceTypeId().GetName() << std::endl;
    } else {
        std::cout << "  - Error: Network device not found at index 1." << std::endl;
    }
}

void TraceNrUeTx(Ptr<const Packet> packet, const Address& dest) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] NR-UE-DEVICE: Packet entered the NR stack! (Dest: " << dest << ")" << std::endl;
}

void TraceSchedulingRequest(uint16_t rnti, uint16_t cellId, uint16_t bwpId) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] MAC-UE: UE is sending a Scheduling Request to gNB to request transmission grant!" << std::endl;
}

void TraceBearerActivated(uint64_t imsi, uint16_t cellId, uint16_t rnti, uint8_t lcid) {
    if (!g_debugMode) return;
    std::cout << "[STEP-X] NR-BEARER: A Data Bearer has been activated! LCID: " << (int)lcid << " for RNTI: " << rnti << std::endl;
}

void TraceUeMacTx(uint32_t nodeId, Ptr<const Packet> packet) {
    std::cout << "\033[1;33m[UE-TX]\033[0m Node " << nodeId << " sends a packet of " << packet->GetSize() << " bytes" << std::endl;
}

void OnRrcStateChange(uint32_t nodeId,
                      uint64_t imsi,
                      uint16_t cellId,
                      uint16_t rnti,
                      LteUeRrc::State oldState,
                      LteUeRrc::State newState) {
    if (newState == LteUeRrc::CONNECTED_NORMALLY) {
        rnti_to_nodeid[rnti] = nodeId; 
        table_radio_5g[nodeId].servingGnb = "gnb:" + std::to_string(cellId);

        std::cout << "\033[1;32m" << "==========================================" << "\033[0m" << std::endl;
        std::cout << "\033[1;32m" << "[CONNEXION RÉUSSIE]" << "\033[0m" << std::endl;
        std::cout << "  -> UE (NodeID): " << nodeId << std::endl;
        std::cout << "  -> RNTI attribué: " << rnti << std::endl;
        std::cout << "  -> CellId (gNB): " << cellId << std::endl;
        std::cout << "\033[1;32m" << "==========================================" << "\033[0m" << std::endl;
    }
}


void ConnectSimulationTraces(NetDeviceContainer& ueDevs, NetDeviceContainer& gnbDevs, NodeContainer& ueNodes) {
    Ptr<NrGnbNetDevice> gnbNetDev = gnbDevs.Get(0)->GetObject<NrGnbNetDevice>();

    for (uint32_t i = 0; i < ueDevs.GetN(); ++i) {
        Ptr<NrUeNetDevice> ueNetDev = ueDevs.Get(i)->GetObject<NrUeNetDevice>();
        uint32_t nodeId = ueNodes.Get(i)->GetId();

        // --- A. Always enabled for the CSV/JSON files ---
        ueNetDev->GetPhy(0)->TraceConnectWithoutContext("DlDataSinr", MakeBoundCallback(&UpdateDlSinrTable, nodeId));
        ueNetDev->GetMac(0)->TraceConnectWithoutContext("UeMacRxPdu", MakeBoundCallback(&TraceMacDlThroughput, nodeId));
        ueNetDev->GetRrc()->TraceConnectWithoutContext("StateTransition", MakeBoundCallback(&OnRrcStateChange, nodeId));

        // --- B. enabled with flags
        if (g_debugMode) {
            ueNetDev->GetMac(0)->TraceConnectWithoutContext("UeMacTxPdu", MakeBoundCallback(&TraceUeMacTx, nodeId));
            
            if (i == 0) { // On debug only the first ue to avoid spam
                Ptr<Ipv4L3Protocol> ipL3 = ueNodes.Get(0)->GetObject<Ipv4L3Protocol>();
                ipL3->TraceConnectWithoutContext("Drop", MakeCallback(&TraceIpDrop));
                ipL3->TraceConnectWithoutContext("SendOutgoing", MakeCallback(&TraceIpSend));
                
                ueNetDev->GetPhy(0)->GetSpectrumPhy()->TraceConnectWithoutContext("PhyTxStart", MakeCallback(&TraceUePhyTx));
                ueNetDev->GetNas()->TraceConnectWithoutContext("UeNasTxPdu", MakeCallback(&TraceNasTx));
                ueNetDev->GetMac(0)->TraceConnectWithoutContext("SchedulingRequest", MakeCallback(&TraceSchedulingRequest));
            }
        }
    }

    // Traces Uplink sur le gNB
    gnbNetDev->GetPhy(0)->TraceConnectWithoutContext("UlDataSinr", MakeCallback(&UpdateUlSinrTable));
    if (g_debugMode) {
        gnbNetDev->GetMac(0)->TraceConnectWithoutContext("MacRxPdu", MakeCallback(&TraceGnbMacRx));
    }
    
}