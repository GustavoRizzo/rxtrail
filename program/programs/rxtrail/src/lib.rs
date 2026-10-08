//! RxTrail: tamper-proof dispensing limits for controlled prescriptions.
//!
//! Authorities enable prescribers and dispensers and keep the medication
//! catalog; prescribers issue prescriptions for a catalog medication with a
//! granted quantity; dispensers record each hand-out and the product given.
//! The program guarantees the total dispensed never exceeds the quantity
//! granted, and every event stays on-chain as its own immutable account.
//!
//! Whoever pays the fees (the operator) never authorizes anything: each action
//! requires the signature of the participant it is attributed to.

pub mod constants;
pub mod error;
pub mod events;
pub mod instructions;
pub mod state;

use anchor_lang::prelude::*;

pub use constants::*;
pub use instructions::*;
pub use state::*;

declare_id!("Hv1GvjSSoF4naRh7wduFJ8x4dJi3E9W3VJ2u544uLrYC");

#[program]
pub mod rxtrail {
    use super::*;

    pub fn initialize(
        ctx: Context<Initialize>,
        professional_authority: Pubkey,
        health_authority: Pubkey,
        catalog_authority: Pubkey,
    ) -> Result<()> {
        instructions::initialize::handle_initialize(
            ctx,
            professional_authority,
            health_authority,
            catalog_authority,
        )
    }

    pub fn register_prescriber(
        ctx: Context<RegisterPrescriber>,
        prescriber_key: Pubkey,
    ) -> Result<()> {
        instructions::register_prescriber::handle_register_prescriber(ctx, prescriber_key)
    }

    pub fn register_dispenser(
        ctx: Context<RegisterDispenser>,
        dispenser_key: Pubkey,
    ) -> Result<()> {
        instructions::register_dispenser::handle_register_dispenser(ctx, dispenser_key)
    }

    pub fn register_medication(
        ctx: Context<RegisterMedication>,
        id: [u8; 32],
        identity_hash: [u8; 32],
    ) -> Result<()> {
        instructions::catalog::handle_register_medication(ctx, id, identity_hash)
    }

    pub fn register_product(
        ctx: Context<RegisterProduct>,
        id: [u8; 32],
        identity_hash: [u8; 32],
    ) -> Result<()> {
        instructions::catalog::handle_register_product(ctx, id, identity_hash)
    }

    /// Withdraw (recall) or reinstate a medication (catalog authority only).
    pub fn set_medication_status(
        ctx: Context<SetMedicationStatus>,
        status: CatalogStatus,
    ) -> Result<()> {
        instructions::catalog::handle_set_medication_status(ctx, status)
    }

    /// Withdraw (recall) or reinstate a product (catalog authority only).
    pub fn set_product_status(ctx: Context<SetProductStatus>, status: CatalogStatus) -> Result<()> {
        instructions::catalog::handle_set_product_status(ctx, status)
    }

    pub fn issue_prescription(
        ctx: Context<IssuePrescription>,
        id: [u8; 32],
        document_hash: [u8; 32],
        quantity: u32,
        expires_at: i64,
    ) -> Result<()> {
        instructions::issue_prescription::handle_issue_prescription(
            ctx,
            id,
            document_hash,
            quantity,
            expires_at,
        )
    }

    pub fn dispense(ctx: Context<Dispense>, quantity: u32) -> Result<()> {
        instructions::dispense::handle_dispense(ctx, quantity)
    }

    /// The issuing prescriber cancels a prescription nobody dispensed yet.
    pub fn cancel_prescription(
        ctx: Context<ClosePrescription>,
        reason: ClosureReason,
    ) -> Result<()> {
        instructions::close_prescription::handle_close(ctx, ClosureKind::Cancelled, reason)
    }

    /// The issuing prescriber stops a partly dispensed prescription: what
    /// remains can no longer be dispensed.
    pub fn stop_prescription(ctx: Context<ClosePrescription>, reason: ClosureReason) -> Result<()> {
        instructions::close_prescription::handle_close(ctx, ClosureKind::Stopped, reason)
    }

    /// Suspend or reinstate a prescriber (professional authority only).
    pub fn set_prescriber_status(
        ctx: Context<SetPrescriberStatus>,
        status: ParticipantStatus,
    ) -> Result<()> {
        instructions::set_status::handle_set_prescriber_status(ctx, status)
    }

    /// Suspend or reinstate a dispenser (health authority only).
    pub fn set_dispenser_status(
        ctx: Context<SetDispenserStatus>,
        status: ParticipantStatus,
    ) -> Result<()> {
        instructions::set_status::handle_set_dispenser_status(ctx, status)
    }
}
