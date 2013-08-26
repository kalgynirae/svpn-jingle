#!/usr/bin/env python

import socket
import select
import json
import time
import sys
import os
import binascii
import struct
import hashlib

IP4 = "172.31.0.100"
IP6 = "fd50:0dbc:41f2:4a3c:0000:0000:0000:0000"
STUN = "209.141.33.252:19302"
LOCALHOST= "127.0.0.1"
LOCALHOST6= "::1"
SVPN_PORT = 5800
CONTROLLER_PORT = 5801
UID_SIZE = 18
MODE = "svpn"
SEC = True

def gen_ip4(uid, count, ip4=IP4):
    return ip4[:-3] + str( 101 + count)

def gen_ip6(uid, ip6=IP6):
    uid_key = uid[-18:]
    count = (len(ip6) - 7) / 2
    ip6 = ip6[:19]
    for i in range(0, 16, 4):
        ip6 += ":"
        ip6 += uid_key[i:i+4]
    return ip6

def make_call(sock, params):
    data = json.dumps(params)
    if socket.has_ipv6: dest = (LOCALHOST6, SVPN_PORT)
    else: dest = (LOCALHOST, SVPN_PORT)
    return sock.sendto(data, dest)

def do_set_callback(sock, addr):
    params = {"m": "set_callback", "ip": addr[0], "port": addr[1]}
    return make_call(sock, params)

def do_register_service(sock, username, password, host):
    params = {"m": "register_service", "u": username, "p": password, "h": host}
    return make_call(sock, params)

def do_create_link(sock, uid, fpr, nid, sec, cas, stun=STUN):
    params = {"m": "create_link", "uid": uid, "fpr": fpr, "nid": nid,
              "stun" : stun, "turn": stun, "sec": sec, "cas": cas}
    return make_call(sock, params)

def do_trim_link(sock, uid):
    params = {"m": "trim_link", "uid": uid}
    return make_call(sock, params)

def do_set_local_ip(sock, uid, ip4, ip6, ip4_mask=24, ip6_mask=64):
    params = {"m": "set_local_ip", "uid": uid, "ip4": ip4, "ip6": ip6,
              "ip4_mask": ip4_mask, "ip6_mask": ip6_mask}
    return make_call(sock, params)

def do_set_remote_ip(sock, uid, ip4, ip6):
    params = {"m": "set_remote_ip", "uid": uid, "ip4": ip4, "ip6": ip6}
    return make_call(sock, params)

def do_send_msg(sock, nid, uid, data):
    params = {"m": "send_msg", "nid": nid, "uid": uid, "data": data}
    return make_call(sock, params)

def do_get_state(sock):
    params = {"m": "get_state"}
    return make_call(sock, params)

class UdpServer:

    def __init__(self, user, password, host, ip4):
        self.user = user
        self.password = password
        self.host = host
        self.ip4 = ip4
        if socket.has_ipv6:
            self.sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", CONTROLLER_PORT))
        self.state = {}
        self.controllers = {}
        self.controllers6 = {}

    def setup_svpn(self):
        uid = binascii.b2a_hex(os.urandom(9))
        hostname = socket.gethostname()
        m = hashlib.sha1()
        if MODE == "svpn" and hostname != "localhost":
            m.update(socket.gethostname())
        elif MODE == "gvpn":
            m.update(self.ip4)

        uid = m.hexdigest()[:UID_SIZE]
        do_set_callback(self.sock, self.sock.getsockname())
        do_set_local_ip(self.sock, uid, self.ip4, gen_ip6(uid))
        do_register_service(self.sock, self.user, self.password, self.host)
        do_get_state(self.sock)

    def set_state(self, state):
        self.state = state
        if len(self.ip4) == 0: self.ip4 = state["_ip4"]
        if len(state["_uid"]) == 0: self.setup_svpn()
        for k, v in self.state.get("peers", {}).iteritems():
            if len(v["ip4"]) == 0: continue
            # We store in network format for easier comparison
            ip4_n = socket.inet_pton(socket.AF_INET, v["ip4"])
            self.controllers[ip4_n] = v["ip6"]
            if socket.has_ipv6:
                ip6_n = socket.inet_pton(socket.AF_INET6, v["ip6"])
                self.controllers6[ip6_n] = v["ip6"]

    def create_connection(self, uid, data, nid, sec, cas, ip4=None):
        if uid == self.state["_uid"]: return
        if MODE == "gvpn":
            do_send_msg(self.sock, 1, uid, "ip4:" + self.state["_ip4"])
        elif MODE == "svpn":
            ip4 = gen_ip4(uid, len(self.state["peers"]), self.ip4)

        ip6 = gen_ip6(uid)
        do_create_link(self.sock, uid, data, nid, sec, cas)
        do_set_remote_ip(self.sock, uid, ip4, ip6)
        do_get_state(self.sock)

    def trim_connections(self):
        for k, v in self.state.get("peers", {}).iteritems():
            if "fpr" in v and v["status"] == "offline":
                if v["last_time"] > 120: do_trim_link(self.sock, k)

    def do_pings(self, social_send=False):
        # TODO - It's not a good idea to send a bunch of packets at once
        msg = {"m":"ping", "uid": self.state["_uid"]}
        for k, v in self.state.get("peers", {}).iteritems():
            if social_send: do_send_msg(self.sock, 1, k, self.state["_fpr"])
            if socket.has_ipv6: dest = (v["ip6"], CONTROLLER_PORT)
            else: dest = (v["ip4"], CONTROLLER_PORT)
            self.sock.sendto(json.dumps(msg), dest)

    # TODO - Add namespace support
    def lookup(self, ip4=None, ip6=None):
        if not socket.has_ipv6: return
        for peer in self.controllers.values():
            request = {"m": "lookup", "ip4": ip4, "ip6": ip6}
            dest = (peer, CONTROLLER_PORT)
            self.sock.sendto(json.dumps(request), dest)

    def process_lookup(self, request, addr):
        ip4 = request.get("ip4", None)
        ip6 = request.get("ip6", None)
        for k, v in self.state.get("peers", {}).iteritems():
            if v["status"] == "online" and \
                (ip4 == v["ip4"] or ip6 == v["ip6"]):
                response = {"uid": k}
                response["data"] = v["fpr"]
                response["ip4"] = ip4
                self.sock.sendto(json.dumps(response), addr)

    def route_notification(self, msg, addr):
        if addr[0] == LOCALHOST6:
            msg["from"] = self.state["_uid"]
            msg["ip4"] = self.state["_ip4"]
            for k, v in self.state.get("peers", {}).iteritems():
                if v["status"] == "online":
                    ip6 = gen_ip6(k, IP6)
                    dest = (ip6, CONTROLLER_PORT, 0, 0)
                    self.sock.sendto(json.dumps(msg), dest)
        elif msg["uid"] in self.state.get("peers", {}):
            peer = self.state["peers"][msg["uid"]]
            if peer["status"] == "online":
                ip6 = gen_ip6(msg["uid"])
                dest = (ip6, CONTROLLER_PORT, 0, 0)
                self.sock.sendto(json.dumps(msg), dest)

    def handle_packet(self, packet, do_lookup=False):
        if len(self.state["_ip4"]) == 0 or not socket.has_ipv6: return
        iph = struct.unpack('!BBHHHBBH4s4s', packet[54:74])
        version_ihl = struct.unpack('!B', packet[54:55])
        version = version_ihl[0] >> 4

        if version == 4:
            s_addr_n = struct.unpack('!4s', packet[66:70])[0]
            d_addr_n = struct.unpack('!4s', packet[70:74])[0]
            addr_family = socket.AF_INET
        elif version == 6:
            s_addr_n = struct.unpack('!16s', packet[62:78])[0]
            d_addr_n = struct.unpack('!16s', packet[78:94])[0]
            addr_family = socket.AF_INET6
        else: return

        s_addr = socket.inet_ntop(addr_family, s_addr_n)
        d_addr = socket.inet_ntop(addr_family, d_addr_n)
        print version, s_addr, d_addr
        if MODE == "svpn" or len(self.state["_ip4"]) == 0: return

        if version == 4:
            self_ip = socket.inet_pton(addr_family, self.state["_ip4"])
            controllers = self.controllers
        elif version == 6:
            self_ip = socket.inet_pton(addr_family, self.state["_ip6"])
            controllers = self.controllers6

        if (s_addr_n == self_ip):
            # TODO - Send to first controller, need better routing policy
            dest = (controllers.values()[0], CONTROLLER_PORT)
        elif (d_addr_n == self_ip):
            dest = (LOCALHOST6, SVPN_PORT)
        elif d_addr_n in controllers:
            dest = (controllers[d_addr_n], CONTROLLER_PORT)
        else: return

        self.sock.sendto(packet, dest)
        return d_addr

    def serve(self):
        msg = None
        socks = select.select([self.sock], [], [], 15)
        for sock in socks[0]:
            data, addr = sock.recvfrom(4096)
            print addr, len(data)
            if data[0] == '{': msg = json.loads(data)
            else: self.handle_packet(data); continue

            print "recv %s %s" % (addr, data)
            if isinstance(msg, dict) and "_uid" in msg:
                self.set_state(msg)
                continue

            # we only process if we have state and msg is json dict
            if len(self.state["_fpr"]) == 0 or not isinstance(msg, dict):
                continue

            if msg.get("m", None) == "lookup":
                self.process_lookup(msg, addr)
                continue

            if msg.get("m", None) == "nc_lookup":
                self.lookup(msg["ip"], msg["ip4"], msg["ip6"])
                continue

            ip4 = msg.get("ip4", None)
            fpr_len = len(self.state["_fpr"])
            local_ip = LOCALHOST6 if socket.has_ipv6 else LOCALHOST

            # this is a peer discovery notification
            if "data" in msg and len(msg["data"]) == fpr_len:
                if addr[0] == local_ip:
                    self.create_connection(msg["uid"], msg["data"], 1, SEC,
                                           "", ip4)
                else:
                    self.create_connection(msg["uid"], msg["data"], 0, SEC,
                                           "", ip4)
            # this is a connection request notification
            elif "data" in msg and len(msg["data"]) > fpr_len:
                fpr = msg["data"][:fpr_len]
                cas = msg["data"][fpr_len + 1:]
                # this came from social network
                if addr[0] == local_ip and fpr != self.state["_fpr"]:
                    self.create_connection(msg["uid"], fpr, 1, SEC, cas, ip4)
                # this came from another controller
                elif msg["uid"] == self.state["_uid"] and "from" in msg:
                    self.create_connection(msg["from"], fpr, 0, SEC, cas, ip4)
                else:
                    self.route_notification(msg, addr)
            # this is an ip address update
            elif "data" in msg and msg["data"].startswith("ip4:"):
                ip4 = msg["data"][4:]
                ip6 = gen_ip6(msg["uid"])
                do_set_remote_ip(self.sock, msg["uid"], ip4, ip6)

def main():
    ip4 = ""
    if len(sys.argv) < 4:
        print "usage: %s username password host [ip]" % (sys.argv[0],)

    if len(sys.argv) > 4:
        ip4 = sys.argv[4]
        global MODE
        MODE = "gvpn"

    server = UdpServer(sys.argv[1], sys.argv[2], sys.argv[3], ip4)
    do_get_state(server.sock)
    last_time = time.time()
    count = 0

    while True:
        server.serve()
        time_diff = time.time() - last_time
        if time_diff > 30:
            count += 1
            server.trim_connections()
            do_get_state(server.sock)
            last_time = time.time()
            if count % 10 == 0: server.do_pings(True)
            else: server.do_pings(False)

if __name__ == '__main__':
    main()
