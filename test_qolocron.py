#!/usr/bin/env python3
"""Tests for the Qolocron archival sink (qolocron.py) and its wiring
into the sovereign node engine.

Covers: hex<->trit round-trips, archive-on-etch, hash->address lookup,
idempotent archive, archive failure -> loud backlog (vow stays etched),
backlog retry, persistence across restarts, tampered archive detected
fail-closed, the enclave POST path archiving, and the `sink` CLI.
Stdlib only, plain style like the other suites.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import urllib.error
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from axoneme_sovereign_node import (
    AxonemeSovereignNode,
    main,
    EXIT_OK,
    EXIT_ERROR,
)
from qolocron import (
    QolocronArchive,
    QolocronCorruptError,
    QolocronError,
    TRITS_PER_HASH,
    hex_to_trits,
    trits_to_hex,
)
from enclave import EnclaveServer

PASS = []


def check(name, fn):
    fn()
    PASS.append(name)
    print(f"PASS: {name}")


def make_paths():
    tmp = tempfile.mkdtemp()
    return tmp, os.path.join(tmp, "n.ledger.jsonl"), os.path.join(
        tmp, "n.qolocron.jsonl")


def make_node():
    tmp, ledger, qolocron = make_paths()
    node = AxonemeSovereignNode("JOR-EL", ledger_path=ledger,
                                qolocron_path=qolocron)
    return node, tmp, ledger, qolocron


def quiet(fn, *args, **kwargs):
    buf = io.StringIO()
    with redirect_stdout(buf):
        return fn(*args, **kwargs)


def test_trit_encoding_round_trips():
    assert TRITS_PER_HASH == 162
    for digest in ("00" * 32, "ff" * 32,
                   "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"):
        trits = hex_to_trits(digest)
        assert len(trits) == TRITS_PER_HASH
        assert all(t in (0, 1, 2) for t in trits)
        assert trits_to_hex(trits) == digest
    # all-zero digest -> all-smectic; all-f -> non-trivial pattern
    assert set(hex_to_trits("00" * 32)) == {0}
    assert len(set(hex_to_trits("ff" * 32))) > 1


def test_trit_encoding_rejects_garbage():
    for bad in ("", "zz" * 32, "ab" * 31, None, 12345):
        try:
            hex_to_trits(bad)
        except QolocronError:
            continue
        raise AssertionError(f"accepted garbage digest: {bad!r}")


def test_archive_on_etch_and_lookup():
    node, tmp, _, _ = make_node()
    try:
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert node.register_vow(100000.0, 50000.0, 155.0) is True
        vow_hash = node.ledger.records[0]["vow_hash"]
        record = node.qolocron.lookup(vow_hash)
        assert record is not None
        assert record["vow_hash"] == vow_hash
        assert record["seq"] == 1 and record["addr"] == 0
        assert len(record["trits"]) == TRITS_PER_HASH
        assert trits_to_hex([int(c) for c in record["trits"]]) == vow_hash
        assert node.verify_sink() is True
        assert "Qolocron" in buf.getvalue()  # the sink announces itself
    finally:
        shutil.rmtree(tmp)


def test_archive_is_idempotent():
    node, tmp, _, _ = make_node()
    try:
        quiet(node.register_vow, 100000.0, 50000.0, 155.0)
        vow_hash = node.ledger.records[0]["vow_hash"]
        first = node.qolocron.archive(vow_hash)
        second = node.qolocron.archive(vow_hash)
        assert first["seq"] == second["seq"] == 1
        assert len(node.qolocron.index) == 1
    finally:
        shutil.rmtree(tmp)


def test_lookup_miss_returns_none():
    node, tmp, _, _ = make_node()
    try:
        assert node.qolocron.lookup("ab" * 32) is None
        assert node.qolocron.lookup(None) is None
    finally:
        shutil.rmtree(tmp)


def test_archive_failure_backlogs_loudly_vow_stays_etched():
    node, tmp, _, _ = make_node()
    try:
        # Simulate a dead sink: the append itself raises.
        def boom(body):
            raise OSError("simulated sink outage")
        node.qolocron._append_line = boom
        buf = io.StringIO()
        with redirect_stdout(buf):
            accepted = node.register_vow(100000.0, 50000.0, 155.0)
        # The vow is NOT un-etched: etch succeeded, sink failed.
        assert accepted is True
        assert len(node.ledger.records) == 1
        assert node.treasury_qq == 155.0
        # The failure is NOT silent: loud log + backlog entry.
        assert "QOLOCRON ARCHIVE FAILURE" in buf.getvalue()
        pending = node.qolocron.backlog()
        assert len(pending) == 1
        assert pending[0]["vow_hash"] == node.ledger.records[0]["vow_hash"]
        assert "simulated sink outage" in pending[0]["error"]
    finally:
        shutil.rmtree(tmp)


def test_backlog_retry_drains_on_recovery():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "r.qolocron.jsonl")
        archive = QolocronArchive(path)
        archive.note_failure("ab" * 32, "simulated outage")
        archive.note_failure("cd" * 32, "simulated outage")
        assert len(archive.backlog()) == 2
        attempted, archived = archive.retry_backlog()
        assert (attempted, archived) == (2, 2)
        assert archive.backlog() == []
        assert archive.lookup("ab" * 32)["seq"] == 1
        assert archive.lookup("cd" * 32)["seq"] == 2
        assert archive.verify_archive() is True
    finally:
        shutil.rmtree(tmp)


def test_archive_persists_across_restarts():
    node, tmp, _, qolocron = make_node()
    try:
        quiet(node.register_vow, 100000.0, 50000.0, 155.0)
        quiet(node.register_vow, 200000.0, 100000.0, 300.0)
        hashes = [r["vow_hash"] for r in node.ledger.records]
        archive2 = QolocronArchive(qolocron)
        for i, vow_hash in enumerate(hashes):
            record = archive2.lookup(vow_hash)
            assert record is not None
            assert record["seq"] == i + 1
            assert record["addr"] == i * TRITS_PER_HASH
        assert archive2.verify_archive() is True
        # And through a restarted node: same map, no re-archive.
        node2 = AxonemeSovereignNode(
            "JOR-EL", ledger_path=os.path.join(tmp, "n.ledger.jsonl"),
            qolocron_path=qolocron)
        assert len(node2.qolocron.index) == 2
        assert node2.verify_sink() is True
    finally:
        shutil.rmtree(tmp)


def test_tampered_archive_refuses_startup():
    node, tmp, _, qolocron = make_node()
    try:
        quiet(node.register_vow, 100000.0, 50000.0, 155.0)
        with open(qolocron, "r+", encoding="utf-8") as handle:
            content = handle.read()
            tampered = content.replace("archived_at", "archived_XX", 1)
            assert tampered != content
            handle.seek(0)
            handle.write(tampered)
            handle.truncate()
        try:
            QolocronArchive(qolocron)
        except QolocronCorruptError:
            return
        raise AssertionError("tampered archive loaded without error")
    finally:
        shutil.rmtree(tmp)


def test_enclave_post_path_archives():
    node, tmp, _, _ = make_node()
    srv = EnclaveServer(node).start()
    try:
        req = urllib.request.Request(
            srv.url + "/vow",
            data=json.dumps({"qira_reserve": 100000.0,
                             "qash_liquidity": 50000.0,
                             "qq_consumed": 155.0}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        with redirect_stdout(io.StringIO()):
            with urllib.request.urlopen(req) as resp:
                body = json.loads(resp.read().decode())
        assert resp.status == 200 and body["accepted"] is True
        assert node.qolocron.lookup(body["vow_hash"]) is not None
    finally:
        srv.stop()
        shutil.rmtree(tmp)


def test_cli_sink_commands():
    tmp, ledger, qolocron = make_paths()
    try:
        base = ["--node-id", "JOR-EL", "--ledger", ledger,
                "--qolocron", qolocron]
        assert quiet(main, base + ["vow", "--qira", "1000", "--qash", "1000",
                                   "--toll", "2"]) == EXIT_OK
        assert quiet(main, base + ["sink"]) == EXIT_OK
        assert quiet(main, base + ["sink", "--verify"]) == EXIT_OK
        vow_hash = AxonemeSovereignNode(
            "JOR-EL", ledger_path=ledger,
            qolocron_path=qolocron).ledger.records[0]["vow_hash"]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(base + ["sink", "--lookup", vow_hash])
        assert code == EXIT_OK and vow_hash in buf.getvalue()
        assert quiet(main, base + ["sink", "--lookup", "ab" * 32]) == EXIT_ERROR
        assert quiet(main, base + ["sink", "--retry"]) == EXIT_OK
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    check("trit encoding round-trips", test_trit_encoding_round_trips)
    check("trit encoding rejects garbage", test_trit_encoding_rejects_garbage)
    check("archive-on-etch and lookup", test_archive_on_etch_and_lookup)
    check("archive is idempotent", test_archive_is_idempotent)
    check("lookup miss returns None", test_lookup_miss_returns_none)
    check("archive failure backlogs loudly, vow stays etched",
          test_archive_failure_backlogs_loudly_vow_stays_etched)
    check("backlog retry drains on recovery",
          test_backlog_retry_drains_on_recovery)
    check("archive persists across restarts",
          test_archive_persists_across_restarts)
    check("tampered archive refuses startup",
          test_tampered_archive_refuses_startup)
    check("enclave POST path archives", test_enclave_post_path_archives)
    check("CLI sink commands", test_cli_sink_commands)
    print(f"\n{len(PASS)}/{len(PASS)} qolocron tests green")
