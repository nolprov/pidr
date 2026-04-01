// src/FiveGNetwork.ned
package src; // 

import inet.node.inet.StandardHost;
import inet.networklayer.configurator.ipv4.Ipv4NetworkConfigurator;
import inet.mobility.single.RandomWaypointMobility;
import inet.visualizer.common.MobilityVisualizer;

import simu5g.nodes.NrUe;
import simu5g.nodes.gNodeB;
import simu5g.nodes.Upf;
import inet.networklayer.ipv4.RoutingTableRecorder;
import simu5g.common.binder.Binder;
import simu5g.world.radio.LteChannelControl;
import simu5g.common.carrierAggregation.CarrierAggregation;
import simu5g.nodes.Upf;
import inet.common.misc.ThruputMeteringChannel;
import simu5g.nodes.BackgroundCell;
import inet.common.scenario.ScenarioManager; 

import src.DTConnector;


network FiveGNetwork
{
    parameters:
        int numUe = default(4);
        int numGnb = default(1);
        int numBgCells = default(1);

        @display("i=block/network2;bgb=1000,1000;bgi=background/pisa");


    types:
        channel Eth10G extends ThruputMeteringChannel {
            delay = 0.1us;
            datarate = 10Gbps;
            thruputDisplayFormat = "#N";
        }


    submodules:
        channelControl: LteChannelControl {
            @display("p=50,25;is=s");
        }
       
        configurator: Ipv4NetworkConfigurator { 
            @display("p=50,125");
        }
        binder: Binder {
            @display("p=50,175;is=s");
        }
        carrierAggregation: CarrierAggregation {
            @display("p=50,258;is=s");
        }
        server: StandardHost {
            @display("p=212,118;is=n;i=device/server");
        }

        upf: Upf {
            @display("p=450,118;is=l");
        }

        visualizer: MobilityVisualizer {
            @display("p=50,200");
        }
       
       
        gnb[numGnb]: gNodeB {
            @display("p=726,277;is=vl");
        }
        bgCell[numBgCells]: BackgroundCell {
            @display("p=416,277;is=vl");
        }
        ue[numUe]: NrUe {
            @display("p=628,411");
        }

        dtConnector: src.DTConnector {
            @display("p=50,300;is=s");
        }

        scenarioManager: ScenarioManager { 
            @display("p=50,350;is=s");
        }

    connections:
        // Le Serveur se connecte à l'UPF (Gate 'filterGate')
        server.pppg++ <--> Eth10G <--> upf.filterGate;
        
        // L'UPF se connecte au gNodeB (Gate 'ppp')
        upf.pppg++ <--> Eth10G <--> gnb[0].ppp;

       
}
