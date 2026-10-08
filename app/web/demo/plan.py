"""The demo's prescriptions, planned before anything is sent.

Deterministic (a fixed random seed): the same profile always plans the same
prescriptions, so a seeding run that stopped half-way picks up where it
left, and tests can check that each investigation finds what was planted.

Most of the network is ordinary. A few prescribers and one pharmacy carry a
story, each one a pattern the insights pages should surface:

- new-drug: three prescribers give the dear escitalopram (no generic) most
  of their SSRI prescriptions; their peers mostly give the generic citalopram;
- generics: one pharmacy (pharmacy-three) hands out the brand almost every
  time a generic was possible;
- brand-locks: one prescriber locks the Dormirex brand on zolpidem again and
  again;
- volume: one prescriber writes far more methylphenidate than peers, above
  the per-prescription limit, nearly all dispensed at one pharmacy;
- specialist: one prescriber writes as much clonazepam, but within limits and
  spread over every pharmacy. The volume signal fires for both: only the
  context tells them apart (the false positive, on purpose).
"""

import random
from dataclasses import dataclass, replace

from rxtrail.domain import ClosureReason, ProductKind
from web.demo.catalog import CATALOG

CITALOPRAM = "Citalopram 20 mg tablet"
ESCITALOPRAM = "Escitalopram 10 mg tablet"
CLONAZEPAM = "Clonazepam 2 mg tablet"
ALPRAZOLAM = "Alprazolam 0.5 mg tablet"
METHYLPHENIDATE = "Methylphenidate 10 mg tablet"
ZOLPIDEM = "Zolpidem 10 mg tablet"

DOSAGE = {
    CITALOPRAM: "1 tablet in the morning",
    ESCITALOPRAM: "1 tablet in the morning",
    CLONAZEPAM: "1 tablet at night",
    ALPRAZOLAM: "1 tablet if anxious",
    METHYLPHENIDATE: "1 tablet in the morning",
    ZOLPIDEM: "1 tablet at bedtime",
}
QUANTITIES = {
    CITALOPRAM: (30, 60),
    ESCITALOPRAM: (30, 60),
    CLONAZEPAM: (30, 60),
    ALPRAZOLAM: (20, 30, 60),
    METHYLPHENIDATE: (30, 60),
    ZOLPIDEM: (15, 30),
}

# brand -> (medication, kind)
PRODUCTS = {brand: (m.name, kind) for m, products in CATALOG for _, brand, kind in products}

ORDINARY = [
    "dr-ana",
    "dr-bruno",
    "dr-carla",
    "dr-diego",
    "dr-elisa",
    "dr-leo",
    "dr-marta",
    "dr-nuno",
]
PHARMACIES = {"pharmacy-one": 3.0, "pharmacy-two": 3.0, "pharmacy-three": 2.5, "pharmacy-four": 1.5}
AVOIDS_GENERICS = "pharmacy-three"

FIRST = [
    "Ana",
    "Bruno",
    "Carla",
    "Davi",
    "Elena",
    "Felipe",
    "Gisele",
    "Heitor",
    "Isabel",
    "Jonas",
    "Laura",
    "Mateus",
    "Nina",
    "Otávio",
]
LAST = [
    "Almeida",
    "Barros",
    "Costa",
    "Dias",
    "Esteves",
    "Freitas",
    "Gomes",
    "Lima",
    "Moreira",
    "Neves",
    "Pires",
    "Ramos",
    "Souza",
]


@dataclass(frozen=True)
class Planned:
    key: str  # the patient's document number: stable, finds the item again on a rerun
    patient: str
    prescriber: str
    medication: str  # catalog name
    quantity: int
    locked: str = ""  # brand, when the prescriber forbids substitution
    dispensations: tuple[tuple[str, str, int], ...] = ()  # (pharmacy, brand, units)
    closure: tuple[str, ClosureReason] | None = None  # ("cancel" | "stop", reason)
    story: str = ""

    @property
    def dosage(self) -> str:
        return DOSAGE[self.medication]


@dataclass(frozen=True)
class Profile:
    name: str
    extra_prescribers: int  # ordinary ones beyond the named cast
    extra_pharmacies: int
    story_scale: int  # stories grow with the network, or they would drown
    about: str
    key_prefix: str  # each profile's items are its own: never mistaken for another's


PROFILES = {
    "story": Profile(
        "story", 0, 0, 1, "every investigation, with just enough peers to compare", "DEMO"
    ),
    "full": Profile(
        "full", 32, 4, 3, "a bigger network around the same stories (localnet)", "FULL"
    ),
}

# The four samples the demo always had: what the login accounts see first.
SHOWCASE = [
    Planned(
        "123.456.789-00",
        "Maria Silva",
        "dr-ana",
        CLONAZEPAM,
        30,
        dispensations=(("pharmacy-one", "Clonazepam Beta 2 mg", 20),),
    ),
    Planned("987.654.321-00", "João Pereira", "dr-ana", METHYLPHENIDATE, 60),
    Planned(
        "555.444.333-22",
        "Carla Mendes",
        "dr-bruno",
        ALPRAZOLAM,
        20,
        dispensations=(
            ("pharmacy-one", "Serenix 0.5 mg", 10),
            ("pharmacy-one", "Alprazolam Beta 0.5 mg", 10),
        ),
    ),
    Planned(
        "222.333.444-55",
        "Pedro Alves",
        "dr-bruno",
        ZOLPIDEM,
        30,
        locked="Dormirex 10 mg",
        dispensations=(("pharmacy-one", "Dormirex 10 mg", 10),),
    ),
]


def prescribers(profile: str) -> list[str]:
    """Every prescriber the plan uses, ordinary and story ones."""
    return sorted({item.prescriber for item in plan(profile)})


def pharmacies(profile: str) -> list[str]:
    return [*PHARMACIES, *_extra_pharmacies(PROFILES[profile])]


def _extra_pharmacies(profile: Profile) -> list[str]:
    return [f"pharmacy-{i:02d}" for i in range(5, 5 + profile.extra_pharmacies)]


class _Planner:
    def __init__(self, profile: Profile):
        self.rng = random.Random(2026)
        self.prefix = profile.key_prefix
        self.weights = {**PHARMACIES, **dict.fromkeys(_extra_pharmacies(profile), 2.0)}
        self.items: list[Planned] = []
        self._rotation = 0

    def add(self, prescriber, medication, count, story="", quantity=None, locked="", rule=None):
        for _ in range(count):
            n = len(self.items) + 1
            amount = quantity or self.rng.choice(QUANTITIES[medication])
            item = Planned(
                key=f"{self.prefix}-{n:04d}",
                patient=f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}",
                prescriber=prescriber,
                medication=medication,
                quantity=amount,
                locked=locked,
                story=story,
            )
            self.items.append(replace(item, dispensations=self._dispensations(item, rule)))

    def _pharmacy(self, rule) -> str:
        if rule == "one-pharmacy" and self.rng.random() < 0.9:
            return "pharmacy-four"
        if rule == "spread":
            names = list(self.weights)
            self._rotation += 1
            return names[self._rotation % len(names)]
        names, weights = zip(*self.weights.items(), strict=True)
        return self.rng.choices(names, weights)[0]

    def _brand(self, item: Planned, pharmacy: str) -> str:
        if item.locked:
            return item.locked
        versions = [b for b, (m, _) in PRODUCTS.items() if m == item.medication]
        generics = [b for b in versions if PRODUCTS[b][1] is ProductKind.GENERIC]
        brands = [b for b in versions if b not in generics]
        if not generics or not brands:
            return self.rng.choice(versions)
        wants_generic = 0.1 if pharmacy == AVOIDS_GENERICS else 0.65
        return self.rng.choice(generics if self.rng.random() < wants_generic else brands)

    def _dispensations(self, item: Planned, rule) -> tuple[tuple[str, str, int], ...]:
        roll = self.rng.random()
        if roll < 0.12:
            return ()  # never collected
        first = self._pharmacy(rule)
        if roll < 0.78:
            return ((first, self._brand(item, first), item.quantity),)
        half = item.quantity // 2
        done = ((first, self._brand(item, first), half),)
        if self.rng.random() < 0.5:
            return done  # collected in part, the rest still open
        second = self._pharmacy(rule)
        return (*done, (second, self._brand(item, second), item.quantity - half))


def plan(profile: str = "story") -> list[Planned]:
    chosen = PROFILES[profile]
    s = chosen.story_scale
    planner = _Planner(chosen)
    ordinary = ORDINARY + [f"dr-{i:02d}" for i in range(1, chosen.extra_prescribers + 1)]
    for doctor in ordinary:
        planner.add(doctor, CITALOPRAM, 4)
        planner.add(doctor, ESCITALOPRAM, 1)
        planner.add(doctor, CLONAZEPAM, 3)
        planner.add(doctor, ALPRAZOLAM, 2)
        planner.add(doctor, METHYLPHENIDATE, 2)
        planner.add(doctor, ZOLPIDEM, 2)
    # One ordinary lock, so a lock alone is not a signal.
    planner.add("dr-carla", ALPRAZOLAM, 1, locked="Serenix 0.5 mg")

    for doctor in ("dr-fabio", "dr-gabriela", "dr-hugo"):
        planner.add(doctor, ESCITALOPRAM, 7 * s, story="new-drug")
        planner.add(doctor, CITALOPRAM, 1 * s, story="new-drug")
        planner.add(doctor, CLONAZEPAM, 2)
        planner.add(doctor, ALPRAZOLAM, 1)
        planner.add(doctor, ZOLPIDEM, 1)

    planner.add("dr-iris", ZOLPIDEM, 6 * s, story="brand-locks", locked="Dormirex 10 mg")
    planner.add("dr-iris", ZOLPIDEM, 1 * s, story="brand-locks")
    planner.add("dr-iris", CITALOPRAM, 3)
    planner.add("dr-iris", ESCITALOPRAM, 1)
    planner.add("dr-iris", CLONAZEPAM, 2)

    planner.add("dr-joao", METHYLPHENIDATE, 8 * s, "volume", quantity=90, rule="one-pharmacy")
    planner.add("dr-joao", METHYLPHENIDATE, 4 * s, "volume", quantity=60, rule="one-pharmacy")
    planner.add("dr-joao", CITALOPRAM, 3)
    planner.add("dr-joao", ESCITALOPRAM, 1)
    planner.add("dr-joao", CLONAZEPAM, 2)

    planner.add("dr-karen", CLONAZEPAM, 12 * s, story="specialist", quantity=30, rule="spread")
    planner.add("dr-karen", CITALOPRAM, 3)
    planner.add("dr-karen", ESCITALOPRAM, 1)
    planner.add("dr-karen", ALPRAZOLAM, 2)

    return SHOWCASE + _closures(planner.items, s)


def _closures(items: list[Planned], scale: int) -> list[Planned]:
    """A few ordinary prescriptions cancelled (never collected) or stopped
    (collected in part): the closure reasons are public data too."""
    cancel = [ClosureReason.ISSUED_IN_ERROR, ClosureReason.REPLACED, ClosureReason.OTHER] * scale
    stop = [
        ClosureReason.CLINICAL_DECISION,
        ClosureReason.SUSPECTED_MISUSE,
        ClosureReason.REPLACED,
    ] * scale
    closed = []
    for item in items:
        collected = sum(units for _, _, units in item.dispensations)
        if item.story or item.locked:
            closed.append(item)
        elif not item.dispensations and cancel:
            closed.append(replace(item, closure=("cancel", cancel.pop(0))))
        elif 0 < collected < item.quantity and stop:
            closed.append(replace(item, closure=("stop", stop.pop(0))))
        else:
            closed.append(item)
    return closed
