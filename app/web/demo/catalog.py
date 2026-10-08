"""The demo catalog. Active ingredients, strengths and ATC codes are real; every
manufacturer and brand is made up, because the demo plants patterns and must
not point at a real company."""

from rxtrail.domain import MedicationDetails, ProductKind

R, G = ProductKind.REFERENCE, ProductKind.GENERIC

# (medication, [(manufacturer, brand, kind)])
CATALOG = [
    (
        MedicationDetails(
            "Clonazepam 2 mg tablet",
            "clonazepam",
            "2 mg",
            "tablet",
            "N03AE01",
            "tablet",
            "B1",
            "0.5 to 4 mg a day, in divided doses",
            2,
            60,
            30,
        ),
        [
            ("Acme Pharma", "Calmazen 2 mg", R),
            ("Beta Labs", "Clonazepam Beta 2 mg", G),
            ("Gama Generics", "Clonazepam Gama 2 mg", G),
        ],
    ),
    (
        MedicationDetails(
            "Alprazolam 0.5 mg tablet",
            "alprazolam",
            "0.5 mg",
            "tablet",
            "N05BA12",
            "tablet",
            "B1",
            "0.25 to 0.5 mg three times a day; up to 4 mg a day",
            6,
            60,
            30,
        ),
        [("Acme Pharma", "Serenix 0.5 mg", R), ("Beta Labs", "Alprazolam Beta 0.5 mg", G)],
    ),
    (
        MedicationDetails(
            "Methylphenidate 10 mg tablet",
            "methylphenidate",
            "10 mg",
            "tablet",
            "N06BA04",
            "tablet",
            "A3",
            "5 to 60 mg a day, in the morning and at noon",
            6,
            60,
            30,
        ),
        [("Delta Pharma", "Focalis 10 mg", R), ("Gama Generics", "Methylphenidate Gama 10 mg", G)],
    ),
    (
        MedicationDetails(
            "Zolpidem 10 mg tablet",
            "zolpidem",
            "10 mg",
            "tablet",
            "N05CF02",
            "tablet",
            "B1",
            "10 mg at bedtime, for the shortest time possible",
            1,
            30,
            30,
        ),
        [("Delta Pharma", "Dormirex 10 mg", R), ("Beta Labs", "Zolpidem Beta 10 mg", G)],
    ),
    (
        MedicationDetails(
            "Citalopram 20 mg tablet",
            "citalopram",
            "20 mg",
            "tablet",
            "N06AB04",
            "tablet",
            "C1",
            "20 to 40 mg once a day",
            2,
            60,
            30,
        ),
        [("Gama Generics", "Citalopram Gama 20 mg", G)],
    ),
    (
        MedicationDetails(
            "Escitalopram 10 mg tablet",
            "escitalopram",
            "10 mg",
            "tablet",
            "N06AB10",
            "tablet",
            "C1",
            "10 to 20 mg once a day",
            2,
            60,
            30,
        ),
        [("Acme Pharma", "Lexacor 10 mg", R)],
    ),
]
