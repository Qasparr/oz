#!/usr/bin/env python3
"""JOR-EL persistent ledger — build step 1 of the pioneer path.

Append-only JSONL vow log, fsync'd per etch. Each record carries a hash
chain link (prev_hash), so any tampering with history is detectable via
verify_chain(). Loading is fail-closed: a malformed or hash-mismatched
line raises LedgerCorruptError naming the exact line.

Not yet: difficulty-scored proof-of-work (step 2), node keypair identity
and signed records (step 3).
"""
import hashlib
import json
import os


def _canonical(record: dict) -> str:
    """Deterministic serialization: sorted keys, no whitespace."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def _sha3(text: str) -> str:
    return hashlib.sha3_256(text.encode("utf-8")).hexdigest()


class LedgerCorruptError(Exception):
    """Raised when the ledger file is malformed or tampered with."""


class AppendOnlyLedger:
    GENESIS = "GENESIS"

    def __init__(self, path: str):
        self.path = path
        self.records: list = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise LedgerCorruptError(
                        f"{self.path}:{lineno}: malformed JSON ({exc})"
                    )
                if not isinstance(record, dict) or "vow_hash" not in record:
                    raise LedgerCorruptError(
                        f"{self.path}:{lineno}: malformed vow record"
                    )
                body = {k: v for k, v in record.items() if k != "vow_hash"}
                if _sha3(_canonical(body)) != record["vow_hash"]:
                    raise LedgerCorruptError(
                        f"{self.path}:{lineno}: vow_hash mismatch — record tampered"
                    )
                self.records.append(record)

    def append(self, body: dict) -> dict:
        """Etch one record: assigns seq + prev_hash, hashes, appends, fsyncs."""
        record = dict(body)
        record["seq"] = len(self.records) + 1
        record["prev_hash"] = (
            self.records[-1]["vow_hash"] if self.records else self.GENESIS
        )
        record["vow_hash"] = _sha3(_canonical(record))
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(_canonical(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self.records.append(record)
        return record

    def verify_chain(self) -> bool:
        """True iff every link's prev_hash matches and every hash is valid."""
        prev = self.GENESIS
        for record in self.records:
            if record.get("prev_hash") != prev:
                return False
            body = {k: v for k, v in record.items() if k != "vow_hash"}
            if _sha3(_canonical(body)) != record["vow_hash"]:
                return False
            prev = record["vow_hash"]
        return True
