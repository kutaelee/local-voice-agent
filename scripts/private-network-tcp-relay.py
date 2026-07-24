#!/usr/bin/env python3
"""Relay a private Windows listener to a private WSL NAT address.

The relay is transport-agnostic: TLS remains end-to-end between the Android
client and the PC server. Both endpoints must be private or loopback addresses.
"""

from __future__ import annotations

import argparse
import ipaddress
import socket
import threading


BUFFER_SIZE = 64 * 1024


def private_or_loopback(value: str) -> str:
    address = ipaddress.ip_address(value)
    if not (address.is_private or address.is_loopback):
        raise argparse.ArgumentTypeError("address must be private or loopback")
    return value


def pump(source: socket.socket, destination: socket.socket) -> None:
    try:
        while data := source.recv(BUFFER_SIZE):
            destination.sendall(data)
    except OSError:
        pass
    finally:
        try:
            destination.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle_client(
    client: socket.socket,
    target_host: str,
    target_port: int,
) -> None:
    target: socket.socket | None = None
    try:
        target = socket.create_connection((target_host, target_port), timeout=10)
        # create_connection leaves the connect timeout on the established
        # socket. Clear it so an idle WebSocket is not disconnected every
        # ten seconds while waiting for its next frame or ping.
        target.settimeout(None)
        threading.Thread(
            target=pump,
            args=(client, target),
            daemon=True,
        ).start()
        pump(target, client)
    finally:
        client.close()
        if target is not None:
            target.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-host", required=True, type=private_or_loopback)
    parser.add_argument("--listen-port", required=True, type=int)
    parser.add_argument("--target-host", required=True, type=private_or_loopback)
    parser.add_argument("--target-port", required=True, type=int)
    args = parser.parse_args()
    for port in (args.listen_port, args.target_port):
        if not 1024 <= port <= 65535:
            parser.error("ports must be between 1024 and 65535")
    return args


def main() -> None:
    args = parse_args()
    with socket.create_server(
        (args.listen_host, args.listen_port),
        family=socket.AF_INET6 if ":" in args.listen_host else socket.AF_INET,
        backlog=64,
        reuse_port=False,
    ) as server:
        while True:
            client, _ = server.accept()
            threading.Thread(
                target=handle_client,
                args=(client, args.target_host, args.target_port),
                daemon=True,
            ).start()


if __name__ == "__main__":
    main()
