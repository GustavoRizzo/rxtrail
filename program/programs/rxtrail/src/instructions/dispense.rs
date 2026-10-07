use anchor_lang::prelude::*;

use crate::{
    constants::{
        DISPENSATION_SEED, DISPENSER_SEED, PRESCRIBER_SEED, PRESCRIPTION_SEED, PRODUCT_SEED,
    },
    error::RxTrailError,
    events::MedicationDispensed,
    state::{
        CatalogStatus, Dispensation, Dispenser, Medication, ParticipantStatus, Prescriber,
        Prescription, PrescriptionStatus, Product,
    },
};

/// An active dispenser hands out medication against a prescription.
///
/// The core guarantee lives here: the total dispensed can never exceed the
/// quantity granted. Two dispensers racing on the same prescription both write
/// to its account, so the network runs them one after the other; the second
/// sees the first's counter and is refused if not enough remains.
///
/// The dispenser records which product it hands out. It must be a version of
/// the prescribed medication (the locked one, if the prescriber locked one),
/// and neither may be withdrawn: a recall reaches every pharmacy at once.
#[derive(Accounts)]
pub struct Dispense<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    pub dispenser_signer: Signer<'info>,
    #[account(
        seeds = [DISPENSER_SEED, dispenser_signer.key().as_ref()],
        bump = dispenser.bump,
        constraint = dispenser.status == ParticipantStatus::Active
            @ RxTrailError::DispenserNotActive
    )]
    pub dispenser: Account<'info, Dispenser>,
    #[account(
        mut,
        seeds = [PRESCRIPTION_SEED, prescription.id.as_ref()],
        bump = prescription.bump
    )]
    pub prescription: Account<'info, Prescription>,
    /// The prescription's prescriber must still be active: a suspended
    /// prescriber's prescriptions stop being dispensable.
    #[account(
        seeds = [PRESCRIBER_SEED, prescription.prescriber.as_ref()],
        bump = prescriber.bump,
        constraint = prescriber.status == ParticipantStatus::Active
            @ RxTrailError::PrescriberNotActive
    )]
    pub prescriber: Account<'info, Prescriber>,
    /// The prescribed medication: a withdrawn one freezes its prescriptions.
    #[account(
        address = prescription.medication,
        constraint = medication.status == CatalogStatus::Active
            @ RxTrailError::MedicationNotActive
    )]
    pub medication: Account<'info, Medication>,
    #[account(
        seeds = [PRODUCT_SEED, product.id.as_ref()],
        bump = product.bump,
        constraint = product.medication == prescription.medication
            @ RxTrailError::ProductMedicationMismatch,
        constraint = product.status == CatalogStatus::Active
            @ RxTrailError::ProductNotActive,
        constraint = prescription.prescribed_product.is_none_or(|locked| locked == product.key())
            @ RxTrailError::PrescribedProductMismatch
    )]
    pub product: Account<'info, Product>,
    #[account(
        init,
        payer = payer,
        space = 8 + Dispensation::INIT_SPACE,
        seeds = [
            DISPENSATION_SEED,
            prescription.key().as_ref(),
            &prescription.dispensation_count.to_le_bytes(),
        ],
        bump
    )]
    pub dispensation: Account<'info, Dispensation>,
    pub system_program: Program<'info, System>,
}

pub fn handle_dispense(ctx: Context<Dispense>, quantity: u32) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let prescription = &mut ctx.accounts.prescription;

    require!(quantity > 0, RxTrailError::InvalidQuantity);
    require!(
        prescription.status == PrescriptionStatus::Active,
        RxTrailError::PrescriptionNotActive
    );
    require!(
        now < prescription.expires_at,
        RxTrailError::PrescriptionExpired
    );
    require!(
        quantity <= prescription.remaining(),
        RxTrailError::QuantityExceedsRemaining
    );

    let index = prescription.dispensation_count;
    prescription.quantity_dispensed += quantity;
    prescription.dispensation_count += 1;
    let remaining_after = prescription.remaining();

    let dispenser = ctx.accounts.dispenser_signer.key();
    let product = ctx.accounts.product.key();
    let prescription_key = prescription.key();
    ctx.accounts.dispensation.set_inner(Dispensation {
        prescription: prescription_key,
        index,
        dispenser,
        product,
        quantity,
        remaining_after,
        dispensed_at: now,
        bump: ctx.bumps.dispensation,
    });
    emit!(MedicationDispensed {
        prescription: prescription_key,
        dispensation: ctx.accounts.dispensation.key(),
        dispenser,
        product,
        quantity,
        remaining_after,
    });
    Ok(())
}
