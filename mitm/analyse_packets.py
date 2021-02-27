#!/usr/bin/env python3

import scapy.all as net
import sys, os, time, subprocess, shlex, threading, ipaddress, json
import atexit

import http.server
import urllib.parse

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
import get_machines

from netfilterqueue import NetfilterQueue as nfqueue # sudo apt install libnetfilter-queue-dev - sudo python3 -m pip install NetfilterQueue


import ipinfo #python3 -m pip install ipinfo
ip_handler = ipinfo.getHandler("c74b5a4469d554") #will only work from my IP

VERBOSITY = 0
HTTP_ADDRESS = "" # "" for anyone
HTTP_PORT = 8000

ip_catalogue = {}
kill_all = False
no_more = 0

class IP:
	def __init__(self, ip):
		self.ip = ip
		self.kill = False
		self.protect = False
		self.first_received = time.time()
		self.heartbeat()
		self.updateIpinfo()

	def heartbeat(self):
		self.last_received = time.time()

	def updateIpinfo(self):
		try:
			self.ip_info = ip_handler.getDetails(self.ip)
		except:
			self.ip_info = None

	def isdead(self):
		return time.time() - self.last_received > 20

	def __str__(self):
		ret = self.__dict__.copy() #copy so things doesn't get overwritten
		if ret["ip_info"]:
			info = ret["ip_info"]
			ret["ip_info"] = {
				"location": {
					"city": info.city,
					"region": info.region,
					"country": info.country,
					"country_name": info.country_name,
					"timezone": info.timezone
				},
				"provider": info.org
			}
		return json.dumps(ret)

class NFQueueThread(threading.Thread):
	def __init__(self, target):
		super().__init__()
		self.target = target
		self.daemon = True #will exit when the program does
		print("Altering iptables...")
		subprocess.run(shlex.split("iptables -I FORWARD -d %s -j NFQUEUE --queue-num 1" % (self.target.ip))) #ps4 destination
		subprocess.run(shlex.split("iptables -I FORWARD -s %s -j NFQUEUE --queue-num 1" % (self.target.ip))) #ps4 source
		atexit.register(self.__del__) #force running __del__, even

	def __del__(self):
		print("Restoring iptables...")
		subprocess.run(shlex.split("iptables -F"))
		subprocess.run(shlex.split("iptables -X"))
		atexit.unregister(self.__del__)

	#returns remote IP address
	def _checkPort(self, packet, port_number):
		ip = packet[net.IP]
		try: #target is the PS4
			if ip.src == self.target.ip and ip.sport == port_number:
				return ip.dst
			elif ip.dst == self.target.ip and ip.dport == port_number:
				return ip.src
		except AttributeError:
			pass
		return None

	def run(self):
		def callback(raw):
			packet = net.IP(raw.get_payload())

			if net.TCP in packet or net.DNS in packet or net.ICMP in packet: #ignore there as they're not used for "actual" game netcode
				raw.accept()
				return

			remote_ip = self._checkPort(packet, 9306) #9306 is gta

			if remote_ip and remote_ip.startswith("52.40.62."): #SONY/Amazon
				raw.accept()
				return

			if remote_ip and ipaddress.ip_address(remote_ip).is_global:
				if remote_ip in ip_catalogue:
					if (kill_all and not ip_catalogue[remote_ip].protect) or ip_catalogue[remote_ip].kill:
						raw.drop()
						ip_catalogue[remote_ip].heartbeat()
						return

					raw.accept()
					if ip_catalogue[remote_ip].ip_info:
						ip_catalogue[remote_ip].heartbeat()

					else: #not found
						ip_catalogue[remote_ip].updateIpinfo()

				elif no_more != 0 and time.time() > no_more:
					raw.drop()

				else:
					raw.accept()
					ip_catalogue[remote_ip] = IP(remote_ip)

				return

			raw.accept()
			#print(packet.summary())

		q = nfqueue()
		q.bind(1, callback)
		q.run()

class CustomHTTPRequestHandler(http.server.BaseHTTPRequestHandler):
	def log_message(self, format, *args):
		pass

	def do_GET(self):
		global kill_all

		parsed = urllib.parse.urlparse(self.path)
		if parsed.path == "/":
			self.send_response(200)
			self.send_header("Content-type", "text/html")
			self.end_headers()
			try:
				with open("ui.html", "rb") as f:
					self.wfile.write(f.read())
			except FileNotFoundError:
				self.wfile.write(b"ui.html not found, make sure your cwd is correct")

		elif parsed.path == "/data":
			self.send_response(200)
			self.send_header("Content-type", "application/json")
			self.end_headers()
			catalogue = ip_catalogue.copy() #hopefully no race conditions?
			ret = []
			for [key, value] in catalogue.items():
				if value.isdead():
					del ip_catalogue[key]
					continue
				ret.append(value.__str__().encode("utf-8"))

			self.wfile.write(b'{"kill_all": %s, "catalogue": [%s]}' % (
				b"true" if kill_all else b"false",
				b",".join(ret))
			)

		elif parsed.path == "/kill_all":
			kill_all = not kill_all
			print("Kill All =", kill_all)
			self.send_response(200)
			self.end_headers()

		elif parsed.path == "/kill":
			try:
				query = urllib.parse.parse_qs(parsed.query)
				for x in query.get("target", []):
					ip_catalogue[x].kill = not ip_catalogue[x].kill
					print("Kill -", x, "=", ip_catalogue[x].kill)

				self.send_response(200)
			except AttributeError:
				self.send_response(404)
			self.end_headers()

		elif parsed.path == "/protect":
			try:
				query = urllib.parse.parse_qs(parsed.query)
				for x in query.get("target", []):
					ip_catalogue[x].protect = not ip_catalogue[x].protect
					print("Protect -", x, "=", ip_catalogue[x].protect)

				self.send_response(200)
			except AttributeError:
				self.send_response(404)
			self.end_headers()

		else:
			self.send_response(404)
			self.end_headers()


if __name__ == "__main__":
	print("Finding network devices...")
	machines = get_machines.search(mac_startswith="00:d9:d1")

	network_thread = NFQueueThread(machines["target"])
	try:
		print("Starting nfqueue...")
		network_thread.start()

		print(f"Starting HTTP server at http://{machines['this'].ip}:{HTTP_PORT}...")
		httpd = http.server.HTTPServer((HTTP_ADDRESS, HTTP_PORT), CustomHTTPRequestHandler)
		httpd.serve_forever()

	except KeyboardInterrupt:
		print("Closing...")

	except Exception as e:
		print(e)



