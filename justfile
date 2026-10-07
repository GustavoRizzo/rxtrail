# RxTrail task runner. Run `just` to list everything.
#
# Environments: `localnet` (private validator, development) and `devnet`
# (Solana's public test network). One environment = one network = one
# database = one key set (.keys/<network>/); both can run side by side.

# Arguments reach commands one by one, quotes intact ("Maria Silva" stays one).
set positional-arguments := true

_default:
    @just --list --unsorted

# Docker Compose scoped to one environment: `just dc localnet ps`.
dc env *ARGS:
    @env="$1"; shift; docker compose -p "rxtrail-$env" --env-file "envs/$env.env" "$@"

# --- Environments -------------------------------------------------------------

# First run of an environment: config, images, services, migrations.
bootstrap env="localnet":
    @test -f envs/{{env}}.env || cp envs/{{env}}.env.example envs/{{env}}.env
    @mkdir -p -m 700 .keys/{{env}}
    just dc {{env}} --profile tools build
    just dc {{env}} up -d --wait
    just dc {{env}} exec web python manage.py migrate

# Start an environment's services (localnet also starts its validator).
up env:
    just dc {{env}} up -d --wait

# Stop an environment, keeping its data.
down env:
    just dc {{env}} --profile tools down

# Follow an environment's logs: `just logs localnet web`.
logs env *SERVICES:
    @env="$1"; shift; docker compose -p "rxtrail-$env" --env-file "envs/$env.env" logs -f --tail=50 "$@"

# Addresses and balances of the deployer and operator; the program, if deployed.
status env:
    #!/usr/bin/env bash
    set -euo pipefail
    url=$([ "{{env}}" = localnet ] && echo http://validator:8899 || echo https://api.{{env}}.solana.com)
    docker compose -p rxtrail-{{env}} --env-file envs/{{env}}.env --profile tools run --rm -T chain sh -c "
        for k in deployer operator; do
            if [ -f /keys/\$k.json ]; then
                echo \"\$k \$(solana-keygen pubkey /keys/\$k.json) \$(solana balance /keys/\$k.json --url $url)\"
            else
                echo \"\$k (no key yet)\"
            fi
        done
        program=\$(solana-keygen pubkey target/deploy/rxtrail-keypair.json)
        echo \"program \$program\"
        solana program show \$program --url $url --keypair /keys/deployer.json 2>&1 | head -3 || true"

# Deploy the compiled program. Localnet: deployer funded from the local faucet.
# Devnet: the deployer needs ~2.1 SOL at the moment of deploying.
deploy env:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{env}}" = localnet ]; then
        url=http://validator:8899
        prepare="test -f /keys/deployer.json || solana-keygen new --no-bip39-passphrase --silent -o /keys/deployer.json; solana airdrop 10 --url $url --keypair /keys/deployer.json >/dev/null;"
    else
        url=https://api.{{env}}.solana.com
        prepare=""
    fi
    docker compose -p rxtrail-{{env}} --env-file envs/{{env}}.env --profile tools run --rm -T chain sh -c "$prepare
        solana program deploy target/deploy/rxtrail.so \
            --program-id target/deploy/rxtrail-keypair.json \
            --keypair /keys/deployer.json --url $url"

# The `rxtrail` command: `just rx localnet issue dr-ana ...`.
rx env *ARGS:
    @env="$1"; shift; docker compose -p "rxtrail-$env" --env-file "envs/$env.env" exec web python manage.py rxtrail "$@"

# Any manage.py command in an environment.
manage env *ARGS:
    @env="$1"; shift; docker compose -p "rxtrail-$env" --env-file "envs/$env.env" exec web python manage.py "$@"

# Apply database migrations in an environment.
migrate env:
    just dc {{env}} exec web python manage.py migrate

# Open psql in an environment's database.
psql env:
    just dc {{env}} exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'

# Wipe the local chain AND its database together, then set everything up again.
reset-localnet:
    just dc localnet --profile tools down
    docker volume rm -f rxtrail-localnet_ledger rxtrail-localnet_pgdata
    just dc localnet up -d --wait
    just dc localnet exec web python manage.py migrate
    just deploy localnet
    just rx localnet setup

# --- On-chain program (program/: Rust, Anchor) ----------------------------------

# Run any command in the toolchain container: `just chain anchor --version`.
chain *ARGS:
    @docker compose -p rxtrail-localnet --env-file envs/localnet.env --profile tools run --rm chain "$@"

# Compile the program; copy its IDL (the program's interface) to the app.
build:
    just dc localnet --profile tools run --rm chain anchor build
    cp program/target/idl/rxtrail.json app/solana_client/rxtrail_idl.json

# Program tests on LiteSVM (in-process Solana VM, no validator needed).
test-program: build
    just dc localnet --profile tools run --rm -e PROPTEST_CASES=16 chain cargo test --workspace

# Format the Rust code in place.
fmt-program:
    just dc localnet --profile tools run --rm chain cargo fmt --all

# Check formatting and lint the Rust code.
lint-program:
    just dc localnet --profile tools run --rm chain sh -c "cargo fmt --all -- --check && cargo clippy --workspace -- -D warnings"

# --- App (app/: Python, Django) ---------------------------------------------------

# App tests, in the localnet environment, against its "_test" database.
test-app *ARGS:
    @docker compose -p rxtrail-localnet --env-file envs/localnet.env exec web sh -c 'POSTGRES_DB="${POSTGRES_DB}_test" exec pytest "$@"' pytest "$@"

# Format and lint the Python code.
lint-app:
    cd app && uv run ruff format --check . && uv run ruff check .

# Format the Python code in place.
fmt-app:
    cd app && uv run ruff format . && uv run ruff check --fix .

# Every everyday test: program (LiteSVM) and app. Fast; stress tests excluded.
test: test-program test-app

# Load and concurrency tests (slow): 256 property cases, pharmacies racing.
test-stress: build
    just dc localnet --profile tools run --rm -e PROPTEST_CASES=256 chain cargo test --workspace
    @docker compose -p rxtrail-localnet --env-file envs/localnet.env exec web sh -c 'POSTGRES_DB="${POSTGRES_DB}_test" exec pytest -m stress -v'
