use anchor_lang::prelude::*;

use crate::{
    constants::{CONFIG_SEED, MEDICATION_SEED, PRODUCT_SEED},
    error::RxTrailError,
    events::{CatalogStatusChanged, MedicationRegistered, ProductRegistered},
    state::{CatalogStatus, Config, Medication, Product},
};

/// The catalog authority registers a medication.
///
/// Only the id and the identity hash go on-chain: names, therapeutic class
/// and dosage guidance live in the published off-chain catalog, and the hash
/// proves which record this id stands for. Nothing here is ever rewritten.
#[derive(Accounts)]
#[instruction(id: [u8; 32])]
pub struct RegisterMedication<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    #[account(
        constraint = catalog_authority.key() == config.catalog_authority
            @ RxTrailError::NotCatalogAuthority
    )]
    pub catalog_authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(
        init,
        payer = payer,
        space = 8 + Medication::INIT_SPACE,
        seeds = [MEDICATION_SEED, id.as_ref()],
        bump
    )]
    pub medication: Account<'info, Medication>,
    pub system_program: Program<'info, System>,
}

pub fn handle_register_medication(
    ctx: Context<RegisterMedication>,
    id: [u8; 32],
    identity_hash: [u8; 32],
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    ctx.accounts.medication.set_inner(Medication {
        id,
        identity_hash,
        status: CatalogStatus::Active,
        registered_at: now,
        status_changed_at: now,
        bump: ctx.bumps.medication,
    });
    emit!(MedicationRegistered {
        medication: ctx.accounts.medication.key(),
        identity_hash,
        registered_at: now,
    });
    Ok(())
}

/// The catalog authority registers a product: one manufacturer's version of
/// a registered medication.
#[derive(Accounts)]
#[instruction(id: [u8; 32])]
pub struct RegisterProduct<'info> {
    #[account(mut)]
    pub payer: Signer<'info>,
    #[account(
        constraint = catalog_authority.key() == config.catalog_authority
            @ RxTrailError::NotCatalogAuthority
    )]
    pub catalog_authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(seeds = [MEDICATION_SEED, medication.id.as_ref()], bump = medication.bump)]
    pub medication: Account<'info, Medication>,
    #[account(
        init,
        payer = payer,
        space = 8 + Product::INIT_SPACE,
        seeds = [PRODUCT_SEED, id.as_ref()],
        bump
    )]
    pub product: Account<'info, Product>,
    pub system_program: Program<'info, System>,
}

pub fn handle_register_product(
    ctx: Context<RegisterProduct>,
    id: [u8; 32],
    identity_hash: [u8; 32],
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let medication = ctx.accounts.medication.key();
    ctx.accounts.product.set_inner(Product {
        id,
        medication,
        identity_hash,
        status: CatalogStatus::Active,
        registered_at: now,
        status_changed_at: now,
        bump: ctx.bumps.product,
    });
    emit!(ProductRegistered {
        product: ctx.accounts.product.key(),
        medication,
        identity_hash,
        registered_at: now,
    });
    Ok(())
}

/// The catalog authority withdraws (recalls) or reinstates a medication.
///
/// Withdrawal takes effect at once, for every pharmacy: no new prescription
/// for it, and every existing one is frozen (dispense checks the medication's
/// status). Reinstating restores both. Nothing already recorded changes.
#[derive(Accounts)]
pub struct SetMedicationStatus<'info> {
    #[account(
        constraint = catalog_authority.key() == config.catalog_authority
            @ RxTrailError::NotCatalogAuthority
    )]
    pub catalog_authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(mut, seeds = [MEDICATION_SEED, medication.id.as_ref()], bump = medication.bump)]
    pub medication: Account<'info, Medication>,
}

pub fn handle_set_medication_status(
    ctx: Context<SetMedicationStatus>,
    status: CatalogStatus,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let medication = &mut ctx.accounts.medication;
    medication.status = status;
    medication.status_changed_at = now;
    emit!(CatalogStatusChanged {
        entry: medication.key(),
        is_medication: true,
        status,
        changed_at: now,
    });
    Ok(())
}

/// The catalog authority withdraws (recalls) or reinstates one product. The
/// medication's other products stay dispensable.
#[derive(Accounts)]
pub struct SetProductStatus<'info> {
    #[account(
        constraint = catalog_authority.key() == config.catalog_authority
            @ RxTrailError::NotCatalogAuthority
    )]
    pub catalog_authority: Signer<'info>,
    #[account(seeds = [CONFIG_SEED], bump = config.bump)]
    pub config: Account<'info, Config>,
    #[account(mut, seeds = [PRODUCT_SEED, product.id.as_ref()], bump = product.bump)]
    pub product: Account<'info, Product>,
}

pub fn handle_set_product_status(
    ctx: Context<SetProductStatus>,
    status: CatalogStatus,
) -> Result<()> {
    let now = Clock::get()?.unix_timestamp;
    let product = &mut ctx.accounts.product;
    product.status = status;
    product.status_changed_at = now;
    emit!(CatalogStatusChanged {
        entry: product.key(),
        is_medication: false,
        status,
        changed_at: now,
    });
    Ok(())
}
