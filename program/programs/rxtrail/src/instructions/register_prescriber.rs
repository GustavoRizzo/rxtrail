use anchor_lang::prelude::*;

use crate::{
    constants::{CONFIG_SEED, PRESCRIBER_SEED},
    error::RxTrailError,
    events::PrescriberRegistered,
    state::{Config, ParticipantStatus, Prescriber},
};

/// The professional authority enables a prescriber's key.
/// The operator pays (`payer`); only the authority's signature authorizes.
#[derive(Accounts)]
#[instruction(prescriber_key: Pubkey)]
pub struct RegisterPrescriber<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    #[account(
        constraint = professional_authority.key() == config.professional_authority
            @ RxTrailError::NotProfessionalAuthority
    )]
    pub professional_authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(
        init,
        payer = payer,
        space = 8 + Prescriber::INIT_SPACE,
        seeds = [PRESCRIBER_SEED, prescriber_key.as_ref()],
        bump
    )]
    pub prescriber: Account<'info, Prescriber>,
    pub system_program: Program<'info, System>,
}

pub fn handle_register_prescriber(
    ctx: Context<RegisterPrescriber>,
    prescriber_key: Pubkey,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    ctx.accounts.prescriber.set_inner(Prescriber {
        key: prescriber_key,
        status: ParticipantStatus::Active,
        registered_at: now,
        status_changed_at: now,
        bump: ctx.bumps.prescriber,
    });
    emit!(PrescriberRegistered {
        prescriber: prescriber_key,
        registered_at: now
    });
    Ok(())
}
