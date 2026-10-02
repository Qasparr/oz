#!/usr/bin/env python3
"""Axoneme Protocol — Sovereign Node Engine (JOR-EL).

Terminal engine for Zero-Trust vow registration and $QQ kinetic-toll
validation. Vows persist to an append-only JSONL ledger (fsync'd per
etch, hash-chained, fail-closed on corruption); the node replays its
treasury from disk on every start.

Architect: Johnathan 'Qasparr' Monroe (Κασπάρρ).
Source: architect-supplied draft PDF ("Let's draft the Python sovereign
node engine…"), rewritten 2026-10-02 from the pioneer sketch into the
real engine. The sketch's logic is preserved; the demo-only `__main__`
is replaced by a proper CLI.

Stable interface (used by enclave.py and the test suites):
    AxonemeSovereignNode(node_id, ledger_path="jorel.ledger.jsonl",
                         qolocron_path="jorel.qolocron.jsonl")
    .toll_required(qira_stake, qash_stake) -> float   # static, single source
    .register_vow(qira_stake, qash_stake, qq_toll) -> bool
    .archive_vow(vow_hash) -> bool   # True archived, False backlogged
    .verify() -> bool                # ledger chain
    .verify_sink() -> bool           # qolocron archive
    .ledger, .qolocron, .treasury_qq, .node_id
    .display_dashboard(), .log_status()

The Qolocron sink: every etched vow's vow_hash is archived to tri-state
storage (qolocron.py) as a post-etch step. Archive failure never
un-etches the vow and never stays silent: it is logged loudly and the
hash lands in the retry backlog. (Architect's ruling, 2026-10-02: wire
the sink — the draft PDF's open question is closed.)

CLI:
    node vow --qira 100000 --qash 50000 --toll 155
    node dashboard | node verify | node treasury
    node sink [--verify | --retry | --lookup HASH]
    node serve [--port 0]

Exit codes: 0 ok · 1 error/chain broken · 2 vow rejected (toll short
or invalid stakes).

Standard library only. Not yet: proof-of-work difficulty, node keypair
identity, P2P gossip (per the architect's build order: onion, then
P2P, then difficulty, then identity).
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

from ledger import AppendOnlyLedger, LedgerCorruptError
from qolocron import QolocronArchive, QolocronCorruptError

DEFAULT_NODE_ID = "JOR-EL"
DEFAULT_LEDGER = "jorel.ledger.jsonl"
DEFAULT_QOLOCRON = "jorel.qolocron.jsonl"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REJECTED = 2


class AxonemeSovereignNode:
    def __init__(self, node_id: str = DEFAULT_NODE_ID,
                 ledger_path: str = DEFAULT_LEDGER,
                 qolocron_path: str = DEFAULT_QOLOCRON):
        self.node_id = node_id
        # Fail-closed: a tampered ledger OR archive raises here; the node
        # never starts on a corrupt store.
        self.ledger = AppendOnlyLedger(ledger_path)
        self.qolocron = QolocronArchive(qolocron_path)
        self.treasury_qq = sum(r["qq_consumed"] for r in self.ledger.records)

    def log_status(self, message: str):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        print(f"[{timestamp}] [AXONEME-NODE:{self.node_id}] {message}")

    @staticmethod
    def toll_required(qira_stake: float, qash_stake: float) -> float:
        """Single source of the kinetic toll rule: 1 $QQ per 1000 staked."""
        return (qira_stake + qash_stake) / 1000.0

    @staticmethod
    def _valid_amounts(qira_stake, qash_stake, qq_toll) -> bool:
        """Fail-closed: every amount must be a finite number >= 0."""
        for amount in (qira_stake, qash_stake, qq_toll):
            if not isinstance(amount, (int, float)) or not math.isfinite(amount):
                return False
            if amount < 0:
                return False
        return True

    def register_vow(self, qira_stake: float, qash_stake: float,
                     qq_toll: float) -> bool:
        self.log_status("Initiating Exchange of Vows validation...")
        if not self._valid_amounts(qira_stake, qash_stake, qq_toll):
            self.log_status(
                "REJECTED: amounts must be finite numbers >= 0 "
                f"(qira={qira_stake}, qash={qash_stake}, toll={qq_toll})"
            )
            return False
        required_toll = self.toll_required(qira_stake, qash_stake)
        if qq_toll < required_toll:
            self.log_status(
                f"REJECTED: Insufficient $QQ mass. Provided: {qq_toll}, "
                f"Required: {required_toll}"
            )
            return False
        body = {
            "node_id": self.node_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "qira_reserve": qira_stake,
            "qash_liquidity": qash_stake,
            "qq_consumed": qq_toll,
            "status": "ETCHED_AMORAL_ANCHORAGE",
        }
        vow_record = self.ledger.append(body)
        self.treasury_qq += qq_toll
        self.log_status("SUCCESS: Vow etched to persistent ledger.")
        print(json.dumps(vow_record, indent=4))
        # Post-etch sink: the vow is etched regardless of what follows.
        self.archive_vow(vow_record["vow_hash"])
        return True

    def archive_vow(self, vow_hash: str) -> bool:
        """Pipe one etched vow_hash into the Qolocron sink.

        Returns True when archived. On failure the vow is NOT un-etched
        and the failure is NOT silent: it is logged loudly and the hash
        is recorded in the retry backlog. A dead backlog file is the
        last resort that still shouts — stderr, never swallowed.
        """
        try:
            record = self.qolocron.archive(vow_hash)
        except Exception as exc:  # noqa: BLE001 — the sink must not kill etch
            self.log_status(
                f"QOLOCRON ARCHIVE FAILURE for {vow_hash[:16]}…: {exc} — "
                "vow remains etched; hash recorded in retry backlog.")
            try:
                self.qolocron.note_failure(vow_hash, exc)
            except Exception as back_exc:  # noqa: BLE001
                print(f"QOLOCRON BACKLOG FAILURE for {vow_hash[:16]}…: "
                      f"{back_exc} — manual recovery required.",
                      file=sys.stderr)
            return False
        self.log_status(
            f"Vow archived to Qolocron (seq {record['seq']}, "
            f"addr {record['addr']}).")
        return True

    def verify(self) -> bool:
        """True iff the ledger's hash chain is intact."""
        return self.ledger.verify_chain()

    def verify_sink(self) -> bool:
        """True iff the Qolocron archive re-derives clean."""
        return self.qolocron.verify_archive()

    def display_dashboard(self):
        chain = "VALID" if self.verify() else "BROKEN"
        print("\n" + "=" * 50)
        print(" The Wizard, in the Emerald City of Oz, at the Crystal Palace.")
        print(f" AXONEME PROTOCOL TERMINAL DASHBOARD (Node: {self.node_id})")
        print("=" * 50)
        print(f" Total Registered Vows: {len(self.ledger.records)}")
        print(f" Accumulated $QQ Treasury: {self.treasury_qq}")
        print(f" Ledger File: {self.ledger.path} (chain {chain})")
        sink = "VALID" if self.verify_sink() else "BROKEN"
        pending = len(self.qolocron.backlog())
        print(f" Qolocron Sink: {self.qolocron.path} "
              f"({len(self.qolocron.index)} archived, {sink}, "
              f"{pending} backlogged)")
        print(" Qrystal Palace Enclave State: ONLINE (POPE Secured)")
        print("=" * 50 + "\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sovereign-node",
        description="JOR-EL sovereign node engine: vow registration, "
                    "ledger dashboard, enclave service.",
    )
    parser.add_argument("--node-id", default=os.environ.get(
        "AXONEME_NODE_ID", DEFAULT_NODE_ID))
    parser.add_argument("--ledger", default=os.environ.get(
        "AXONEME_LEDGER", DEFAULT_LEDGER))
    parser.add_argument("--qolocron", default=os.environ.get(
        "AXONEME_QOLOCRON", DEFAULT_QOLOCRON))
    sub = parser.add_subparsers(dest="command", required=True)

    vow = sub.add_parser("vow", help="register an Exchange of Vows")
    vow.add_argument("--qira", type=float, required=True)
    vow.add_argument("--qash", type=float, required=True)
    vow.add_argument("--toll", type=float, required=True)

    sub.add_parser("dashboard", help="print the terminal dashboard")
    sub.add_parser("verify", help="verify the ledger hash chain")
    sub.add_parser("treasury", help="print the accumulated $QQ treasury")

    sink = sub.add_parser("sink", help="inspect the Qolocron archive")
    sink.add_argument("--verify", action="store_true",
                      help="re-derive every archived hash")
    sink.add_argument("--retry", action="store_true",
                      help="re-attempt backlogged archives")
    sink.add_argument("--lookup", metavar="HASH",
                      help="look up one vow_hash in the archive")

    serve = sub.add_parser("serve",
                           help="run the loopback enclave HTTP front")
    serve.add_argument("--port", type=int, default=0)
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        node = AxonemeSovereignNode(args.node_id, ledger_path=args.ledger,
                                    qolocron_path=args.qolocron)
    except LedgerCorruptError as exc:
        print(f"FATAL: ledger failed to load: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except QolocronCorruptError as exc:
        print(f"FATAL: qolocron archive failed to load: {exc}",
              file=sys.stderr)
        return EXIT_ERROR

    if args.command == "vow":
        accepted = node.register_vow(args.qira, args.qash, args.toll)
        return EXIT_OK if accepted else EXIT_REJECTED
    if args.command == "dashboard":
        node.display_dashboard()
        return EXIT_OK
    if args.command == "verify":
        valid = node.verify()
        print(f"chain: {'VALID' if valid else 'BROKEN'} "
              f"({len(node.ledger.records)} records)")
        return EXIT_OK if valid else EXIT_ERROR
    if args.command == "treasury":
        print(f"{node.treasury_qq}")
        return EXIT_OK
    if args.command == "sink":
        if args.lookup:
            record = node.qolocron.lookup(args.lookup)
            if record is None:
                print("not archived")
                return EXIT_ERROR
            print(json.dumps(record, indent=4))
            return EXIT_OK
        if args.retry:
            attempted, archived = node.qolocron.retry_backlog()
            print(f"backlog: {attempted} attempted, {archived} archived")
            return EXIT_OK
        if args.verify:
            valid = node.verify_sink()
            print(f"archive: {'VALID' if valid else 'BROKEN'} "
                  f"({len(node.qolocron.index)} records)")
            return EXIT_OK if valid else EXIT_ERROR
        print(f"archived: {len(node.qolocron.index)} "
              f"backlogged: {len(node.qolocron.backlog())} "
              f"integrity: {'VALID' if node.verify_sink() else 'BROKEN'}")
        return EXIT_OK
    if args.command == "serve":
        from enclave import EnclaveServer
        server = EnclaveServer(node, port=args.port).start()
        node.log_status(f"enclave listening on {server.url} (loopback only)")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            node.log_status("enclave shutting down")
        finally:
            server.stop()
        return EXIT_OK
    return EXIT_ERROR  # unreachable: argparse enforces a command


if __name__ == "__main__":
    sys.exit(main())
