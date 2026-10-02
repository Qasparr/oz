#!/usr/bin/env python3
"""Tests for the JOR-EL inner enclave (loopback HTTP) and the Tor front's
failure modes. The live onion provisioning is NOT part of this suite —
it needs a tor binary and Tor network access; run it by hand and report
honestly (see README §VIII).
"""
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from axoneme_sovereign_node import AxonemeSovereignNode
from enclave import EnclaveServer
from tor_front import OnionFront, TorNotAvailable, find_tor

PASS = []


def check(name, fn):
    fn()
    PASS.append(name)
    print(f"PASS: {name}")


def make_node():
    tmp = tempfile.mkdtemp()
    ledger = os.path.join(tmp, "t.ledger.jsonl")
    qolocron = os.path.join(tmp, "t.qolocron.jsonl")
    return AxonemeSovereignNode("JOR-EL", ledger_path=ledger,
                                qolocron_path=qolocron), tmp


def get(server, path):
    with urllib.request.urlopen(server.url + path) as resp:
        return resp.status, json.loads(resp.read().decode())


def post(server, path, obj):
    req = urllib.request.Request(
        server.url + path,
        data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def test_status_reflects_node():
    node, _ = make_node()
    srv = EnclaveServer(node).start()
    try:
        code, body = get(srv, "/status")
        assert code == 200
        assert body["node_id"] == "JOR-EL"
        assert body["engine"] == "JOR-EL"
        assert body["vows"] == 0 and body["chain_valid"] is True
    finally:
        srv.stop()


def test_vow_accepted_over_http():
    node, _ = make_node()
    srv = EnclaveServer(node).start()
    try:
        code, body = post(srv, "/vow", {
            "qira_reserve": 100000.0,
            "qash_liquidity": 50000.0,
            "qq_consumed": 155.0,
        })
        assert code == 200 and body["accepted"] is True
        assert body["seq"] == 1 and len(body["vow_hash"]) == 64
        _, status = get(srv, "/status")
        assert status["vows"] == 1 and status["treasury_qq"] == 155.0
    finally:
        srv.stop()


def test_vow_rejected_402_when_toll_short():
    node, _ = make_node()
    srv = EnclaveServer(node).start()
    try:
        code, body = post(srv, "/vow", {
            "qira_reserve": 200000.0,
            "qash_liquidity": 100000.0,
            "qq_consumed": 250.0,  # needs 300
        })
        assert code == 402 and body["accepted"] is False
        assert body["required"] == 300.0
        _, status = get(srv, "/status")
        assert status["vows"] == 0
    finally:
        srv.stop()


def test_tip_and_lookup_roundtrip():
    node, _ = make_node()
    srv = EnclaveServer(node).start()
    try:
        post(srv, "/vow", {"qira_reserve": 1000.0,
                           "qash_liquidity": 1000.0, "qq_consumed": 5.0})
        _, tip = get(srv, "/tip")
        assert tip["seq"] == 1
        _, rec = get(srv, "/vow?hash=" + tip["vow_hash"])
        assert rec["vow_hash"] == tip["vow_hash"]
        try:
            get(srv, "/vow?hash=" + "0" * 64)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("unknown hash did not 404")
    finally:
        srv.stop()


def test_loopback_only():
    node, _ = make_node()
    srv = EnclaveServer(node)
    host, _ = srv._httpd.server_address[:2]
    assert host == "127.0.0.1", f"bound to {host}, want loopback"
    try:
        EnclaveServer(node, host="0.0.0.0")
    except ValueError as exc:
        assert "loopback only" in str(exc)
    else:
        raise AssertionError("non-loopback bind was not refused")


def test_tor_missing_is_a_clean_error():
    real_which = shutil.which
    shutil.which = lambda *a, **k: None
    try:
        try:
            find_tor()
        except TorNotAvailable as exc:
            assert "tor binary not found" in str(exc)
        else:
            raise AssertionError("missing tor did not raise")
    finally:
        shutil.which = real_which


def test_provision_timeout_is_a_clean_error(tmp_bin=None):
    # A fake tor that never writes a hostname file.
    tmp = tempfile.mkdtemp()
    fake = os.path.join(tmp, "tor")
    with open(fake, "w") as handle:
        handle.write("#!/bin/sh\nsleep 60\n")
    os.chmod(fake, 0o755)
    front = OnionFront(os.path.join(tmp, "svc"), 18081, tor_bin=fake)
    try:
        front.provision(timeout=3)
    except TorNotAvailable as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("hung tor did not time out cleanly")
    finally:
        front.shutdown()


if __name__ == "__main__":
    check("status reflects node", test_status_reflects_node)
    check("vow accepted over HTTP", test_vow_accepted_over_http)
    check("vow rejected 402 when toll short",
          test_vow_rejected_402_when_toll_short)
    check("tip and lookup roundtrip", test_tip_and_lookup_roundtrip)
    check("loopback only", test_loopback_only)
    check("tor missing is a clean error", test_tor_missing_is_a_clean_error)
    check("provision timeout is a clean error",
          test_provision_timeout_is_a_clean_error)
    print(f"\n{len(PASS)}/{len(PASS)} tests passed.")
