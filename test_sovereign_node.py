#!/usr/bin/env python3
"""Tests for the rewritten JOR-EL sovereign node engine.

Covers the toll rule, accept/reject paths, fail-closed amount
validation, persistence across restarts, chain verification, the
tamper-eviction path, and the CLI exit codes. Stdlib only.
"""
import io
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from axoneme_sovereign_node import (
    AxonemeSovereignNode,
    main,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_REJECTED,
)
from ledger import LedgerCorruptError

PASS = []


def check(name, fn):
    fn()
    PASS.append(name)
    print(f"PASS: {name}")


def make_node():
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "node.ledger.jsonl")
    qpath = os.path.join(tmp, "node.qolocron.jsonl")
    node = AxonemeSovereignNode("JOR-EL", ledger_path=path, qolocron_path=qpath)
    return node, tmp, path


def quiet(fn, *args, **kwargs):
    buf = io.StringIO()
    with redirect_stdout(buf):
        return fn(*args, **kwargs)


def test_toll_rule_single_source():
    # 1 $QQ per 1000 staked — the rule enclave.py also reads.
    assert AxonemeSovereignNode.toll_required(100000.0, 50000.0) == 150.0
    assert AxonemeSovereignNode.toll_required(0.0, 0.0) == 0.0


def test_vow_accepted_at_exact_toll():
    node, tmp, _ = make_node()
    try:
        assert quiet(node.register_vow, 100000.0, 50000.0, 150.0) is True
        assert len(node.ledger.records) == 1
        assert node.treasury_qq == 150.0
        assert node.verify() is True
    finally:
        shutil.rmtree(tmp)


def test_vow_rejected_when_toll_short():
    node, tmp, _ = make_node()
    try:
        assert quiet(node.register_vow, 100000.0, 50000.0, 149.99) is False
        assert len(node.ledger.records) == 0
        assert node.treasury_qq == 0.0
    finally:
        shutil.rmtree(tmp)


def test_vow_rejects_negative_stake():
    node, tmp, _ = make_node()
    try:
        assert quiet(node.register_vow, -100.0, 50.0, 0.0) is False
        assert quiet(node.register_vow, 100.0, 50.0, -1.0) is False
        assert len(node.ledger.records) == 0
    finally:
        shutil.rmtree(tmp)


def test_vow_rejects_nan_and_inf():
    node, tmp, _ = make_node()
    try:
        nan = float("nan")
        inf = float("inf")
        assert quiet(node.register_vow, nan, 50.0, 10.0) is False
        assert quiet(node.register_vow, 100.0, 50.0, inf) is False
        assert len(node.ledger.records) == 0
    finally:
        shutil.rmtree(tmp)


def test_treasury_replayed_from_disk():
    node, tmp, path = make_node()
    try:
        quiet(node.register_vow, 100000.0, 50000.0, 155.0)
        quiet(node.register_vow, 200000.0, 100000.0, 300.0)
        node2 = AxonemeSovereignNode(
            "JOR-EL", ledger_path=path,
            qolocron_path=os.path.join(tmp, "node.qolocron.jsonl"))
        assert node2.treasury_qq == 455.0
        assert len(node2.ledger.records) == 2
        assert node2.verify() is True
    finally:
        shutil.rmtree(tmp)


def test_tampered_ledger_refuses_startup():
    node, tmp, path = make_node()
    try:
        quiet(node.register_vow, 100000.0, 50000.0, 155.0)
        with open(path, "r+", encoding="utf-8") as handle:
            lines = handle.readlines()
            lines[0] = lines[0].replace("ETCHED_AMORAL_ANCHORAGE", "FORGED")
            handle.seek(0)
            handle.writelines(lines)
            handle.truncate()
        try:
            AxonemeSovereignNode(
                "JOR-EL", ledger_path=path,
                qolocron_path=os.path.join(tmp, "node.qolocron.jsonl"))
        except LedgerCorruptError:
            return
        raise AssertionError("tampered ledger was loaded without error")
    finally:
        shutil.rmtree(tmp)


def test_cli_vow_accept_exit_code():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "cli.ledger.jsonl")
        argv = ["--node-id", "JOR-EL", "--ledger", path,
                "--qolocron", os.path.join(tmp, "cli.qolocron.jsonl"),
                "vow", "--qira", "100000", "--qash", "50000", "--toll", "155"]
        assert quiet(main, argv) == EXIT_OK
    finally:
        shutil.rmtree(tmp)


def test_cli_vow_reject_exit_code():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "cli.ledger.jsonl")
        argv = ["--node-id", "JOR-EL", "--ledger", path,
                "--qolocron", os.path.join(tmp, "cli.qolocron.jsonl"),
                "vow", "--qira", "100000", "--qash", "50000", "--toll", "1"]
        assert quiet(main, argv) == EXIT_REJECTED
    finally:
        shutil.rmtree(tmp)


def test_cli_verify_and_treasury():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "cli.ledger.jsonl")
        base = ["--node-id", "JOR-EL", "--ledger", path,
                "--qolocron", os.path.join(tmp, "cli.qolocron.jsonl")]
        assert quiet(main, base + ["vow", "--qira", "1000",
                                   "--qash", "1000", "--toll", "2"]) == EXIT_OK
        assert quiet(main, base + ["verify"]) == EXIT_OK
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(base + ["treasury"])
        assert code == EXIT_OK
        assert buf.getvalue().strip() == "2.0"
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    check("toll rule single-sourced", test_toll_rule_single_source)
    check("vow accepted at exact toll", test_vow_accepted_at_exact_toll)
    check("vow rejected when toll short", test_vow_rejected_when_toll_short)
    check("vow rejects negative stake", test_vow_rejects_negative_stake)
    check("vow rejects NaN and inf", test_vow_rejects_nan_and_inf)
    check("treasury replayed from disk", test_treasury_replayed_from_disk)
    check("tampered ledger refuses startup",
          test_tampered_ledger_refuses_startup)
    check("CLI vow accept exit 0", test_cli_vow_accept_exit_code)
    check("CLI vow reject exit 2", test_cli_vow_reject_exit_code)
    check("CLI verify and treasury", test_cli_verify_and_treasury)
    print(f"\n{len(PASS)}/{len(PASS)} node engine tests green")
