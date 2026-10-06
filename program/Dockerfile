# Solana toolchain in one image: Rust, Agave (validator, CLI, SBF compiler)
# and the Anchor CLI. Used both to build/test the program and to run a local
# single-node cluster.
FROM debian:trixie-slim

ARG AGAVE_VERSION=v4.3.0
ARG ANCHOR_VERSION=1.2.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential bzip2 ca-certificates curl git libssl-dev libudev-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 builder \
    && mkdir /work && chown builder:builder /work
USER builder
WORKDIR /home/builder

ENV PATH="/home/builder/.cargo/bin:/home/builder/.local/share/solana/install/active_release/bin:/home/builder/.local/bin:${PATH}"

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal \
    && curl -sSfL "https://release.anza.xyz/${AGAVE_VERSION}/install" | sh \
    && mkdir -p /home/builder/.local/bin \
    && curl -sSfL -o /home/builder/.local/bin/anchor \
        "https://github.com/solana-foundation/anchor/releases/download/v${ANCHOR_VERSION}/anchor-${ANCHOR_VERSION}-x86_64-unknown-linux-gnu" \
    && chmod +x /home/builder/.local/bin/anchor \
    # Pre-created so named volumes mounted here are owned by this user.
    && mkdir -p /home/builder/ledger /home/builder/.cache/solana /home/builder/.cargo/registry

COPY --chmod=755 localnet-entrypoint.sh /usr/local/bin/localnet-entrypoint

WORKDIR /work
