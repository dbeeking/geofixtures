"""Best-effort network block for offline runs.

This patches Python's socket module in one process. It stops Python code from
reaching other hosts, but it can't see native libraries with their own network
stack or separate programs. To enforce offline execution, run under a network
namespace or container with no network.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from .models import OfflineViolation


def _is_local(host: Any) -> bool:
    if host is None or host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@contextmanager
def offline_guard(enabled: bool = True) -> Iterator[None]:
    """Make connections, datagrams, and name lookups for other hosts raise OfflineViolation."""
    if not enabled:
        yield
        return
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    sendto = socket.socket.sendto
    getaddrinfo = socket.getaddrinfo

    def check(sock: socket.socket, address: Any) -> None:
        if sock.family in (socket.AF_INET, socket.AF_INET6) and not _is_local(address[0]):
            raise OfflineViolation(f"Network access is disabled: {address!r}")

    def guarded_connect(self: socket.socket, address: Any) -> None:
        check(self, address)
        connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> int:
        check(self, address)
        return connect_ex(self, address)

    def guarded_sendto(self: socket.socket, data: Any, *args: Any) -> int:
        check(self, args[-1])
        return sendto(self, data, *args)

    def guarded_getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if not _is_local(host):
            raise OfflineViolation(f"Network access is disabled: {host!r}")
        return getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign,assignment]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign,assignment]
    socket.socket.sendto = guarded_sendto  # type: ignore[method-assign,assignment]
    socket.getaddrinfo = guarded_getaddrinfo
    try:
        yield
    finally:
        socket.socket.connect = connect  # type: ignore[method-assign]
        socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
        socket.socket.sendto = sendto  # type: ignore[method-assign]
        socket.getaddrinfo = getaddrinfo
