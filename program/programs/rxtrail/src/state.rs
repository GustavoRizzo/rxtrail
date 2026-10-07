//! On-chain records.
//!
//! No personal data lives here: prescriptions are identified by random 32-byte
//! ids, nothing identifies the patient, and the full prescription document
//! stays off-chain, represented only by its salted hash.
//!
//! Only what a rule needs, or what must never be rewritten, is stored. The
//! catalog's names, classes and dosage guidance live off-chain, published as
//! open data; each catalog record pins its meaning with an identity hash.

use anchor_lang::prelude::*;

/// Who may enable participants. Set once, at initialization.
#[account]
#[derive(InitSpace)]
pub struct Config {
    /// Enables prescribers (e.g. a medical council).
    pub professional_authority: Pubkey,
    /// Enables dispensers (e.g. a health regulator).
    pub health_authority: Pubkey,
    /// Registers and withdraws medications and products (e.g. a drug regulator).
    pub catalog_authority: Pubkey,
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
    /// When the status last changed (registration, suspension, reinstatement).
    pub status_changed_at: i64,
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
    /// When the status last changed (registration, suspension, reinstatement).
    pub status_changed_at: i64,
    pub bump: u8,
}

#[derive(AnchorSerialize, AnchorDeserialize, Clone, Copy, PartialEq, Eq, InitSpace, Debug)]
pub enum CatalogStatus {
    Active,
    /// Recalled: nothing new may be prescribed or dispensed against it.
    Withdrawn,
}

/// A medication in the catalog: an active ingredient, strength and form
/// (e.g. clonazepam 2 mg tablet). What a prescriber prescribes.
#[account]
#[derive(InitSpace)]
pub struct Medication {
    /// Random id; also the PDA seed.
    pub id: [u8; 32],
    /// sha256 of the fields that define the medication, as published in the
    /// off-chain catalog. Written once: the meaning of this record can never
    /// be rewritten, while names and guidance stay off-chain.
    pub identity_hash: [u8; 32],
    pub status: CatalogStatus,
    pub registered_at: i64,
    /// When the status last changed (registration, withdrawal, reinstatement).
    pub status_changed_at: i64,
    pub bump: u8,
}

/// A medication as one manufacturer makes it: the box a pharmacy hands out.
#[account]
#[derive(InitSpace)]
pub struct Product {
    /// Random id; also the PDA seed.
    pub id: [u8; 32],
    /// The medication this product is a version of.
    pub medication: Pubkey,
    /// sha256 of the fields that define the product (medication, manufacturer,
    /// brand, kind). Written once.
    pub identity_hash: [u8; 32],
    pub status: CatalogStatus,
    pub registered_at: i64,
    pub status_changed_at: i64,
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
    /// The catalog medication prescribed (its account address).
    pub medication: Pubkey,
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
    /// Set when the prescriber locked a product ("do not substitute"): only
    /// that one may be dispensed. Last, so the fixed-size fields before it keep
    /// fixed offsets for filtered queries.
    pub prescribed_product: Option<Pubkey>,
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
    /// The product handed out (its account address).
    pub product: Pubkey,
    pub quantity: u32,
    /// Remaining quantity right after this dispensation.
    pub remaining_after: u32,
    pub dispensed_at: i64,
    pub bump: u8,
}
