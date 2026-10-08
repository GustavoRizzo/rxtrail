"""The data behind the insights pages: the chain and the open catalog, nothing else.

Exactly what anyone can download: every program account (getProgramAccounts)
and the catalog published at /catalog.json. Never the operator's private
records: no patients, no prescription documents, no participant names. So
every number on those pages can be recomputed by a third party.

Reading the whole program is heavy on a public node, so the result is kept
for a short while. At scale an indexer replaces this.
"""

import asyncio
import time

from rxtrail.domain import ProductKind
from rxtrail.insights import MedicationInfo, ProductInfo, PublicData
from web.catalog import open_data
from web.chain import with_chain

CACHE_SECONDS = 30

_cache: dict[str, tuple[float, PublicData]] = {}


def catalog_from(published: dict) -> tuple[dict[str, MedicationInfo], dict[str, ProductInfo]]:
    """The open catalog's JSON, as the insights read it."""
    medications, products = {}, {}
    for m in published["medications"]:
        medications[m["address"]] = MedicationInfo(
            address=m["address"],
            id=m["id"],
            name=m["name"],
            active_ingredient=m["active_ingredient"],
            atc_code=m["atc_code"],
            max_quantity=m["max_quantity"],
            usual_max_daily_units=m["usual_max_daily_units"],
        )
        for p in m["products"]:
            products[p["address"]] = ProductInfo(
                address=p["address"],
                id=p["id"],
                medication=m["address"],
                manufacturer=p["manufacturer"],
                brand=p["brand_name"],
                kind=ProductKind(p["kind"]),
            )
    return medications, products


def assemble(prescriptions, dispensations, closures, published: dict) -> PublicData:
    """Only records of medications the published catalog covers: anything else
    on the program (another operator's catalog, test runs on a local chain)
    could not be named or checked against open data."""
    medications, products = catalog_from(published)
    prescriptions = [p for p in prescriptions if p.medication in medications]
    covered = {p.address for p in prescriptions}
    return PublicData(
        prescriptions=prescriptions,
        dispensations=[d for d in dispensations if d.prescription in covered],
        closures=[c for c in closures if c.prescription in covered],
        medications=medications,
        products=products,
    )


def public_data(fresh: bool = False) -> PublicData:
    cached = _cache.get("data")
    if cached and not fresh and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]

    async def read(_app, ledger):
        return await asyncio.gather(
            ledger.all_prescriptions(), ledger.all_dispensations(), ledger.all_closures()
        )

    prescriptions, dispensations, closures = with_chain(read)
    data = assemble(prescriptions, dispensations, closures, open_data())
    _cache["data"] = (time.monotonic(), data)
    return data


def forget() -> None:
    """Drop the cached copy (tests, and right after the demo is seeded)."""
    _cache.clear()
