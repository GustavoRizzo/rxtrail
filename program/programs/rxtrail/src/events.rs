//! Events emitted for off-chain indexers. The accounts remain the source of
//! truth: logs are pruned by nodes, accounts are not.

use anchor_lang::prelude::*;

#[event]
pub struct PrescriberRegistered {
    pub prescriber: Pubkey,
    pub registered_at: i64,
}

#[event]
pub struct DispenserRegistered {
    pub dispenser: Pubkey,
    pub registered_at: i64,
}

#[event]
pub struct PrescriptionIssued {
    pub prescription: Pubkey,
    pub prescriber: Pubkey,
    pub quantity_granted: u32,
    pub expires_at: i64,
}

#[event]
pub struct MedicationDispensed {
    pub prescription: Pubkey,
    pub dispensation: Pubkey,
    pub dispenser: Pubkey,
    pub quantity: u32,
    pub remaining_after: u32,
}
