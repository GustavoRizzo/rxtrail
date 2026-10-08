"""Demo data: participants for every role, enabled on-chain, a medication
catalog, and a planned network of prescriptions that tells the insights'
stories (see plan.py). Safe to run again: whatever is already on the chain
is kept, and a run that stopped half-way continues where it left.

Demo only. The cast, the catalog and the plan will change as the product
does; nothing depends on them but the login page's account cards.

Every record costs rent on a real network (see estimate()), so the size is
a profile the person seeding chooses, and a public network asks for an
explicit confirmation before anything is sent.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model

from config import container
from records.models import CatalogMedication, CatalogProduct, Participant, PrescriptionRecord
from rxtrail.domain import PrescriptionDocument, ProductDetails, RxTrailError
from web.demo.cast import CAST, NETWORK_PHARMACIES, Role, prescriber_name
from web.demo.catalog import CATALOG
from web.demo.plan import PROFILES, Planned, pharmacies, plan, prescribers

# Every account locks a rent deposit, never returned: audit records are never
# closed. The rate differs per network, so the node is asked. Sizes are
# 8 + INIT_SPACE (program/programs/rxtrail/src/state.rs).
ACCOUNT_BYTES = {
    "participant": 58,
    "medication": 90,
    "product": 122,
    "prescription": 207,
    "dispensation": 125,
    "closure": 91,
}
FEE = 10_000  # lamports per transaction: two signatures (operator + participant)
LAMPORTS_PER_SOL = 1_000_000_000

# Transactions in flight at once: a local validator takes many, a public
# node throttles.
CONCURRENCY = {"localnet": 8}
DEFAULT_CONCURRENCY = 2


class ConfirmationNeeded(RxTrailError):
    """Seeding a public network spends real (test) SOL: say --yes first."""


@dataclass
class Estimate:
    accounts: dict[str, int]
    rent: dict[str, int]  # lamports per account of each kind, on this network

    @property
    def transactions(self) -> int:
        return sum(self.accounts.values())

    @property
    def lamports(self) -> int:
        return sum(n * (self.rent[kind] + FEE) for kind, n in self.accounts.items())

    def describe(self) -> str:
        parts = ", ".join(
            f"{n} {kind}{'s' if n != 1 else ''}" for kind, n in self.accounts.items() if n
        )
        return f"{parts or 'nothing'}: ~{self.lamports / LAMPORTS_PER_SOL:.3f} SOL"


def _ensure_users() -> list[str]:
    User = get_user_model()
    keys = container.key_store()
    created = []
    for username, role, key_name, display, licence in CAST:
        if key_name and not keys.exists(key_name):
            keys.create(key_name)
        if User.objects.filter(username=username).exists():
            continue
        user = User.objects.create_user(username, password=settings.RXTRAIL_DEMO_PASSWORD)
        Participant.objects.create(
            user=user, role=role, key_name=key_name, display_name=display, license_number=licence
        )
        created.append(username)
    return created


def _ensure_keys(names) -> None:
    keys = container.key_store()
    for name in names:
        if not keys.exists(name):
            keys.create(name)


def _participants(profile: str) -> list[tuple[str, str]]:
    """(role, key name) of every prescriber and pharmacy the profile needs."""
    logins = [
        ({Role.PRESCRIBER: "prescriber", Role.DISPENSER: "dispenser"}[role], key)
        for _, role, key, _, _ in CAST
        if role in (Role.PRESCRIBER, Role.DISPENSER)
    ]
    wanted = [("prescriber", p) for p in prescribers(profile)]
    wanted += [("dispenser", p) for p in pharmacies(profile)]
    wanted += [("dispenser", key) for key, _ in NETWORK_PHARMACIES]
    return list(dict.fromkeys(logins + wanted))


async def _on_chain(ledger, items: list[Planned]) -> dict[str, tuple[bytes, object]]:
    """Planned items already issued: key → (prescription id, on-chain prescription)."""
    ids: dict[str, list[bytes]] = {}
    async for record in PrescriptionRecord.objects.filter(
        patient__document_number__in=[i.key for i in items]
    ).select_related("patient"):
        ids.setdefault(record.patient.document_number, []).append(
            bytes.fromhex(record.prescription_id)
        )
    flat = [(key, rx_id) for key, found in ids.items() for rx_id in found]
    on_chain = await ledger.prescriptions_by_id([rx_id for _, rx_id in flat]) if flat else []
    done = {}
    for (key, rx_id), prescription in zip(flat, on_chain, strict=True):
        if prescription is not None:  # an off-chain orphan (failed send) does not count
            done[key] = (rx_id, prescription)
    return done


async def estimate(ledger, profile: str) -> tuple[Estimate, dict]:
    """What a run would still create, and its cost. Reads only."""
    participants = _participants(profile)
    missing = [
        (role, name)
        for role, name in participants
        if await ledger.participant_status(role, name) is None
    ]
    catalog_missing = not await CatalogMedication.objects.aexists()
    items = plan(profile)
    done = await _on_chain(ledger, items)
    counts = {"participant": len(missing), "medication": 0, "product": 0}
    if catalog_missing:
        counts["medication"] = len(CATALOG)
        counts["product"] = sum(len(products) for _, products in CATALOG)
    counts["prescription"] = sum(1 for i in items if i.key not in done)
    counts["dispensation"] = sum(
        len(i.dispensations) - (done[i.key][1].dispensation_count if i.key in done else 0)
        for i in items
    )
    counts["closure"] = sum(
        1 for i in items if i.closure and not (i.key in done and done[i.key][1].status != "active")
    )
    rent = {kind: await ledger.rent_exempt_minimum(size) for kind, size in ACCOUNT_BYTES.items()}
    return Estimate(counts, rent), done


async def seed(log, profile: str = "story", estimate_only: bool = False, confirmed: bool = False):
    """Create what the profile plans and is not on the chain yet.

    On a public network nothing is sent without `confirmed`: the estimate is
    shown and ConfirmationNeeded raised instead."""
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}: choose {', '.join(PROFILES)}")
    network = settings.SOLANA_NETWORK
    for username in await sync_to_async(_ensure_users)():
        log(f"  login {username}")
    await sync_to_async(_ensure_keys)([name for _, name in _participants(profile)])

    async with container.open_rxtrail() as (app, ledger):
        cost, done = await estimate(ledger, profile)
        balance = await ledger.operator_balance()
        log(f"  profile {profile} ({PROFILES[profile].about})")
        log(f"  still to create on {network}: {cost.describe()}")
        log(f"  operator balance: {balance / LAMPORTS_PER_SOL:.3f} SOL")
        if estimate_only or not cost.transactions:
            return cost
        if network != "localnet" and not confirmed:
            raise ConfirmationNeeded(
                f"this spends ~{cost.lamports / LAMPORTS_PER_SOL:.3f} SOL on {network}; "
                "run again with --yes to go ahead"
            )
        if cost.lamports > balance:
            raise ConfirmationNeeded(
                f"the operator has {balance / LAMPORTS_PER_SOL:.3f} SOL, the run needs "
                f"~{cost.lamports / LAMPORTS_PER_SOL:.3f}: fund it first"
            )

        for role, name in _participants(profile):
            if await ledger.participant_status(role, name) is None:
                authority = "professional-authority" if role == "prescriber" else "health-authority"
                await getattr(app, f"enable_{role}")(authority, name)
                log(f"  enabled {role} {name} on-chain")

        if not await CatalogMedication.objects.aexists():
            for medication, products in CATALOG:
                entry = await app.register_medication("catalog-authority", medication)
                for manufacturer, brand, kind in products:
                    await app.register_product(
                        "catalog-authority",
                        ProductDetails(entry.id.hex(), manufacturer, brand, kind),
                    )
                log(f"  catalog: {medication.name} ({len(products)} products)")

        catalog = await _catalog_ids()
        gate = asyncio.Semaphore(CONCURRENCY.get(network, DEFAULT_CONCURRENCY))
        items = plan(profile)
        progress = {"done": 0}

        async def one(item: Planned):
            async with gate:
                await _carry_out(app, ledger, item, done.get(item.key), catalog)
            progress["done"] += 1
            if progress["done"] % 25 == 0 or progress["done"] == len(items):
                log(f"  {progress['done']}/{len(items)} prescriptions in place")

        await asyncio.gather(*(one(item) for item in items))
    return cost


async def _catalog_ids() -> dict[str, str]:
    """Catalog name or brand → its hex id."""
    found = {m.name: m.medication_id async for m in CatalogMedication.objects.all()}
    found.update({p.brand_name: p.product_id async for p in CatalogProduct.objects.all()})
    return found


async def _carry_out(app, ledger, item: Planned, existing, catalog: dict[str, str]) -> None:
    """Issue (unless already on the chain), then whatever dispensations and
    closure are still missing: a rerun resumes, never repeats."""
    if existing is None:
        document = PrescriptionDocument(
            medication_id=catalog[item.medication],
            medication=item.medication,
            dosage=item.dosage,
            instructions="",
            quantity=item.quantity,
            prescriber_name=prescriber_name(item.prescriber),
            patient_name=item.patient,
            issued_on=datetime.now(UTC).date().isoformat(),
            locked_product_id=catalog[item.locked] if item.locked else "",
        )
        issued = await app.issue(item.prescriber, item.key, document, timedelta(days=30))
        prescription_id, already = issued.prescription_id, 0
        closed = False
    else:
        prescription_id, prescription = existing
        already, closed = prescription.dispensation_count, prescription.status != "active"
    for pharmacy, brand, units in item.dispensations[already:]:
        await app.dispense(pharmacy, prescription_id, bytes.fromhex(catalog[brand]), units)
    if item.closure and not closed:
        verb, reason = item.closure
        await getattr(app, verb)(item.prescriber, prescription_id, reason)
