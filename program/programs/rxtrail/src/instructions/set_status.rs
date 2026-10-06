use anchor_lang::prelude::*;

use crate::{
    constants::{CONFIG_SEED, DISPENSER_SEED, PRESCRIBER_SEED},
    error::RxTrailError,
    events::ParticipantStatusChanged,
    state::{Config, Dispenser, ParticipantStatus, Prescriber},
};

/// The professional authority suspends or reinstates a prescriber.
///
/// Suspension takes effect immediately and everywhere: the prescriber can no
/// longer issue, and none of their prescriptions can be dispensed (dispense
/// checks the prescriber's status). It is the answer to a leaked key or a
/// revoked licence. Reinstating restores both. Nothing already recorded changes.
#[derive(Accounts)]
pub struct SetPrescriberStatus<'info> {
    #[account(
        constraint = professional_authority.key() == config.professional_authority
            @ RxTrailError::NotProfessionalAuthority
    )]
    pub professional_authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(mut, seeds = [PRESCRIBER_SEED, prescriber.key.as_ref()], bump = prescriber.bump)]
    pub prescriber: Account<'info, Prescriber>,
}

pub fn handle_set_prescriber_status(
    ctx: Context<SetPrescriberStatus>,
    status: ParticipantStatus,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let prescriber = &mut ctx.accounts.prescriber;
    prescriber.status = status;
    prescriber.status_changed_at = now;
    emit!(ParticipantStatusChanged {
        participant: prescriber.key,
        is_prescriber: true,
        status,
        changed_at: now,
    });
    Ok(())
}

/// The health authority suspends or reinstates a dispenser.
#[derive(Accounts)]
pub struct SetDispenserStatus<'info> {
    #[account(
        constraint = health_authority.key() == config.health_authority
            @ RxTrailError::NotHealthAuthority
    )]
    pub health_authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(mut, seeds = [DISPENSER_SEED, dispenser.key.as_ref()], bump = dispenser.bump)]
    pub dispenser: Account<'info, Dispenser>,
}

pub fn handle_set_dispenser_status(
    ctx: Context<SetDispenserStatus>,
    status: ParticipantStatus,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let dispenser = &mut ctx.accounts.dispenser;
    dispenser.status = status;
    dispenser.status_changed_at = now;
    emit!(ParticipantStatusChanged {
        participant: dispenser.key,
        is_prescriber: false,
        status,
        changed_at: now,
    });
    Ok(())
}
