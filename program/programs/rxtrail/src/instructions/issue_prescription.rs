use anchor_lang::prelude::*;

use crate::{
    constants::{MEDICATION_SEED, PRESCRIBER_SEED, PRESCRIPTION_SEED, PRODUCT_SEED},
    error::RxTrailError,
    events::PrescriptionIssued,
    state::{
        CatalogStatus, Medication, ParticipantStatus, Prescriber, Prescription, PrescriptionStatus,
        Product,
    },
};

/// An active prescriber issues a prescription, signing with their own key.
///
/// The prescriber record is found by the signer's key, so nobody can issue in
/// someone else's name: without that key's signature there is no record to
/// match, and the operator who pays the fees cannot sign for a prescriber.
///
/// The prescription names a catalog medication that is not withdrawn. The
/// prescriber may also lock one of its products ("do not substitute").
#[derive(Accounts)]
#[instruction(id: [u8; 32])]
pub struct IssuePrescription<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    pub prescriber_signer: Signer<'info>,
    #[account(
        seeds = [PRESCRIBER_SEED, prescriber_signer.key().as_ref()],
        bump = prescriber.bump,
        constraint = prescriber.status == ParticipantStatus::Active
            @ RxTrailError::PrescriberNotActive
    )]
    pub prescriber: Account<'info, Prescriber>,
    #[account(
        seeds = [MEDICATION_SEED, medication.id.as_ref()],
        bump = medication.bump,
        constraint = medication.status == CatalogStatus::Active
            @ RxTrailError::MedicationNotActive
    )]
    pub medication: Account<'info, Medication>,
    /// The locked product, if any: it must be a version of `medication`.
    #[account(
        seeds = [PRODUCT_SEED, prescribed_product.id.as_ref()],
        bump = prescribed_product.bump,
        constraint = prescribed_product.medication == medication.key()
            @ RxTrailError::ProductMedicationMismatch,
        constraint = prescribed_product.status == CatalogStatus::Active
            @ RxTrailError::ProductNotActive
    )]
    pub prescribed_product: Option<Account<'info, Product>>,
    #[account(
        init,
        payer = payer,
        space = 8 + Prescription::INIT_SPACE,
        seeds = [PRESCRIPTION_SEED, id.as_ref()],
        bump
    )]
    pub prescription: Account<'info, Prescription>,
    pub system_program: Program<'info, System>,
}

pub fn handle_issue_prescription(
    ctx: Context<IssuePrescription>,
    id: [u8; 32],
    document_hash: [u8; 32],
    quantity: u32,
    expires_at: i64,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    require!(quantity > 0, RxTrailError::InvalidQuantity);
    require!(expires_at > now, RxTrailError::ExpiryInThePast);

    let prescriber = ctx.accounts.prescriber_signer.key();
    let medication = ctx.accounts.medication.key();
    let prescribed_product = ctx.accounts.prescribed_product.as_ref().map(|p| p.key());
    ctx.accounts.prescription.set_inner(Prescription {
        id,
        prescriber,
        medication,
        document_hash,
        quantity_granted: quantity,
        quantity_dispensed: 0,
        dispensation_count: 0,
        issued_at: now,
        expires_at,
        status: PrescriptionStatus::Active,
        prescribed_product,
        bump: ctx.bumps.prescription,
    });
    emit!(PrescriptionIssued {
        prescription: ctx.accounts.prescription.key(),
        prescriber,
        medication,
        prescribed_product,
        quantity_granted: quantity,
        expires_at,
    });
    Ok(())
}
