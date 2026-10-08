"""Behaviour signals, computed from public data only: the chain and the open catalog.

Anyone can download the same data and get the same numbers: nothing here
reads personal data or the operator's private records. Prescribers and
pharmacies appear by their on-chain key (a pseudonym), never by name.

A signal is a reason to look closer, never a finding: a number that stands
out has legitimate explanations as often as not, and only an authority can
tell them apart. Every comparison keeps its sample size, and none is called
out below MIN_SAMPLE records.

Pure functions over plain data, so each one is testable without a chain.
"""

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from statistics import median

from rxtrail.domain import (
    Closure,
    ClosureKind,
    ClosureReason,
    Dispensation,
    Prescription,
    ProductKind,
    Standing,
)

# Fewer records than this and a rate says nothing: never called out.
MIN_SAMPLE = 5

# How far from the baseline a value must be to stand out: at least this much
# in absolute terms, and at least STAND_OUT_RATIO times (or 1/ratio of) it.
STAND_OUT_GAP = 0.2
STAND_OUT_RATIO = 2.0
VOLUME_RATIO = 3.0  # volume: this many times the peers' median

# WHO ATC level 4 (chemical subgroup) names, for the classes in the catalog.
ATC_CLASSES = {
    "N03AE": "Benzodiazepine derivatives (antiepileptics)",
    "N05BA": "Benzodiazepine derivatives (anxiolytics)",
    "N05CF": "Benzodiazepine-related drugs (Z-drugs)",
    "N06AB": "Selective serotonin reuptake inhibitors (SSRIs)",
    "N06BA": "Centrally acting sympathomimetics",
}


def therapeutic_class(atc_code: str) -> str:
    """ATC level 4: medications that do the same job (e.g. N06AB, the SSRIs)."""
    return atc_code[:5].upper()


def class_name(atc_class: str) -> str:
    return ATC_CLASSES.get(atc_class, atc_class)


def pseudonym(address: str) -> str:
    """How a participant appears: their public key, shortened. Stable, and the
    same id anyone sees on the chain."""
    return f"{address[:4]}…{address[-4:]}"


# -- the data ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MedicationInfo:
    """A medication as the open catalog publishes it."""

    address: str
    id: str
    name: str
    active_ingredient: str
    atc_code: str
    max_quantity: int | None = None
    usual_max_daily_units: int | None = None

    @property
    def atc_class(self) -> str:
        return therapeutic_class(self.atc_code)


@dataclass(frozen=True, slots=True)
class ProductInfo:
    address: str
    id: str
    medication: str  # address
    manufacturer: str
    brand: str
    kind: ProductKind


@dataclass
class PublicData:
    """Everything public: the program's accounts and the open catalog."""

    prescriptions: list[Prescription]
    dispensations: list[Dispensation]
    closures: list[Closure]
    medications: dict[str, MedicationInfo]  # by address
    products: dict[str, ProductInfo]  # by address

    @cached_property
    def prescription_at(self) -> dict[str, Prescription]:
        return {p.address: p for p in self.prescriptions}

    @cached_property
    def products_of(self) -> dict[str, list[ProductInfo]]:
        found: dict[str, list[ProductInfo]] = defaultdict(list)
        for product in self.products.values():
            found[product.medication].append(product)
        return found

    def has_choice(self, medication: str) -> bool:
        """More than one version on the market: someone chose which one."""
        return len(self.products_of.get(medication, [])) > 1

    def generic_substitutable(self, medication: str) -> bool:
        """A generic exists, and so does a version that is not one."""
        kinds = {p.kind for p in self.products_of.get(medication, [])}
        return ProductKind.GENERIC in kinds and len(kinds) > 1

    @cached_property
    def prescribers(self) -> list[str]:
        return sorted({p.prescriber for p in self.prescriptions})

    @cached_property
    def pharmacies(self) -> list[str]:
        return sorted({d.dispenser for d in self.dispensations})

    def medication_of(self, prescription: Prescription) -> MedicationInfo | None:
        return self.medications.get(prescription.medication)

    @cached_property
    def classes(self) -> dict[str, list[MedicationInfo]]:
        """Therapeutic classes with prescriptions, and their medications."""
        prescribed = {p.medication for p in self.prescriptions}
        found: dict[str, list[MedicationInfo]] = defaultdict(list)
        for m in self.medications.values():
            if m.atc_code and m.address in prescribed:
                found[m.atc_class].append(m)
        return {k: sorted(v, key=lambda m: m.name) for k, v in sorted(found.items())}


# -- comparisons -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Comparison:
    """One subject's value against the baseline it is compared with."""

    subject: str  # an address, or a manufacturer's name
    value: float
    baseline: float
    sample: int  # how many records the value is computed from
    hits: int = 0  # how many of them count towards the value (a rate's numerator)
    stands_out: bool = False

    @property
    def ratio(self) -> float | None:
        return self.value / self.baseline if self.baseline else None

    @property
    def enough_data(self) -> bool:
        return self.sample >= MIN_SAMPLE


def _above(value: float, baseline: float, sample: int) -> bool:
    return (
        sample >= MIN_SAMPLE
        and value - baseline >= STAND_OUT_GAP
        and value >= baseline * STAND_OUT_RATIO
    )


def _below(value: float, baseline: float, sample: int) -> bool:
    return (
        sample >= MIN_SAMPLE
        and baseline - value >= STAND_OUT_GAP
        and value <= baseline / STAND_OUT_RATIO
    )


def _rates(
    counts: dict[str, tuple[int, int]], baseline: float, stands_out: Callable
) -> list[Comparison]:
    """(hits, sample) per subject → comparisons, most striking first."""
    rows = [
        Comparison(s, hits / n, baseline, n, hits, stands_out(hits / n, baseline, n))
        for s, (hits, n) in counts.items()
        if n
    ]
    return sorted(rows, key=lambda r: (not r.stands_out, -abs(r.value - baseline), r.subject))


def _median_of_peers(counts: dict[str, tuple[int, int]]) -> float:
    """Median rate among subjects with enough data (all of them if none has)."""
    rates = [h / n for h, n in counts.values() if n >= MIN_SAMPLE] or [
        h / n for h, n in counts.values() if n
    ]
    return median(rates) if rates else 0.0


# -- A1: who is pushing a new drug? --------------------------------------------------


@dataclass(frozen=True)
class ClassShare:
    atc_class: str
    medications: list[tuple[MedicationInfo, int]]  # each one's prescriptions in the class
    focus: MedicationInfo | None
    prescribers: list[Comparison]  # the focus medication's share of each one's class

    @property
    def total(self) -> int:
        return sum(n for _, n in self.medications)


def default_focus(data: PublicData, atc_class: str) -> MedicationInfo | None:
    """The medication to look at in a class: one with no generic on the market
    (usually the newest and dearest), the most prescribed of those; else the
    most prescribed."""
    counts = Counter(p.medication for p in data.prescriptions)
    members = data.classes.get(atc_class, [])
    no_generic = [
        m
        for m in members
        if ProductKind.GENERIC not in {p.kind for p in data.products_of.get(m.address, [])}
    ]
    pool = no_generic or members
    return max(pool, key=lambda m: (counts[m.address], m.name), default=None)


def class_share(data: PublicData, atc_class: str, focus: str | None = None) -> ClassShare:
    """Each prescriber's share of a class going to one medication, against the
    median of their peers. Same job, different molecule: the "me-too" push."""
    members = data.classes.get(atc_class, [])
    addresses = {m.address for m in members}
    chosen = data.medications.get(focus) if focus in addresses else None
    chosen = chosen or default_focus(data, atc_class)
    in_class = [p for p in data.prescriptions if p.medication in addresses]
    per_medication = Counter(p.medication for p in in_class)
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for p in in_class:
        counts[p.prescriber][1] += 1
        if chosen and p.medication == chosen.address:
            counts[p.prescriber][0] += 1
    tallies = {k: (h, n) for k, (h, n) in counts.items()}
    baseline = _median_of_peers(tallies)
    return ClassShare(
        atc_class,
        sorted(((m, per_medication[m.address]) for m in members), key=lambda x: -x[1]),
        chosen,
        _rates(tallies, baseline, _above),
    )


# -- A2: who locks the brand? ----------------------------------------------------------


@dataclass(frozen=True)
class BrandLocks:
    prescribers: list[Comparison]  # share of prescriptions with a locked brand
    by_manufacturer: list[tuple[str, int]]  # locks per manufacturer, most first

    def manufacturers_locked_by(self, data: PublicData, prescriber: str) -> Counter:
        return Counter(
            data.products[p.prescribed_product].manufacturer
            for p in data.prescriptions
            if p.prescriber == prescriber
            and p.prescribed_product
            and p.prescribed_product in data.products
        )


def brand_locks(data: PublicData) -> BrandLocks:
    """How often each prescriber forbids substitution, where there was a
    choice of versions, against the median of their peers."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    makers: Counter = Counter()
    for p in data.prescriptions:
        if not data.has_choice(p.medication):
            continue
        counts[p.prescriber][1] += 1
        if p.prescribed_product:
            counts[p.prescriber][0] += 1
            if product := data.products.get(p.prescribed_product):
                makers[product.manufacturer] += 1
    tallies = {k: (h, n) for k, (h, n) in counts.items()}
    return BrandLocks(_rates(tallies, _median_of_peers(tallies), _above), makers.most_common())


# -- B: which pharmacies avoid generics? ----------------------------------------------


def _substitutable(data: PublicData, d: Dispensation) -> bool:
    """The pharmacy could have handed out a generic: one exists, the medication
    has other versions too, and the prescriber did not lock a brand."""
    rx = data.prescription_at.get(d.prescription)
    return (
        rx is not None
        and rx.prescribed_product is None
        and data.generic_substitutable(rx.medication)
        and d.product in data.products
    )


@dataclass(frozen=True)
class GenericRates:
    network: float  # the whole network's generic rate, pooled
    sample: int
    pharmacies: list[Comparison]


def generic_rates(data: PublicData) -> GenericRates:
    """Each pharmacy's share of generics where it could have chosen one,
    against the whole network's. Behaviour, not money: no prices here."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for d in data.dispensations:
        if not _substitutable(data, d):
            continue
        counts[d.dispenser][1] += 1
        if data.products[d.product].kind is ProductKind.GENERIC:
            counts[d.dispenser][0] += 1
    hits = sum(h for h, _ in counts.values())
    total = sum(n for _, n in counts.values())
    network = hits / total if total else 0.0
    tallies = {k: (h, n) for k, (h, n) in counts.items()}
    return GenericRates(network, total, _rates(tallies, network, _below))


# -- C: unusual volume ----------------------------------------------------------------


@dataclass(frozen=True)
class VolumeRow:
    prescriber: str
    medication: MedicationInfo
    prescriptions: int
    units: int
    peers_median: float  # prescriptions, among prescribers of this medication
    above_limit: int  # prescriptions above the medication's per-prescription limit
    top_pharmacy_share: float  # how much of it one single pharmacy dispensed
    stands_out: bool


def above_limit(data: PublicData, p: Prescription) -> bool:
    """More than the regulatory limit per prescription: warned, never blocked."""
    m = data.medication_of(p)
    return bool(m and m.max_quantity and p.quantity_granted > m.max_quantity)


def unusual_volume(data: PublicData) -> list[VolumeRow]:
    """Prescriptions per prescriber and medication, against the median of the
    prescribers of that medication. Context comes with it: limits exceeded,
    and how concentrated in one pharmacy the dispensing was."""
    by_pair: dict[tuple[str, str], list[Prescription]] = defaultdict(list)
    for p in data.prescriptions:
        by_pair[(p.prescriber, p.medication)].append(p)
    per_medication: dict[str, list[int]] = defaultdict(list)
    for (_, medication), found in by_pair.items():
        per_medication[medication].append(len(found))
    dispensed_by = _dispensers_by_prescription(data)

    rows = []
    for (prescriber, medication), found in by_pair.items():
        info = data.medications.get(medication)
        if info is None:
            continue
        typical = median(per_medication[medication])
        pharmacies = Counter(ph for p in found for ph in dispensed_by.get(p.address, []))
        top = pharmacies.most_common(1)[0][1] / sum(pharmacies.values()) if pharmacies else 0.0
        rows.append(
            VolumeRow(
                prescriber,
                info,
                len(found),
                sum(p.quantity_granted for p in found),
                typical,
                sum(above_limit(data, p) for p in found),
                top,
                len(found) >= MIN_SAMPLE and len(found) >= typical * VOLUME_RATIO,
            )
        )
    return sorted(
        rows,
        key=lambda r: (not r.stands_out, -(r.prescriptions / (r.peers_median or 1)), r.prescriber),
    )


def _dispensers_by_prescription(data: PublicData) -> dict[str, list[str]]:
    found: dict[str, list[str]] = defaultdict(list)
    for d in data.dispensations:
        found[d.prescription].append(d.dispenser)
    return found


@dataclass(frozen=True)
class ManufacturerShare:
    pharmacy: str
    manufacturer: str
    share: float  # of the pharmacy's dispensations where there was a choice
    network: float  # the manufacturer's share across the network, same basis
    sample: int
    stands_out: bool


def manufacturer_concentration(data: PublicData) -> list[ManufacturerShare]:
    """Pharmacies dispensing one manufacturer far above its share of the
    network, counting only dispensations where there was a choice."""
    per_pharmacy: dict[str, Counter] = defaultdict(Counter)
    network: Counter = Counter()
    for d in data.dispensations:
        rx = data.prescription_at.get(d.prescription)
        product = data.products.get(d.product)
        if rx is None or product is None or rx.prescribed_product:
            continue
        if not data.has_choice(rx.medication):
            continue
        per_pharmacy[d.dispenser][product.manufacturer] += 1
        network[product.manufacturer] += 1
    total = sum(network.values())
    rows = []
    for pharmacy, makers in per_pharmacy.items():
        n = sum(makers.values())
        for maker, count in makers.items():
            share, base = count / n, network[maker] / total
            rows.append(ManufacturerShare(pharmacy, maker, share, base, n, _above(share, base, n)))
    return sorted(rows, key=lambda r: (not r.stands_out, -(r.share - r.network), r.pharmacy))


# -- overview ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Overview:
    prescriptions: int
    prescribers: int
    pharmacies: int
    dispensations: int
    units_granted: int
    units_dispensed: int
    units_voided: int
    standing: Counter  # Standing → prescriptions
    closures: Counter  # ClosureReason → closures
    by_medication: list[tuple[MedicationInfo, int, int, int]]  # rx, granted, dispensed
    per_prescriber_median: float
    per_prescriber_max: int

    @property
    def use_rate(self) -> float:
        return self.units_dispensed / self.units_granted if self.units_granted else 0.0

    # Lists for templates: a template looking up `counter.most_common` gets a 0.
    @property
    def standing_rows(self) -> list[tuple[Standing, int]]:
        return self.standing.most_common()

    @property
    def closure_rows(self) -> list[tuple[ClosureReason, int]]:
        return self.closures.most_common()


def overview(data: PublicData, now: datetime) -> Overview:
    """The whole network in numbers. Counts of prescriptions, never of patients:
    the chain does not know who the patients are."""
    per_medication: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for p in data.prescriptions:
        row = per_medication[p.medication]
        row[0] += 1
        row[1] += p.quantity_granted
        row[2] += p.quantity_dispensed
    per_prescriber = Counter(p.prescriber for p in data.prescriptions)
    return Overview(
        prescriptions=len(data.prescriptions),
        prescribers=len(per_prescriber),
        pharmacies=len(data.pharmacies),
        dispensations=len(data.dispensations),
        units_granted=sum(p.quantity_granted for p in data.prescriptions),
        units_dispensed=sum(p.quantity_dispensed for p in data.prescriptions),
        units_voided=sum(c.quantity_voided for c in data.closures),
        standing=Counter(p.standing(now) for p in data.prescriptions),
        closures=Counter(c.reason for c in data.closures),
        by_medication=sorted(
            (
                (data.medications[m], *counts)
                for m, counts in per_medication.items()
                if m in data.medications
            ),
            key=lambda row: -row[1],
        ),
        per_prescriber_median=median(per_prescriber.values()) if per_prescriber else 0,
        per_prescriber_max=max(per_prescriber.values(), default=0),
    )


# -- one entity -----------------------------------------------------------------------


def _share_rows(counter: Counter) -> list[tuple[str, int, float]]:
    total = sum(counter.values())
    return [(k, n, n / total) for k, n in counter.most_common()] if total else []


@dataclass(frozen=True)
class PrescriberProfile:
    address: str
    prescriptions: list[Prescription]
    medications: list[tuple[MedicationInfo, int, float]]  # rx here, peers' median
    classes: list[tuple[str, Comparison]]  # focus share in each class they prescribe
    locks: Comparison | None
    above_limit: int
    pharmacies: list[tuple[str, int, float]]  # dispensations of their prescriptions
    closures: list[tuple[tuple[ClosureKind, ClosureReason], int]]  # most first
    signals: list[str] = field(default_factory=list)


def prescriber_profile(data: PublicData, address: str) -> PrescriberProfile | None:
    mine = [p for p in data.prescriptions if p.prescriber == address]
    if not mine:
        return None
    signals = []
    peers: dict[str, list[int]] = defaultdict(list)
    counts = Counter((p.prescriber, p.medication) for p in data.prescriptions)
    for (_, medication), n in counts.items():
        peers[medication].append(n)
    medications = sorted(
        (
            (data.medications[m], n, median(peers[m]))
            for (who, m), n in counts.items()
            if who == address and m in data.medications
        ),
        key=lambda row: -row[1],
    )
    classes = []
    for atc_class in sorted({m.atc_class for m, _, _ in medications}):
        if len(data.classes.get(atc_class, [])) < 2:
            continue
        share = class_share(data, atc_class)
        mine_in = next((c for c in share.prescribers if c.subject == address), None)
        if mine_in and share.focus:
            classes.append((atc_class, mine_in))
            if mine_in.stands_out:
                signals.append(f"Prescribes far more {share.focus.name} than peers, in its class")
    locks = next((c for c in brand_locks(data).prescribers if c.subject == address), None)
    if locks and locks.stands_out:
        signals.append("Locks the brand far more often than peers")
    for row in unusual_volume(data):
        if row.prescriber == address and row.stands_out:
            signals.append(f"{row.medication.name}: volume far above peers")
    over = sum(above_limit(data, p) for p in mine)
    addresses = {p.address for p in mine}
    pharmacies = Counter(d.dispenser for d in data.dispensations if d.prescription in addresses)
    return PrescriberProfile(
        address,
        sorted(mine, key=lambda p: p.issued_at, reverse=True),
        medications,
        classes,
        locks,
        over,
        _share_rows(pharmacies),
        Counter((c.kind, c.reason) for c in data.closures if c.prescriber == address).most_common(),
        signals,
    )


@dataclass(frozen=True)
class PharmacyProfile:
    address: str
    dispensations: list[Dispensation]
    units: int
    generics: Comparison | None
    network_generic_rate: float
    manufacturers: list[ManufacturerShare]
    prescribers: list[tuple[str, int, float]]  # whose prescriptions it dispensed
    medications: list[tuple[MedicationInfo, int]]
    signals: list[str] = field(default_factory=list)


def pharmacy_profile(data: PublicData, address: str) -> PharmacyProfile | None:
    mine = [d for d in data.dispensations if d.dispenser == address]
    if not mine:
        return None
    rates = generic_rates(data)
    generics = next((c for c in rates.pharmacies if c.subject == address), None)
    makers = [r for r in manufacturer_concentration(data) if r.pharmacy == address]
    signals = []
    if generics and generics.stands_out:
        signals.append("Hands out generics far less often than the network")
    signals += [
        f"Dispenses {r.manufacturer} far above its market share" for r in makers if r.stands_out
    ]
    prescribers = Counter(
        data.prescription_at[d.prescription].prescriber
        for d in mine
        if d.prescription in data.prescription_at
    )
    medications = Counter(
        data.prescription_at[d.prescription].medication
        for d in mine
        if d.prescription in data.prescription_at
    )
    return PharmacyProfile(
        address,
        sorted(mine, key=lambda d: d.dispensed_at, reverse=True),
        sum(d.quantity for d in mine),
        generics,
        rates.network,
        sorted(makers, key=lambda r: -r.share),
        _share_rows(prescribers),
        [(data.medications[m], n) for m, n in medications.most_common() if m in data.medications],
        signals,
    )


@dataclass(frozen=True)
class MedicationProfile:
    medication: MedicationInfo
    prescriptions: int
    units_granted: int
    units_dispensed: int
    prescribers: list[tuple[str, int, bool]]  # prescriptions each, stands out
    peers_median: float
    products: list[tuple[ProductInfo, int, int]]  # dispensations, units, of each version
    pharmacies: list[tuple[str, int, float]]
    class_share: float  # of its class's prescriptions
    locked: int


def medication_profile(data: PublicData, address: str) -> MedicationProfile | None:
    medication = data.medications.get(address)
    if medication is None:
        return None
    mine = [p for p in data.prescriptions if p.medication == address]
    addresses = {p.address for p in mine}
    dispensed = [d for d in data.dispensations if d.prescription in addresses]
    per_prescriber = Counter(p.prescriber for p in mine)
    typical = median(per_prescriber.values()) if per_prescriber else 0
    flagged = {
        r.prescriber
        for r in unusual_volume(data)
        if r.medication.address == address and r.stands_out
    }
    per_product: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for d in dispensed:
        per_product[d.product][0] += 1
        per_product[d.product][1] += d.quantity
    in_class = [
        p
        for p in data.prescriptions
        if (m := data.medication_of(p)) and m.atc_class == medication.atc_class
    ]
    return MedicationProfile(
        medication,
        len(mine),
        sum(p.quantity_granted for p in mine),
        sum(p.quantity_dispensed for p in mine),
        [(who, n, who in flagged) for who, n in per_prescriber.most_common()],
        typical,
        sorted(
            (
                (product, *per_product.get(product.address, [0, 0]))
                for product in data.products_of.get(address, [])
            ),
            key=lambda row: -row[2],
        ),
        _share_rows(Counter(d.dispenser for d in dispensed)),
        len(mine) / len(in_class) if in_class else 0.0,
        sum(1 for p in mine if p.prescribed_product),
    )


@dataclass(frozen=True)
class ManufacturerProfile:
    name: str
    products: list[tuple[ProductInfo, MedicationInfo | None, int, float]]  # units, share
    pharmacies: list[ManufacturerShare]
    lockers: list[tuple[str, int]]  # prescribers locking its brands


def manufacturer_profile(data: PublicData, name: str) -> ManufacturerProfile | None:
    made = [p for p in data.products.values() if p.manufacturer == name]
    if not made:
        return None
    units_by_product: Counter = Counter()
    units_by_medication: Counter = Counter()
    for d in data.dispensations:
        product = data.products.get(d.product)
        if product:
            units_by_product[product.address] += d.quantity
            units_by_medication[product.medication] += d.quantity
    lockers = Counter(
        p.prescriber
        for p in data.prescriptions
        if p.prescribed_product in {m.address for m in made}
    )
    return ManufacturerProfile(
        name,
        [
            (
                p,
                data.medications.get(p.medication),
                units_by_product[p.address],
                units_by_product[p.address] / units_by_medication[p.medication]
                if units_by_medication[p.medication]
                else 0.0,
            )
            for p in sorted(made, key=lambda p: p.brand)
        ],
        [r for r in manufacturer_concentration(data) if r.manufacturer == name],
        lockers.most_common(),
    )
