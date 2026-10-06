# RxTrail task runner. Run `just` to list everything.

set dotenv-load := true
set dotenv-required := false

_default:
    @just --list --unsorted

# --- Setup ------------------------------------------------------------------

# First run: .env, images, database, migrations.
bootstrap:
    @test -f .env || cp .env.example .env
    docker compose --profile tools build
    docker compose up -d --wait db web
    @just migrate

# --- On-chain program (program/: Rust, Anchor) ------------------------------

# Run any command in the toolchain container: `just chain anchor --version`.
chain *ARGS:
    docker compose --profile tools run --rm chain {{ARGS}}

# Compile the program; copy its IDL (the program's interface) to the app.
build:
    docker compose --profile tools run --rm chain anchor build
    cp program/target/idl/rxtrail.json app/solana_client/rxtrail_idl.json

# Program tests on LiteSVM (in-process Solana VM, no validator needed).
test-program: build
    docker compose --profile tools run --rm chain cargo test --workspace

# Format the Rust code in place.
fmt-program:
    docker compose --profile tools run --rm chain cargo fmt --all

# Check formatting and lint the Rust code.
lint-program:
    docker compose --profile tools run --rm chain sh -c "cargo fmt --all -- --check && cargo clippy --workspace -- -D warnings"

# Deploy the compiled program to the local validator (start it first).
deploy-localnet:
    docker compose --profile tools run --rm chain sh -c '\
        test -f /keys/deployer.json || solana-keygen new --no-bip39-passphrase --silent -o /keys/deployer.json; \
        solana airdrop 10 --url http://localnet:8899 --keypair /keys/deployer.json >/dev/null; \
        solana program deploy target/deploy/rxtrail.so \
            --program-id target/deploy/rxtrail-keypair.json \
            --keypair /keys/deployer.json --url http://localnet:8899'

# Addresses and devnet balances of the deployer and the operator.
devnet-status:
    @docker compose --profile tools run --rm chain sh -c '\
        for k in deployer operator; do \
            echo "$k $(solana-keygen pubkey /keys/$k.json) $(solana balance /keys/$k.json --url https://api.devnet.solana.com)"; \
        done; \
        echo "program $(solana-keygen pubkey target/deploy/rxtrail-keypair.json)"; \
        solana program show $(solana-keygen pubkey target/deploy/rxtrail-keypair.json) \
            --keypair /keys/deployer.json --url https://api.devnet.solana.com 2>&1 | head -3'

# Deploy the compiled program to devnet. The deployer needs ~2.1 SOL during
# the deploy (program account + a temporary buffer, refunded after).
deploy-devnet:
    docker compose --profile tools run --rm chain solana program deploy target/deploy/rxtrail.so \
        --program-id target/deploy/rxtrail-keypair.json \
        --keypair /keys/deployer.json --url https://api.devnet.solana.com

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

# --- App (app/: Python, Django) -----------------------------------------------

# Start the database and the web app.
up:
    docker compose up -d --wait db web

# Stop everything, keeping data.
down:
    docker compose --profile localnet --profile tools down

# Run any manage.py command: `just manage rxtrail status`.
manage *ARGS:
    docker compose exec web python manage.py {{ARGS}}

# The `rxtrail` command on a network: `just rx devnet issue dr-ana ...`.
rx network *ARGS:
    docker compose exec -e SOLANA_NETWORK={{network}} web python manage.py rxtrail {{ARGS}}

# Apply database migrations.
migrate:
    docker compose exec web python manage.py migrate

# Generate migrations for the off-chain records.
migrations:
    docker compose exec web python manage.py makemigrations records

# App tests in the container (test database; localnet tests need a deployed program).
test-app *ARGS:
    docker compose exec -e POSTGRES_DB="${POSTGRES_DB}_test" web pytest {{ARGS}}

# Format and lint the Python code.
lint-app:
    cd app && uv run ruff format --check . && uv run ruff check .

# Format the Python code in place.
fmt-app:
    cd app && uv run ruff format . && uv run ruff check --fix .

# Every test: program (LiteSVM) and app.
test: test-program test-app

# --- Database -----------------------------------------------------------------

# (Re)create the store's schema and user (idempotent).
db-init:
    docker compose exec db /docker-entrypoint-initdb.d/10-stores.sh

# Open psql as the superuser.
psql:
    docker compose exec db psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"

# Delete every volume: database, local chain, caches.
nuke:
    docker compose --profile localnet --profile tools down -v
