#!/usr/bin/env bash
# Single-node Solana cluster for development and tests.
#
# Agave 4.x binds every service (RPC included) to --bind-address and refuses
# 0.0.0.0, so bind to this container's own IP: other containers reach it as
# `localnet`, and Docker's port mapping forwards host traffic to it.
set -euo pipefail

ip="$(hostname -i | awk '{print $1}')"
exec solana-test-validator \
    --ledger /home/builder/ledger \
    --bind-address "$ip" \
    --limit-ledger-size "${LOCALNET_LEDGER_SHREDS:-2000000}" \
    --quiet \
    "$@"
