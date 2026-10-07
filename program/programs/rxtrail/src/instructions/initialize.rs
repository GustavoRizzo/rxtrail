use anchor_lang::prelude::*;

use crate::{constants::CONFIG_SEED, state::Config};

/// Records which keys act as the professional, health and catalog authorities.
/// Runs once: the config account can only be created one time.
#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    #[account(init, payer = payer, space = 8 + Config::INIT_SPACE, seeds = [CONFIG_SEED], bump)]
    pub config: Account<'info, Config>,
    pub system_program: Program<'info, System>,
}

pub fn handle_initialize(
    ctx: Context<Initialize>,
    professional_authority: Pubkey,
    health_authority: Pubkey,
    catalog_authority: Pubkey,
) -> Result<()> {
    ctx.accounts.config.set_inner(Config {
        professional_authority,
        health_authority,
        catalog_authority,
        bump: ctx.bumps.config,
    });
    Ok(())
}
