
#include "metrics-calc.h"

double g_snapshotInterval = 0.2;
std::string g_outputFile = "dt_state.json";
std::map<std::string, Ptr<Node>> thingIdToNode;
std::map<uint32_t, UeRadioTable> table_radio_5g;
std::map<uint16_t, uint32_t> rnti_to_nodeid;
std::map<std::string, FlowInfo> active_flows;
std::map<uint16_t, uint32_t> g_dlAck;
std::map<uint16_t, uint32_t> g_dlNack;
std::map<uint16_t, uint32_t> g_ulAck;
std::map<uint16_t, uint32_t> g_ulNack;



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

// // Fonction pour calculer le débit toutes les secondes
// void ComputeThroughput() {
//     for (auto & [nodeId, metrics] : table_radio_5g) {
//         metrics.macThroughputDl = (metrics.bytesRxDl * 8.0) / (1e6 * g_captureInterval);
//         metrics.macThroughputUl = (metrics.bytesRxUl * 8.0) / (1e6 * g_captureInterval);
        
//         // PRINT DE PREUVE SI TRAFIC
//         if (metrics.macThroughputDl > 0 || metrics.macThroughputUl > 0) {
//             std::cout << "\033[1;32m[MAC-STATS]\033[0m Node " << nodeId 
//                       << " | Thr DL: " << metrics.macThroughputDl << " Mbps"
//                       << " | Thr UL: " << metrics.macThroughputUl << " Mbps" << std::endl;
//         }

//         metrics.bytesRxDl = 0; metrics.bytesRxUl = 0;
//     }
//     Simulator::Schedule(Seconds(g_captureInterval), &ComputeThroughput);
// }

void UpdateDlSinrTable(uint32_t nodeId, uint16_t cellId, uint16_t rnti, double sinr, uint16_t bwpId) {
    table_radio_5g[nodeId].dlSinr = sinr;
    std::cout << "\033[1;36m[PHY-DL]\033[0m Node: " << nodeId 
              << " | RNTI: " << rnti 
              << " | SINR: " << sinr << " dB" << std::endl;
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



// --- THROUGHPUT ---
void ComputeThroughput(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes) {
    double interval = 1.0;
    Ptr<NrBearerStatsCalculator> bearerStats = nrHelper->GetRlcStatsCalculator();
    if (!bearerStats) {
        Simulator::Schedule(Seconds(interval), &ComputeThroughput, nrHelper, nGnbs, nUes);
        return;
    }

    static std::map<uint64_t, uint64_t> lastDlBytes, lastUlBytes;
    std::cout << "\n\033[1;32m--- 5G THROUGHPUT (Mbps) ---\033[0m" << std::endl;

    for (uint32_t i = 0; i < nUes; ++i) {
        uint64_t imsi = i + 2 + nGnbs;           // 
        uint32_t nodeId = i + 2 + nGnbs; // Tap(2) + Gnbs
        
        uint64_t currentDl = 0, currentUl = 0;
        for (uint8_t lcid = 1; lcid <= 5; ++lcid) {
            currentDl += bearerStats->GetDlRxData(imsi, lcid);
            currentUl += bearerStats->GetUlRxData(imsi, lcid);
        }
        
        double dlThr = ((currentDl - lastDlBytes[imsi]) * 8.0) / (interval * 1e6);
        double ulThr = ((currentUl - lastUlBytes[imsi]) * 8.0) / (interval * 1e6);
        lastDlBytes[imsi] = currentDl; lastUlBytes[imsi] = currentUl;

        std::cout << "Node " << nodeId << " (UE" << i << ") | DL: " << std::fixed << std::setprecision(3) << dlThr << " Mbps" << std::endl;

        if (table_radio_5g.count(nodeId)) {
            table_radio_5g[nodeId].macThroughputDl = dlThr;
            table_radio_5g[nodeId].macThroughputUl = ulThr;
        }
    }
    Simulator::Schedule(Seconds(interval), &ComputeThroughput, nrHelper, nGnbs, nUes);
}

// --- LATENCY ---
void ComputeLatency(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes) {
    double interval = 1.0; 
    Ptr<NrBearerStatsCalculator> bearerStats = nrHelper->GetRlcStatsCalculator();
    if (!bearerStats) {
        Simulator::Schedule(Seconds(interval), &ComputeLatency, nrHelper, nGnbs, nUes);
        return;
    }

    std::cout << "\n\033[1;36m--- 5G LATENCY (ms) ---\033[0m" << std::endl;

    for (uint32_t i = 0; i < nUes; ++i) {
        uint64_t imsi = i + 2 + nGnbs;
        uint32_t nodeId = i + 2 + nGnbs;
        uint8_t lcid = 3;

        std::vector<double> dlStats = bearerStats->GetDlDelayStats(imsi, lcid);
        std::vector<double> ulStats = bearerStats->GetUlDelayStats(imsi, lcid);

        double dlMaxLat = (dlStats.size() >= 3) ? dlStats[2] / 1e6 : 0.0;
        double ulMaxLat = (ulStats.size() >= 3) ? ulStats[2] / 1e6 : 0.0;

        std::cout << "Node " << nodeId << " | DL Max Lat: " << dlMaxLat << " ms" << std::endl;

        if (table_radio_5g.count(nodeId)) {
            table_radio_5g[nodeId].macDelayDl = dlMaxLat;
            table_radio_5g[nodeId].macDelayUl = ulMaxLat;
        }
    }
    Simulator::Schedule(Seconds(interval), &ComputeLatency, nrHelper, nGnbs, nUes);
}

// --- DISTANCE ---
void ComputeDistance(Ptr<NrHelper> nrHelper, NodeContainer gnbNodes, uint32_t nGnbs, uint32_t nUes) {
    double interval = 1.0; 
    Ptr<NrBearerStatsCalculator> bearerStats = nrHelper->GetRlcStatsCalculator();
    if (!bearerStats) {
        Simulator::Schedule(Seconds(interval), &ComputeDistance, nrHelper, gnbNodes, nGnbs, nUes);
        return;
    }

    std::cout << "\n\033[1;33m--- 5G GEOMETRY (Distance) ---\033[0m" << std::endl;

    for (uint32_t i = 0; i < nUes; ++i) {
        uint32_t ueNodeId = i + 2 + nGnbs;
        uint64_t imsi = i + 2 + nGnbs;
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
        std::cout << "Node " << ueNodeId << " | Dist: " << distance << " m" << std::endl;
    }
    Simulator::Schedule(Seconds(interval), &ComputeDistance, nrHelper, gnbNodes, nGnbs, nUes);
}

// --- PACKET LOSS ---
void ComputePacketLoss(Ptr<NrHelper> nrHelper, uint32_t nGnbs, uint32_t nUes) {
    double interval = 1.0; 
    Ptr<NrBearerStatsCalculator> bearerStats = nrHelper->GetRlcStatsCalculator();
    if (!bearerStats) {
        Simulator::Schedule(Seconds(interval), &ComputePacketLoss, nrHelper, nGnbs, nUes);
        return;
    }

    static std::map<uint64_t, uint64_t> lastDlTx, lastDlRx, lastUlTx, lastUlRx;
    std::cout << "\n\033[1;31m--- 5G PACKET LOSS (%) ---\033[0m" << std::endl;

    for (uint32_t i = 0; i < nUes; ++i) {
        uint64_t imsi = i + 2 + nGnbs;
        uint32_t nodeId = i + 2 + nGnbs;
        uint8_t lcid = 3;

        uint64_t curDlTx = bearerStats->GetDlTxPackets(imsi, lcid);
        uint64_t curDlRx = bearerStats->GetDlRxPackets(imsi, lcid);
        double dlLoss = (curDlTx > lastDlTx[imsi]) ? (static_cast<double>( (curDlTx-lastDlTx[imsi]) - (curDlRx-lastDlRx[imsi]) ) / (curDlTx-lastDlTx[imsi])) * 100.0 : 0.0;

        lastDlTx[imsi] = curDlTx; lastDlRx[imsi] = curDlRx;

        std::cout << "Node " << nodeId << " | Loss: " << std::fixed << std::setprecision(2) << dlLoss << "%" << std::endl;

        if (table_radio_5g.count(nodeId)) {
            table_radio_5g[nodeId].packetLossDl = (dlLoss < 0) ? 0 : dlLoss;
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
    double interval = 1.0; 
    // Historiques pour calcul des deltas (Ta logique)
    static std::map<uint16_t, uint64_t> lastDlAck, lastDlNack, lastUlAck, lastUlNack;
    
    std::cout << "\n\033[1;35m--- 5G BLER (%) [DL & UL] ---\033[0m" << std::endl;

    for (uint32_t i = 0; i < nUes; ++i) {
        uint16_t rnti = i + 1; 
        uint32_t nodeId = i + 2 + nGnbs; 

        // --- CALCUL DOWNLINK BLER ---
        uint64_t dAck = g_dlAck[rnti] - lastDlAck[rnti];
        uint64_t dNack = g_dlNack[rnti] - lastDlNack[rnti];
        uint64_t dTotal = dAck + dNack;
        double blerDl = (dTotal > 0) ? (static_cast<double>(dNack) / dTotal) * 100.0 : 0.0;

        // --- CALCUL UPLINK BLER ---
        uint64_t uAck = g_ulAck[rnti] - lastUlAck[rnti];
        uint64_t uNack = g_ulNack[rnti] - lastUlNack[rnti];
        uint64_t uTotal = uAck + uNack;
        double blerUl = (uTotal > 0) ? (static_cast<double>(uNack) / uTotal) * 100.0 : 0.0;

        // Sauvegardes
        lastDlAck[rnti] = g_dlAck[rnti]; lastDlNack[rnti] = g_dlNack[rnti];
        lastUlAck[rnti] = g_ulAck[rnti]; lastUlNack[rnti] = g_ulNack[rnti];

        std::cout << "Node " << nodeId << " | DL BLER: " << std::fixed << std::setprecision(2) << blerDl 
                  << "% | UL BLER: " << blerUl << "%" << std::endl;

        // Mise à jour table radio
        if (table_radio_5g.count(nodeId)) {
            table_radio_5g[nodeId].blerDl = (blerDl < 0) ? 0 : blerDl;
            table_radio_5g[nodeId].blerUl = (blerUl < 0) ? 0 : blerUl;
        }
    }
    Simulator::Schedule(Seconds(interval), &ComputeBler, nrHelper, nGnbs, nUes);
}