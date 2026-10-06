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

## Running RxTrail

You need Docker and [just](https://just.systems). Everything else — Rust,
Agave (Solana), Anchor, Python (managed by uv), Postgres — runs in
containers. `just` alone lists every command.

```bash
git clone https://github.com/GustavoRizzo/rxtrail && cd rxtrail
just bootstrap        # .env, images, database, migrations
just build            # compile the program; copy its IDL to the app
```

Keys live in `.keys/` (never committed): one JSON keypair per participant,
in the Solana CLI format. Three roles matter for running it:

| Key | Role | Needs SOL? |
|---|---|---|
| `rxtrail-program-keypair.json` | the program's own address (`declare_id!`) | no |
| `deployer.json` | publishes and upgrades the program | yes, to deploy |
| `operator.json` | pays every fee and rent deposit for participants | yes, while in use |

Participants (authorities, prescribers, dispensers) sign but never pay.

### On a local validator (development)

A private single-node chain in a container, with an unlimited faucet.

```bash
just localnet                                  # start the validator
just deploy-localnet                           # creates and funds the deployer
just rx localnet setup                         # keys, operator funds, initialize
just rx localnet enable-prescriber dr-ana      # the professional authority signs
just rx localnet enable-dispenser pharmacy-one # the health authority signs
just rx localnet issue dr-ana --patient-document 123 --patient-name "Maria Silva" \
    --medication "Clonazepam 2mg" --quantity 30 --days 30
just rx localnet dispense pharmacy-one <prescription id> 20
just rx localnet dispense pharmacy-one <prescription id> 15   # refused: 10 remain
just rx localnet audit <prescription id>
```

`just localnet-reset` wipes the chain (redeploy afterwards).

### On devnet (the public test network)

Same commands with `devnet`, after funding two keys. Devnet SOL is free
but rationed: use https://faucet.solana.com (connecting GitHub raises the
limit) and confirm arrivals with `just devnet-status`.

```bash
just devnet-status    # prints the deployer and operator addresses and balances
```

1. **Fund the deployer with ~2.5 SOL** (see costs below), then deploy:
   ```bash
   just deploy-devnet
   just devnet-status    # the program now shows up
   ```
2. **Fund the operator with ~0.3 SOL** — from the faucet, or from any devnet
   wallet you hold. After deploying, the deployer keeps ~1.4 SOL; leave at
   least ~1.1 SOL there, since every upgrade needs a temporary buffer again:
   ```bash
   just chain solana transfer <operator address> 0.3 \
       --keypair /keys/deployer.json --url https://api.devnet.solana.com \
       --allow-unfunded-recipient
   ```
3. **Initialize and run the flow**:
   ```bash
   just rx devnet setup
   just rx devnet enable-prescriber dr-ana
   just rx devnet enable-dispenser pharmacy-one
   just rx devnet issue dr-ana --patient-document 123 --patient-name "Maria Silva" \
       --medication "Clonazepam 2mg" --quantity 30 --days 30
   ```

Every address printed can be inspected on
`https://explorer.solana.com/address/<address>?cluster=devnet`.

### What it costs

Solana charges two things: a **fee** per transaction (5,000 lamports per
signature; 1 SOL = 10⁹ lamports) and a **rent deposit** for every account
created, proportional to its size. The deposit is locked, not spent: it
comes back if the account is closed. RxTrail never closes its records,
because they are the audit trail.

| Paid by | When | Cost |
|---|---|---|
| deployer | first deploy | ~1.04 SOL locked in the program account (205 KB binary), plus a same-size temporary buffer refunded at the end: **~2.1 SOL needed at the moment of deploying** |
| deployer | each upgrade | a temporary buffer again (~1.04 SOL, refunded), plus more rent only if the binary grows |
| operator | `setup`, once | 0.00102 SOL (configuration record) |
| operator | per prescriber or dispenser enabled | 0.00090 SOL |
| operator | **per prescription** | **0.00149 SOL** |
| operator | **per dispensation** | **0.00112 SOL** |
| operator | per transaction | 0.000005 SOL |

A prescription filled in three dispensations costs about **0.0049 SOL**,
almost all of it rent that stays locked as the permanent record. The
deployer pays once (and on upgrades); the operator pays as the system is
used.

### Tests

```bash
just test             # program tests (LiteSVM) + app tests
```

| Suite | Runs against | Covers |
|---|---|---|
| `program/programs/rxtrail/tests` | the compiled program on LiteSVM | every on-chain guarantee |
| `app/tests/unit` | in-memory fakes | rules mirror, document hashing, IDL codec, error mapping, use cases |
| `app/tests/integration` | Postgres | off-chain store, database permissions |
| `app/tests/localnet` | the program deployed on the local validator | the full flow; refusals come from the chain itself |

The localnet suite is skipped unless the program is deployed
(`just localnet && just deploy-localnet`). CI runs everything on each push.

## Roadmap

- Python client (hexagonal: domain, ports, adapters) and devnet deployment
- Demo web app: prescriber issues, pharmacy dispenses, auditor verifies
- Cancellation, corrections (reversal records) and suspension cascades
- Upgrade authority under a multisig of authorities; verifiable builds
