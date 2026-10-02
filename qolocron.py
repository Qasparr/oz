#!/usr/bin/env python3
"""Qolocron — the archival sink of the Axoneme sovereign node.

The Architect's question, from the draft PDF: "should we pipe these
etched vow hashes directly into the Qolocron crystal storage layer?"
His answer: yes — wire it. This module is the sink: every etched vow's
`vow_hash` is archived here, encoded into tri-state cells, with a
lookup map of vow_hash -> cell address.

Hex -> tri-state encoding (the Architect's red pen owns this design):
  A vow_hash is SHA3-256: 64 hex chars = 256 bits. Each hex digest is
  converted to base 3, least-significant trit first, zero-padded to
  exactly TRITS_PER_HASH trits. 3**162 > 2**256 > 3**161, so 162 trits
  carry any 256-bit value losslessly; the round-trip is verified on
  every archive.

Tri-state mechanics ported from the Axon simulation (Qasparr/axon,
axon/tristate.py and axon/repair.py — same logic, stdlib-only port so
this repo keeps no cross-repo runtime dependency):
  - cells hold 0/1/2 (smectic / nematic / cholesteric analogues);
  - every logical trit is written 3x across juxtaposed cells and read
    back by majority vote (the scrubber's triple-redundancy pattern).
  Deliberately NOT ported: the entropy injector and crosstalk models.
  A sink that simulated its own rot would be theater; the archive's
  durability comes from the fsync'd file, the per-line integrity hash,
  and the read-back verification — not from modeled decay.

What this is: virtual tri-state storage, the logic closed in software.
What it assumes: a substrate holding three stable states per cell —
UNBUILT for liquid-crystal hardware, trivially true in software. The
README fence stands: the logic closes, the substrate is assumed,
"immortal" remains aspiration. The Qolocron is the heirloom COPY, not
a claim about crystal physics.

Persistence: append-only JSONL, fsync'd per archive. Each line carries
a line_hash (SHA3-256 of the canonical body); loading re-verifies every
line and raises QolocronCorruptError fail-closed on any mismatch — the
node then refuses to start, exactly like a tampered ledger.

The archive map lives ALONGSIDE the ledger, never inside the hashed
vow body: ledger.py's hash verification is untouched by this module.
"""
import hashlib
import json
import math
import os
from datetime import datetime, timezone

# 256-bit digest -> trits: ceil(256 / log2(3)).
TRITS_PER_HASH = math.ceil(256 * math.log(2, 3))  # == 162
assert 3 ** TRITS_PER_HASH > 2 ** 256 > 3 ** (TRITS_PER_HASH - 1)

# Tri-state cell values, cf. axon/tristate.py: smectic / nematic /
# cholesteric analogues.
SMECTIC, NEMATIC, CHOLESTERIC = 0, 1, 2


def _canonical(record: dict) -> str:
    """Deterministic serialization: sorted keys, no whitespace."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def _sha3(text: str) -> str:
    return hashlib.sha3_256(text.encode("utf-8")).hexdigest()


class QolocronError(Exception):
    """Archive-time failure (bad hash, lattice read-back mismatch)."""


class QolocronCorruptError(QolocronError):
    """The archive file itself is malformed or tampered with."""


def hex_to_trits(hex_digest: str) -> list:
    """64 hex chars -> TRITS_PER_HASH trits, least-significant first."""
    if (not isinstance(hex_digest, str) or len(hex_digest) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in hex_digest)):
        raise QolocronError(f"not a 64-char hex digest: {hex_digest!r}")
    n = int(hex_digest, 16)
    trits = []
    for _ in range(TRITS_PER_HASH):
        trits.append(n % 3)
        n //= 3
    if n != 0:  # cannot happen for 256-bit values; fail-closed if it does
        raise QolocronError("digest does not fit in TRITS_PER_HASH trits")
    return trits


def trits_to_hex(trits) -> str:
    """Inverse of hex_to_trits; the round-trip the archive verifies."""
    n = 0
    for trit in reversed(trits):
        if trit not in (SMECTIC, NEMATIC, CHOLESTERIC):
            raise QolocronError(f"not a trit: {trit!r}")
        n = n * 3 + trit
    return format(n, "064x")


class CrystalLattice:
    """Triple-redundant tri-state rows. Logical trit i of a record lives
    in row (base + i), written to all 3 cells, read by majority vote."""

    def __init__(self):
        self.rows = []  # list of [c0, c1, c2]

    def ensure_rows(self, count: int):
        while len(self.rows) < count:
            self.rows.append([SMECTIC, SMECTIC, SMECTIC])

    def write_trit(self, row: int, value: int):
        assert value in (SMECTIC, NEMATIC, CHOLESTERIC), value
        self.ensure_rows(row + 1)
        self.rows[row] = [value, value, value]

    def read_trit(self, row: int) -> int:
        votes = self.rows[row]
        return max(set(votes), key=votes.count)

    def write_trits(self, base: int, trits):
        for i, trit in enumerate(trits):
            self.write_trit(base + i, trit)

    def read_trits(self, base: int, count: int) -> list:
        return [self.read_trit(base + i) for i in range(count)]


class QolocronArchive:
    """Persistent vow_hash -> tri-state archive with lookup map."""

    def __init__(self, path: str):
        self.path = path
        self.backlog_path = path + ".backlog"
        self.lattice = CrystalLattice()
        self.index = {}  # vow_hash -> archived record
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            return
        if not os.path.isfile(self.path):
            raise QolocronCorruptError(
                f"{self.path}: not a regular file — archive unreadable")
        with open(self.path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise QolocronCorruptError(
                        f"{self.path}:{lineno}: malformed JSON ({exc})")
                if not isinstance(record, dict) or "line_hash" not in record:
                    raise QolocronCorruptError(
                        f"{self.path}:{lineno}: malformed archive record")
                body = {k: v for k, v in record.items() if k != "line_hash"}
                if _sha3(_canonical(body)) != record["line_hash"]:
                    raise QolocronCorruptError(
                        f"{self.path}:{lineno}: line_hash mismatch — "
                        "archive tampered")
                trits = [int(c) for c in body["trits"]]
                if len(trits) != TRITS_PER_HASH:
                    raise QolocronCorruptError(
                        f"{self.path}:{lineno}: trit count wrong")
                self.lattice.write_trits(body["addr"], trits)
                self.index[body["vow_hash"]] = record

    def _append_line(self, body: dict) -> dict:
        record = dict(body)
        record["line_hash"] = _sha3(_canonical(record))
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(_canonical(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record

    def archive(self, vow_hash: str) -> dict:
        """Encode vow_hash to trits, write through the lattice, verify the
        read-back, then commit the archive line. Idempotent: an already
        archived hash returns its existing record."""
        if vow_hash in self.index:
            return self.index[vow_hash]
        trits = hex_to_trits(vow_hash)  # raises QolocronError on bad input
        base = len(self.index) * TRITS_PER_HASH
        self.lattice.write_trits(base, trits)
        read_back = self.lattice.read_trits(base, TRITS_PER_HASH)
        if read_back != trits:
            raise QolocronError(
                f"lattice read-back mismatch for {vow_hash[:16]}…")
        if trits_to_hex(read_back) != vow_hash.lower():
            raise QolocronError(
                f"trit round-trip mismatch for {vow_hash[:16]}…")
        body = {
            "seq": len(self.index) + 1,
            "vow_hash": vow_hash.lower(),
            "trits": "".join(str(t) for t in trits),
            "addr": base,
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }
        record = self._append_line(body)
        self.index[body["vow_hash"]] = record
        return record

    def lookup(self, vow_hash: str):
        """vow_hash -> archived record (with cell addr), or None."""
        if not isinstance(vow_hash, str):
            return None
        return self.index.get(vow_hash.lower())

    def verify_archive(self) -> bool:
        """True iff every line re-derives: trits match the hash, the
        lattice majority read-back matches the stored trits."""
        for vow_hash, record in self.index.items():
            body = {k: v for k, v in record.items() if k != "line_hash"}
            if _sha3(_canonical(body)) != record["line_hash"]:
                return False
            stored = [int(c) for c in body["trits"]]
            if hex_to_trits(vow_hash) != stored:
                return False
            if self.lattice.read_trits(body["addr"], TRITS_PER_HASH) != stored:
                return False
        return True

    def note_failure(self, vow_hash: str, error: str):
        """Record an un-archived vow_hash in the retry backlog, fsync'd."""
        entry = {
            "vow_hash": vow_hash,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
            "error": str(error),
        }
        with open(self.backlog_path, "a", encoding="utf-8") as handle:
            handle.write(_canonical(entry) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def backlog(self) -> list:
        """Pending retry entries (each a dict with vow_hash/error)."""
        entries = []
        if not os.path.exists(self.backlog_path):
            return entries
        with open(self.backlog_path, "r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries

    def retry_backlog(self):
        """Re-attempt every backlogged hash. Returns (attempted, archived).
        Entries that archive are dropped; the rest stay backlogged."""
        entries = self.backlog()
        remaining = []
        archived = 0
        for entry in entries:
            try:
                self.archive(entry["vow_hash"])
                archived += 1
            except QolocronError as exc:
                entry["error"] = str(exc)
                entry["attempted_at"] = datetime.now(
                    timezone.utc).isoformat()
                remaining.append(entry)
        with open(self.backlog_path, "w", encoding="utf-8") as handle:
            for entry in remaining:
                handle.write(_canonical(entry) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return len(entries), archived
