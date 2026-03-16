#ifndef METRICS_H
#define METRICS_H

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
#include "json/json.h"
#include <iostream>
#include <fstream>
#include <sstream>
#include <map>
#include <algorithm>
#include <fstream>
#include <iomanip>
#include "ns3/nr-ue-rrc.h" 
#include "ns3/traffic-control-helper.h"
#include "ns3/traffic-control-layer.h"
#include "ns3/ipv4-interface.h"
#include "ns3/arp-cache.h"
#include "ns3/eps-bearer.h"
#include "ns3/nr-point-to-point-epc-helper.h"
#include "ns3/nr-eps-bearer.h"
#include "ns3/nr-epc-tft.h"
#include "ns3/core-module.h"
#include "ns3/nr-gnb-mac.h"
#include "ns3/nr-phy-mac-common.h" 

using namespace ns3;
 
struct UeRadioTable {
    double dlSinr = -999.0;
    double ulSinr = -999.0;
    double macThroughputDl = 0.0;
    double macThroughputUl = 0.0;
    double macDelayDl = 0.0;
    double macDelayUl = 0.0;
    double blerDl = 0.0;
    double blerUl = 0.0;
    uint32_t packetLossDl = 0;
    uint32_t packetLossUl = 0;
    uint32_t bytesRxDl = 0;
    uint32_t bytesRxUl = 0;
    double currentSpeed = 0.0; 
    double distance = -1.0;
    std::string servingGnb = "gnb";
}; 

struct FlowInfo {
    std::string flowId;
    std::string srcName;
    std::string dstName;
    int packetSize;
    double interval;
    Ptr<Node> srcNode;
    Ptr<Node> dstNode;
};

extern double g_snapshotInterval;
extern std::string g_outputFile;
extern std::map<std::string, Ptr<Node>> thingIdToNode;
extern std::map<uint32_t, UeRadioTable> table_radio_5g;
extern std::map<uint16_t, uint32_t> rnti_to_nodeid;
extern std::map<std::string, FlowInfo> active_flows;


extern std::map<uint16_t, uint32_t> g_dlAck;
extern std::map<uint16_t, uint32_t> g_dlNack;

extern std::map<uint16_t, uint32_t> g_ulAck;
extern std::map<uint16_t, uint32_t> g_ulNack;




void TraceMacDlThroughput(uint32_t nodeId, Ptr<const Packet> packet);
// void ComputeThroughput();
void UpdateDlSinrTable(uint32_t nodeId, uint16_t cellId, uint16_t rnti, double sinr, uint16_t bwpId);
void UpdateUlSinrTable(uint64_t rnti, SpectrumValue& sinr, SpectrumValue& interference);
void TracePhyStatsDl(uint32_t nodeId, uint16_t rnti, uint16_t bwpId, uint32_t nCbs, uint32_t nPassedCbs);
void TracePhyStatsUl(uint16_t rnti, uint16_t bwpId, uint32_t nCbs, uint32_t nPassedCbs);
void OnRrcStateChange(uint32_t nodeId, uint64_t imsi, uint16_t cellId, uint16_t rnti, NrUeRrc::State oldState, NrUeRrc::State newState);
void ComputeThroughput(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes);
void ComputeLatency(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes);
void ComputeDistance(Ptr<NrHelper> nrHelper, NodeContainer gnbNodes, uint32_t nGnbs, uint32_t nUes);
void ComputePacketLoss(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes);
void ComputeBler(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes);
void HarqDlSink(ns3::DlHarqInfo const & info);
void HarqUlSink(ns3::UlHarqInfo const & info);


#endif