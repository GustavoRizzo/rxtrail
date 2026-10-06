//! PDA seeds. Every account the program owns lives at an address derived from
//! one of these, so anyone can recompute where a record must be.

pub const CONFIG_SEED: &[u8] = b"config";
pub const PRESCRIBER_SEED: &[u8] = b"prescriber";
pub const DISPENSER_SEED: &[u8] = b"dispenser";
pub const PRESCRIPTION_SEED: &[u8] = b"prescription";
pub const DISPENSATION_SEED: &[u8] = b"dispensation";
