# RxTrail

**Tamper-proof dispensing limits for controlled prescriptions, on Solana.**

Controlled medications can only be sold against a prescription that grants a
maximum quantity. Today each pharmacy only knows what *it* dispensed: the same
prescription can be filled at several pharmacies past its limit, records can
be edited after the fact, and auditing means asking every pharmacy for its
data.

RxTrail puts the rule itself on a shared ledger that no single party
controls. A prescription is issued once; every dispensation is recorded
against it; and the program **guarantees the total dispensed never exceeds
the quantity granted** — even when two pharmacies try at the same time.
Every event stays on-chain as its own immutable record, so a regulator or
auditor can verify the full history without trusting anyone.

> Status: early build for the Colosseum hackathon (October 2026). The
> on-chain program (milestone 1) is implemented and tested; the client, the
> devnet deployment and the demo app are in progress.

## How it works

| Actor | Can |
|---|---|
| Professional authority (e.g. a medical council) | enable prescribers |
| Health authority (e.g. a health regulator) | enable dispensers |
| Prescriber | issue a prescription: quantity, expiry, document hash |
| Dispenser (pharmacy) | dispense against a prescription, never past what remains |
| Anyone | read and verify the full history |

- **Non-custodial.** Every action is signed by the participant it is
  attributed to. The operator only pays fees and rent; it cannot sign for
  anyone, and the program enforces it.
- **No personal data on-chain.** Prescriptions and patients are identified by
  random ids. The full prescription document stays off-chain; only its salted
  hash is recorded, proving it was not altered.
- **Append-only history.** A prescription keeps two counters (dispensed,
  count); each dispensation is a separate account that no instruction can
  modify.

### On-chain accounts

| Account | Address (PDA seeds) | Changes? |
|---|---|---|
| `Config` | `["config"]` | never (set once) |
| `Prescriber` | `["prescriber", key]` | status only |
| `Dispenser` | `["dispenser", key]` | status only |
| `Prescription` | `["prescription", id]` | counters only, via `dispense` |
| `Dispensation` | `["dispensation", prescription, index]` | never |

## Development

Everything runs in Docker; [just](https://just.systems) wraps the commands.

```bash
cp .env.example .env
just toolchain       # build the image: Rust, Agave 4.3, Anchor 1.2
just build           # compile the program and its IDL
just test-program    # program tests on LiteSVM (in-process Solana VM)
just lint-program    # rustfmt + clippy
just localnet        # local single-node validator
```

The program tests run the compiled bytecode and cover the guarantees above:
never dispensing past the grant (including two dispensers racing), expiry,
and that only enabled participants — and never the operator — can act.

## Roadmap

- Python client (hexagonal: domain, ports, adapters) and devnet deployment
- Demo web app: prescriber issues, pharmacy dispenses, auditor verifies
- Cancellation, corrections (reversal records) and suspension cascades
- Upgrade authority under a multisig of authorities; verifiable builds
