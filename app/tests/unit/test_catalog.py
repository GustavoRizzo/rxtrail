"""The identity hash that pins a catalog record's meaning, and the warnings."""

from dataclasses import replace

from rxtrail import catalog
from rxtrail.domain import MedicationDetails, ProductDetails, ProductKind

CLONAZEPAM = MedicationDetails(
    name="Clonazepam 2 mg tablet",
    active_ingredient="clonazepam",
    strength="2 mg",
    form="tablet",
    atc_code="N03AE01",
    unit="tablet",
    usual_max_daily_units=3,
    max_quantity=60,
    max_validity_days=30,
)


def test_the_hash_covers_what_defines_the_medication():
    original = catalog.identity_hash(CLONAZEPAM)

    assert catalog.identity_hash(replace(CLONAZEPAM, strength="0.5 mg")) != original
    assert catalog.identity_hash(replace(CLONAZEPAM, active_ingredient="alprazolam")) != original


def test_guidance_and_class_can_change_without_touching_the_chain():
    original = catalog.identity_hash(CLONAZEPAM)

    corrected = replace(
        CLONAZEPAM, name="Clonazepam 2mg", atc_code="N05BA", dosage_guidance="new", max_quantity=90
    )

    assert catalog.identity_hash(corrected) == original


def test_the_same_record_typed_differently_hashes_the_same():
    assert catalog.identity_hash(
        replace(CLONAZEPAM, active_ingredient=" Clonazepam ", form="TABLET")
    ) == catalog.identity_hash(CLONAZEPAM)


def test_a_product_is_defined_by_its_medication_maker_brand_and_kind():
    product = ProductDetails("a1" * 32, "Acme Pharma", "Calmazen", ProductKind.REFERENCE)
    original = catalog.identity_hash(product)

    assert catalog.identity_hash(replace(product, kind=ProductKind.GENERIC)) != original
    assert catalog.identity_hash(replace(product, manufacturer="Beta Labs")) != original
    assert len(original) == 32


def test_a_prescription_within_the_guidance_raises_no_warning():
    assert catalog.warnings(CLONAZEPAM, quantity=30, valid_days=30) == []


def test_warnings_explain_each_limit_passed_without_blocking():
    found = catalog.warnings(CLONAZEPAM, quantity=120, valid_days=35)

    assert any("regulatory limit of 60" in w for w in found)
    assert any("regulatory validity of 30 days" in w for w in found)
    assert any("usual maximum of 3 a day" in w for w in found)


def test_no_limit_in_the_catalog_means_no_warning():
    bare = MedicationDetails("X", "x", "1 mg", "tablet")
    assert catalog.warnings(bare, quantity=10_000, valid_days=365) == []
