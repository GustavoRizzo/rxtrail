"""Adapter between the domain and the RxTrail on-chain program.

The only package that knows about solana-py, solders, keypairs and the
program's binary format. It reads everything about the program (instruction
layouts, account layouts, error codes) from the IDL Anchor generates
(`rxtrail_idl.json`, refreshed by `just build`), so a change in the Rust
program needs no hand-copied constants here.
"""
