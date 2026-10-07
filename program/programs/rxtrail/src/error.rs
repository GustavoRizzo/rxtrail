use anchor_lang::prelude::*;

#[error_code]
pub enum RxTrailError {
    #[msg("Signer is not the professional authority")]
    NotProfessionalAuthority,
    #[msg("Signer is not the health authority")]
    NotHealthAuthority,
    #[msg("Prescriber is not active")]
    PrescriberNotActive,
    #[msg("Dispenser is not active")]
    DispenserNotActive,
    #[msg("Quantity must be greater than zero")]
    InvalidQuantity,
    #[msg("Expiry must be in the future")]
    ExpiryInThePast,
    #[msg("Prescription has expired")]
    PrescriptionExpired,
    #[msg("Prescription is not active")]
    PrescriptionNotActive,
    #[msg("Quantity exceeds what remains on the prescription")]
    QuantityExceedsRemaining,
    #[msg("Signer is not the catalog authority")]
    NotCatalogAuthority,
    #[msg("Medication is withdrawn from the catalog")]
    MedicationNotActive,
    #[msg("Product is withdrawn from the catalog")]
    ProductNotActive,
    #[msg("Product is not a version of the prescribed medication")]
    ProductMedicationMismatch,
    #[msg("The prescriber locked another product: substitution not allowed")]
    PrescribedProductMismatch,
}
