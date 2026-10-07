//! Program tests on LiteSVM: the compiled program runs in an in-process Solana
//! VM, so every guarantee is checked against the real bytecode.

use {
    anchor_lang::{
        prelude::{Clock, Pubkey},
        solana_program::{instruction::Instruction, system_program},
        AccountDeserialize, InstructionData, ToAccountMetas,
    },
    litesvm::LiteSVM,
    rxtrail::{
        error::RxTrailError,
        state::{Dispensation, Dispenser, ParticipantStatus, Prescriber, Prescription},
        CONFIG_SEED, DISPENSATION_SEED, DISPENSER_SEED, PRESCRIBER_SEED, PRESCRIPTION_SEED,
    },
    solana_keypair::Keypair,
    solana_message::{Message, VersionedMessage},
    solana_signer::Signer,
    solana_transaction::versioned::VersionedTransaction,
};

const DAY: i64 = 86_400;

/// A fresh chain with the program deployed, both authorities configured, one
/// prescriber and one dispenser enabled.
struct Env {
    svm: LiteSVM,
    operator: Keypair,
    professional_authority: Keypair,
    health_authority: Keypair,
    prescriber: Keypair,
    dispenser: Keypair,
    next_id: u8,
}

fn pda(seeds: &[&[u8]]) -> Pubkey {
    Pubkey::find_program_address(seeds, &rxtrail::id()).0
}

fn config_pda() -> Pubkey {
    pda(&[CONFIG_SEED])
}

fn prescriber_pda(key: &Pubkey) -> Pubkey {
    pda(&[PRESCRIBER_SEED, key.as_ref()])
}

fn dispenser_pda(key: &Pubkey) -> Pubkey {
    pda(&[DISPENSER_SEED, key.as_ref()])
}

fn prescription_pda(id: &[u8; 32]) -> Pubkey {
    pda(&[PRESCRIPTION_SEED, id])
}

fn dispensation_pda(prescription: &Pubkey, index: u32) -> Pubkey {
    pda(&[
        DISPENSATION_SEED,
        prescription.as_ref(),
        &index.to_le_bytes(),
    ])
}

/// Anchor encodes custom errors as `Custom(6000 + variant index)`.
fn code(error: RxTrailError) -> String {
    format!("Custom({})", u32::from(error))
}

impl Env {
    fn new() -> Self {
        let mut svm = LiteSVM::new();
        let bytes = include_bytes!(concat!(
            env!("CARGO_TARGET_TMPDIR"),
            "/../deploy/rxtrail.so"
        ));
        svm.add_program(rxtrail::id(), bytes).unwrap();

        let mut env = Env {
            svm,
            operator: Keypair::new(),
            professional_authority: Keypair::new(),
            health_authority: Keypair::new(),
            prescriber: Keypair::new(),
            dispenser: Keypair::new(),
            next_id: 0,
        };
        // Only the operator holds SOL: it pays every fee and every rent deposit.
        env.svm
            .airdrop(&env.operator.pubkey(), 100_000_000_000)
            .unwrap();
        env.set_time(1_800_000_000);

        env.initialize().unwrap();
        let prescriber = env.prescriber.pubkey();
        env.register_prescriber(&prescriber).unwrap();
        let dispenser = env.dispenser.pubkey();
        env.register_dispenser(&dispenser).unwrap();
        env
    }

    fn set_time(&mut self, unix_timestamp: i64) {
        let mut clock = self.svm.get_sysvar::<Clock>();
        clock.unix_timestamp = unix_timestamp;
        self.svm.set_sysvar::<Clock>(&clock);
    }

    fn now(&self) -> i64 {
        self.svm.get_sysvar::<Clock>().unix_timestamp
    }

    /// Sends one instruction; the operator always pays, `signers` authorize.
    fn send(&mut self, instruction: Instruction, signers: &[&Keypair]) -> Result<(), String> {
        let payer = self.operator.insecure_clone();
        let mut all: Vec<&Keypair> = vec![&payer];
        // A key signs once, even when it plays two roles (e.g. the operator
        // trying to sign as a prescriber).
        for signer in signers {
            if !all.iter().any(|k| k.pubkey() == signer.pubkey()) {
                all.push(signer);
            }
        }
        self.svm.expire_blockhash();
        let message = Message::new_with_blockhash(
            &[instruction],
            Some(&payer.pubkey()),
            &self.svm.latest_blockhash(),
        );
        let tx = VersionedTransaction::try_new(VersionedMessage::Legacy(message), &all).unwrap();
        self.svm
            .send_transaction(tx)
            .map(|_| ())
            .map_err(|e| format!("{:?}", e.err))
    }

    fn initialize(&mut self) -> Result<(), String> {
        let ix = Instruction::new_with_bytes(
            rxtrail::id(),
            &rxtrail::instruction::Initialize {
                professional_authority: self.professional_authority.pubkey(),
                health_authority: self.health_authority.pubkey(),
            }
            .data(),
            rxtrail::accounts::Initialize {
                payer: self.operator.pubkey(),
                config: config_pda(),
                system_program: system_program::ID,
            }
            .to_account_metas(None),
        );
        self.send(ix, &[])
    }

    fn register_prescriber_signed_by(
        &mut self,
        key: &Pubkey,
        authority: &Keypair,
    ) -> Result<(), String> {
        let ix = Instruction::new_with_bytes(
            rxtrail::id(),
            &rxtrail::instruction::RegisterPrescriber {
                prescriber_key: *key,
            }
            .data(),
            rxtrail::accounts::RegisterPrescriber {
                payer: self.operator.pubkey(),
                professional_authority: authority.pubkey(),
                config: config_pda(),
                prescriber: prescriber_pda(key),
                system_program: system_program::ID,
            }
            .to_account_metas(None),
        );
        self.send(ix, &[authority])
    }

    fn register_prescriber(&mut self, key: &Pubkey) -> Result<(), String> {
        let authority = self.professional_authority.insecure_clone();
        self.register_prescriber_signed_by(key, &authority)
    }

    fn register_dispenser_signed_by(
        &mut self,
        key: &Pubkey,
        authority: &Keypair,
    ) -> Result<(), String> {
        let ix = Instruction::new_with_bytes(
            rxtrail::id(),
            &rxtrail::instruction::RegisterDispenser {
                dispenser_key: *key,
            }
            .data(),
            rxtrail::accounts::RegisterDispenser {
                payer: self.operator.pubkey(),
                health_authority: authority.pubkey(),
                config: config_pda(),
                dispenser: dispenser_pda(key),
                system_program: system_program::ID,
            }
            .to_account_metas(None),
        );
        self.send(ix, &[authority])
    }

    fn register_dispenser(&mut self, key: &Pubkey) -> Result<(), String> {
        let authority = self.health_authority.insecure_clone();
        self.register_dispenser_signed_by(key, &authority)
    }

    fn new_id(&mut self) -> [u8; 32] {
        self.next_id += 1;
        [self.next_id; 32]
    }

    fn issue_by(
        &mut self,
        prescriber: &Keypair,
        quantity: u32,
        expires_at: i64,
    ) -> Result<[u8; 32], String> {
        let id = self.new_id();
        let ix = Instruction::new_with_bytes(
            rxtrail::id(),
            &rxtrail::instruction::IssuePrescription {
                id,
                patient_id: [7; 32],
                document_hash: [9; 32],
                quantity,
                expires_at,
            }
            .data(),
            rxtrail::accounts::IssuePrescription {
                payer: self.operator.pubkey(),
                prescriber_signer: prescriber.pubkey(),
                prescriber: prescriber_pda(&prescriber.pubkey()),
                prescription: prescription_pda(&id),
                system_program: system_program::ID,
            }
            .to_account_metas(None),
        );
        self.send(ix, &[prescriber]).map(|_| id)
    }

    fn issue(&mut self, quantity: u32) -> [u8; 32] {
        let prescriber = self.prescriber.insecure_clone();
        let expires_at = self.now() + 30 * DAY;
        self.issue_by(&prescriber, quantity, expires_at).unwrap()
    }

    fn dispense_by(
        &mut self,
        dispenser: &Keypair,
        id: &[u8; 32],
        quantity: u32,
    ) -> Result<(), String> {
        let prescription = prescription_pda(id);
        let state = self.prescription(id);
        let ix = Instruction::new_with_bytes(
            rxtrail::id(),
            &rxtrail::instruction::Dispense { quantity }.data(),
            rxtrail::accounts::Dispense {
                payer: self.operator.pubkey(),
                dispenser_signer: dispenser.pubkey(),
                dispenser: dispenser_pda(&dispenser.pubkey()),
                prescription,
                prescriber: prescriber_pda(&state.prescriber),
                dispensation: dispensation_pda(&prescription, state.dispensation_count),
                system_program: system_program::ID,
            }
            .to_account_metas(None),
        );
        self.send(ix, &[dispenser])
    }

    fn dispense(&mut self, id: &[u8; 32], quantity: u32) -> Result<(), String> {
        let dispenser = self.dispenser.insecure_clone();
        self.dispense_by(&dispenser, id, quantity)
    }

    fn set_prescriber_status_signed_by(
        &mut self,
        key: &Pubkey,
        status: ParticipantStatus,
        authority: &Keypair,
    ) -> Result<(), String> {
        let ix = Instruction::new_with_bytes(
            rxtrail::id(),
            &rxtrail::instruction::SetPrescriberStatus { status }.data(),
            rxtrail::accounts::SetPrescriberStatus {
                professional_authority: authority.pubkey(),
                config: config_pda(),
                prescriber: prescriber_pda(key),
            }
            .to_account_metas(None),
        );
        self.send(ix, &[authority])
    }

    fn set_prescriber_status(&mut self, status: ParticipantStatus) -> Result<(), String> {
        let (key, authority) = (
            self.prescriber.pubkey(),
            self.professional_authority.insecure_clone(),
        );
        self.set_prescriber_status_signed_by(&key, status, &authority)
    }

    fn set_dispenser_status(&mut self, status: ParticipantStatus) -> Result<(), String> {
        let (key, authority) = (
            self.dispenser.pubkey(),
            self.health_authority.insecure_clone(),
        );
        let ix = Instruction::new_with_bytes(
            rxtrail::id(),
            &rxtrail::instruction::SetDispenserStatus { status }.data(),
            rxtrail::accounts::SetDispenserStatus {
                health_authority: authority.pubkey(),
                config: config_pda(),
                dispenser: dispenser_pda(&key),
            }
            .to_account_metas(None),
        );
        self.send(ix, &[&authority])
    }

    fn prescription(&self, id: &[u8; 32]) -> Prescription {
        let account = self.svm.get_account(&prescription_pda(id)).unwrap();
        Prescription::try_deserialize(&mut account.data.as_slice()).unwrap()
    }

    fn dispensation(&self, id: &[u8; 32], index: u32) -> Dispensation {
        let account = self
            .svm
            .get_account(&dispensation_pda(&prescription_pda(id), index))
            .unwrap();
        Dispensation::try_deserialize(&mut account.data.as_slice()).unwrap()
    }
}

// ------------------------------------------------------------ happy path ----

#[test]
fn a_prescription_is_issued_with_its_terms() {
    let mut env = Env::new();
    let id = env.issue(30);

    let p = env.prescription(&id);
    assert_eq!(p.prescriber, env.prescriber.pubkey());
    assert_eq!(
        (
            p.quantity_granted,
            p.quantity_dispensed,
            p.dispensation_count
        ),
        (30, 0, 0)
    );
    assert_eq!(p.patient_id, [7; 32]);
    assert_eq!(p.document_hash, [9; 32]);
    assert_eq!(p.issued_at, env.now());
}

#[test]
fn partial_dispensations_each_leave_an_immutable_record() {
    let mut env = Env::new();
    let id = env.issue(30);

    env.dispense(&id, 10).unwrap();
    env.dispense(&id, 15).unwrap();

    let p = env.prescription(&id);
    assert_eq!(
        (p.quantity_dispensed, p.dispensation_count, p.remaining()),
        (25, 2, 5)
    );
    let first = env.dispensation(&id, 0);
    let second = env.dispensation(&id, 1);
    assert_eq!(
        (first.index, first.quantity, first.remaining_after),
        (0, 10, 20)
    );
    assert_eq!(
        (second.index, second.quantity, second.remaining_after),
        (1, 15, 5)
    );
    assert_eq!(first.dispenser, env.dispenser.pubkey());
    assert_eq!(first.prescription, prescription_pda(&id));
}

// ---------------------------------------------- RN-06: never over-dispense --

#[test]
fn dispensing_more_than_remains_is_refused() {
    let mut env = Env::new();
    let id = env.issue(30);
    env.dispense(&id, 20).unwrap();

    let err = env.dispense(&id, 11).unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::QuantityExceedsRemaining)),
        "{err}"
    );
    assert_eq!(env.prescription(&id).quantity_dispensed, 20);
}

#[test]
fn the_exact_remainder_can_be_dispensed_and_then_nothing_more() {
    let mut env = Env::new();
    let id = env.issue(30);
    env.dispense(&id, 20).unwrap();

    env.dispense(&id, 10).unwrap();
    let err = env.dispense(&id, 1).unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::QuantityExceedsRemaining)),
        "{err}"
    );
    assert_eq!(env.prescription(&id).remaining(), 0);
}

#[test]
fn two_dispensers_cannot_jointly_exceed_the_grant() {
    let mut env = Env::new();
    let other = Keypair::new();
    env.register_dispenser(&other.pubkey()).unwrap();
    let id = env.issue(30);

    env.dispense(&id, 20).unwrap();
    let err = env.dispense_by(&other, &id, 20).unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::QuantityExceedsRemaining)),
        "{err}"
    );
    env.dispense_by(&other, &id, 10).unwrap();
    assert_eq!(env.prescription(&id).quantity_dispensed, 30);
}

#[test]
fn a_zero_quantity_is_refused() {
    let mut env = Env::new();
    let id = env.issue(30);
    let err = env.dispense(&id, 0).unwrap_err();
    assert!(err.contains(&code(RxTrailError::InvalidQuantity)), "{err}");
}

// ----------------------------------------------------------- expiry --------

#[test]
fn an_expired_prescription_cannot_be_dispensed() {
    let mut env = Env::new();
    let id = env.issue(30);
    let expires_at = env.prescription(&id).expires_at;

    env.set_time(expires_at);
    let err = env.dispense(&id, 1).unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::PrescriptionExpired)),
        "{err}"
    );
}

#[test]
fn a_prescription_cannot_be_issued_already_expired() {
    let mut env = Env::new();
    let prescriber = env.prescriber.insecure_clone();
    let now = env.now();
    let err = env.issue_by(&prescriber, 30, now).unwrap_err();
    assert!(err.contains(&code(RxTrailError::ExpiryInThePast)), "{err}");
}

// ---------------------------------------------- who may do what (RN-19/20) --

#[test]
fn an_unregistered_prescriber_cannot_issue() {
    let mut env = Env::new();
    let stranger = Keypair::new();
    let expires_at = env.now() + DAY;

    let err = env.issue_by(&stranger, 30, expires_at).unwrap_err();

    // There is no prescriber record for this key: Anchor's AccountNotInitialized.
    assert!(err.contains("Custom(3012)"), "{err}");
}

#[test]
fn an_unregistered_dispenser_cannot_dispense() {
    let mut env = Env::new();
    let id = env.issue(30);
    let stranger = Keypair::new();

    let err = env.dispense_by(&stranger, &id, 1).unwrap_err();

    assert!(err.contains("Custom(3012)"), "{err}");
    assert_eq!(env.prescription(&id).quantity_dispensed, 0);
}

#[test]
fn only_the_professional_authority_registers_prescribers() {
    let mut env = Env::new();
    let impostor = Keypair::new();
    let key = Keypair::new().pubkey();

    let err = env
        .register_prescriber_signed_by(&key, &impostor)
        .unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::NotProfessionalAuthority)),
        "{err}"
    );
}

#[test]
fn only_the_health_authority_registers_dispensers() {
    let mut env = Env::new();
    let professional = env.professional_authority.insecure_clone();
    let key = Keypair::new().pubkey();

    // The other authority is not enough: each one enables its own participants.
    let err = env
        .register_dispenser_signed_by(&key, &professional)
        .unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::NotHealthAuthority)),
        "{err}"
    );
}

#[test]
fn the_operator_cannot_issue_in_a_prescribers_name() {
    let mut env = Env::new();
    // The operator holds the funds but no prescriber key: signing as itself
    // finds no prescriber record for the operator's key.
    let operator = env.operator.insecure_clone();
    let expires_at = env.now() + DAY;

    let err = env.issue_by(&operator, 30, expires_at).unwrap_err();

    assert!(err.contains("Custom(3012)"), "{err}");
}

#[test]
fn registration_starts_active_and_cannot_be_repeated() {
    let mut env = Env::new();
    let account = env
        .svm
        .get_account(&prescriber_pda(&env.prescriber.pubkey()))
        .unwrap();
    let record = rxtrail::state::Prescriber::try_deserialize(&mut account.data.as_slice()).unwrap();
    assert_eq!(record.status, ParticipantStatus::Active);

    let key = env.prescriber.pubkey();
    assert!(env.register_prescriber(&key).is_err());
}

#[test]
fn the_configuration_is_set_once() {
    let mut env = Env::new();
    assert!(env.initialize().is_err());
}

#[test]
fn the_operator_pays_every_fee_and_deposit() {
    let mut env = Env::new();
    let id = env.issue(30);
    env.dispense(&id, 5).unwrap();

    // Participants never needed SOL: non-custodial signing, sponsored fees.
    for key in [
        env.prescriber.pubkey(),
        env.dispenser.pubkey(),
        env.professional_authority.pubkey(),
    ] {
        assert_eq!(env.svm.get_balance(&key).unwrap_or(0), 0);
    }
}

// ------------------------------------------- suspension (RN-11a, RN-21) ----

#[test]
fn a_suspended_prescriber_cannot_issue() {
    let mut env = Env::new();
    env.set_prescriber_status(ParticipantStatus::Suspended)
        .unwrap();

    let prescriber = env.prescriber.insecure_clone();
    let expires_at = env.now() + DAY;
    let err = env.issue_by(&prescriber, 30, expires_at).unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::PrescriberNotActive)),
        "{err}"
    );
}

#[test]
fn suspending_a_prescriber_freezes_their_existing_prescriptions() {
    let mut env = Env::new();
    let id = env.issue(30);
    env.dispense(&id, 10).unwrap();

    env.set_prescriber_status(ParticipantStatus::Suspended)
        .unwrap();
    let err = env.dispense(&id, 5).unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::PrescriberNotActive)),
        "{err}"
    );
    // What was already dispensed stays on record, untouched.
    assert_eq!(env.prescription(&id).quantity_dispensed, 10);
    assert_eq!(env.dispensation(&id, 0).quantity, 10);
}

#[test]
fn reinstating_a_prescriber_restores_their_prescriptions() {
    let mut env = Env::new();
    let id = env.issue(30);
    env.set_prescriber_status(ParticipantStatus::Suspended)
        .unwrap();
    env.set_prescriber_status(ParticipantStatus::Active)
        .unwrap();

    env.dispense(&id, 5).unwrap();

    let account = env
        .svm
        .get_account(&prescriber_pda(&env.prescriber.pubkey()))
        .unwrap();
    let record = Prescriber::try_deserialize(&mut account.data.as_slice()).unwrap();
    assert_eq!(record.status, ParticipantStatus::Active);
    assert_eq!(record.status_changed_at, env.now());
}

#[test]
fn a_suspended_dispenser_cannot_dispense() {
    let mut env = Env::new();
    let id = env.issue(30);
    env.set_dispenser_status(ParticipantStatus::Suspended)
        .unwrap();

    let err = env.dispense(&id, 1).unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::DispenserNotActive)),
        "{err}"
    );
    let account = env
        .svm
        .get_account(&dispenser_pda(&env.dispenser.pubkey()))
        .unwrap();
    let record = Dispenser::try_deserialize(&mut account.data.as_slice()).unwrap();
    assert_eq!(record.status, ParticipantStatus::Suspended);
}

#[test]
fn only_the_professional_authority_suspends_prescribers() {
    let mut env = Env::new();
    let key = env.prescriber.pubkey();
    let health = env.health_authority.insecure_clone();

    let err = env
        .set_prescriber_status_signed_by(&key, ParticipantStatus::Suspended, &health)
        .unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::NotProfessionalAuthority)),
        "{err}"
    );
}

// ----------------------------------------------------------------- limits --

#[test]
fn the_largest_grant_never_overflows() {
    let mut env = Env::new();
    let id = env.issue(u32::MAX);

    env.dispense(&id, u32::MAX - 1).unwrap();
    env.dispense(&id, 1).unwrap();
    let err = env.dispense(&id, 1).unwrap_err();

    assert!(
        err.contains(&code(RxTrailError::QuantityExceedsRemaining)),
        "{err}"
    );
    assert_eq!(env.prescription(&id).quantity_dispensed, u32::MAX);
}

// ------------------------------------------------ property: RN-06 always --

use proptest::prelude::*;

proptest! {
    // Case count comes from PROPTEST_CASES: few in everyday runs, many in
    // `just test-stress`.
    #![proptest_config(ProptestConfig::default())]

    /// Whatever pharmacies ask for, in whatever order: the program never
    /// dispenses past the grant, every request that fits is accepted, and the
    /// on-chain history adds up.
    #[test]
    fn dispensing_never_exceeds_the_grant(
        granted in 1u32..200,
        requests in proptest::collection::vec((1u32..80, 0usize..3), 1..12),
    ) {
        let mut env = Env::new();
        let pharmacies: Vec<Keypair> = (0..3).map(|_| Keypair::new()).collect();
        for pharmacy in &pharmacies {
            env.register_dispenser(&pharmacy.pubkey()).unwrap();
        }
        let id = env.issue(granted);

        let mut expected_dispensed = 0u32;
        for (quantity, who) in requests {
            let fits = quantity <= granted - expected_dispensed;
            let result = env.dispense_by(&pharmacies[who], &id, quantity);
            prop_assert_eq!(result.is_ok(), fits, "asked {} with {} left", quantity, granted - expected_dispensed);
            if fits {
                expected_dispensed += quantity;
            }
        }

        let p = env.prescription(&id);
        prop_assert!(p.quantity_dispensed <= p.quantity_granted);
        prop_assert_eq!(p.quantity_dispensed, expected_dispensed);
        let mut remaining = granted;
        for index in 0..p.dispensation_count {
            let d = env.dispensation(&id, index);
            remaining -= d.quantity;
            prop_assert_eq!(d.remaining_after, remaining);
        }
    }
}
