use anchor_lang::prelude::*;

use crate::{
    constants::{CLOSURE_SEED, PRESCRIBER_SEED, PRESCRIPTION_SEED},
    error::RxTrailError,
    events::PrescriptionClosed,
    state::{
        ClosureKind, ClosureReason, ParticipantStatus, Prescriber, Prescription,
        PrescriptionClosure, PrescriptionStatus,
    },
};

/// The issuing prescriber closes a prescription for good.
///
/// Two explicit instructions share this context: cancel (nothing dispensed
/// yet) and stop (partly dispensed; the rest is voided). If a pharmacy
/// dispenses first, a cancel is refused rather than silently turned into a
/// stop: the prescriber's intent is never swapped for another.
///
/// A suspended prescriber cannot close anything: suspension answers a leaked
/// key, and whoever holds it must not be able to void patients' prescriptions.
#[derive(Accounts)]
pub struct ClosePrescription<'info> {
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
        mut,
        seeds = [PRESCRIPTION_SEED, prescription.id.as_ref()],
        bump = prescription.bump,
        constraint = prescription.prescriber == prescriber_signer.key()
            @ RxTrailError::NotPrescriptionIssuer
    )]
    pub prescription: Account<'info, Prescription>,
    #[account(
        init,
        payer = payer,
        space = 8 + PrescriptionClosure::INIT_SPACE,
        seeds = [CLOSURE_SEED, prescription.key().as_ref()],
        bump
    )]
    pub closure: Account<'info, PrescriptionClosure>,
    pub system_program: Program<'info, System>,
}

pub fn handle_close(
    ctx: Context<ClosePrescription>,
    kind: ClosureKind,
    reason: ClosureReason,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let prescription = &mut ctx.accounts.prescription;

    require!(
        prescription.status == PrescriptionStatus::Active,
        RxTrailError::PrescriptionNotActive
    );
    require!(
        now < prescription.expires_at,
        RxTrailError::PrescriptionExpired
    );
    match kind {
        ClosureKind::Cancelled => require!(
            prescription.dispensation_count == 0,
            RxTrailError::AlreadyDispensed
        ),
        ClosureKind::Stopped => {
            require!(
                prescription.dispensation_count > 0,
                RxTrailError::NothingDispensed
            );
            require!(prescription.remaining() > 0, RxTrailError::NothingRemaining);
        }
    }

    prescription.status = match kind {
        ClosureKind::Cancelled => PrescriptionStatus::Cancelled,
        ClosureKind::Stopped => PrescriptionStatus::Stopped,
    };
    let prescriber = ctx.accounts.prescriber_signer.key();
    let prescription_key = prescription.key();
    let quantity_dispensed = prescription.quantity_dispensed;
    let quantity_voided = prescription.remaining();
    ctx.accounts.closure.set_inner(PrescriptionClosure {
        prescription: prescription_key,
        prescriber,
        kind,
        reason,
        quantity_dispensed,
        quantity_voided,
        closed_at: now,
        bump: ctx.bumps.closure,
    });
    emit!(PrescriptionClosed {
        prescription: prescription_key,
        prescriber,
        kind,
        reason,
        quantity_dispensed,
        quantity_voided,
        closed_at: now,
    });
    Ok(())
}
