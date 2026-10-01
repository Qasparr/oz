#!/usr/bin/env python3
"""Tests for the JOR-EL persistent ledger (pioneer build, step 1).

Covers: acceptance, rejection, persistence across restarts, hash-chain
linking, tamper detection (fail-closed load), malformed-line handling,
and immediate durability (fsync per etch).
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from axoneme_sovereign_node import AxonemeSovereignNode
from ledger import AppendOnlyLedger, LedgerCorruptError

PASS = []


def check(name, fn):
    fn()
    PASS.append(name)
    print(f"PASS: {name}")


def fresh_path():
    fd, path = tempfile.mkstemp(suffix=".ledger.jsonl")
    os.close(fd)
    os.unlink(path)  # ledger must create it itself
    return path


def test_acceptance():
    path = fresh_path()
    node = AxonemeSovereignNode("JOR-EL", ledger_path=path)
    assert node.register_vow(100000.0, 50000.0, 155.0) is True
    assert len(node.ledger.records) == 1
    assert node.treasury_qq == 155.0


def test_rejection_records_nothing():
    path = fresh_path()
    node = AxonemeSovereignNode("JOR-EL", ledger_path=path)
    assert node.register_vow(200000.0, 100000.0, 250.0) is False  # needs 300
    assert len(node.ledger.records) == 0
    assert node.treasury_qq == 0.0
    assert not os.path.exists(path) or os.path.getsize(path) == 0


def test_persistence_across_restart():
    path = fresh_path()
    node = AxonemeSovereignNode("JOR-EL", ledger_path=path)
    node.register_vow(100000.0, 50000.0, 155.0)
    node.register_vow(200000.0, 100000.0, 300.0)
    del node
    node2 = AxonemeSovereignNode("JOR-EL", ledger_path=path)
    assert len(node2.ledger.records) == 2
    assert node2.treasury_qq == 455.0
    assert node2.ledger.records[0]["seq"] == 1
    assert node2.ledger.records[1]["seq"] == 2


def test_chain_links():
    path = fresh_path()
    node = AxonemeSovereignNode("JOR-EL", ledger_path=path)
    node.register_vow(100000.0, 50000.0, 155.0)
    node.register_vow(100000.0, 50000.0, 160.0)
    r1, r2 = node.ledger.records
    assert r1["prev_hash"] == "GENESIS"
    assert r2["prev_hash"] == r1["vow_hash"]
    assert node.ledger.verify_chain() is True


def test_tamper_detected_fail_closed():
    path = fresh_path()
    node = AxonemeSovereignNode("JOR-EL", ledger_path=path)
    node.register_vow(100000.0, 50000.0, 155.0)
    with open(path, "r+", encoding="utf-8") as handle:
        content = handle.read().replace("100000.0", "999999.0")
        handle.seek(0)
        handle.write(content)
        handle.truncate()
    try:
        AppendOnlyLedger(path)
    except LedgerCorruptError as exc:
        assert "vow_hash mismatch" in str(exc)
    else:
        raise AssertionError("tampered ledger loaded without error")


def test_malformed_line_fail_closed():
    path = fresh_path()
    with open(path, "w", encoding="utf-8") as handle:
        handle.write('{"this is": "not a vow record"}\n')
    try:
        AppendOnlyLedger(path)
    except LedgerCorruptError as exc:
        assert "malformed vow record" in str(exc)
    else:
        raise AssertionError("malformed ledger loaded without error")


def test_durable_without_close():
    path = fresh_path()
    ledger = AppendOnlyLedger(path)
    ledger.append({"node_id": "JOR-EL", "probe": True})
    # No close/flush by us: the etch itself must have hit disk.
    with open(path, "r", encoding="utf-8") as handle:
        assert '"probe":true' in handle.read().replace(" ", "")


if __name__ == "__main__":
    check("acceptance", test_acceptance)
    check("rejection records nothing", test_rejection_records_nothing)
    check("persistence across restart", test_persistence_across_restart)
    check("chain links", test_chain_links)
    check("tamper detected, fail-closed", test_tamper_detected_fail_closed)
    check("malformed line, fail-closed", test_malformed_line_fail_closed)
    check("durable without close (fsync per etch)", test_durable_without_close)
    print(f"\n{PASS.__len__()}/{PASS.__len__()} tests passed.")
