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
> on-chain program and the Python application run end to end on a local
> validator; the devnet deployment and the web demo are in progress.

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

## Repository layout

```
program/   on-chain: the Anchor program (Rust) and its tests
app/       off-chain: the Python/Django application and its tests
```

### The app (`app/`)

| Package | Role |
|---|---|
| `rxtrail/` | the domain in plain Python: entities, the prescription rules, use cases, and the ports it needs |
| `solana_client/` | adapter to the on-chain program: builds and signs transactions from the program's IDL, follows confirmations over WebSocket, maps program errors to domain errors |
| `records/` | adapter to the off-chain store (Postgres): patients, the link to their random on-chain id, prescription documents and salts |
| `web/` | entry points: the `rxtrail` command today, web pages next |
| `config/` | Django settings and the composition root wiring ports to adapters |

The rules live twice, on purpose. The on-chain program enforces them and is
the authority; `rxtrail/rules.py` mirrors them so the app can explain a
refusal before sending a doomed transaction. Tests pin both.

What goes where:

| On-chain (public) | Off-chain (private) |
|---|---|
| random prescription and patient ids | patient name and document number |
| quantity granted, dispensed, expiry | the full prescription document |
| salted hash of the document | the salt |
| every dispensation, signed | |

## Development

Everything runs in Docker; [just](https://just.systems) wraps the commands.

```bash
just bootstrap        # .env, images, database, migrations
just build            # compile the program; copy its IDL to the app
just localnet         # start a local single-node validator
just deploy-localnet  # deploy the program to it
just test             # program tests (LiteSVM) + app tests (Postgres, localnet)
```

Try it end to end on the local validator:

```bash
just manage rxtrail setup                       # keys, operator funds, initialize
just manage rxtrail enable-prescriber dr-ana    # the professional authority signs
just manage rxtrail enable-dispenser pharmacy-one
just manage rxtrail issue dr-ana --patient-document 123 --patient-name "Maria Silva" \
    --medication "Clonazepam 2mg" --quantity 30 --days 30
just manage rxtrail dispense pharmacy-one <prescription id> 20
just manage rxtrail dispense pharmacy-one <prescription id> 15   # refused: 10 remain
just manage rxtrail audit <prescription id>
```

Tests:

| Suite | Runs against | Covers |
|---|---|---|
| `program/programs/rxtrail/tests` | the compiled program on LiteSVM | every on-chain guarantee |
| `app/tests/unit` | in-memory fakes | rules mirror, document hashing, IDL codec, use cases |
| `app/tests/integration` | Postgres | off-chain store, database permissions |
| `app/tests/localnet` | the deployed program on a local validator | the full flow; refusals come from the chain itself |

Python is installed and managed by [uv](https://docs.astral.sh/uv/)
(version in `app/.python-version`); Rust, Agave and Anchor live in the
`program/` image. Nothing but Docker and `just` is needed on the host.

## Roadmap

- Python client (hexagonal: domain, ports, adapters) and devnet deployment
- Demo web app: prescriber issues, pharmacy dispenses, auditor verifies
- Cancellation, corrections (reversal records) and suspension cascades
- Upgrade authority under a multisig of authorities; verifiable builds
