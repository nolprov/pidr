
#include "metrics-calc.h"

double g_snapshotInterval = 0.2;
// Default resolved at startup by main() — overridden via NS3_OUTPUT_DIR env var.
std::string g_outputFile = "ns3_received_history.json";
NetDeviceContainer g_gnbDevs;
NetDeviceContainer g_ueDevs;
std::map<std::string, Ptr<Node>> thingIdToNode;
std::map<uint32_t, UeRadioTable> table_radio_5g;
std::map<uint16_t, uint32_t> rnti_to_nodeid;
std::map<std::string, FlowInfo> active_flows;
std::map<uint16_t, uint32_t> g_dlAck;
std::map<uint16_t, uint32_t> g_dlNack;
std::map<uint16_t, uint32_t> g_ulAck;
std::map<uint16_t, uint32_t> g_ulNack;
std::map<uint64_t, uint32_t> imsi_to_nodeid;
std::vector<std::pair<uint64_t, uint32_t>> g_ueImsiNodeIds;



void TraceMacDlThroughput(uint32_t nodeId, Ptr<const Packet> packet) {
    table_radio_5g[nodeId].bytesRxDl += packet->GetSize();
    std::cout << "\033[1;32m[RECEPTION-MAC]\033[0m Node " << nodeId << " received " << packet->GetSize() << " bytes" << std::endl;
}

// Capturé au niveau du gNB pour l'Uplink
void TraceMacUlThroughput(uint16_t rnti, Ptr<const Packet> packet) {
    if (rnti_to_nodeid.count(rnti)) {
        uint32_t nodeId = rnti_to_nodeid[rnti];
        table_radio_5g[nodeId].bytesRxUl += packet->GetSize();
        // Print si on trouve le noeud
        std::cout << "\033[1;34m[UL-DATA]\033[0m RNTI " << rnti << " -> Node " << nodeId 
                  << " | Reçu: " << packet->GetSize() << " octets" << std::endl;
    } else {
        // C'EST ICI QUE CA BLOQUE SOUVENT
        static std::map<uint16_t, bool> warned_rnti;
        if (!warned_rnti[rnti]) {
            std::cout << "\033[1;31m[UL-ERROR]\033[0m Paquet reçu pour RNTI " << rnti 
                      << " mais ce RNTI n'est PAS dans la map rnti_to_nodeid !" << std::endl;
            warned_rnti[rnti] = true; 
        }
    }
}

void UpdateDlSinrTable(uint32_t nodeId,
                       uint16_t cellId,
                       uint16_t rnti,
                       double sinr,
                       uint16_t bwpId,
                       uint8_t streamId) {
    (void)streamId;
    // CONVERSION LINÉAIRE -> dB
    double sinrDb = 10 * std::log10(sinr); 
    
    table_radio_5g[nodeId].dlSinr = sinrDb;

    static std::map<uint32_t, Time> lastPrintTimes;
    Time now = Simulator::Now();

    if (now - lastPrintTimes[nodeId] >= Seconds(0.5)) {
        std::cout << "\033[1;36m[PHY-DL]\033[0m Node: " << nodeId 
                  << " | RNTI: " << rnti 
                  << " | SINR: " << sinrDb << " dB" << std::endl;
        
        lastPrintTimes[nodeId] = now; 
    }
}


void UpdateUlSinrTable(uint64_t rnti, SpectrumValue& sinr, SpectrumValue& interference) {
    uint16_t rnti16 = static_cast<uint16_t>(rnti);
    if (rnti_to_nodeid.count(rnti16)) {
        uint32_t nodeId = rnti_to_nodeid[rnti16];

        double sumSinr = 0;
        uint32_t count = 0;
        for (auto it = sinr.ConstValuesBegin(); it != sinr.ConstValuesEnd(); ++it) {
            sumSinr += (*it);
            count++;
        }

        if (count > 0) {
            double avgSinrLin = sumSinr / count;
            // CONVERSION EN dB : INDISPENSABLE
            double avgSinrDb = 10 * std::log10(avgSinrLin);
            
            table_radio_5g[nodeId].ulSinr = avgSinrDb;
            std::cout << "\033[1;35m[PHY-UL]\033[0m Node " << nodeId 
                      << " | SINR: " << avgSinrDb << " dB" << std::endl;
        }
    }
}



void TracePhyStatsDl(uint32_t nodeId, uint16_t rnti, uint16_t bwpId, uint32_t nCbs, uint32_t nPassedCbs) {
    if (nCbs > 0) {
        table_radio_5g[nodeId].blerDl = 1.0 - ((double)nPassedCbs / (double)nCbs);
        if (nCbs > nPassedCbs) table_radio_5g[nodeId].packetLossDl += (nCbs - nPassedCbs);
    }
}

void TracePhyStatsUl(uint16_t rnti, uint16_t bwpId, uint32_t nCbs, uint32_t nPassedCbs) {
    if (rnti_to_nodeid.count(rnti) && nCbs > 0) {
        uint32_t nodeId = rnti_to_nodeid[rnti];
        table_radio_5g[nodeId].blerUl = 1.0 - ((double)nPassedCbs / (double)nCbs);
        if (nCbs > nPassedCbs) table_radio_5g[nodeId].packetLossUl += (nCbs - nPassedCbs);
    }
}

void ComputeThroughput(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes) {
    (void)nGnbs; (void)nUes;
    double samplingInterval = 0.1;
    double windowSize = 1.0;

    Ptr<NrBearerStatsCalculator> bearerStats = nrHelper->GetRlcStatsCalculator();
    if (!bearerStats) return;

    static std::map<uint64_t, std::vector<uint64_t>> history;

    for (auto const& kv : g_ueImsiNodeIds) {
        uint64_t imsi = kv.first;
        uint32_t nodeId = kv.second;

        uint64_t currentDl = 0;
        for (uint8_t lcid = 1; lcid <= 5; ++lcid) {
            currentDl += bearerStats->GetDlRxData(imsi, lcid);
        }

        if (history[imsi].size() >= 10) {
            double bytesInWindow = static_cast<double>(currentDl - history[imsi].front());
            double thrBytesPerSec = bytesInWindow / windowSize;

            if (table_radio_5g.count(nodeId)) {
                // Mbps for cross-comparability with the OMNeT side
                table_radio_5g[nodeId].macThroughputDl = (thrBytesPerSec * 8.0) / 1e6;
            }
            history[imsi].erase(history[imsi].begin());
        }
        history[imsi].push_back(currentDl);
    }
    Simulator::Schedule(Seconds(samplingInterval), &ComputeThroughput, nrHelper, nGnbs, nUes);
}

// --- LATENCY ---
void ComputeLatency(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes) {
    (void)nGnbs; (void)nUes;
    double interval = 1.0;
    Ptr<NrBearerStatsCalculator> bearerStats = nrHelper->GetRlcStatsCalculator();
    if (!bearerStats) {
        Simulator::Schedule(Seconds(interval), &ComputeLatency, nrHelper, nGnbs, nUes);
        return;
    }

    for (auto const& kv : g_ueImsiNodeIds) {
        uint64_t imsi = kv.first;
        uint32_t nodeId = kv.second;
        uint8_t lcid = 3;

        std::vector<double> dlStats = bearerStats->GetDlDelayStats(imsi, lcid);
        std::vector<double> ulStats = bearerStats->GetUlDelayStats(imsi, lcid);

        double dlMaxLat = (dlStats.size() >= 3) ? dlStats[2] / 1e6 : 0.0;
        double ulMaxLat = (ulStats.size() >= 3) ? ulStats[2] / 1e6 : 0.0;

        if (table_radio_5g.count(nodeId)) {
            table_radio_5g[nodeId].macDelayDl = dlMaxLat;
            table_radio_5g[nodeId].macDelayUl = ulMaxLat;
        }
    }
    Simulator::Schedule(Seconds(interval), &ComputeLatency, nrHelper, nGnbs, nUes);
}

// --- DISTANCE ---
void ComputeDistance(Ptr<NrHelper> nrHelper, NodeContainer gnbNodes, uint32_t nGnbs, uint32_t nUes) {
    (void)nGnbs; (void)nUes;
    double interval = 1.0;
    Ptr<NrBearerStatsCalculator> bearerStats = nrHelper->GetRlcStatsCalculator();
    if (!bearerStats) {
        Simulator::Schedule(Seconds(interval), &ComputeDistance, nrHelper, gnbNodes, nGnbs, nUes);
        return;
    }

    for (auto const& kv : g_ueImsiNodeIds) {
        uint64_t imsi = kv.first;
        uint32_t ueNodeId = kv.second;
        uint8_t lcid = 3;

        uint16_t servingCellId = bearerStats->GetDlCellId(imsi, lcid);
        double distance = -1.0;

        for (uint32_t j = 0; j < gnbNodes.GetN(); ++j) {
            Ptr<Node> gnbNode = gnbNodes.Get(j);
            Ptr<NrGnbNetDevice> gnbDev = nullptr;
            for (uint32_t d = 0; d < gnbNode->GetNDevices(); ++d) {
                gnbDev = gnbNode->GetDevice(d)->GetObject<NrGnbNetDevice>();
                if (gnbDev) break;
            }

            if (gnbDev && (gnbDev->GetCellId() == servingCellId)) {
                Ptr<MobilityModel> ueMob = NodeList::GetNode(ueNodeId)->GetObject<MobilityModel>();
                Ptr<MobilityModel> gnbMob = gnbNode->GetObject<MobilityModel>();
                distance = ueMob->GetDistanceFrom(gnbMob);
                break;
            }
        }
        if (table_radio_5g.count(ueNodeId)) table_radio_5g[ueNodeId].distance = distance;
    }
    Simulator::Schedule(Seconds(interval), &ComputeDistance, nrHelper, gnbNodes, nGnbs, nUes);
}

// --- PACKET LOSS ---
void ComputePacketLoss(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes) {
    (void)nGnbs; (void)nUes;
    double interval = 1.0;
    Ptr<NrBearerStatsCalculator> bearerStats = nrHelper->GetRlcStatsCalculator();
    if (!bearerStats) {
        Simulator::Schedule(Seconds(interval), &ComputePacketLoss, nrHelper, nGnbs, nUes);
        return;
    }

    static std::map<uint64_t, uint64_t> lastDlTx, lastDlRx;

    for (auto const& kv : g_ueImsiNodeIds) {
        uint64_t imsi = kv.first;
        uint32_t nodeId = kv.second;
        uint8_t lcid = 3;

        uint64_t curDlTx = bearerStats->GetDlTxPackets(imsi, lcid);
        uint64_t curDlRx = bearerStats->GetDlRxPackets(imsi, lcid);
        double dlLoss = 0.0;
        if (curDlTx > lastDlTx[imsi]) {
            uint64_t txDelta = curDlTx - lastDlTx[imsi];
            uint64_t rxDelta = curDlRx - lastDlRx[imsi];
            dlLoss = static_cast<double>(txDelta > rxDelta ? txDelta - rxDelta : 0) / static_cast<double>(txDelta) * 100.0;
        }

        lastDlTx[imsi] = curDlTx; lastDlRx[imsi] = curDlRx;

        if (table_radio_5g.count(nodeId)) {
            table_radio_5g[nodeId].packetLossDl = (dlLoss < 0) ? 0 : static_cast<uint32_t>(dlLoss);
        }
    }
    Simulator::Schedule(Seconds(interval), &ComputePacketLoss, nrHelper, nGnbs, nUes);
}


void HarqDlSink(const ns3::DlHarqInfo& info) {
    if (info.IsReceivedOk()) {
        g_dlAck[info.m_rnti]++;
    } else {
        g_dlNack[info.m_rnti]++;
    }
}

void HarqUlSink(const ns3::UlHarqInfo& info) {
    if (info.IsReceivedOk()) {
        g_ulAck[info.m_rnti]++;
    } else {
        g_ulNack[info.m_rnti]++;
    }
}

void ComputeBler(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes) {
    (void)nGnbs; (void)nUes;
    double interval = 1.0;
    static std::map<uint16_t, uint64_t> lastDlAck, lastDlNack, lastUlAck, lastUlNack;

    for (auto const& kv : rnti_to_nodeid) {
        uint16_t rnti = kv.first;
        uint32_t nodeId = kv.second;

        uint64_t dAck = g_dlAck[rnti] - lastDlAck[rnti];
        uint64_t dNack = g_dlNack[rnti] - lastDlNack[rnti];
        uint64_t dTotal = dAck + dNack;
        double blerDl = (dTotal > 0) ? (static_cast<double>(dNack) / dTotal) * 100.0 : 0.0;

        uint64_t uAck = g_ulAck[rnti] - lastUlAck[rnti];
        uint64_t uNack = g_ulNack[rnti] - lastUlNack[rnti];
        uint64_t uTotal = uAck + uNack;
        double blerUl = (uTotal > 0) ? (static_cast<double>(uNack) / uTotal) * 100.0 : 0.0;

        lastDlAck[rnti] = g_dlAck[rnti]; lastDlNack[rnti] = g_dlNack[rnti];
        lastUlAck[rnti] = g_ulAck[rnti]; lastUlNack[rnti] = g_ulNack[rnti];

        if (table_radio_5g.count(nodeId)) {
            table_radio_5g[nodeId].blerDl = (blerDl < 0) ? 0 : blerDl;
            table_radio_5g[nodeId].blerUl = (blerUl < 0) ? 0 : blerUl;
        }
    }
    Simulator::Schedule(Seconds(interval), &ComputeBler, nrHelper, nGnbs, nUes);
}