"""
Egress guard for the OUTREMER pipeline (M17.3, #85).

With the guard installed, every outbound ``connect()`` from this process is
refused unless it targets one of the configured inference services:

    GPUSTACK_BASE_URL   LLM extraction and page recognition (qwen3.8-27b)
    ATR_GATEWAY_URL     ATR recognition engines (kraken, TrOCR), if set
    MCP_BASE_URL        MCP federation candidates, if set

A blocked connection raises ``PermissionError("EGRESS BLOCKED: …")``, which
the pipeline reports as a failed document rather than empty output.

The guard is process-local, so it must reach every process that does network
I/O.  ``install_if_requested()`` installs it when ``OUTREMER_AIRGAP=1`` is in
the environment; ``block_egress()`` sets that variable, so child processes
started afterwards (the Wikidata reconciliation, for one) inherit the rule as
long as their entry point calls ``install_if_requested()`` too.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
from urllib.parse import urlparse

ENV_FLAG = "OUTREMER_AIRGAP"

# The service URLs whose hosts the pipeline may contact. The README section
# "Permitted network hosts" lists the same three; change both together.
PERMITTED_URL_VARS = ("GPUSTACK_BASE_URL", "ATR_GATEWAY_URL", "MCP_BASE_URL")

_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex
_allowed: set[str] = set()


def _config_value(name: str) -> str:
    """The configured URL: environment first, then scripts/config.py."""
    value = os.environ.get(name, "")
    if value:
        return value
    try:
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import config  # noqa: PLC0415  (lazy: config loads .env.gpustack)

        return str(getattr(config, name, "") or "")
    except Exception:
        return ""


def permitted_hosts() -> set[str]:
    """Host names of the configured inference services."""
    hosts: set[str] = set()
    for var in PERMITTED_URL_VARS:
        host = urlparse(_config_value(var)).hostname
        if host:
            hosts.add(host.casefold())
    return hosts


def resolve_permitted_addresses(hosts: set[str] | None = None) -> set[str]:
    """Names and IP addresses of the permitted hosts, resolved before the cut.

    Clients resolve the name themselves and then connect() to the address,
    so the allow-list must hold the addresses, not only the names.
    """
    allowed: set[str] = set()
    for host in (permitted_hosts() if hosts is None else hosts):
        allowed.add(host.casefold())
        try:
            for info in socket.getaddrinfo(host, None):
                allowed.add(info[4][0])
        except OSError:
            pass  # unresolvable now: the name stays allowed, the run fails loudly
    return allowed


def is_allowed(host: str) -> bool:
    return str(host).casefold() in _allowed


def check(address) -> None:
    """Raise PermissionError when *address* is an outbound target not allowed."""
    # AF_UNIX addresses are str/bytes paths, not (host, port) tuples.
    if not isinstance(address, tuple) or not address:
        return
    host = address[0]
    if not is_allowed(host):
        port = address[1] if len(address) > 1 else "?"
        raise PermissionError(
            f"EGRESS BLOCKED: {host}:{port} is not a permitted host "
            f"(permitted: {sorted(_allowed) or 'none configured'}). "
            "A new outbound dependency must be declared in scripts/airgap.py "
            "and README 'Permitted network hosts' before it may be used."
        )


def block_egress(hosts: set[str] | None = None) -> set[str]:
    """Refuse outbound connect() to anything but the permitted hosts.

    Returns the allow-list in force.  Sets OUTREMER_AIRGAP=1 so that child
    processes can install the same guard.
    """
    _allowed.clear()
    _allowed.update(resolve_permitted_addresses(hosts))

    def connect(self, address):
        check(address)
        return _original_connect(self, address)

    def connect_ex(self, address):
        check(address)
        return _original_connect_ex(self, address)

    socket.socket.connect = connect  # type: ignore[method-assign]
    socket.socket.connect_ex = connect_ex  # type: ignore[method-assign]
    os.environ[ENV_FLAG] = "1"
    return set(_allowed)


def unblock_egress() -> None:
    """Restore the real connect() (tests only)."""
    socket.socket.connect = _original_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _original_connect_ex  # type: ignore[method-assign]
    _allowed.clear()
    os.environ.pop(ENV_FLAG, None)


def is_active() -> bool:
    return socket.socket.connect is not _original_connect


def requested() -> bool:
    return os.environ.get(ENV_FLAG, "").strip() in {"1", "true", "yes"}


def install_if_requested() -> bool:
    """Install the guard when OUTREMER_AIRGAP=1; True when it is in force."""
    if requested() and not is_active():
        block_egress()
    return is_active()
