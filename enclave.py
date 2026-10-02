#!/usr/bin/env python3
"""JOR-EL inner enclave — the lower-level tier.

A loopback-only HTTP service fronting the sovereign node. It binds
127.0.0.1 exclusively: the enclave never listens on an external
interface. The outer tier (Tor onion service, see tor_front.py) is the
only path in from outside — that binding is the "quantum-entanglement"
[Coinage: Johnathan "Qasparr (Κασπάρρ)" Monroe].

Endpoints (all JSON):
  GET  /status            node state, chain validity, onion address (if any)
  POST /vow               {qira_reserve, qash_liquidity, qq_consumed}
                         -> 200 accepted | 402 toll insufficient
                         (accepted vows are also piped to the Qolocron sink)
  GET  /tip               latest record {seq, vow_hash} (for future P2P sync)
  GET  /vow?hash=<hex>    one record | 404 unknown

Standard library only. Not yet: authentication (step: node identity),
rate limiting, P2P gossip.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


def _json(handler, code, obj):
    body = json.dumps(obj).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class _Handler(BaseHTTPRequestHandler):
    server_version = "JorEl-Enclave/0.1"

    def log_message(self, *args):  # keep test output clean
        pass

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if not length:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def do_GET(self):
        node = self.server.node
        parsed = urlparse(self.path)
        if parsed.path == "/status":
            records = node.ledger.records
            _json(self, 200, {
                "node_id": node.node_id,
                "engine": "JOR-EL",
                "vows": len(records),
                "treasury_qq": node.treasury_qq,
                "chain_valid": node.ledger.verify_chain(),
                "tip": records[-1]["vow_hash"] if records else None,
                "onion": getattr(self.server, "onion", None),
            })
        elif parsed.path == "/tip":
            records = node.ledger.records
            if not records:
                _json(self, 404, {"error": "no vows etched yet"})
            else:
                _json(self, 200, {
                    "seq": records[-1]["seq"],
                    "vow_hash": records[-1]["vow_hash"],
                })
        elif parsed.path == "/vow":
            want = parse_qs(parsed.query).get("hash", [None])[0]
            found = next(
                (r for r in node.ledger.records if r["vow_hash"] == want), None
            )
            if found is None:
                _json(self, 404, {"error": "unknown vow hash"})
            else:
                _json(self, 200, found)
        else:
            _json(self, 404, {"error": "unknown endpoint"})

    def do_POST(self):
        node = self.server.node
        if urlparse(self.path).path != "/vow":
            _json(self, 404, {"error": "unknown endpoint"})
            return
        data = self._read_json()
        if not isinstance(data, dict):
            _json(self, 400, {"error": "JSON object required"})
            return
        try:
            qira = float(data["qira_reserve"])
            qash = float(data["qash_liquidity"])
            toll = float(data["qq_consumed"])
        except (KeyError, TypeError, ValueError):
            _json(self, 400, {
                "error": "fields required: qira_reserve, qash_liquidity, qq_consumed"
            })
            return
        required = node.toll_required(qira, qash)
        if toll < required:
            # 402 Payment Required: the toll is the price of admission.
            _json(self, 402, {
                "accepted": False,
                "required": required,
                "provided": toll,
            })
            return
        body = {
            "node_id": node.node_id,
            "qira_reserve": qira,
            "qash_liquidity": qash,
            "qq_consumed": toll,
            "status": "ETCHED_AMORAL_ANCHORAGE",
        }
        import datetime
        body["timestamp"] = datetime.datetime.now(
            datetime.timezone.utc).isoformat()
        record = node.ledger.append(body)
        node.treasury_qq += toll
        node.archive_vow(record["vow_hash"])
        _json(self, 200, {
            "accepted": True,
            "seq": record["seq"],
            "vow_hash": record["vow_hash"],
        })


class EnclaveServer:
    """Loopback-only HTTP front for a node. Non-loopback hosts refused."""

    def __init__(self, node, host="127.0.0.1", port=0):
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise ValueError(
                f"enclave binds loopback only; refused host {host!r}"
            )
        self._httpd = ThreadingHTTPServer((host, port), _Handler)
        self._httpd.node = node
        self._httpd.onion = None
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, daemon=True
        )

    @property
    def url(self):
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def set_onion(self, onion_address):
        """Record the outer-tier address (set by tor_front after provision)."""
        self._httpd.onion = onion_address

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
