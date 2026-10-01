# Axoneme Protocol — Sovereign Node (sketch)

**Project Leviathan · Architect: Johnathan "Qasparr" (Κασπάρρ) Monroe, Keeper of the Secret Treasure**
*All Rights Reserved, Without Prejudice*

A terminal dashboard and ledger sketch for Zero-Trust vow registration —
binding **$QIRA** and **$$QASH** through the expenditure of **$QQ** kinetic
tokens, per the *Liber Leviathan* four-token doctrine (Books VII, VIII, XIII).

> **Status: SKETCH.** This is a working draft, not a node engine. It runs,
> it hashes, it tallies — and its limits are listed honestly below. Nothing
> here is deployed, audited, or consensus-bearing.

## Run it

```sh
python3 axoneme_sovereign_node.py
```

Registers one demo vow (100,000 $QIRA + 50,000 $$QASH against a 155 $QQ toll)
and prints the dashboard before and after.

## What it does

- **Vow registration** — `register_vow(qira_stake, qash_stake, qq_toll)`:
  toll-gate check (`required = (qira + qash) / 1000`), then a SHA3-256 vow
  signature over stakes + toll + timestamp, appended to the ledger.
- **Kinetic enforcement** — under-toll vows are rejected, not recorded.
- **Terminal dashboard** — vow count, accumulated $QQ treasury, enclave state.

## Honest limits (the red-pen list)

1. **The ledger is in-memory only.** Kill the process and every vow is gone.
   First real step: an append-only ledger file (JSONL), fsync'd per etch.
2. **No actual proof-of-work.** The "toll" is a ratio check, not hashcash —
   there is no difficulty target on the vow hash. A real registrarr would
   require the vow hash to beat a difficulty (leading-zero) target.
3. **No node identity.** `node_id` is a string, not a keypair. No signatures,
   no peer authentication, no replay protection.
4. **Sigil note:** the code prints `$QASH`; the canonical written form per
   the Architect's ruling R-65 is `$$QASH` (double sigil, distinguishing the
   unrelated third-party QASH asset). Code labels to be aligned.
5. **"Qolocron crystal storage" is not a defined interface.** Per the
   Architect's question in the draft: do not route ledger output anywhere
   until the sink is specified as a real interface. The append-only local
   ledger (limit 1) comes first.

## Next steps, in order

1. Append-only JSONL ledger with per-etch fsync.
2. Difficulty target on the vow hash (real PoW binding the toll to work).
3. Ed25519 node identity; signed vow records; replay nonces.
4. Then — and only then — specify the downstream sink interface.

## License

AGPL-3.0-only. See `LICENSE`.
