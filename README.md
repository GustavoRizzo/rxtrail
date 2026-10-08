# RxTrail

**Tamper-proof dispensing limits for controlled prescriptions, on Solana.**

[![CI](https://github.com/GustavoRizzo/rxtrail/actions/workflows/ci.yml/badge.svg)](https://github.com/GustavoRizzo/rxtrail/actions/workflows/ci.yml)
![Solana](https://img.shields.io/badge/Solana-Agave_4.3-9945FF?logo=solana&logoColor=white)
![Anchor](https://img.shields.io/badge/Anchor-1.2.1-512BD4)
![Rust](https://img.shields.io/badge/Rust-1.99-B7410E?logo=rust&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)
![Django](https://img.shields.io/badge/Django-6.1-0C4B33?logo=django&logoColor=white)

Controlled medications are sold against a prescription that caps the
quantity. Keeping that cap is harder than it sounds: a prescription can be
filled in parts, at different pharmacies, over weeks, and health departments
struggle to follow every one of them from start to finish. Wherever records
are scattered and depend on each party reporting them right, a gap in control
can become real harm: a prescription filled past its limit, a record that no
longer matches what was handed out, an audit that takes weeks to piece
together.

RxTrail puts the rule itself on a shared ledger that no single party
controls. A prescription is issued once; every fill is recorded against
it; and the program **guarantees the total dispensed never exceeds the
quantity prescribed** — even when two pharmacies try at the same time.
Every event stays on-chain as its own immutable record, so a regulator or
auditor can verify the full history without trusting anyone.

Every prescription names a medication from a shared catalog, and every
fill records which manufacturer's product was handed out. That turns
the history into evidence about *professionals*, never patients: which
prescribers push a new, pricier drug over an equivalent one, or which
pharmacies avoid generics. And a recall reaches every pharmacy at once.

> [!NOTE]
> Early build for the Colosseum hackathon (October 2026). The on-chain
> program, the Python application and the web demo run end to end on a
> local validator; the devnet deployment is next.

> [!TIP]
> **Run it in one command.** With [Docker](#-prerequisites) and
> [just](#-prerequisites) installed:
> `git clone https://github.com/GustavoRizzo/rxtrail && cd rxtrail && just quickstart`,
> then open <http://localhost:8142>. Details in [Quick start](#-quick-start).

## 📑 Contents

- [How it works](#️-how-it-works)
- [Repository layout](#️-repository-layout)
- [Quick start](#-quick-start) · [Prerequisites](#-prerequisites) · [Step by step](#-step-by-step)
- [Try it in the browser](#️-try-it-in-the-browser) · [Explore the investigations](#-explore-the-investigations)
- [Day-to-day commands](#-day-to-day-commands) · [The command line](#️-the-command-line)
- [Environments: localnet and devnet](#-environments-localnet-and-devnet) · [What it costs](#-what-it-costs)
- [Tests](#-tests) · [Troubleshooting](#-troubleshooting) · [Contributing](#-contributing)
- [Roadmap](#️-roadmap) · [Team](#-team)

## ⚙️ How it works

| Actor | Can |
|---|---|
| Medical board (licenses prescribers) | register, suspend and reinstate prescribers |
| Pharmacy board (licenses pharmacies) | register, suspend and reinstate pharmacies |
| Drug regulator | register medications and products; recall and reinstate them |
| Prescriber | issue a prescription for a catalog medication: quantity, expiry, document hash; optionally lock one product ("do not substitute"); cancel it before the first fill, or discontinue what remains of a partly filled one |
| Pharmacy | dispense against a prescription, in one fill or several, never past what remains, recording the product handed out |
| Anyone | read and verify the full history; study behaviour patterns at `/insights/` |

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
- **Recall takes effect everywhere at once.** A recalled product can no
  longer be dispensed (pharmacies hand out another version); a recalled
  medication cannot be prescribed, and all its prescriptions are on hold
  until it is reinstated.
- **Suspension takes effect everywhere at once.** A suspended prescriber can
  no longer issue, and none of their prescriptions can be dispensed — the
  answer to a leaked key or a revoked licence. Reinstating restores both;
  nothing already recorded changes.
- **Cancel and discontinue, never edit.** The issuing prescriber may cancel
  a prescription nobody filled yet, or discontinue what remains of a partly
  filled one, with a public, non-clinical reason (a private note stays
  off-chain). Both are final. If a pharmacy fills it first, a cancel is
  refused, never silently turned into a discontinuation. A suspended prescriber cannot
  do either: whoever holds a leaked key must not void patients' prescriptions.
- **Open auditing.** `/insights/` reads only public data (every program
  account, plus the open catalog) and looks for behaviour patterns: who gives
  a new, pricier drug a share of its class far above their peers; which
  pharmacies avoid generics; who keeps locking one brand; who writes far more
  than peers, with the context that tells a specialist from a problem.
  Prescribers and pharmacies appear by their public key, never by name;
  nothing concerns patients. Every number leads to the records behind it, and
  every page says it plainly: signals for investigation, not findings.
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
| `Prescription` | `["prescription", id]` | counters, via `dispense`; status once, via cancel or stop |
| `Dispensation` | `["dispensation", prescription, index]` | never |
| `PrescriptionClosure` | `["closure", prescription]` | never (one per prescription: closing is final) |

## 🗂️ Repository layout

```
program/      on-chain: the Anchor program (Rust) and its tests
app/          off-chain: the Python/Django application and its tests
envs/         one config per environment (*.env.example is the template)
justfile      every command: run `just` to list them
compose.yaml  the services: database, web app, local validator, toolchain
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
| the medication prescribed; quantity prescribed, dispensed, expiry | private: the full prescription document |
| salted hash of the document | private: the salt |
| every fill and the product handed out, signed | |
| catalog records: id, identity hash, status | public open data: names, ATC class, kind, dosage guidance |

## 🚀 Quick start

Everything runs in Docker: Rust, Agave (Solana), Anchor, Python, Postgres.
You install only two tools; no Solana wallet, keys or SOL are needed to run
it locally.

```bash
git clone https://github.com/GustavoRizzo/rxtrail
cd rxtrail
just quickstart
```

When it prints `RxTrail is running`, open **<http://localhost:8142>**. The
login page lists one demo account per role and fills the form for you
(every demo password is `rxtrail-demo`). Then follow the
[browser tour](#️-try-it-in-the-browser).

> [!IMPORTANT]
> The **first run takes a while** — 10–20 minutes, depending on the machine and the
> connection — because it builds the Solana toolchain image and compiles the
> program. Later runs reuse the caches: starting again is `just up localnet`
> and takes seconds.

### 📋 Prerequisites

| Tool | Tested with | Install |
|---|---|---|
| 🐳 **Docker** with Compose v2+ | Docker 29, Compose 5 | [Docker Desktop](https://docs.docker.com/get-started/get-docker/) (Windows, macOS) or [Docker Engine](https://docs.docker.com/engine/install/) + [Compose plugin](https://docs.docker.com/compose/install/linux/) (Linux) |
| 🤖 **just**, the command runner | 1.53 | [packages for every OS](https://just.systems/man/en/packages.html) — e.g. `brew install just`, `sudo apt install just` (Ubuntu 24.04+), `cargo install just` |
| 🌱 **Git** | 2.53 | [git-scm.com](https://git-scm.com/downloads) |
| 🐍 *uv* (optional) | 0.12 | [docs.astral.sh/uv](https://docs.astral.sh/uv/getting-started/installation/) — only to lint and format the Python code on your machine (`just lint-app`) |

Check them with `docker compose version` and `just --version`.

| Platform | Status |
|---|---|
| 🐧 Linux x86-64 | ✅ the same setup as WSL2; CI runs it on Ubuntu from a fresh clone |
| 🪟 Windows | ✅ tested through **WSL2**: install [WSL](https://learn.microsoft.com/windows/wsl/install), enable Docker Desktop's [WSL integration](https://docs.docker.com/desktop/features/wsl/), and clone inside the Linux file system (`~/...`, not `/mnt/c/...`) |
| 🍎 macOS | ⚠️ untested. The Solana toolchain ships x86-64 Linux binaries, so on Apple Silicon the toolchain container runs emulated: turn on *Use Rosetta for x86_64/amd64 emulation* in Docker Desktop's settings |

Plan for **8 GB of RAM** (16 GB is comfortable) and **~20 GB of free disk**: the images and build
caches take about 7 GB, and the local validator's ledger grows with use
(see `LOCALNET_LEDGER_SHREDS` in `envs/localnet.env`).

Ports used on your machine (change them in `envs/localnet.env` if one is
taken):

| Port | Service |
|---|---|
| `8142` | web app |
| `55532` | Postgres |
| `59899` / `59900` | local validator RPC / WebSocket |

### 🪜 Step by step

`just quickstart` runs four commands. Run them yourself to see each stage,
or to resume after a failure — every one of them is safe to repeat:

| # | Command | What it does |
|---|---|---|
| 1 | `just build` | creates `envs/localnet.env` from the template (as your user), builds the Solana toolchain image, compiles the program with Anchor and copies its interface (IDL) to the app |
| 2 | `just bootstrap localnet` | builds the app image, starts Postgres, the web app and a private Solana validator, applies the migrations |
| 3 | `just deploy localnet` | creates a local deployer key, funds it from the local faucet and deploys the program |
| 4 | `just rx localnet demo` | creates the operator and authority keys, initializes the program, then seeds the demo: participants registered on-chain, a catalog, ~200 prescriptions |

> [!NOTE]
> **About the program id.** A Solana program lives at an address set by its
> keypair, which this repository does not publish. On a fresh clone,
> `just build` creates a local one and points `declare_id!`,
> `Anchor.toml` and the app's IDL at it, so `git status` shows those three
> files changed. That is expected: everything works locally under your own
> address; just don't commit them.

## 🖥️ Try it in the browser

Open <http://localhost:8142> and sign in: the login page lists the demo
accounts (one per role) and fills the form for you. A suggested tour:

1. **Prescriber** (e.g. Dr. Ana Souza) — issue a prescription: search the
   catalog by name, active ingredient, ATC code, brand or manufacturer; you
   land on its audit page. Copy its id.
2. **Pharmacy** (e.g. Central Pharmacy) — look the id up, pick the product
   handed out and dispense part of it, then try to dispense more than
   remains: the chain refuses.
3. **Medical board** (Regional Medical Council) — suspend the
   prescriber, then try dispensing again as the pharmacy: refused
   everywhere. Reinstate.
4. **Drug regulator** (National Medication Registry) — recall a
   product: the pharmacy must hand out another version. Recall the
   medication: its prescriptions go on hold for every pharmacy. Reinstate.
5. **Auditor** (Health Inspector) — open any prescription: the verdict, the
   medication and the on-chain history, without the patient's data. Every
   key and record links to the Solana explorer.
6. **Prescriber again** — open a prescription you issued: cancel it if
   nobody filled it, or discontinue what remains. The pharmacy is refused from
   then on, and the public page shows who closed it, when and why.
7. **Anyone, signed out** — open **Insights**: the case for open auditing,
   then the investigations below.

The demo seeds a small network (14 prescribers, 4 pharmacies, ~200
prescriptions) that tells the stories below. It is planned in advance and
deterministic: a run that stops half-way continues where it left, and a
second run creates nothing. Choose the size, and see the cost before
anything is sent:

| Profile | What | Devnet cost |
|---|---|---|
| `story` (default) | every investigation, with just enough peers to compare | ~0.6 SOL |
| `full` | ~4× the network around the same stories | ~2.3 SOL; meant for localnet |

```bash
just rx localnet demo --estimate                # what it would create and cost; sends nothing
just rx localnet demo --profile full
just rx devnet demo --estimate
just rx devnet demo --yes                       # a public network asks for --yes
```

### 🔎 Explore the investigations

`/insights/` needs no account. Each investigation on its home page is a
short tour whose links follow whatever stands out in the data.

1. **A new drug, pushed.** Open *New drugs*: in the SSRI class, escitalopram
   (no generic on the market) gets ~20% of a typical prescriber's
   prescriptions, but ~90% of three prescribers'. Open one of them: the same
   pattern against their peers, and each of their prescriptions links to its
   public record and its accounts on the explorer.
2. **The pharmacy without generics.** Open *Generics*: where a generic could
   have been handed out, the network chooses it about half the time; one
   pharmacy, under 10%. Its page shows which manufacturers it favours.
3. **Always the same brand.** Open *Brand locks*: one prescriber forbids
   substitution on most zolpidem prescriptions, always for the same
   manufacturer's brand; peers almost never do.
4. **Volume: one signal, two stories.** Open *Volume*: two prescribers write
   far more of a medication than their peers. One wrote quantities above the
   regulatory limit, nearly all dispensed at one pharmacy; the other stays
   within limits and is dispensed everywhere, like a specialist's practice.
   The same signal, and only the context tells them apart: the insights show
   signals for an authority to look into, never conclusions.

Anyone can browse the catalog at `/catalog/` and download it as open data.

The demo cast, manufacturers and brands are made up (active ingredients and
ATC codes are real), and will evolve with the project.

> [!WARNING]
> **Demo mode holds the participants' keys on the server** so that one
> browser can play every role; the footer says so. The program itself is
> unchanged by this: every action still needs the participant's signature,
> and the operator cannot sign for anyone. In production each participant
> signs with their own wallet.

## 🧭 Day-to-day commands

Run `just` alone to list every command with a one-line description.

| Command | What it does |
|---|---|
| `just up localnet` | start the environment again (after a reboot, or `down`) |
| `just down localnet` | stop it, keeping the chain and the database |
| `just logs localnet` | follow the logs; add a service to narrow it: `just logs localnet web` |
| `just status localnet` | deployer and operator addresses and balances; the program, if deployed |
| `just build && just deploy localnet` | rebuild and upgrade the program after changing the Rust code |
| `just reset-localnet` | wipe the local chain **and** its database together, redeploy and set up again |
| `just psql localnet` | open a SQL shell on the environment's database |

The web app reloads by itself when you edit the Python code or templates.

## ⌨️ The command line

Every action in the browser is also a command, run inside the environment
with `just rx <environment> ...`:

```bash
just rx localnet --help                         # every subcommand
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

## 🌐 Environments: localnet and devnet

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
| `program/target/deploy/rxtrail-keypair.json` | the program's address (same on every network); `just build` copies it from `.keys/rxtrail-program-keypair.json` if you have it, or creates one | no |
| `.keys/<network>/deployer.json` | publishes and upgrades the program | yes, to deploy |
| `.keys/<network>/operator.json` | pays every fee and rent deposit | yes, while in use |

Participants (boards, regulators, prescribers, pharmacies) sign but never pay.

### Devnet (public demo)

Devnet SOL is free but rationed: use the [Solana faucet](https://faucet.solana.com)
(connecting GitHub raises the limit) and check arrivals with
`just status devnet`.

```bash
just bootstrap devnet
just build               # if you haven't already
just status devnet       # deployer and operator addresses and balances
```

1. **Fund the deployer with ~3 SOL** (deploying needs about twice the
   program's rent at that moment; see [costs](#-what-it-costs)), then deploy:
   ```bash
   just deploy devnet
   just status devnet    # the program now shows up
   ```
2. **Fund the operator with ~0.3 SOL** (~1 SOL for the `story` demo). Its
   key is created by `setup`: run `just rx devnet setup` once to create it
   and print its address, fund it, then run `setup` again. Keep ~1.5 SOL in
   the deployer for future upgrades.
3. **Run the flow** with `just rx devnet ...`, as above, and the web app at
   <http://localhost:8143>.

Every address printed can be inspected on
`https://explorer.solana.com/address/<address>?cluster=devnet`.

## 💸 What it costs

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
| operator | per prescriber or pharmacy registered | 0.00094 SOL |
| operator | per medication / product in the catalog | 0.00110 / 0.00127 SOL |
| operator | **per prescription** | **0.00166 SOL** |
| operator | **per fill** | **0.00128 SOL** |
| operator | per cancellation or discontinuation | 0.00111 SOL |
| operator | per transaction | 0.000005 SOL |

Rent figures use devnet's rate (about 5,070 lamports per account byte, plus
128 bytes of overhead per account). A prescription filled in three
parts costs about **0.0055 SOL**,
almost all of it rent that stays locked as the permanent record. The
deployer pays once (and on upgrades); the operator pays as the system is
used.

## 🧪 Tests

```bash
just test             # program tests (LiteSVM) + app tests
just test-stress      # slow: 256 property cases, pharmacies racing
just test-app -k catalog   # pytest arguments pass through
```

| Suite | Runs against | Covers |
|---|---|---|
| `program/programs/rxtrail/tests` | the compiled program on LiteSVM | every on-chain guarantee, plus a property test: random sequences of requests from several pharmacies never dispense past the grant |
| `app/tests/unit` | in-memory fakes | rules mirror, document and catalog identity hashing, IDL codec, error mapping, use cases; every insight finds the pattern the demo planted, and nothing else |
| `app/tests/integration` | Postgres | off-chain store, database permissions, the web pages (who sees and does what) with the chain faked; the insights never name a person nor use an accusing word, and read public sources only |
| `app/tests/localnet` | the program deployed on the local validator | the full flow; refusals come from the chain itself (wrong product, recall, locked brand); **five pharmacies racing for the same prescription at the same time** — exactly the granted quantity lands |

App tests run in the `localnet` environment (start it first) against its own
`_test` database. The localnet suite is skipped unless the program is
deployed there (`just deploy localnet`). CI runs everything on each push,
from a fresh clone, with the same `just` commands.

## 🩺 Troubleshooting

<details>
<summary><b>"port is already allocated" when starting</b></summary>

Another program uses one of the ports. Pick free ones in `envs/localnet.env`
(`WEB_PORT`, `POSTGRES_PORT`, `LOCALNET_RPC_PORT`, `LOCALNET_WS_PORT`) and
run `just up localnet`.
</details>

<details>
<summary><b>"Permission denied" inside a container</b></summary>

The containers run as your user. `HOST_UID` and `HOST_GID` in
`envs/localnet.env` must match `id -u` and `id -g` (they do when `just`
creates the file). Fix them, then rebuild the images with
`just bootstrap localnet`.
</details>

<details>
<summary><b>The app refuses to start: <code>ChainMismatchError</code></b></summary>

The database belongs to another chain — usually the local validator's data
was wiped while the database was kept. Reset both together:
`just reset-localnet`, then `just rx localnet demo` for the demo data.
</details>

<details>
<summary><b>"service web is not running" on a <code>just rx</code> command</b></summary>

The environment is stopped (after a reboot, for instance). Start it with
`just up localnet`.
</details>

<details>
<summary><b>The validator never becomes healthy</b></summary>

Look at `just logs localnet validator`. The validator needs `io_uring`,
which `compose.yaml` allows for that container only; very old kernels or
restrictive Docker setups may still block it. On Apple Silicon, check that
Rosetta emulation is enabled in Docker Desktop.
</details>

<details>
<summary><b>The build stops with <code>SIGSEGV</code> or <code>Killed</code></b></summary>

The Rust compiler occasionally crashes on a heavy first build, or runs out
of memory. Run the same command again: it resumes from what was already
compiled. If it keeps failing, give Docker more memory (Docker Desktop:
*Settings → Resources*).
</details>

<details>
<summary><b>A step of <code>just quickstart</code> failed half-way</b></summary>

Fix the cause and run `just quickstart` again: every step is safe to
repeat, and the demo seed continues where it stopped.
</details>

## 🤝 Contributing

- Start with `just quickstart`, then `just test`: both suites should pass
  before you change anything.
- The Rust program is the source of truth. A rule change goes into the
  program first and into `app/rxtrail/rules.py` second, with tests in both.
- After changing the program, `just build` also refreshes the app's copy of
  the IDL (`app/solana_client/rxtrail_idl.json`).
- Format and lint: `just fmt-program`, `just lint-program`, and, with
  [uv](https://docs.astral.sh/uv/) installed, `just fmt-app`, `just lint-app`.
- Code, comments and docs are in English.

## 🗺️ Roadmap

- Devnet deployment
- Corrections to a fill (reversal records)
- Insights over time: filters by period, and adoption curves after a
  medication's launch
- A "reveal identity" action for the medical board only, itself
  recorded
- Wallet sign-in (each participant signs in their own wallet)
- An indexer of the program's events, so lists and dashboards stop reading
  the chain on every page view
- Upgrade authority under a multisig of authorities; verifiable builds

## 👥 Team

| Member | Links |
|---|---|
| **Gustavo Rizzo S. M. de Albuquerque** | [GitHub](https://github.com/GustavoRizzo) · [LinkedIn](https://www.linkedin.com/in/gustavo-albuquerque/) |
| **Filipi Edgar Barbosa** | [LinkedIn](https://www.linkedin.com/in/filipi-edgar-barbosa/) |
