# RxTrail task runner. Run `just` to list everything.

set dotenv-load := true
set dotenv-required := false

_default:
    @just --list --unsorted

# --- Program (Rust / Anchor) ---------------------------------------------

# Build the toolchain image (Rust, Agave, Anchor).
toolchain:
    docker compose --profile tools build chain

# Run any command in the toolchain container: `just chain anchor --version`.
chain *ARGS:
    docker compose --profile tools run --rm chain {{ARGS}}

# Compile the on-chain program and its IDL.
build:
    docker compose --profile tools run --rm chain anchor build

# Program tests (LiteSVM: in-process Solana VM, no validator needed).
test-program: build
    docker compose --profile tools run --rm chain cargo test --workspace

# Format the Rust code in place.
fmt-program:
    docker compose --profile tools run --rm chain cargo fmt --all

# Check formatting and lint the Rust code.
lint-program:
    docker compose --profile tools run --rm chain sh -c "cargo fmt --all -- --check && cargo clippy --workspace -- -D warnings"

# --- Localnet ---------------------------------------------------------------

# Start the local validator and wait until it answers.
localnet:
    docker compose --profile localnet up -d --wait localnet
    @echo "localnet up — http://localhost:${LOCALNET_RPC_PORT}"

# Stop the local validator, keeping its chain.
localnet-stop:
    docker compose --profile localnet stop localnet

# Wipe the local chain and start again from genesis.
localnet-reset:
    docker compose --profile localnet rm -sf localnet
    docker volume rm -f rxtrail_localnet-ledger
    @just localnet
