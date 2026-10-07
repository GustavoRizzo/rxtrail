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

Every prescription names a medication from a shared catalog, and every
dispensation records which manufacturer's product was handed out. That turns
the history into evidence about *professionals*, never patients: which
prescribers push a new, pricier drug over an equivalent one, or which
pharmacies avoid generics. And a recall reaches every pharmacy at once.

> Status: early build for the Colosseum hackathon (October 2026). The
> on-chain program, the Python application and the web demo run end to end
> on a local validator; the devnet deployment is next.

## How it works

| Actor | Can |
|---|---|
| Professional authority (e.g. a medical council) | enable, suspend and reinstate prescribers |
| Health authority (e.g. a health regulator) | enable, suspend and reinstate dispensers |
| Catalog authority (e.g. a drug regulator) | register medications and products; withdraw (recall) and reinstate them |
| Prescriber | issue a prescription for a catalog medication: quantity, expiry, document hash; optionally lock one product ("do not substitute") |
| Dispenser (pharmacy) | dispense against a prescription, never past what remains, recording the product handed out |
| Anyone | read and verify the full history |

- **Non-custodial.** Every action is signed by the participant it is
  attributed to. The operator only pays fees and rent; it cannot sign for
  anyone, and the program enforces it.
- **No personal data on-chain.** Prescriptions are identified by random ids
  and nothing on-chain identifies the patient, not even a pseudonym. The full
  prescription document stays off-chain; only its salted hash is recorded,
  proving it was not altered.
- **One catalog, one language.** A medication is an active ingredient,
  strength and form; a product is one manufacturer's version of it
  (reference, generic or similar). Names, therapeutic class (WHO ATC) and
  dosage guidance live off-chain as open data (`/catalog.json`); on-chain,
  each record keeps only an identity hash, so nobody can quietly change what
  an id means. The program refuses a product that is not a version of the
  prescribed medication.
- **Recall takes effect everywhere at once.** A withdrawn product can no
  longer be dispensed (pharmacies hand out another version); a withdrawn
  medication cannot be prescribed, and all its prescriptions freeze until it
  is reinstated.
- **Suspension takes effect everywhere at once.** A suspended prescriber can
  no longer issue, and none of their prescriptions can be dispensed — the
  answer to a leaked key or a revoked licence. Reinstating restores both;
  nothing already recorded changes.
- **Append-only history.** A prescription keeps two counters (dispensed,
  count); each dispensation is a separate account that no instruction can
  modify.

### On-chain accounts

| Account | Address (PDA seeds) | Changes? |
|---|---|---|
| `Config` | `["config"]` | never (set once) |
| `Prescriber` | `["prescriber", key]` | status only (by its authority) |
| `Dispenser` | `["dispenser", key]` | status only (by its authority) |
| `Medication` | `["medication", id]` | status only (withdraw, reinstate) |
| `Product` | `["product", id]` | status only (withdraw, reinstate) |
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
| `records/` | adapter to the off-chain store (Postgres): patients, prescription documents and salts, and the medication catalog |
| `web/` | entry points: the `rxtrail` command and the web app (one dashboard per role, public verification page, public catalog with open data). The visual identity is a handful of tokens in `web/static/web/tokens.css`; `/styleguide/` previews every component (development only) |
| `config/` | Django settings and the composition root wiring ports to adapters |

The rules live twice, on purpose. The on-chain program enforces them and is
the authority; `rxtrail/rules.py` mirrors them so the app can explain a
refusal before sending a doomed transaction. Tests pin both.

What goes where:

| On-chain (public) | Off-chain |
|---|---|
| random prescription ids; nothing about the patient | private: patient name and document number |
| the medication prescribed; quantity granted, dispensed, expiry | private: the full prescription document |
| salted hash of the document | private: the salt |
| every dispensation and the product handed out, signed | |
| catalog records: id, identity hash, status | public open data: names, ATC class, kind, dosage guidance |

## Running RxTrail

You need Docker and [just](https://just.systems). Everything else — Rust,
Agave (Solana), Anchor, Python (managed by uv), Postgres — runs in
containers. `just` alone lists every command.

### Environments

RxTrail runs in **environments**, one per Solana network:

| Environment | Network | Use |
|---|---|---|
| `localnet` | a private validator in a container, unlimited faucet | development and tests |
| `devnet` | Solana's public test network | public demo |

One environment = one network = one database = one key set
(`.keys/<network>/`, never committed) = one config (`envs/<network>.env`).
Both can run side by side without mixing: each is its own Docker Compose
project with its own containers and volumes. A deployment binds to exactly
one.

The database also remembers which chain it belongs to (the network's
genesis hash) and the app refuses to run against any other — a misconfigured
environment, or a local validator that was reset, fails loudly instead of
mixing records from two chains.

Three keys matter for running an environment:

| Key | Role | Needs SOL? |
|---|---|---|
| `.keys/rxtrail-program-keypair.json` | the program's address (same on every network) | no |
| `.keys/<network>/deployer.json` | publishes and upgrades the program | yes, to deploy |
| `.keys/<network>/operator.json` | pays every fee and rent deposit | yes, while in use |

Participants (authorities, prescribers, dispensers) sign but never pay.

### Local environment (development)

```bash
git clone https://github.com/GustavoRizzo/rxtrail && cd rxtrail
just bootstrap localnet          # config, images, database, validator, migrations
just build                       # compile the program; copy its IDL to the app
just deploy localnet             # creates and funds a local deployer
just rx localnet setup           # keys, operator funds, initialize
just rx localnet demo            # participants enabled on-chain, a catalog, samples
just rx localnet enable-prescriber dr-new       # the professional authority signs
just rx localnet catalog                        # medications, products, on-chain status
just rx localnet issue dr-ana --patient-document 123 --patient-name "Maria Silva" \
    --medication "Clonazepam 2 mg tablet" --quantity 30 --days 30
just rx localnet dispense pharmacy-one <prescription id> "Clonazepam Beta 2 mg" 20
just rx localnet dispense pharmacy-one <prescription id> "Calmazen 2 mg" 15   # refused: 10 remain
just rx localnet audit <prescription id>
just rx localnet suspend-prescriber dr-ana      # her prescriptions stop dispensing
just rx localnet reinstate-prescriber dr-ana
```

`just reset-localnet` wipes the local chain **and** its database together,
then redeploys and sets up again.

### Try it in the browser

```bash
just rx localnet demo       # demo logins, enabled on-chain, a catalog, sample prescriptions
```

Open http://localhost:8142 and sign in: the login page lists the demo
accounts (one per role) and fills the form for you. A suggested tour:

1. **Prescriber** (e.g. Dr. Ana Souza) — issue a prescription: search the
   catalog by name, active ingredient, ATC code, brand or manufacturer; you
   land on its audit page. Copy its id.
2. **Pharmacy** (e.g. Central Pharmacy) — look the id up, pick the product
   handed out and dispense part of it, then try to dispense more than
   remains: the chain refuses.
3. **Professional authority** (Regional Medical Council) — suspend the
   prescriber, then try dispensing again as the pharmacy: refused
   everywhere. Reinstate.
4. **Catalog authority** (National Medication Registry) — withdraw a
   product: the pharmacy must hand out another version. Withdraw the
   medication: its prescriptions freeze for every pharmacy. Reinstate.
5. **Auditor** (Health Inspector) — open any prescription: the verdict, the
   medication and the on-chain history, without the patient's data. Every
   key and record links to the Solana explorer.

Anyone can browse the catalog at `/catalog/` and download it as open data.

The demo cast and samples are illustrative and will evolve with the project.

**Demo mode holds the participants' keys on the server** so that one browser
can play every role; the footer says so. The program itself is unchanged by
this: every action still needs the participant's signature, and the operator
cannot sign for anyone. In production each participant signs with their own
wallet.

### Devnet environment (public demo)

Devnet SOL is free but rationed: use https://faucet.solana.com (connecting
GitHub raises the limit) and check arrivals with `just status devnet`.

```bash
just bootstrap devnet
just status devnet       # deployer and operator addresses and balances
```

1. **Fund the deployer with ~2.5 SOL**, then deploy:
   ```bash
   just deploy devnet
   just status devnet    # the program now shows up
   ```
2. **Fund the operator with ~0.3 SOL.** Its key is created by `setup`; run
   `just rx devnet setup` once to create it and print its address, fund it,
   then run `setup` again. Keep ~1.1 SOL in the deployer for future upgrades.
3. **Run the flow** with `just rx devnet ...`, as above.

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
| deployer | first deploy | ~1.46 SOL locked in the program account (289 KB binary), plus a same-size temporary buffer refunded at the end: **~2.9 SOL needed at the moment of deploying** |
| deployer | each upgrade | a temporary buffer again (~1.46 SOL, refunded), plus more rent only if the binary grows |
| operator | `setup`, once | 0.00118 SOL (configuration record) |
| operator | per prescriber or dispenser enabled | 0.00094 SOL |
| operator | per medication / product in the catalog | 0.00110 / 0.00127 SOL |
| operator | **per prescription** | **0.00166 SOL** |
| operator | **per dispensation** | **0.00128 SOL** |
| operator | per transaction | 0.000005 SOL |

Rent figures use devnet's rate (about 5,070 lamports per account byte, plus
128 bytes of overhead per account). A prescription filled in three
dispensations costs about **0.0055 SOL**,
almost all of it rent that stays locked as the permanent record. The
deployer pays once (and on upgrades); the operator pays as the system is
used.

### Tests

```bash
just test             # program tests (LiteSVM) + app tests
```

| Suite | Runs against | Covers |
|---|---|---|
| `program/programs/rxtrail/tests` | the compiled program on LiteSVM | every on-chain guarantee, plus a property test: random sequences of requests from several pharmacies never dispense past the grant |
| `app/tests/unit` | in-memory fakes | rules mirror, document and catalog identity hashing, IDL codec, error mapping, use cases |
| `app/tests/integration` | Postgres | off-chain store, database permissions, the web pages (who sees and does what) with the chain faked |
| `app/tests/localnet` | the program deployed on the local validator | the full flow; refusals come from the chain itself (wrong product, recall, locked brand); **five pharmacies racing for the same prescription at the same time** — exactly the granted quantity lands |

App tests run in the `localnet` environment against its own `_test`
database. The localnet suite is skipped unless the program is deployed
there (`just deploy localnet`). CI runs everything on each push.

## Roadmap

- Devnet deployment
- Cancelling a prescription before any dispensation, and stopping the
  remainder of a partly dispensed one
- Corrections to a dispensation (reversal records)
- Audit insights: per therapeutic class, which prescribers adopt a new drug
  far above their peers; which pharmacies dispense generics far below the
  network. Prescribers and pharmacies appear by their on-chain id, never by
  name
- Wallet sign-in (each participant signs in their own wallet)
- An indexer of the program's events, so lists and dashboards stop reading
  the chain on every page view
- Upgrade authority under a multisig of authorities; verifiable builds

## Team

Built by **Gustavo Rizzo S. M. de Albuquerque** —
[GitHub](https://github.com/GustavoRizzo) ·
[LinkedIn](https://www.linkedin.com/in/gustavo-albuquerque/).
