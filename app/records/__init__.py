"""Off-chain records: what must never go on-chain.

Patients' real identities, the link to their random on-chain id, and the full
prescription documents with their salts. Back this store up: unlike chain
data, it cannot be rebuilt. Deleting a patient's link anonymizes them (their
on-chain id becomes meaningless) without touching the audit trail.
"""
