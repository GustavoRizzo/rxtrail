use anchor_lang::prelude::*;

use crate::{
    constants::{CONFIG_SEED, DISPENSER_SEED},
    error::RxTrailError,
    events::DispenserRegistered,
    state::{Config, Dispenser, ParticipantStatus},
};

/// The health authority enables a dispenser's key.
/// The operator pays (`payer`); only the authority's signature authorizes.
#[derive(Accounts)]
#[instruction(dispenser_key: Pubkey)]
pub struct RegisterDispenser<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    #[account(
        constraint = health_authority.key() == config.health_authority
            @ RxTrailError::NotHealthAuthority
    )]
    pub health_authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(
        init,
        payer = payer,
        space = 8 + Dispenser::INIT_SPACE,
        seeds = [DISPENSER_SEED, dispenser_key.as_ref()],
        bump
    )]
    pub dispenser: Account<'info, Dispenser>,
    pub system_program: Program<'info, System>,
}

pub fn handle_register_dispenser(
    ctx: Context<RegisterDispenser>,
    dispenser_key: Pubkey,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    ctx.accounts.dispenser.set_inner(Dispenser {
        key: dispenser_key,
        status: ParticipantStatus::Active,
        registered_at: now,
        status_changed_at: now,
        bump: ctx.bumps.dispenser,
    });
    emit!(DispenserRegistered {
        dispenser: dispenser_key,
        registered_at: now
    });
    Ok(())
}
