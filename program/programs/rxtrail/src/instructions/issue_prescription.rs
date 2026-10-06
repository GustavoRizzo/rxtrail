use anchor_lang::prelude::*;

use crate::{
    constants::{PRESCRIBER_SEED, PRESCRIPTION_SEED},
    error::RxTrailError,
    events::PrescriptionIssued,
    state::{ParticipantStatus, Prescriber, Prescription, PrescriptionStatus},
};

/// An active prescriber issues a prescription, signing with their own key.
///
/// The prescriber record is found by the signer's key, so nobody can issue in
/// someone else's name: without that key's signature there is no record to
/// match, and the operator who pays the fees cannot sign for a prescriber.
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
    patient_id: [u8; 32],
    document_hash: [u8; 32],
    quantity: u32,
    expires_at: i64,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    require!(quantity > 0, RxTrailError::InvalidQuantity);
    require!(expires_at > now, RxTrailError::ExpiryInThePast);

    let prescriber = ctx.accounts.prescriber_signer.key();
    ctx.accounts.prescription.set_inner(Prescription {
        id,
        prescriber,
        patient_id,
        document_hash,
        quantity_granted: quantity,
        quantity_dispensed: 0,
        dispensation_count: 0,
        issued_at: now,
        expires_at,
        status: PrescriptionStatus::Active,
        bump: ctx.bumps.prescription,
    });
    emit!(PrescriptionIssued {
        prescription: ctx.accounts.prescription.key(),
        prescriber,
        quantity_granted: quantity,
        expires_at,
    });
    Ok(())
}
