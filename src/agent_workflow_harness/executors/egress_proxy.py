# SPDX-License-Identifier: Apache-2.0
"""Small fail-closed HTTPS CONNECT proxy for isolated agent networks.

The proxy accepts only TLS tunnels to an explicit hostname allowlist, resolves
the destination itself, rejects non-public addresses, and connects to the
validated address to prevent DNS rebinding between check and connect. It does
not terminate TLS or log request contents.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import argparse
import select
import socket
import socketserver
import threading
import time
from typing import Callable, Iterable


class ProxyRejected(ValueError):
    """A request does not satisfy the configured egress policy."""


@dataclass(frozen=True)
class ConnectTarget:
    host: str
    port: int


def normalize_allowlist(domains: Iterable[str]) -> tuple[str, ...]:
    result = set()
    for domain in domains:
        if not isinstance(domain, str) or not domain or domain != domain.strip():
            raise ValueError("egress allowlist entries must be DNS names")
        try:
            canonical = domain.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise ValueError("egress allowlist contains an invalid DNS name") from None
        if (not canonical or len(canonical) > 253 or "/" in canonical
                or "*" in canonical or "@" in canonical
                or any(not label or len(label) > 63 or label.startswith("-")
                       or label.endswith("-")
                       or any(not (ch.isalnum() or ch == "-") for ch in label)
                       for label in canonical.split("."))):
            raise ValueError("egress allowlist contains an invalid DNS name")
        try:
            ipaddress.ip_address(canonical)
        except ValueError:
            pass
        else:
            raise ValueError("egress allowlist cannot contain IP addresses")
        result.add(canonical)
    if not result:
        raise ValueError("egress allowlist must not be empty")
    return tuple(sorted(result))


def parse_connect_request(data: bytes) -> ConnectTarget:
    """Parse a bounded HTTP CONNECT header; reject all other proxy methods."""
    if not isinstance(data, bytes) or len(data) > 16_384 or b"\r\n\r\n" not in data:
        raise ProxyRejected("invalid proxy request")
    header = data.split(b"\r\n\r\n", 1)[0]
    try:
        lines = header.decode("ascii").split("\r\n")
    except UnicodeDecodeError:
        raise ProxyRejected("invalid proxy request") from None
    if not lines or len(lines) > 64:
        raise ProxyRejected("invalid proxy request")
    parts = lines[0].split(" ")
    if len(parts) != 3 or parts[0] != "CONNECT" or parts[2] != "HTTP/1.1":
        raise ProxyRejected("only HTTPS CONNECT is supported")
    authority = parts[1]
    if authority.count(":") != 1:
        raise ProxyRejected("invalid proxy authority")
    host, port_text = authority.rsplit(":", 1)
    try:
        port = int(port_text)
        normalized = host.rstrip(".").encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError):
        raise ProxyRejected("invalid proxy authority") from None
    if port != 443 or not normalized or len(normalized) > 253 or any(
            not label or len(label) > 63 or label.startswith("-") or label.endswith("-")
            or any(not (ch.isalnum() or ch == "-") for ch in label)
            for label in normalized.split(".")):
        raise ProxyRejected("only valid DNS names on port 443 are supported")
    try:
        ipaddress.ip_address(normalized)
    except ValueError:
        pass
    else:
        raise ProxyRejected("IP literals are not allowed")
    for line in lines[1:]:
        if not line or line[0] in " \t" or ":" not in line:
            raise ProxyRejected("invalid proxy header")
    return ConnectTarget(normalized, port)


def host_is_allowed(host: str, allowlist: Iterable[str]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in allowlist)


def resolve_public(host: str, port: int, *, resolver: Callable = socket.getaddrinfo):
    try:
        records = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise ProxyRejected("destination resolution failed") from None
    addresses = []
    for record in records:
        address = record[4][0]
        try:
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            raise ProxyRejected("destination resolution returned an invalid address") from None
        if not parsed.is_global:
            raise ProxyRejected("destination resolved outside the public address space")
        if address not in addresses:
            addresses.append(address)
    if not addresses:
        raise ProxyRejected("destination resolution returned no addresses")
    return tuple(addresses)


class ConnectProxy:
    def __init__(self, allowlist: Iterable[str], *, timeout_seconds: float = 300,
                 max_bytes: int = 1_073_741_824, resolver: Callable = socket.getaddrinfo,
                 connector: Callable = socket.create_connection):
        self.allowlist = normalize_allowlist(allowlist)
        if not 1 <= timeout_seconds <= 3600 or not 1 <= max_bytes <= 8_589_934_592:
            raise ValueError("proxy limits are outside supported bounds")
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.resolver = resolver
        self.connector = connector

    def connect(self, client, request: bytes):
        target = parse_connect_request(request)
        if not host_is_allowed(target.host, self.allowlist):
            raise ProxyRejected("destination hostname is not allowlisted")
        addresses = resolve_public(target.host, target.port, resolver=self.resolver)
        last_error = None
        upstream = None
        for address in addresses:
            try:
                upstream = self.connector((address, target.port), timeout=10)
                break
            except OSError as error:
                last_error = error
        if upstream is None:
            raise ProxyRejected("destination connection failed") from last_error
        with upstream:
            client.settimeout(None)
            upstream.settimeout(None)
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            _tunnel(client, upstream, timeout_seconds=self.timeout_seconds,
                    max_bytes=self.max_bytes)


def _tunnel(client, upstream, *, timeout_seconds: float, max_bytes: int):
    peers = (client, upstream)
    total = 0
    deadline = time.monotonic() + timeout_seconds
    while total < max_bytes:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        readable, _, exceptional = select.select(peers, (), peers, min(remaining, 30))
        if exceptional:
            return
        if not readable:
            continue
        for source in readable:
            try:
                payload = source.recv(min(65_536, max_bytes - total))
            except OSError:
                return
            if not payload:
                return
            destination = upstream if source is client else client
            try:
                destination.sendall(payload)
            except OSError:
                return
            total += len(payload)


class _Handler(socketserver.BaseRequestHandler):
    proxy: ConnectProxy

    def handle(self):
        self.request.settimeout(10)
        try:
            data = bytearray()
            while b"\r\n\r\n" not in data and len(data) <= 16_384:
                chunk = self.request.recv(min(4096, 16_385 - len(data)))
                if not chunk:
                    return
                data.extend(chunk)
            self.proxy.connect(self.request, bytes(data))
        except (OSError, ProxyRejected):
            try:
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass


class ThreadedProxyServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    max_workers = 32

    def __init__(self, address, proxy: ConnectProxy):
        self._slots = threading.BoundedSemaphore(self.max_workers)
        handler = type("ConfiguredProxyHandler", (_Handler,), {"proxy": proxy})
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Busy\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def serve(host: str, port: int, allowlist: Iterable[str]):
    proxy = ConnectProxy(allowlist)
    server = ThreadedProxyServer((host, port), proxy)
    server.serve_forever(poll_interval=0.25)


def main(argv=None):
    parser = argparse.ArgumentParser(description="AWH allowlisted HTTPS CONNECT proxy")
    parser.add_argument("--listen-host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=3128)
    parser.add_argument("--allow-domain", action="append", required=True)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65_535:
        parser.error("port must be in the range 1-65535")
    try:
        serve(args.listen_host, args.port, args.allow_domain)
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
