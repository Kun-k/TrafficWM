#!/usr/bin/env python3
"""Expose Chromium's container-loopback CDP socket to a Docker-published port."""

import argparse
import select
import socket
import socketserver


class TunnelHandler(socketserver.BaseRequestHandler):
    target_host = "127.0.0.1"
    target_port = 9222

    def handle(self) -> None:
        with socket.create_connection((self.target_host, self.target_port), timeout=5) as target:
            peers = (self.request, target)
            while True:
                readable, _, _ = select.select(peers, (), (), 30)
                if not readable:
                    continue
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination = target if source is self.request else self.request
                    destination.sendall(data)


class ThreadingTunnel(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-port", type=int, default=9223)
    parser.add_argument("--target-port", type=int, default=9222)
    args = parser.parse_args()
    TunnelHandler.target_port = args.target_port
    with ThreadingTunnel(("0.0.0.0", args.listen_port), TunnelHandler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
