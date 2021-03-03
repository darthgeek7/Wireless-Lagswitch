#!/usr/bin/env python3

import os, sys, scapy.all as net, packet_analysis

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import get_machines

def logPacket(raw):
	raw.accept()
	packet = net.IP(raw.get_payload())
	if net.DNS in packet or net.ICMP in packet: #ignore there as they're not used for "actual" game netcode
		return
	print(packet.summary())

print("Finding network devices...")
machines = get_machines.search(ps4=True)

#will default to UDP
network_thread = packet_analysis.NFQueueThread(machines["target"], callback=logPacket)
try:
	print("Starting nfqueue...")
	network_thread.start()
	network_thread.join()

except KeyboardInterrupt:
	print("Closing...")

except Exception as e:
	print(e)




