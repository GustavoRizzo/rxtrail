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
    pub medication: Pubkey,
    pub prescribed_product: Option<Pubkey>,
    pub quantity_granted: u32,
    pub expires_at: i64,
}

#[event]
pub struct MedicationDispensed {
    pub prescription: Pubkey,
    pub dispensation: Pubkey,
    pub dispenser: Pubkey,
    pub product: Pubkey,
    pub quantity: u32,
    pub remaining_after: u32,
}

#[event]
pub struct MedicationRegistered {
    pub medication: Pubkey,
    pub identity_hash: [u8; 32],
    pub registered_at: i64,
}

#[event]
pub struct ProductRegistered {
    pub product: Pubkey,
    pub medication: Pubkey,
    pub identity_hash: [u8; 32],
    pub registered_at: i64,
}

#[event]
pub struct CatalogStatusChanged {
    /// The medication or product account.
    pub entry: Pubkey,
    /// True for a medication, false for a product.
    pub is_medication: bool,
    pub status: crate::state::CatalogStatus,
    pub changed_at: i64,
}

#[event]
pub struct ParticipantStatusChanged {
    /// The participant's own key.
    pub participant: Pubkey,
    /// True for a prescriber, false for a dispenser.
    pub is_prescriber: bool,
    pub status: crate::state::ParticipantStatus,
    pub changed_at: i64,
}

#[event]
pub struct PrescriptionClosed {
    pub prescription: Pubkey,
    pub prescriber: Pubkey,
    pub kind: crate::state::ClosureKind,
    pub reason: crate::state::ClosureReason,
    pub quantity_dispensed: u32,
    pub quantity_voided: u32,
    pub closed_at: i64,
}
