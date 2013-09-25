#!/usr/bin/env python

import socket, select, json, time, sys, hashlib, binascii, os, argparse

# Set default config values
CONFIG = {
    "stun": "stun.l.google.com:19302",
    "turn": "",
    "turn_user": "",
    "turn_pass": "",
    "ip4": "172.31.0.100",
    "localhost":"127.0.0.1",
    "ip6_prefix": "fd50:0dbc:41f2:4a3c",
    "localhost6":"::1",
    "svpn_port": 5800,
    "controller_port": 5801,
    "uid_size": 40,
    "sec": True,
    "wait_time": 30,
    "buf_size": 4096,
}

def gen_ip4(uid, peers, ip4=None):
    if ip4 is None:
        ip4 = CONFIG["ip4"]
    return ip4[:-3] + str( 101 + len(peers))

def gen_ip6(uid, ip6=None):
    if ip6 is None:
        ip6 = CONFIG["ip6_prefix"]
    for i in range(0, 16, 4): ip6 += ":" + uid[i:i+4]
    return ip6

def gen_uid(ip4):
    return hashlib.sha1(ip4).hexdigest()[:CONFIG["uid_size"]]

def get_ip4(uid, ip4):
    parts = ip4.split(".")
    ip4 = parts[0] + "." + parts[1] + "." + parts[2] + "."
    for i in range(1, 255):
        if uid == gen_uid(ip4 + str(i)): return ip4 + str(i)
    return None

def make_call(sock, **params):
    if socket.has_ipv6: dest = (CONFIG["localhost6"], CONFIG["svpn_port"])
    else: dest = (CONFIG["localhost"], CONFIG["svpn_port"])
    return sock.sendto(json.dumps(params), dest)

def do_set_callback(sock, addr):
    return make_call(sock, m="set_callback", ip=addr[0], port=addr[1])

def do_register_service(sock, username, password, host):
    return make_call(sock, m="register_service", username=username,
                     password=password, host=host)

def do_create_link(sock, uid, fpr, nid, sec, cas, stun=None, turn=None):
    if stun is None:
        stun = CONFIG["stun"]
    if turn is None:
        turn = CONFIG["turn"]
    return make_call(sock, m="create_link", uid=uid, fpr=fpr, nid=nid,
                     stun=stun, turn=turn, turn_user=CONFIG["turn_user"],
                     turn_pass=CONFIG["turn_pass"], sec=sec, cas=cas)

def do_trim_link(sock, uid):
    return make_call(sock, m="trim_link", uid=uid)

def do_set_local_ip(sock, uid, ip4, ip6, ip4_mask=24, ip6_mask=64):
    return make_call(sock, m="set_local_ip", uid=uid, ip4=ip4, ip6=ip6,
                     ip4_mask=ip4_mask, ip6_mask=ip6_mask)

def do_set_remote_ip(sock, uid, ip4, ip6):
    return make_call(sock, m="set_remote_ip", uid=uid, ip4=ip4, ip6=ip6)

def do_get_state(sock):
    return make_call(sock, m="get_state")

class UdpServer:
    def __init__(self, user, password, host, ip4):
        self.state = {}
        self.peers = {}
        self.peerlist = set()
        if socket.has_ipv6:
            self.sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        else:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", CONFIG["controller_port"]))
        uid = binascii.b2a_hex(os.urandom(CONFIG["uid_size"] / 2))
        do_set_callback(self.sock, self.sock.getsockname())
        do_set_local_ip(self.sock, uid, ip4, gen_ip6(uid))
        do_register_service(self.sock, user, password, host)
        do_get_state(self.sock)

    def create_connection(self, uid, data, nid, sec, cas, ip4):
        self.peerlist.add(uid)
        do_create_link(self.sock, uid, data, nid, sec, cas)
        do_set_remote_ip(self.sock, uid, ip4, gen_ip6(uid))

    def trim_connections(self):
        for k, v in self.peers.iteritems():
            if "fpr" in v and v["status"] == "offline":
                if v["last_time"] > CONFIG["wait_time"] * 2:
                    do_trim_link(self.sock, k)

    def serve(self):
        socks = select.select([self.sock], [], [], CONFIG["wait_time"])
        for sock in socks[0]:
            data, addr = sock.recvfrom(CONFIG["buf_size"])
            if data[0] == '{':
                msg = json.loads(data)
                print "recv %s %s" % (addr, data)

                if "_fpr" in msg: self.state = msg; continue
                if isinstance(msg, dict) and "uid" in msg and "status" in msg:
                    self.peers[msg["uid"]] = msg; continue

                fpr_len = len(self.state["_fpr"])
                if "data" in msg and len(msg["data"]) >= fpr_len:
                    fpr = msg["data"][:fpr_len]
                    cas = msg["data"][fpr_len + 1:]
                    ip4 = gen_ip4(msg["uid"], self.peerlist, self.state["_ip4"])
                    self.create_connection(msg["uid"], fpr, 1, CONFIG["sec"],
                                           cas, ip4)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("password")
    parser.add_argument("host")
    parser.add_argument("-c", help="load configuration from a file",
                        dest="config_file", metavar="config_file")
    args = parser.parse_args()

    if args.config_file:
        # Load the config file
        with open(args.config_file) as f:
            loaded_config = json.load(f)
        CONFIG.update(loaded_config)

    count = 0
    server = UdpServer(args.username, args.password, args.host, CONFIG["ip4"])
    last_time = time.time()
    while True:
        server.serve()
        time_diff = time.time() - last_time
        if time_diff > CONFIG["wait_time"]:
            count += 1
            server.trim_connections()
            do_get_state(server.sock)
            last_time = time.time()

if __name__ == '__main__':
    main()

