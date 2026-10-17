"""#131: the morning healthcheck judges the MCP server's /health body.

Runs only the MCP block of deploy/tei/healthcheck.sh against a local HTTP
server, so each verdict is the one the script would print on tei.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "tei" / "healthcheck.sh"


def _mcp_block() -> str:
    text = SCRIPT.read_text()
    start = text.index("MCP_LOCAL=")
    end = text.index('if [ -n "$FAILS" ]; then')
    return text[start:end]


def _serve(body: dict | str, code: int = 200):
    payload = (body if isinstance(body, str) else json.dumps(body)).encode()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/health"


def _fails(local_url: str, public_url: str) -> str:
    script = 'FAILS=""\n' + _mcp_block() + 'echo "$FAILS"\n'
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
           "OUTREMER_MCP_HEALTH": local_url, "OUTREMER_MCP_PUBLIC_HEALTH": public_url}
    out = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, check=True)
    return out.stdout.strip()


GOOD = {"status": "ok", "records": 143, "documents": 3, "withheld": 0,
        "run_at": "2026-10-16T01:50:10+00:00", "gate": "pass"}


def test_a_healthy_server_raises_nothing():
    srv, url = _serve(GOOD)
    try:
        assert _fails(url, url) == ""
    finally:
        srv.shutdown()


@pytest.mark.parametrize("body,expected", [
    (dict(GOOD, withheld=3), "withheld=3"),
    (dict(GOOD, gate="fail"), "gate=fail"),
    (dict(GOOD, records=0), "records=0"),
    ("not json", "unreadable"),
])
def test_a_bad_body_is_named(body, expected):
    srv, url = _serve(body)
    try:
        fails = _fails(url, url)
        assert f"mcp-local({expected})" in fails and f"mcp-public({expected})" in fails
    finally:
        srv.shutdown()


def test_a_missing_nginx_route_reports_its_status():
    good, gurl = _serve(GOOD)
    missing, murl = _serve("<html>404</html>", code=404)
    try:
        assert _fails(gurl, murl) == "mcp-public=HTTP404;"
    finally:
        good.shutdown()
        missing.shutdown()


def test_an_unreachable_server_is_named():
    fails = _fails("http://127.0.0.1:9/health", "http://127.0.0.1:9/health")
    assert re.search(r"mcp-local\((unreachable|unreadable)\)", fails)
    assert "mcp-public=HTTP000;" in fails
