#ifndef DEBUG_H
#define DEBUG_H

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/internet-module.h"
#include "ns3/mobility-module.h"
#include "ns3/csma-module.h"
#include "ns3/tap-bridge-module.h"
#include "ns3/nr-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/netanim-module.h"
#include "ns3/applications-module.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <map>
#include <algorithm>
#include <fstream>
#include <iomanip>
#include "ns3/lte-ue-rrc.h"
#include "ns3/traffic-control-helper.h"
#include "ns3/traffic-control-layer.h"
#include "ns3/ipv4-interface.h"
#include "ns3/arp-cache.h"
#include "ns3/eps-bearer.h"
#include "ns3/epc-ue-nas.h"
#include "ns3/epc-tft.h"
#include "ns3/nr-point-to-point-epc-helper.h"

using namespace ns3;

extern bool g_debugMode;

void TraceIpDrop(const Ipv4Header &header, Ptr<const Packet> packet, Ipv4L3Protocol::DropReason reason, Ptr<Ipv4> ipv4, uint32_t interface);
void TracePhyRxBegin(Ptr<const PacketBurst> pb);
void TraceAppTx(Ptr<const Packet> packet);
void TraceIpSend(const Ipv4Header &header, Ptr<const Packet> packet, uint32_t interface);
void TraceUePhyTx(Ptr<const PacketBurst> pb);
void TraceNetDeviceTx(Ptr<const Packet> packet, Ptr<NetDevice> device, uint16_t protocol, const Address& dest);
void TraceQueueEnqueue(Ptr<const QueueDiscItem> item);
void TraceQueueDrop(Ptr<const QueueDiscItem> item, const char* reason);
void TraceArpDrop(Ptr<const Packet> packet);
void TraceArpTx(Ptr<const Packet> packet, Ipv4Address destination);
void TraceNasTx(Ptr<const Packet> packet);
void TraceGnbMacRx(uint16_t rnti, Ptr<const Packet> packet);
void CheckInterfaceStatus(Ptr<Node> node);
void CheckNeighborCache(Ptr<Node> node);
void TraceNrUeTx(Ptr<const Packet> packet, const Address& dest);
void TraceSchedulingRequest(uint16_t rnti, uint16_t cellId, uint16_t bwpId);
void TraceBearerActivated(uint64_t imsi, uint16_t cellId, uint16_t rnti, uint8_t lcid);
void TraceUeMacTx(uint32_t nodeId, Ptr<const Packet> packet);
void ConnectSimulationTraces(NetDeviceContainer& ueDevs, NetDeviceContainer& gnbDevs, NodeContainer& ueNodes);

#endif