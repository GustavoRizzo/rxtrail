"""The catalog as pages show it: off-chain details, on-chain status.

Names and guidance come from the public off-chain catalog; whether a
medication or product is withdrawn is read from the chain, in one batch call
per page, never stored off-chain.
"""

import json
from collections.abc import Iterable
from dataclasses import dataclass

from django.db.models import Count, Q

from records.models import CatalogMedication, CatalogProduct, PrescriptionRecord
from rxtrail.domain import CatalogStatus
from web.chain import with_chain

PICKER_RESULTS = 12


def chain_status(addresses: Iterable[str]) -> dict[str, CatalogStatus | None]:
    """On-chain status of each catalog address; None if it is not on this chain."""
    addresses = list(dict.fromkeys(addresses))
    if not addresses:
        return {}
    entries = with_chain(lambda _app, ledger: ledger.catalog_entries(addresses))
    return {a: (e.status if e else None) for a, e in zip(addresses, entries, strict=True)}


@dataclass(frozen=True)
class ProductCard:
    record: CatalogProduct
    status: CatalogStatus | None

    @property
    def available(self) -> bool:
        return self.status is CatalogStatus.ACTIVE


@dataclass(frozen=True)
class MedicationCard:
    record: CatalogMedication
    status: CatalogStatus | None
    products: list[ProductCard]

    @property
    def available(self) -> bool:
        return self.status is CatalogStatus.ACTIVE

    def data(self) -> dict:
        """What the prescription form needs once this medication is chosen."""
        m = self.record
        return {
            "id": m.medication_id,
            "name": m.name,
            "active_ingredient": m.active_ingredient,
            "form": m.form,
            "unit": m.unit,
            "max_quantity": m.max_quantity,
            "max_validity_days": m.max_validity_days,
            "usual_max_daily_units": m.usual_max_daily_units,
            "products": [
                {
                    "id": p.record.product_id,
                    "brand": p.record.brand_name,
                    "manufacturer": p.record.manufacturer.name,
                    "kind": p.record.get_kind_display().lower(),
                }
                for p in self.products
                if p.available
            ],
        }

    def json(self) -> str:
        return json.dumps(self.data())


def cards(medications: Iterable[CatalogMedication]) -> list[MedicationCard]:
    """Medications (with products and manufacturers prefetched) and their status."""
    medications = list(medications)
    status = chain_status(
        [m.address for m in medications]
        + [p.address for m in medications for p in m.products.all()]
    )
    return [
        MedicationCard(
            m,
            status.get(m.address),
            [ProductCard(p, status.get(p.address)) for p in m.products.all()],
        )
        for m in medications
    ]


def _with_products():
    return CatalogMedication.objects.prefetch_related("products__manufacturer")


def search(q: str, prescriber_key: str = "") -> list[CatalogMedication]:
    """By name, active ingredient, ATC code, brand or manufacturer. With no
    query, this prescriber's most used medications come first."""
    q = q.strip()
    if q:
        found = _with_products().filter(
            Q(name__icontains=q)
            | Q(active_ingredient__icontains=q)
            | Q(atc_code__istartswith=q)
            | Q(products__brand_name__icontains=q)
            | Q(products__manufacturer__name__icontains=q)
        )
        return list(found.distinct()[:PICKER_RESULTS])

    used = list(
        PrescriptionRecord.objects.filter(prescriber=prescriber_key)
        .values_list("document__medication_id", flat=True)
        .annotate(n=Count("id"))
        .order_by("-n")[:PICKER_RESULTS]
    )
    favourites = {m.medication_id: m for m in _with_products().filter(medication_id__in=used)}
    first = [favourites[i] for i in used if i in favourites]
    rest = _with_products().exclude(medication_id__in=favourites)[: PICKER_RESULTS - len(first)]
    return first + list(rest)


def by_address(addresses: Iterable[str]) -> dict[str, CatalogMedication | CatalogProduct]:
    """Catalog records behind on-chain addresses, for naming them on a page."""
    addresses = set(addresses)
    found: dict[str, CatalogMedication | CatalogProduct] = {
        m.address: m for m in CatalogMedication.objects.filter(address__in=addresses)
    }
    found.update(
        (p.address, p)
        for p in CatalogProduct.objects.select_related("manufacturer").filter(address__in=addresses)
    )
    return found


def open_data() -> dict:
    """The whole catalog as open data: everything needed to recompute each
    record's identity hash and compare it with the chain."""
    return {
        "about": (
            "RxTrail medication catalog. identity_hash = sha256 of the canonical JSON of "
            "identity_fields (keys sorted, values trimmed and lower-cased, no whitespace). "
            "Compare it with the account at `address` on Solana; the account's status "
            "says whether the record is withdrawn."
        ),
        "identity_fields": {
            "medication": ["active_ingredient", "strength", "form"],
            "product": ["medication_id", "manufacturer", "brand_name", "kind"],
        },
        "medications": [
            {
                "id": m.medication_id,
                "address": m.address,
                "identity_hash": m.identity_hash,
                "name": m.name,
                "active_ingredient": m.active_ingredient,
                "strength": m.strength,
                "form": m.form,
                "atc_code": m.atc_code,
                "unit": m.unit,
                "regulatory_list": m.regulatory_list,
                "dosage_guidance": m.dosage_guidance,
                "usual_max_daily_units": m.usual_max_daily_units,
                "max_quantity": m.max_quantity,
                "max_validity_days": m.max_validity_days,
                "products": [
                    {
                        "id": p.product_id,
                        "address": p.address,
                        "identity_hash": p.identity_hash,
                        "medication_id": m.medication_id,
                        "manufacturer": p.manufacturer.name,
                        "brand_name": p.brand_name,
                        "kind": p.kind,
                    }
                    for p in m.products.all()
                ],
            }
            for m in _with_products()
        ],
    }
