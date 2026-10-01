#!/usr/bin/env python3
"""Project Leviathan: Axoneme Protocol Sovereign Node
Module: Proof-of-Work Registrarr & Ledger Engine
Engine: JOR-EL
Architect: Johnathan 'Qasparr' Monroe (Κασπάρρ)
Description: Terminal dashboard for Zero-Trust vow registration and $QQ validation.

Source: architect-supplied draft PDF, 2026-10-01. Filed as a sketch;
not yet a real node engine (see review notes alongside).

Pioneer build, step 1: vows now persist to an append-only JSONL ledger
(fsync'd per etch, hash-chained, fail-closed on corruption). Step 2 is
real proof-of-work difficulty; step 3 is node keypair identity.
"""
import json
import time
from datetime import datetime, timezone

from ledger import AppendOnlyLedger


class AxonemeSovereignNode:
    def __init__(self, node_id: str, ledger_path: str = "jorel.ledger.jsonl"):
        self.node_id = node_id
        self.ledger = AppendOnlyLedger(ledger_path)
        self.treasury_qq = sum(r["qq_consumed"] for r in self.ledger.records)

    def log_status(self, message: str):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
        print(f"[{timestamp}] [AXONEME-NODE:{self.node_id}] {message}")

    def register_vow(self, qira_stake: float, qash_stake: float, qq_toll: float) -> bool:
        self.log_status("Initiating Exchange of Vows validation...")
        # Calculate required kinetic toll based on stake volume
        required_toll = (qira_stake + qash_stake) / 1000.0
        if qq_toll < required_toll:
            self.log_status(
                f"REJECTED: Insufficient $QQ mass. Provided: {qq_toll}, Required: {required_toll}"
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

    def display_dashboard(self):
        chain = "VALID" if self.ledger.verify_chain() else "BROKEN"
        print("\n" + "=" * 50)
        print(" The Wizard, in the Emerald City of Oz, at the Crystal Palace.")
        print(f" AXONEME PROTOCOL TERMINAL DASHBOARD (Node: {self.node_id})")
        print("=" * 50)
        print(f" Total Registered Vows: {len(self.ledger.records)}")
        print(f" Accumulated $QQ Treasury: {self.treasury_qq}")
        print(f" Ledger File: {self.ledger.path} (chain {chain})")
        print(" Qrystal Palace Enclave State: ONLINE (POPE Secured)")
        print("=" * 50 + "\n")


if __name__ == "__main__":
    # Initialize sovereign node instance
    node = AxonemeSovereignNode("JOR-EL")
    node.display_dashboard()
    # Attempt a vow registration using mined $QQ tokens
    node.register_vow(qira_stake=100000.0, qash_stake=50000.0, qq_toll=155.0)
    # Display updated state
    node.display_dashboard()
