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
    AxonemeSovereignNode(node_id, ledger_path="jorel.ledger.jsonl")
    .toll_required(qira_stake, qash_stake) -> float   # static, single source
    .register_vow(qira_stake, qash_stake, qq_toll) -> bool
    .verify() -> bool
    .ledger, .treasury_qq, .node_id
    .display_dashboard(), .log_status()

CLI:
    node vow --qira 100000 --qash 50000 --toll 155
    node dashboard | node verify | node treasury
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

DEFAULT_NODE_ID = "JOR-EL"
DEFAULT_LEDGER = "jorel.ledger.jsonl"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REJECTED = 2


class AxonemeSovereignNode:
    def __init__(self, node_id: str = DEFAULT_NODE_ID,
                 ledger_path: str = DEFAULT_LEDGER):
        self.node_id = node_id
        # Fail-closed: a tampered ledger raises here, the node never starts.
        self.ledger = AppendOnlyLedger(ledger_path)
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
        return True

    def verify(self) -> bool:
        """True iff the ledger's hash chain is intact."""
        return self.ledger.verify_chain()

    def display_dashboard(self):
        chain = "VALID" if self.verify() else "BROKEN"
        print("\n" + "=" * 50)
        print(" The Wizard, in the Emerald City of Oz, at the Crystal Palace.")
        print(f" AXONEME PROTOCOL TERMINAL DASHBOARD (Node: {self.node_id})")
        print("=" * 50)
        print(f" Total Registered Vows: {len(self.ledger.records)}")
        print(f" Accumulated $QQ Treasury: {self.treasury_qq}")
        print(f" Ledger File: {self.ledger.path} (chain {chain})")
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
    sub = parser.add_subparsers(dest="command", required=True)

    vow = sub.add_parser("vow", help="register an Exchange of Vows")
    vow.add_argument("--qira", type=float, required=True)
    vow.add_argument("--qash", type=float, required=True)
    vow.add_argument("--toll", type=float, required=True)

    sub.add_parser("dashboard", help="print the terminal dashboard")
    sub.add_parser("verify", help="verify the ledger hash chain")
    sub.add_parser("treasury", help="print the accumulated $QQ treasury")

    serve = sub.add_parser("serve",
                           help="run the loopback enclave HTTP front")
    serve.add_argument("--port", type=int, default=0)
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        node = AxonemeSovereignNode(args.node_id, ledger_path=args.ledger)
    except LedgerCorruptError as exc:
        print(f"FATAL: ledger failed to load: {exc}", file=sys.stderr)
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
