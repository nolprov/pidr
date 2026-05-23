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
#include <nlohmann/json.hpp>
#include <iostream>
#include <fstream>
#include <sstream>
#include <map>
#include <algorithm>
#include <fstream>
#include <iomanip>
#include <chrono>
#include <thread>
#include <cstdlib>
#include "ns3/lte-ue-rrc.h"
#include "ns3/traffic-control-helper.h"
#include "ns3/traffic-control-layer.h"
#include "ns3/ipv4-interface.h"
#include "ns3/arp-cache.h"
#include "ns3/eps-bearer.h"
#include "ns3/epc-tft.h"
#include "ns3/nr-point-to-point-epc-helper.h"
#include "debug-functions.h"
#include "metrics-calc.h"
#include "ns3/nr-ue-net-device.h"
#include "ns3/nr-ue-mac.h"
#include "ns3/nr-ue-phy.h"
#include "ns3/nr-gnb-net-device.h"
#include "ns3/nr-gnb-mac.h"
#include "ns3/nr-gnb-phy.h"
#include "ns3/nr-bearer-stats-calculator.h"
#include <set> 
#include <cctype> 

using namespace ns3;
using json = nlohmann::json;

NS_LOG_COMPONENT_DEFINE("Ditto5GControl");

// ===========================================================================
// GLOBAL DECLARATIONS
// =========================================================================== 

bool g_debugMode = false;   // this variable to enable or disbale the debugging functions



// void ComputeBler() {
//     double interval = 1.0;
//     std::cout << "\n\033[1;35m--- 5G RADIO HEALTH (BLER %) ---\033[0m" << std::endl;

//     for (uint32_t i = 0; i < 4; ++i) {
//         uint16_t rnti = i + 1; // Vérifie tes RNTI dans les logs
//         uint32_t nodeId = i + 3;

//         // --- Downlink ---
//         uint32_t dlTotal = g_dlAck[rnti] + g_dlNack[rnti];
//         double dlBler = (dlTotal > 0) ? (static_cast<double>(g_dlNack[rnti]) / dlTotal) * 100.0 : 0.0;

//         // --- Uplink ---
//         uint32_t ulTotal = g_ulAck[rnti] + g_ulNack[rnti];
//         double ulBler = (ulTotal > 0) ? (static_cast<double>(g_ulNack[rnti]) / ulTotal) * 100.0 : 0.0;

//         if (dlTotal > 0 || ulTotal > 0) {
//             std::cout << "Node " << nodeId << " | DL BLER: " << dlBler << "% (" << dlTotal << " pks)"
//                       << " | UL BLER: " << ulBler << "% (" << ulTotal << " pks)" << std::endl;
//         } else {
//             std::cout << "Node " << nodeId << " | Status: Idle (No radio traffic detected)" << std::endl;
//         }

//         if (table_radio_5g.count(nodeId)) {
//             table_radio_5g[nodeId].blerDl = dlBler;
//             table_radio_5g[nodeId].blerUl = ulBler;
//         }

//         // Reset
//         g_dlAck[rnti] = 0; g_dlNack[rnti] = 0;
//         g_ulAck[rnti] = 0; g_ulNack[rnti] = 0;
//     }
//     Simulator::Schedule(Seconds(interval), &ComputeBler);
// }


void PrintIncomingJson(std::string source, std::string jsonStr) {
    NS_LOG_INFO("\033[1;33m[DEBUG " << source << "]\033[0m Content: " << jsonStr);
    
    if (jsonStr.empty()) {
        NS_LOG_WARN("!!! WARNING: JSON received is EMPTY !!!");
    }
}


// ===========================================
//    This function for debugging
// ===========================================

void InstallControlTraffic(NodeContainer ueNodes, Ptr<Node> remoteHost, Ipv4Address remoteHostAddr) {
    uint16_t ulPort = 11000; // control port (différents de Ditto)
    uint16_t dlPort = 12000;

    for (uint32_t i = 0; i < ueNodes.GetN(); ++i) {
        Ptr<Node> ue = ueNodes.Get(i);
        Ipv4Address ueAddr = ue->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal();

        // --- UPLINK CONTROL (UE -> Server) 
        UdpClientHelper ulClient(remoteHostAddr, ulPort + i);
        ulClient.SetAttribute("MaxPackets", UintegerValue(4294967295U));
        ulClient.SetAttribute("Interval", TimeValue(MilliSeconds(100))); 
        ulClient.SetAttribute("PacketSize", UintegerValue(1600));
        ApplicationContainer ulApp = ulClient.Install(ue);
        
        ulApp.Start(Seconds(1.0));
        ulApp.Get(0)->TraceConnectWithoutContext("Tx", MakeCallback(&TraceAppTx));


        UdpServerHelper ulServer(ulPort + i);
        ulServer.Install(remoteHost).Start(Seconds(1.0));

        // --- DOWNLINK CONTROL (Server -> UE)
        UdpClientHelper dlClient(ueAddr, dlPort + i);
        dlClient.SetAttribute("MaxPackets", UintegerValue(4294967295U));
        dlClient.SetAttribute("Interval", TimeValue(MilliSeconds(100)));
        dlClient.SetAttribute("PacketSize", UintegerValue(1600));
        ApplicationContainer dlApp = dlClient.Install(remoteHost);
        dlApp.Start(Seconds(1.0));

        UdpServerHelper dlServer(dlPort + i);
        dlServer.Install(ue).Start(Seconds(1.0));

        NS_LOG_INFO("Control traffic installed for UE " << i << " (UL Port: " << ulPort+i << ", DL Port: " << dlPort+i << ")");
    }
}


// ===========================================================================
// 1. DITTO DATA HANDLER
// ===========================================================================
class DittoDataHandler {
private:
    std::map<std::string, Ptr<Application>> m_flowApps; 

public:
    void UpdateNodeMobility(std::string id, double x, double y, double z, double speed = 0.0) {
    std::string cleanId = id;

    cleanId.erase(std::remove(cleanId.begin(), cleanId.end(), '['), cleanId.end());
    cleanId.erase(std::remove(cleanId.begin(), cleanId.end(), ']'), cleanId.end());


    if (cleanId.find("my5GNetwork:") == std::string::npos && cleanId != "server") {
        cleanId = "my5GNetwork:" + cleanId;
    }


    // --- AJOUT DU DEBUG LOG ---
    if (thingIdToNode.count(cleanId)) {
        Ptr<Node> node = thingIdToNode[cleanId];
        uint32_t nodeId = node->GetId();
        Ptr<MobilityModel> mobility = node->GetObject<MobilityModel>();
        if (mobility) {
            double safeZ = z;
            if (cleanId.find("gnb") != std::string::npos) {
                safeZ = std::max(z, 10.0);
            } else {
                safeZ = std::max(z, 1.5);
            }
            mobility->SetPosition(Vector3D(x, y, safeZ));
            table_radio_5g[nodeId].currentSpeed = speed; 
            std::cout << "\033[1;32m[MOBILITY-OK]\033[0m Node " << cleanId << " moved to (" << x << "," << y << ")" << std::endl;
        }
    } else {
        std::cout << "\033[1;31m[MOBILITY-ERROR]\033[0m ID received from PT '" << id << "' (cleaned as '" << cleanId << "') is NOT in thingIdToNode map!" << std::endl;
    }
}

    void SetGlobalTrafficParams(uint32_t pktSize, double intervalMs) {
        for (auto& kv : m_flowApps) {
            Ptr<Application> app = kv.second;
            if (!app) continue;
            app->SetAttribute("PacketSize", UintegerValue(pktSize));
            app->SetAttribute("Interval", TimeValue(MilliSeconds(intervalMs)));
            if (active_flows.count(kv.first)) {
                active_flows[kv.first].packetSize = static_cast<int>(pktSize);
                active_flows[kv.first].interval   = intervalMs / 1000.0;
            }
        }
        std::cout << "\033[1;35m[TRAFFIC-UPDATE]\033[0m "
                  << m_flowApps.size() << " flows → pkt=" << pktSize
                  << "B  interval=" << intervalMs << "ms" << std::endl;
    }

    Ipv4Address GetNodeIp(Ptr<Node> node) {
        Ptr<Ipv4> ipv4 = node->GetObject<Ipv4>();
        if (ipv4->GetNInterfaces() > 1) {
            // L'interface 0 est loopback, l'interface 1 est la 5G ou le P2P
            return ipv4->GetAddress(1, 0).GetLocal();
        }
        return Ipv4Address::GetAny();
    }

    void UpdateFlowParameters(std::string flowIdFromDitto, std::string srcStr, std::string dstStr, int pSize, double flowInt) {
    // 1. Nettoyage et mapping des IDs Ditto vers ns-3
    auto clean = [](std::string n) {
        n.erase(std::remove(n.begin(), n.end(), '['), n.end());
        n.erase(std::remove(n.begin(), n.end(), ']'), n.end());
        if (n == "server") return std::string("my5GNetwork:remoteHost");
        return std::string("my5GNetwork:" + n);
    };

    std::string sId = clean(srcStr);
    // std::cout << "sId is  " << sId << std::endl;
    std::string dId = clean(dstStr);
    // std::cout << "dId is  " << dId << std::endl;
    
    // 2. Création d'un ID interne unique pour éviter de recréer le même flux
    std::string internalFlowId = sId + "->" + dId;

    // Vérification de l'existence des noeuds
    if (thingIdToNode.count(sId) == 0 || thingIdToNode.count(dId) == 0) {
        std::cout << "\033[1;31m[FLOW-ERROR]\033[0m Node not found: " << sId << " or " << dId << std::endl;
        return;
    }

    Ptr<Node> srcNode = thingIdToNode[sId];
    Ptr<Node> dstNode = thingIdToNode[dId];

    // 3. MISE À JOUR si le flux existe déjà
    if (m_flowApps.count(internalFlowId)) {
        Ptr<Application> app = m_flowApps[internalFlowId];
        app->SetAttribute("Interval", TimeValue(Seconds(flowInt)));
        app->SetAttribute("PacketSize", UintegerValue(pSize));
        
        // Mise à jour des infos pour le SnapshotManager
        active_flows[internalFlowId].packetSize = pSize;
        active_flows[internalFlowId].interval = flowInt;
        
        std::cout << "\033[1;34m[FLOW-UPDATE]\033[0m " << internalFlowId << " | Int: " << flowInt << "s" << std::endl;
    }
    // 4. INSTALLATION si c'est un nouveau flux
    else {
        std::cout << "\033[1;32m[FLOW-INSTALL]\033[0m " << sId << " to " << dId << std::endl;

        // Attribution d'un port unique (commence à 9000)
        uint16_t port = 9000 + m_flowApps.size();

        // Installation du Serveur sur la destination
        UdpServerHelper serverHelper(port);
        ApplicationContainer serverApp = serverHelper.Install(dstNode);
        serverApp.Start(Seconds(0.01));

        // Récupération de l'IP de destination (Interface 1 = 5G ou P2P)
        Ipv4Address destIp = dstNode->GetObject<Ipv4>()->GetAddress(1, 0).GetLocal();
        std::cout << "\n adresse de la destination est : " << destIp << std::endl;

        // Installation du Client sur la source
        UdpClientHelper clientHelper(destIp, port);
        clientHelper.SetAttribute("MaxPackets", UintegerValue(4294967295U));
        clientHelper.SetAttribute("Interval", TimeValue(Seconds(flowInt)));
        clientHelper.SetAttribute("PacketSize", UintegerValue(pSize));

        ApplicationContainer clientApps = clientHelper.Install(srcNode);
        Ptr<Application> clientPtr = clientApps.Get(0);
        
        // Démarrage immédiat (Now + 10ms)
        clientApps.Start(Seconds(Simulator::Now().GetSeconds() + 1.0));

        // Sauvegarde dans les maps globales
        m_flowApps[internalFlowId] = clientPtr;
        
        FlowInfo info;
        info.flowId = internalFlowId;
        info.srcName = srcStr;
        info.dstName = dstStr;
        info.packetSize = pSize;
        info.interval = flowInt;
        info.srcNode = srcNode;
        info.dstNode = dstNode;
        active_flows[internalFlowId] = info;
    }
}

};


DittoDataHandler g_handler; 

// ===========================================================================
// 2. DITTO LOGGER
// ===========================================================================
class DittoLogger {
public:
    void Open(std::string filename) {
        m_file.open(filename, std::ios::out | std::ios::trunc);
        m_file << "[\n";
        m_first = true;
    }
    void LogSnapshot(const json& root) {
        if (!m_file.is_open()) return;
        if (!m_first) m_file << ",\n";
        m_file << root.dump(2);
        m_first = false;
        m_file.flush();
    }
    void Close() {
        if (m_file.is_open()) { m_file << "\n]"; m_file.close(); }
    }
private:
    std::ofstream m_file;
    bool m_first;
};


// ===========================================================================
// 3. DITTO CONTROLLER APPLICATION (UDP Signal + RAM Buffer)
// ===========================================================================
class DittoControllerApp : public Application {
public:
    DittoControllerApp() : m_port(5000) {}
    
    // Setup mis à jour pour accepter le nom du fichier log
    void Setup(uint16_t port, std::string logFile) { 
        m_port = port; 
        m_logFileName = logFile;
    }

private:
    uint16_t m_port;
    Ptr<Socket> m_socket;
    std::string m_logFileName;
    std::string m_bufferPath = "/dev/shm/ditto_buffer.json";
    std::string m_lastBufferContent;
    std::string m_lastActionContent;
    
    DittoLogger m_logger;       

    virtual void StartApplication() override {
        m_logger.Open(m_logFileName);

        m_socket = Socket::CreateSocket(GetNode(), UdpSocketFactory::GetTypeId());
        m_socket->Bind(InetSocketAddress(Ipv4Address::GetAny(), m_port));
        m_socket->SetRecvCallback(MakeCallback(&DittoControllerApp::HandleRead, this));

        Simulator::Schedule(Seconds(0.2), &DittoControllerApp::PollSharedBuffer, this);
        
       NS_LOG_INFO("[NS3] Ready. Waiting for UDP signals on port " << m_port << "...");
    }

    virtual void StopApplication() override {
        m_logger.Close();
        if (m_socket) m_socket->Close();
    }

    void HandleRead(Ptr<Socket> socket) {
        Ptr<Packet> packet;
        Address from;
        while ((packet = socket->RecvFrom(from))) {
            // Un signal UDP est reçu -> On lit le buffer en RAM
            std::ifstream ifs(m_bufferPath);
            if (ifs.is_open()) {
                std::stringstream ss;
                ss << ifs.rdbuf();
                std::string jsonContent = ss.str();
                ifs.close();

                // PrintIncomingJson("RAM_BUFFER", jsonContent);

                if (!jsonContent.empty()) {
                    NS_LOG_INFO("Signal received. Processing RAM buffer...");
                    ProcessJson(jsonContent); 
                    m_lastBufferContent = jsonContent;
                }
            }
        }
    }

    void PollSharedBuffer() {
        // 1. Process Ditto topology updates
        std::ifstream ifs(m_bufferPath);
        if (ifs.is_open()) {
            std::stringstream ss;
            ss << ifs.rdbuf();
            std::string jsonContent = ss.str();
            ifs.close();

            if (!jsonContent.empty() && jsonContent != m_lastBufferContent) {
                ProcessJson(jsonContent);
                m_lastBufferContent = jsonContent;
            }
        }

        // 2. Apply DRL agent action if available (/dev/shm/agent_action.json)
        ApplyAgentAction();

        Simulator::Schedule(Seconds(0.5), &DittoControllerApp::PollSharedBuffer, this);
    }

    void ApplyAgentAction() {
        const std::string actionPath = "/dev/shm/agent_action.json";
        std::ifstream afs(actionPath);
        if (!afs.is_open()) return;

        std::stringstream ss;
        ss << afs.rdbuf();
        afs.close();
        std::string content = ss.str();
        if (content == m_lastActionContent) return;
        m_lastActionContent = content;

        json act;
        try { act = json::parse(content); } catch (...) { return; }
        if (!act.contains("action") || !act["action"].is_object()) return;
        const auto& a = act["action"];

        // --- gNB attributes ---
        if (a.contains("ns3_gnb_tx_dbm") || a.contains("ns3_gnb_nf_db")) {
            for (uint32_t i = 0; i < g_gnbDevs.GetN(); ++i) {
                Ptr<NrGnbNetDevice> dev = DynamicCast<NrGnbNetDevice>(g_gnbDevs.Get(i));
                if (!dev) continue;
                for (uint32_t bwp = 0; bwp < dev->GetCcMapSize(); ++bwp) {
                    Ptr<NrGnbPhy> phy = dev->GetPhy(bwp);
                    if (!phy) continue;
                    if (a.contains("ns3_gnb_tx_dbm"))
                        phy->SetAttribute("TxPower", DoubleValue(a["ns3_gnb_tx_dbm"].get<double>()));
                    if (a.contains("ns3_gnb_nf_db"))
                        phy->SetAttribute("NoiseFigure", DoubleValue(a["ns3_gnb_nf_db"].get<double>()));
                }
            }
        }
        // --- UE attributes ---
        if (a.contains("ns3_ue_tx_dbm") || a.contains("ns3_ue_nf_db")) {
            for (uint32_t i = 0; i < g_ueDevs.GetN(); ++i) {
                Ptr<NrUeNetDevice> dev = DynamicCast<NrUeNetDevice>(g_ueDevs.Get(i));
                if (!dev) continue;
                for (uint32_t bwp = 0; bwp < dev->GetCcMapSize(); ++bwp) {
                    Ptr<NrUePhy> phy = dev->GetPhy(bwp);
                    if (!phy) continue;
                    if (a.contains("ns3_ue_tx_dbm"))
                        phy->SetAttribute("TxPower", DoubleValue(a["ns3_ue_tx_dbm"].get<double>()));
                    if (a.contains("ns3_ue_nf_db"))
                        phy->SetAttribute("NoiseFigure", DoubleValue(a["ns3_ue_nf_db"].get<double>()));
                }
            }
        }
        // --- Snapshot interval ---
        if (a.contains("ns3_snapshot_s")) {
            double newInterval = a["ns3_snapshot_s"].get<double>();
            if (newInterval > 0.0) g_snapshotInterval = newInterval;
        }
        // --- Traffic parameters (packet size + inter-packet interval) ---
        if (a.contains("ns3_pkt_size_bytes") || a.contains("ns3_pkt_interval_ms")) {
            uint32_t pktSize   = a.contains("ns3_pkt_size_bytes")
                                     ? static_cast<uint32_t>(a["ns3_pkt_size_bytes"].get<double>())
                                     : 1400u;
            double intervalMs  = a.contains("ns3_pkt_interval_ms")
                                     ? a["ns3_pkt_interval_ms"].get<double>()
                                     : 10.0;
            if (pktSize   < 1)    pktSize   = 1;
            if (pktSize   > 65507) pktSize   = 65507;
            if (intervalMs < 0.1) intervalMs = 0.1;
            g_handler.SetGlobalTrafficParams(pktSize, intervalMs);
        }

        std::cout << "\033[1;35m[AGENT-ACTION]\033[0m Applied at t="
                  << Simulator::Now().GetSeconds() << "s: " << a.dump() << std::endl;
    }

   void ProcessJson(std::string jsonStr) {
    json root;
    try {
        root = json::parse(jsonStr);
    } catch (const std::exception&) {
        return;
    }

    if (!root.is_array()) {
        return;
    }

    m_logger.LogSnapshot(root);

    for (const auto& item : root) {
        if (!item.contains("thingId") || !item["thingId"].is_string()) {
            continue;
        }
        std::string tid = item["thingId"].get<std::string>();

        if (!item.contains("attributes") || !item["attributes"].is_object()) {
            continue;
        }
        const auto& attr = item["attributes"];

        // 1. MOBILITY
        if (attr.contains("x")) {
            g_handler.UpdateNodeMobility(tid,
                                         attr.value("x", 0.0),
                                         attr.value("y", 0.0),
                                         attr.value("z", 0.0),
                                         attr.value("speed", 0.0));
        }

        // 2. TRAFIC
        if (attr.contains("src") && attr.contains("dst")) {
            double flowInt = attr.value("interval", 0.001);
            int pSize = attr.value("packet_size", 1000);

            std::cout << std::fixed << std::setprecision(6);
            std::cout << "[DEBUG] Interval recu: " << flowInt << " s" << std::endl;

            g_handler.UpdateFlowParameters(tid,
                                           attr.value("src", std::string()),
                                           attr.value("dst", std::string()),
                                           pSize,
                                           flowInt);
        }
    }
}
};





class SnapshotManager {
private:
    std::fstream m_file;
    bool m_isFirst = true;

public:
    void Open(std::string filename) {
        // On ouvre en lecture/écriture
        m_file.open(filename, std::ios::out | std::ios::trunc);
        m_file << "[\n";
    
        m_file.flush();
    }

    void DoSnapshot() {
        if (!m_file.is_open()) return;

        double now = Simulator::Now().GetSeconds();

        // Si c'est pas le premier, on recule pour effacer le "]" et mettre une virgule
        if (!m_isFirst) {
            m_file.seekp(-2, std::ios::end); 
            m_file << ",\n";
        }
        m_isFirst = false;

        m_file << "  {\n";
        m_file << "    \"timestamp\": " << std::fixed << std::setprecision(2) << now << ",\n";

        // --- SECTION NODES (UEs et gNBs) ---
        m_file << "    \"nodes\": [\n";
        bool firstNode = true;
        for (auto const& [dittoId, nodePtr] : thingIdToNode) {
            uint32_t nid = nodePtr->GetId();
            // On filtre pour ne prendre que les équipements physiques
            if (dittoId.find("ue") != std::string::npos || dittoId.find("gnb") != std::string::npos) {
                if (!firstNode) m_file << ",\n";
                
                Ptr<MobilityModel> mob = nodePtr->GetObject<MobilityModel>();
                Vector pos = mob->GetPosition();
                UeRadioTable& radio = table_radio_5g[nid];

                m_file << "      { ";
                m_file << "\"id\": \"" << dittoId << "\", ";
                m_file << "\"x\": " << pos.x << ", \"y\": " << pos.y << ", \"z\": " << pos.z << ", ";
                m_file << "\"speed\": " << radio.currentSpeed << ", ";
                
                if (dittoId.find("ue") != std::string::npos) {
                    m_file << "\"serving_gnb\": \"" << radio.servingGnb << "\", ";
                    m_file << "\"sinr_dl\": " << radio.dlSinr ;
                    // m_file << "\"sinr_d2d\": -999";
                } else {
                    m_file << "\"type\": \"gNB\"";
                }
                m_file << " }";
                firstNode = false;
            }
        }
        m_file << "\n    ],\n";

        // --- SECTION FLOWS ---
        m_file << "    \"flows\": [\n";
        bool firstFlow = true;
        for (auto const& [fid, flow] : active_flows) {
            if (!firstFlow) m_file << ",\n";
            
            bool isDl = (flow.srcName.find("server") != std::string::npos);
            uint32_t ueId = isDl ? flow.dstNode->GetId() : flow.srcNode->GetId();
            UeRadioTable& stats = table_radio_5g[ueId];

            m_file << "      { ";
            m_file << "\"type\": \"" << (isDl ? "DL" : "UL") << "\", ";
            m_file << "\"src\": \"" << flow.srcName << "\", ";
            m_file << "\"dst\": \"" << flow.dstName << "\", ";
            // m_file << "\"app\": \"" << (isDl ? "DL_Traffic" : "UL_Traffic") << "\", ";
            m_file << "\"packet_size\": " << flow.packetSize << ", ";
            m_file << "\"interval\": " << flow.interval << ", ";
            m_file << "\"throughput\": " << (isDl ? stats.macThroughputDl : stats.macThroughputUl) << ", ";
            m_file << "\"delay\": " << (isDl ? stats.macDelayDl : stats.macDelayUl) << ", ";
            m_file << "\"bler\": " << (isDl ? stats.blerDl : stats.blerUl) << ", ";
            m_file << "\"packet_loss\": " << (isDl ? stats.packetLossDl : stats.packetLossUl);
            m_file << " }";
            firstFlow = false;
        }
        m_file << "\n    ]\n";
        
        // --- FERMETURE DU SNAPSHOT ---
        m_file << "  }\n]"; // 
        m_file.flush();

        Simulator::Schedule(Seconds(g_snapshotInterval), &SnapshotManager::DoSnapshot, this);

    }

    void Close() {
        if (m_file.is_open()) m_file.close();
    }
};


SnapshotManager g_snapshotMgr;


/**
 * Reads the initial JSON configuration and prints exactly what it finds.
 * Uses std::set to ensure each UE/gNB is only counted ONCE.
 */
void PreParseInitialEntities(std::string filePath, std::vector<std::string>& ueList, std::vector<std::string>& gnbList) {
    std::ifstream ifs(filePath);
    if (!ifs.is_open()) {
        std::cout << "\033[1;31m[PRE-PARSE] ERROR: Could not open " << filePath << "\033[0m" << std::endl;
        return;
    }

    json root;
    
    std::set<std::string> uniqueUes;
    std::set<std::string> uniqueGnbs;

    try {
        ifs >> root;
    } catch (const std::exception&) {
        ifs.close();
        return;
    }

    if (root.is_array()) {
            std::cout << "\033[1;34m[PRE-PARSE] Starting Strict JSON scan...\033[0m" << std::endl;
            
            for (const auto& item : root) {
                if (!item.contains("thingId") || !item["thingId"].is_string()) continue;
                
                std::string tid = item["thingId"].get<std::string>();

                // --- 1. STRICT UE FILTER ---
                // Must start with "my5GNetwork:ue"
                // Must NOT contain "_to_" (this filters out flows like server_to_ue)
                if (tid.find("my5GNetwork:ue") == 0 && tid.find("_to_") == std::string::npos) {
                    
                    // Verify that what follows "ue" is actually a number (to avoid "ue_template" etc)
                    // "my5GNetwork:ue" is 14 characters long
                    if (tid.length() > 14 && std::isdigit(tid[14])) {
                        if (uniqueUes.find(tid) == uniqueUes.end()) {
                            uniqueUes.insert(tid);
                            std::cout << "  [NODE] Found Physical UE: " << tid << std::endl;
                        }
                    }
                } 
                // --- 2. STRICT GNB FILTER ---
                // Must start with "my5GNetwork:gnb" AND be followed by a digit
                // ("my5GNetwork:gnb" alone is rejected — bug fix for double-creation)
                else if (tid.find("my5GNetwork:gnb") == 0 && tid.find("_to_") == std::string::npos) {
                    // "my5GNetwork:gnb" is 15 characters long
                    if (tid.length() > 15 && std::isdigit(tid[15])) {
                        if (uniqueGnbs.find(tid) == uniqueGnbs.end()) {
                            uniqueGnbs.insert(tid);
                            std::cout << "  [NODE] Found Physical gNB: " << tid << std::endl;
                        }
                    }
                }
                else {
                    // This is likely a flow or a remote host, we ignore it for Node Creation
                    // std::cout << "  [IGNORE] Skipping Flow/Object: " << tid << std::endl;
                }
            }
    }
    ifs.close();

    ueList.assign(uniqueUes.begin(), uniqueUes.end());
    gnbList.assign(uniqueGnbs.begin(), uniqueGnbs.end());

    std::cout << "\033[1;32m[PRE-PARSE] SUCCESS: " << ueList.size() 
              << " unique UE nodes and " << gnbList.size() << " gNB nodes identified.\033[0m" << std::endl;
}


// ===========================================================================
// 4. MAIN
// ===========================================================================
int main(int argc, char *argv[]) {
    // --- 0. WAIT FOR DITTO BRIDGE READINESS ---
    // Both omnet_to_ditto_sync and ditto_ns3_sender create this sentinel
    // once they have written their first valid payload. Without this wait
    // ns-3 used to start with an empty buffer and fall back to a single UE.
    const std::string readyFile = "/dev/shm/ditto_buffer.ready";
    const std::string configPath = "/dev/shm/ditto_buffer.json";
    int readyTimeoutSec = 60;
    if (const char* envTimeout = std::getenv("NS3_READY_TIMEOUT")) {
        try { readyTimeoutSec = std::max(1, std::stoi(envTimeout)); } catch (...) {}
    }
    {
        std::cout << "[NS3] Waiting for Ditto bridge readiness (max "
                  << readyTimeoutSec << "s)..." << std::endl;
        auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(readyTimeoutSec);
        bool ready = false;
        while (std::chrono::steady_clock::now() < deadline) {
            std::ifstream rf(readyFile);
            std::ifstream cf(configPath);
            if (rf.good() && cf.good() && cf.peek() != EOF) { ready = true; break; }
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }
        if (!ready) {
            std::cout << "[NS3] WARNING: Ditto bridge not ready after timeout — falling back to defaults." << std::endl;
        } else {
            std::cout << "[NS3] Bridge ready, proceeding to pre-parse entities." << std::endl;
        }
    }

    // --- 0b. RESOLVE OUTPUT FILE PATH ----------------------------------------
    // If NS3_OUTPUT_DIR is set (by run_full_pipeline.sh) write snapshots there
    // so the agent can find them regardless of where the ns3 binary runs from.
    {
        const char* outDir = std::getenv("NS3_OUTPUT_DIR");
        if (outDir && std::string(outDir).length() > 0) {
            g_outputFile = std::string(outDir) + "/ns3_received_history.json";
        }
        std::cout << "[NS3] Snapshot output: " << g_outputFile << std::endl;
    }

    // --- 1. DYNAMIC DETECTION OF UEs and GNBs (Ditto/RAM Buffer) ---
    std::vector<std::string> discoveredUes;
    std::vector<std::string> discoveredGnbs;

    PreParseInitialEntities(configPath, discoveredUes, discoveredGnbs);

    // Fallback par défaut
    if (discoveredUes.empty()) discoveredUes.push_back("my5GNetwork:ue0");
    if (discoveredGnbs.empty()) discoveredGnbs.push_back("my5GNetwork:gnb0");

    uint32_t nUes = discoveredUes.size();
    uint32_t nGnbs = discoveredGnbs.size();

    // --- 2. NODE CREATION ---
    NodeContainer tapNodes, gnbNodes, ueNodes, remoteHost;
    tapNodes.Create(2); 
    gnbNodes.Create(nGnbs); 
    ueNodes.Create(nUes); 
    remoteHost.Create(1);

    // --- 3. MOBILITY SETUP ---
    MobilityHelper mobility;
    mobility.SetMobilityModel("ns3::ConstantPositionMobilityModel");
    mobility.Install(tapNodes);
    mobility.Install(gnbNodes);
    mobility.Install(ueNodes); 
    mobility.Install(remoteHost);

    for (uint32_t i = 0; i < nGnbs; ++i) {
        gnbNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector(726.0 + (i * 50.0), 277.0, 10.0));
    }
    for (uint32_t i = 0; i < nUes; ++i) {
        ueNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector(850.0 + (i * 5.0), 850.0, 1.5));
    }

    // Positions initiales dynamiques
    // for (uint32_t i = 0; i < nGnbs; ++i) {
    //     gnbNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector(726.0 + (i * 100), 277.0, 0.0));
    // }
    // for (uint32_t i = 0; i < nUes; ++i) {
    //     ueNodes.Get(i)->GetObject<MobilityModel>()->SetPosition(Vector(200.0 + (i * 60.0), 480.0 + (i * 0.0), 1.5));
    // }

    // --- 4. DITTO MAPPING ---
    for (uint32_t i = 0; i < nGnbs; ++i) thingIdToNode[discoveredGnbs[i]] = gnbNodes.Get(i);
    for (uint32_t i = 0; i < nUes; ++i) thingIdToNode[discoveredUes[i]] = ueNodes.Get(i);
    thingIdToNode["my5GNetwork:remoteHost"] = remoteHost.Get(0);

    // --- 5. CONTROL NETWORK (TAP Bridge & Ditto App) ---
    InternetStackHelper internetControl;
    internetControl.Install(tapNodes);

    CsmaHelper csma;
    csma.SetChannelAttribute("DataRate", StringValue("100Mbps"));
    csma.SetChannelAttribute("Delay", StringValue("1ms"));
    NetDeviceContainer csmaDevs = csma.Install(tapNodes);

    Ipv4AddressHelper ipv4Control;
    ipv4Control.SetBase("10.1.1.0", "255.255.255.0");
    Ipv4InterfaceContainer csmaIfaces = ipv4Control.Assign(csmaDevs);

    TapBridgeHelper tapBridge;
    tapBridge.SetAttribute("Mode", StringValue("UseLocal"));
    tapBridge.SetAttribute("DeviceName", StringValue("thetap"));
    tapBridge.Install(tapNodes.Get(0), csmaDevs.Get(0));

    Ptr<DittoControllerApp> dittoApp = CreateObject<DittoControllerApp>();
    dittoApp->Setup(5000, "ns3_ditto_raw.json");
    tapNodes.Get(1)->AddApplication(dittoApp);
    dittoApp->SetStartTime(Seconds(0.1));

    Ptr<NrPointToPointEpcHelper> epcHelper = CreateObject<NrPointToPointEpcHelper>();
    Ptr<NrHelper> nrHelper = CreateObject<NrHelper>();
    nrHelper->SetEpcHelper(epcHelper);

    nrHelper->SetGnbPhyAttribute("TxPower", DoubleValue(43.0));

    nrHelper->SetUePhyAttribute("TxPower", DoubleValue(23.0));


    nrHelper->SetUePhyAttribute("NoiseFigure", DoubleValue(7.0)); 
    nrHelper->SetGnbPhyAttribute("NoiseFigure", DoubleValue(5.0));

    // Beamforming
    // Ptr<IdealBeamformingHelper> bfHelper = CreateObject<IdealBeamformingHelper>();
    // bfHelper->SetAttribute("BeamformingPeriodicity", TimeValue(MilliSeconds(1000)));

    // nrHelper->SetBeamformingHelper(bfHelper);



    // Spectre et Bande passante (3.5 GHz, 100 MHz)
    CcBwpCreator ccBwpCreator;
    CcBwpCreator::SimpleOperationBandConf bandConf(3.5e9, 100e6, 1);
    OperationBandInfo band = ccBwpCreator.CreateOperationBandContiguousCc(bandConf);
    nrHelper->InitializeOperationBand(&band);

    // Installation des couches Internet (GNB, UE, RemoteHost)
    InternetStackHelper internet5G;
    internet5G.Install(gnbNodes); 
    internet5G.Install(ueNodes); 
    internet5G.Install(remoteHost);

    // Installation des terminaux 5G
    NetDeviceContainer gnbDevs = nrHelper->InstallGnbDevice(gnbNodes, CcBwpCreator::GetAllBwps({band}));
    NetDeviceContainer ueDevs = nrHelper->InstallUeDevice(ueNodes, CcBwpCreator::GetAllBwps({band}));

    for (auto it = gnbDevs.Begin(); it != gnbDevs.End(); ++it) {
        DynamicCast<NrGnbNetDevice>(*it)->UpdateConfig();
    }
    for (auto it = ueDevs.Begin(); it != ueDevs.End(); ++it) {
        DynamicCast<NrUeNetDevice>(*it)->UpdateConfig();
    }

    // Expose devices globally so ApplyAgentAction() can update PHY params at runtime.
    g_gnbDevs = gnbDevs;
    g_ueDevs  = ueDevs;
    
    // IP et Attachement
    epcHelper->AssignUeIpv4Address(NetDeviceContainer(ueDevs));
    nrHelper->AttachToClosestEnb(ueDevs, gnbDevs);

    // --- 7. BEARER ACTIVATION + IMSI <-> nodeId mapping ---
    g_ueImsiNodeIds.clear();
    imsi_to_nodeid.clear();
    for (uint32_t i = 0; i < ueDevs.GetN(); ++i) {
        Ptr<NrUeNetDevice> nrUeDev = ueDevs.Get(i)->GetObject<NrUeNetDevice>();
        uint64_t imsi = nrUeDev->GetImsi();
        uint32_t nodeId = ueNodes.Get(i)->GetId();
        g_ueImsiNodeIds.emplace_back(imsi, nodeId);
        imsi_to_nodeid[imsi] = nodeId;
        epcHelper->ActivateEpsBearer(ueDevs.Get(i), imsi, Create<EpcTft>(),
                         EpsBearer(EpsBearer::NGBR_VIDEO_TCP_DEFAULT));
    }

    // --- 8. METRICS & TRACES (Connexion finale) ---
    ConnectSimulationTraces(ueDevs, gnbDevs, ueNodes);
    
    Simulator::Schedule(Seconds(1.1), &ComputeThroughput, nrHelper, nGnbs, nUes);
    Simulator::Schedule(Seconds(1.2), &ComputeLatency, nrHelper, nGnbs, nUes);
    Simulator::Schedule(Seconds(1.3), &ComputeDistance, nrHelper, gnbNodes, nGnbs, nUes);
    Simulator::Schedule(Seconds(1.4), &ComputePacketLoss, nrHelper, nGnbs, nUes);
    Simulator::Schedule(Seconds(1.5), &ComputeBler, nrHelper, nGnbs, nUes);

    // --- 9. CORE NETWORK & INTERNET ROUTING ---
    Ptr<Node> pgw = epcHelper->GetPgwNode();
    PointToPointHelper p2p;
    p2p.SetDeviceAttribute("DataRate", StringValue("10Gbps"));
    p2p.SetChannelAttribute("Delay", StringValue("1ms"));
    NetDeviceContainer internetDevices = p2p.Install(pgw, remoteHost.Get(0));
    
    Ipv4AddressHelper ipv4Internet;
    ipv4Internet.SetBase("1.0.0.0", "255.0.0.0");
    Ipv4InterfaceContainer internetIpIfaces = ipv4Internet.Assign(internetDevices);

    // Routage statique pour le RemoteHost
    Ipv4StaticRoutingHelper ipv4RoutingHelper;
    Ptr<Ipv4StaticRouting> remoteHostStaticRouting = ipv4RoutingHelper.GetStaticRouting(remoteHost.Get(0)->GetObject<Ipv4>());
    remoteHostStaticRouting->AddNetworkRouteTo(Ipv4Address("7.0.0.0"), Ipv4Mask("255.0.0.0"), Ipv4Address("1.0.0.1"), 1);
    
    // Routage par défaut pour les UEs
    Ipv4StaticRoutingHelper staticRouting;
    for (uint32_t i = 0; i < ueNodes.GetN(); ++i) {
        Ptr<Ipv4StaticRouting> ueStaticRouting = staticRouting.GetStaticRouting(ueNodes.Get(i)->GetObject<Ipv4>());
        ueStaticRouting->SetDefaultRoute(Ipv4Address("7.0.0.1"), 1);
    }
    
    // --- 10. FINALIZATION & RUN ---
    // Fix mobilité pour tous les noeuds
    for (uint32_t i = 0; i < NodeList::GetNNodes(); ++i) {
        Ptr<Node> n = NodeList::GetNode(i);
        if (!n->GetObject<MobilityModel>()) mobility.Install(n);
    }

    // for (uint32_t i = 0; i < gnbDevs.GetN(); ++i) {
    //     Ptr<NrGnbNetDevice> gnbDev = DynamicCast<NrGnbNetDevice>(gnbDevs.Get(i));
    //     if (gnbDev) {
    //         Ptr<NrGnbMac> gnbMac = gnbDev->GetMac(0);
    //         if (gnbMac) {
    //             gnbMac->TraceConnectWithoutContext("DlHarqFeedback", MakeCallback(&HarqDlSink));
    //             gnbMac->TraceConnectWithoutContext("UlHarqFeedback", MakeCallback(&HarqUlSink));
    //         }
    //     }
    // }

    

    if (g_debugMode) {
        Simulator::Schedule(Seconds(1.0), &CheckInterfaceStatus, ueNodes.Get(0));
        Simulator::Schedule(Seconds(5.0), &CheckInterfaceStatus, ueNodes.Get(0));
        Simulator::Schedule(Seconds(10.0), &CheckInterfaceStatus, ueNodes.Get(0));
        Simulator::Schedule(Seconds(1.0), &CheckNeighborCache, ueNodes.Get(0));
        Simulator::Schedule(Seconds(5.0), &CheckNeighborCache, ueNodes.Get(0));
        Simulator::Schedule(Seconds(10.0), &CheckNeighborCache, ueNodes.Get(0));
    }

    nrHelper->EnableTraces();
    g_snapshotMgr.Open(g_outputFile);
    Simulator::Schedule(Seconds(1.0), &SnapshotManager::DoSnapshot, &g_snapshotMgr);

    NS_LOG_INFO("Simulation Starting...");
    Simulator::Stop(Seconds(600.0));
    Simulator::Run();

    g_snapshotMgr.Close();
    Simulator::Destroy();
    return 0;
}

