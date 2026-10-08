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

# --- Getting started ------------------------------------------------------------

# The program is built first, so the app never starts with another program's IDL.
# From a fresh clone to the browser: localnet up, program deployed, demo seeded.
quickstart:
    #!/usr/bin/env bash
    set -euo pipefail
    just build
    just bootstrap localnet
    just deploy localnet
    just rx localnet demo
    port=$(sed -n 's/^WEB_PORT=//p' envs/localnet.env)
    echo
    echo "RxTrail is running: http://localhost:${port}  (every demo password: rxtrail-demo)"

# --- Environments -------------------------------------------------------------

# Create an environment's config (envs/<env>.env, as your user) and key folder.
configure env:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -f envs/{{env}}.env ]; then
        sed "s/^HOST_UID=.*/HOST_UID=$(id -u)/; s/^HOST_GID=.*/HOST_GID=$(id -g)/" \
            envs/{{env}}.env.example > envs/{{env}}.env
        echo "created envs/{{env}}.env"
    fi
    mkdir -p -m 700 .keys/{{env}}
    mkdir -p program/target/deploy

# First run of an environment: config, images, services, migrations.
bootstrap env="localnet": (configure env)
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

# Move SOL from the operator to the deployer: `just fund-deployer devnet 1`.
fund-deployer env amount:
    #!/usr/bin/env bash
    set -euo pipefail
    url=$([ "{{env}}" = localnet ] && echo http://validator:8899 || echo https://api.{{env}}.solana.com)
    docker compose -p rxtrail-{{env}} --env-file envs/{{env}}.env --profile tools run --rm -T chain sh -c "
        solana transfer \$(solana-keygen pubkey /keys/deployer.json) {{amount}} \
            --keypair /keys/operator.json --url $url --allow-unfunded-recipient"

# Localnet: the deployer is funded from the local faucet. Devnet: it needs
# ~3.2 SOL at the moment of deploying (README: what it costs).
# Deploy the compiled program.
deploy env:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ "{{env}}" = localnet ]; then
        url=http://validator:8899
        prepare="test -f /keys/deployer.json || solana-keygen new --no-bip39-passphrase --silent -o /keys/deployer.json; solana airdrop 10 --url $url --keypair /keys/deployer.json >/dev/null;"
    else
        url=https://api.{{env}}.solana.com
        prepare="test -f /keys/deployer.json || {
            solana-keygen new --no-bip39-passphrase --silent -o /keys/deployer.json
            echo \"new deployer \$(solana-keygen pubkey /keys/deployer.json): fund it with ~3.2 SOL, then deploy again\"
            exit 1; };"
    fi
    docker compose -p rxtrail-{{env}} --env-file envs/{{env}}.env --profile tools run --rm -T chain sh -c "$prepare
        solana program deploy target/deploy/rxtrail.so \
            --program-id target/deploy/rxtrail-keypair.json \
            --keypair /keys/deployer.json --url $url"

# Anchor 1.x stores the IDL with the Program Metadata program through its
# npm CLI, so this runs in a Node container. Public networks only: a local
# validator does not have that program. Signed by the deployer (the upgrade
# authority); the first upload costs ~0.03 SOL of rent.
# Publish the program's IDL on-chain, so explorers decode its instructions.
publish-idl env:
    docker run --rm \
        -v "$PWD/.keys/{{env}}/deployer.json:/keys/deployer.json:ro" \
        -v "$PWD/program/target/idl/rxtrail.json:/idl/rxtrail.json:ro" \
        node:24-slim npx --yes @solana-program/program-metadata@0.10.0 \
        write idl "$(sed -n 's/^  "address": "\(.*\)",$/\1/p' program/target/idl/rxtrail.json)" /idl/rxtrail.json \
        --keypair /keys/deployer.json --rpc https://api.{{env}}.solana.com --priority-fees 0

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

# The chain keeps only half of each record: names, logins, patients and the
# participants' keys live here. Lose them and the on-chain records can no
# longer be used, and seeding again pays for every record again. Copy the
# archive off this machine: it holds private keys.
# Back up an environment's database and keys to .keys/backups/ (or DIR).
backup env dir=".keys/backups":
    #!/usr/bin/env bash
    set -euo pipefail
    stamp=$(date -u +%Y%m%d-%H%M%S)
    work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
    dc() { docker compose -p rxtrail-{{env}} --env-file envs/{{env}}.env "$@"; }
    dc exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB" -n transactional' > "$work/db.dump"
    cp -p .keys/{{env}}/*.json "$work/"
    {
        echo "environment: {{env}}"
        echo "taken: $(date -u +%FT%TZ)"
        echo "commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
        echo "keys: $(ls .keys/{{env}}/*.json | wc -l)"
        echo "select 'chain: ' || network || ' genesis ' || genesis_hash || ' program ' || program_id
              from transactional.records_chainbinding" |
            dc exec -T db sh -c 'psql -At -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    } > "$work/MANIFEST"
    mkdir -p -m 700 "{{dir}}"
    out="{{dir}}/rxtrail-{{env}}-$stamp.tar.gz"
    tar -czf "$out" -C "$work" .
    chmod 600 "$out"
    cat "$work/MANIFEST"
    echo "backup: $out ($(du -h "$out" | cut -f1)) — copy it off this machine"

# Keys already in .keys/<env>/ are kept; a different key under the same name
# stops the restore before anything changes.
# Restore an environment's database and keys from a `backup` archive.
restore env archive:
    #!/usr/bin/env bash
    set -euo pipefail
    work=$(mktemp -d); trap 'rm -rf "$work"' EXIT
    tar -xzf "{{archive}}" -C "$work"
    grep -q "^environment: {{env}}$" "$work/MANIFEST" || { echo "not a {{env}} backup:"; cat "$work/MANIFEST"; exit 1; }
    for key in "$work"/*.json; do
        name=.keys/{{env}}/$(basename "$key")
        if [ -f "$name" ] && ! cmp -s "$key" "$name"; then
            echo "refusing: $name differs from the backup's"; exit 1
        fi
    done
    mkdir -p -m 700 .keys/{{env}}
    for key in "$work"/*.json; do
        [ -f ".keys/{{env}}/$(basename "$key")" ] || cp -p "$key" .keys/{{env}}/
    done
    dc() { docker compose -p rxtrail-{{env}} --env-file envs/{{env}}.env "$@"; }
    dc up -d --wait db
    dc stop web
    dc exec -T db sh -c 'pg_restore --clean --if-exists -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$work/db.dump"
    dc up -d --wait web
    cat "$work/MANIFEST"
    echo "restored."

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

# Taken from .keys/rxtrail-program-keypair.json when you have the project's
# key; otherwise a new local one, with the source (declare_id!, Anchor.toml)
# pointed at it, so a fresh clone builds and deploys under its own address.
# The program's address keypair, needed to deploy (`build` runs this).
program-id:
    #!/usr/bin/env bash
    set -euo pipefail
    key=program/target/deploy/rxtrail-keypair.json
    [ -f "$key" ] && exit 0
    mkdir -p program/target/deploy
    if [ -f .keys/rxtrail-program-keypair.json ]; then
        cp .keys/rxtrail-program-keypair.json "$key"
        exit 0
    fi
    docker compose -p rxtrail-localnet --env-file envs/localnet.env --profile tools run --rm -T chain sh -c \
        "solana-keygen new --no-bip39-passphrase --silent -o target/deploy/rxtrail-keypair.json && anchor keys sync"
    echo "note: this clone deploys under its own program id. Three files now carry it"
    echo "      (lib.rs, Anchor.toml and, after the build, the app's IDL): don't commit them."

# Compile the program; copy its IDL (the program's interface) to the app.
build: (configure "localnet") program-id
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
