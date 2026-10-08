"""The behaviour signals, over the demo's planned network: each investigation
finds exactly what was planted, and nothing else is called out."""

from datetime import timedelta

import pytest

from rxtrail import insights
from rxtrail.domain import (
    Closure,
    ClosureKind,
    Dispensation,
    Prescription,
    PrescriptionStatus,
    ProductKind,
)
from tests.fakes import T0
from web.demo.catalog import CATALOG
from web.demo.plan import AVOIDS_GENERICS, ESCITALOPRAM, ORDINARY, PROFILES, plan
from web.insights import assemble


def world(profile: str = "story") -> insights.PublicData:
    """The plan as the chain would hold it: keys stand for names, addresses for ids."""
    medications, products = {}, {}
    for m, versions in CATALOG:
        medications[f"med:{m.name}"] = insights.MedicationInfo(
            f"med:{m.name}", m.name, m.name, m.active_ingredient, m.atc_code, m.max_quantity
        )
        for maker, brand, kind in versions:
            products[f"prod:{brand}"] = insights.ProductInfo(
                f"prod:{brand}", brand, f"med:{m.name}", maker, brand, kind
            )
    prescriptions, dispensations, closures = [], [], []
    for n, item in enumerate(plan(profile)):
        address = f"rx:{item.key}"
        dispensed = sum(units for _, _, units in item.dispensations)
        status = PrescriptionStatus.ACTIVE
        if item.closure:
            status = (
                PrescriptionStatus.CANCELLED
                if item.closure[0] == "cancel"
                else PrescriptionStatus.STOPPED
            )
            closures.append(
                Closure(
                    f"closure:{item.key}",
                    address,
                    item.prescriber,
                    ClosureKind(status.value),
                    item.closure[1],
                    dispensed,
                    item.quantity - dispensed,
                    T0,
                )
            )
        prescriptions.append(
            Prescription(
                id=n.to_bytes(32, "big"),
                address=address,
                prescriber=item.prescriber,
                medication=f"med:{item.medication}",
                document_hash=bytes(32),
                quantity_granted=item.quantity,
                quantity_dispensed=dispensed,
                dispensation_count=len(item.dispensations),
                issued_at=T0,
                expires_at=T0 + timedelta(days=30),
                status=status,
                prescribed_product=f"prod:{item.locked}" if item.locked else None,
            )
        )
        remaining = item.quantity
        for index, (pharmacy, brand, units) in enumerate(item.dispensations):
            remaining -= units
            dispensations.append(
                Dispensation(
                    f"{address}-{index}",
                    address,
                    index,
                    pharmacy,
                    f"prod:{brand}",
                    units,
                    remaining,
                    T0,
                )
            )
    return insights.PublicData(prescriptions, dispensations, closures, medications, products)


PROFILE_NAMES = list(PROFILES)


@pytest.fixture(scope="module", params=PROFILE_NAMES)
def data(request):
    return world(request.param)


def standing_out(rows, key=lambda r: r.subject):
    return {key(r) for r in rows if r.stands_out}


def test_the_new_drug_push_points_at_the_three_prescribers(data):
    share = insights.class_share(data, "N06AB")

    assert share.focus.name == ESCITALOPRAM  # no generic: the default to look at
    assert standing_out(share.prescribers) == {"dr-fabio", "dr-gabriela", "dr-hugo"}
    assert share.prescribers[0].baseline < 0.3


def test_the_pharmacy_avoiding_generics_is_the_only_one_called_out(data):
    rates = insights.generic_rates(data)

    assert standing_out(rates.pharmacies) == {AVOIDS_GENERICS}
    assert 0.4 < rates.network < 0.7


def test_the_brand_locker_is_the_only_one_called_out(data):
    locks = insights.brand_locks(data)

    assert standing_out(locks.prescribers) == {"dr-iris"}
    assert locks.by_manufacturer[0][0] == "Delta Pharma"  # Dormirex's maker


def test_volume_fires_for_both_and_the_context_tells_them_apart(data):
    flagged = {
        (r.prescriber, r.medication.name): r for r in insights.unusual_volume(data) if r.stands_out
    }

    assert {
        ("dr-joao", "Methylphenidate 10 mg tablet"),
        ("dr-karen", "Clonazepam 2 mg tablet"),
    } <= set(flagged)
    # Other stories' prescribers write a lot of their drug too; the ordinary never stand out.
    assert not {who for who, _ in flagged} & set(ORDINARY)
    busy = flagged[("dr-joao", "Methylphenidate 10 mg tablet")]
    specialist = flagged[("dr-karen", "Clonazepam 2 mg tablet")]
    assert busy.above_limit > 0 and busy.top_pharmacy_share >= 0.6
    assert specialist.above_limit == 0 and specialist.top_pharmacy_share < 0.6


def test_a_profile_gathers_the_signals_of_its_prescriber(data):
    profile = insights.prescriber_profile(data, "dr-joao")

    assert any("Methylphenidate" in s for s in profile.signals)
    assert profile.above_limit > 0
    assert insights.prescriber_profile(data, "dr-ana").signals == []
    assert insights.prescriber_profile(data, "nobody") is None


def test_a_pharmacy_profile_shows_the_brands_it_favours(data):
    profile = insights.pharmacy_profile(data, AVOIDS_GENERICS)

    assert profile.generics.stands_out
    assert any("generics" in s for s in profile.signals)
    assert profile.manufacturers[0].share > profile.manufacturers[0].network


def test_the_overview_counts_prescriptions_never_patients(data):
    o = insights.overview(data, T0)

    assert o.prescriptions == len(data.prescriptions)
    assert o.dispensations == len(data.dispensations)
    assert o.units_dispensed == sum(d.quantity for d in data.dispensations)
    assert sum(o.closures.values()) == len(data.closures) > 0
    assert not hasattr(o, "patients")


def test_too_few_records_never_stand_out():
    data = world()
    lone = Prescription(
        id=b"\xff" * 32,
        address="rx:lone",
        prescriber="dr-lone",
        medication=f"med:{ESCITALOPRAM}",
        document_hash=bytes(32),
        quantity_granted=30,
        quantity_dispensed=0,
        dispensation_count=0,
        issued_at=T0,
        expires_at=T0 + timedelta(days=30),
        status=PrescriptionStatus.ACTIVE,
    )
    data = insights.PublicData(
        [*data.prescriptions, lone],
        data.dispensations,
        data.closures,
        data.medications,
        data.products,
    )

    row = next(r for r in insights.class_share(data, "N06AB").prescribers if r.subject == "dr-lone")

    assert row.value == 1.0 and not row.enough_data and not row.stands_out


def test_records_outside_the_open_catalog_are_left_out():
    data = world()
    published = {
        "medications": [
            {
                "address": m.address,
                "id": m.id,
                "name": m.name,
                "active_ingredient": m.active_ingredient,
                "atc_code": m.atc_code,
                "max_quantity": m.max_quantity,
                "usual_max_daily_units": None,
                "products": [
                    {
                        "address": p.address,
                        "id": p.id,
                        "manufacturer": p.manufacturer,
                        "brand_name": p.brand,
                        "kind": p.kind.value,
                    }
                    for p in data.products_of[m.address]
                ],
            }
            for m in data.medications.values()
        ]
    }
    stray = data.prescriptions[0].__class__(
        **{
            **{f: getattr(data.prescriptions[0], f) for f in Prescription.__slots__},
            "address": "rx:stray",
            "medication": "med:unknown",
        }
    )

    kept = assemble([*data.prescriptions, stray], data.dispensations, data.closures, published)

    assert len(kept.prescriptions) == len(data.prescriptions)
    assert kept.products[f"prod:{CATALOG[0][1][0][1]}"].kind is ProductKind.REFERENCE


def test_participants_appear_by_their_key_shortened():
    assert insights.pseudonym("7xK3abcdefghijklmnopQpQ2") == "7xK3…QpQ2"
