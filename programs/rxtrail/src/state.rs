//! On-chain records.
//!
//! No personal data lives here: prescriptions and patients are identified by
//! random 32-byte ids, and the full prescription document stays off-chain,
//! represented only by its salted hash.

use anchor_lang::prelude::*;

/// Who may enable participants. Set once, at initialization.
#[account]
#[derive(InitSpace)]
pub struct Config {
    /// Enables prescribers (e.g. a medical council).
    pub professional_authority: Pubkey,
    /// Enables dispensers (e.g. a health regulator).
    pub health_authority: Pubkey,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace, Debug)]
pub enum ParticipantStatus {
    Active,
    Suspended,
}

/// A prescriber enabled by the professional authority.
#[account]
#[derive(InitSpace)]
pub struct Prescriber {
    /// The prescriber's own key: the one that must sign their prescriptions.
    pub key: Pubkey,
    pub status: ParticipantStatus,
    pub registered_at: i64,
    pub bump: u8,
}

/// A dispenser (pharmacy) enabled by the health authority.
#[account]
#[derive(InitSpace)]
pub struct Dispenser {
    /// The dispenser's own key: the one that must sign its dispensations.
    pub key: Pubkey,
    pub status: ParticipantStatus,
    pub registered_at: i64,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace, Debug)]
pub enum PrescriptionStatus {
    Active,
}

/// A prescription for a controlled medication.
///
/// Created once and never rewritten: only the counters move, and only through
/// `dispense`. Each dispensation is its own immutable account.
#[account]
#[derive(InitSpace)]
pub struct Prescription {
    /// Random id; also the PDA seed.
    pub id: [u8; 32],
    /// Key of the prescriber who signed it.
    pub prescriber: Pubkey,
    /// Random patient id. Never derived from a real-world document.
    pub patient_id: [u8; 32],
    /// Salted hash of the full off-chain prescription document: proves the
    /// document was not altered after issuance, without revealing it.
    pub document_hash: [u8; 32],
    pub quantity_granted: u32,
    pub quantity_dispensed: u32,
    /// Number of dispensations so far; also the seed of the next one.
    pub dispensation_count: u32,
    pub issued_at: i64,
    pub expires_at: i64,
    pub status: PrescriptionStatus,
    pub bump: u8,
}

impl Prescription {
    pub fn remaining(&self) -> u32 {
        self.quantity_granted - self.quantity_dispensed
    }
}

/// One dispensation event. Created once; no instruction ever modifies it.
#[account]
#[derive(InitSpace)]
pub struct Dispensation {
    pub prescription: Pubkey,
    /// Position in the prescription's history: 0, 1, 2, ...
    pub index: u32,
    /// Key of the dispenser who signed it.
    pub dispenser: Pubkey,
    pub quantity: u32,
    /// Remaining quantity right after this dispensation.
    pub remaining_after: u32,
    pub dispensed_at: i64,
    pub bump: u8,
}
