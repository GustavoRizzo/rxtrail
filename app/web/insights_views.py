"""Insights: public pages that look for behaviour patterns in public data.

Open to anyone, no sign-in: the data is the chain and the open catalog, and
prescribers and pharmacies appear by their on-chain key, never by name.
Every page speaks of signals, never of findings.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from django.contrib import messages
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse

from rxtrail import insights
from rxtrail.domain import RxTrailError
from web.icons import ICONS
from web.insights import public_data


def _data(request):
    try:
        return public_data()
    except RxTrailError as exc:
        messages.error(request, f"Could not read the chain: {exc}")
        return insights.PublicData([], [], [], {}, {})


# (url name, tab, icon, the question the page asks)
TABS = [
    ("web:insights_overview", "Overview", "layout-dashboard", "The whole network in numbers"),
    ("web:insights_new_drugs", "New drugs", "flask-conical", "Who is pushing the new drug?"),
    ("web:insights_generics", "Generics", ICONS["pharmacy"], "Which pharmacies avoid generics?"),
    ("web:insights_brand_locks", "Brand locks", ICONS["brand lock"], "Who locks the brand?"),
    ("web:insights_volume", "Volume", "scale", "Who writes far more than their peers?"),
]


def _page(request, template, **context):
    return render(request, f"web/insights/{template}.html", {"tabs": TABS, **context})


# -- the pitch, and the guided investigations ----------------------------------------


@dataclass(frozen=True)
class Step:
    text: str
    url: str = ""
    label: str = ""


@dataclass(frozen=True)
class Story:
    slug: str
    title: str
    question: str
    icon: str
    steps: list[Step]
    found: bool  # the data shows the pattern right now


def _stories(data: insights.PublicData) -> list[Story]:
    """Each investigation, step by step, with links to where the data shows it.
    Built from the data itself: the links follow whatever stands out now."""
    stories = []

    lobby_class = next(
        (
            c
            for c in data.classes
            if len(data.classes[c]) > 1
            and any(r.stands_out for r in insights.class_share(data, c).prescribers)
        ),
        next(iter(data.classes), ""),
    )
    share = insights.class_share(data, lobby_class) if lobby_class else None
    pushing = [r for r in share.prescribers if r.stands_out] if share else []
    focus = share.focus.name if share and share.focus else "the newest drug"
    stories.append(
        Story(
            "new-drug",
            "A new drug, pushed",
            "A laboratory launches a pricey medication that does the same job as a cheap "
            "one, and pays prescribers to switch. Who switched?",
            "flask-conical",
            [
                Step(
                    f"Open the class and see how {focus} compares with the rest of it.",
                    reverse("web:insights_new_drugs") + f"?class={lobby_class}",
                    "Who is pushing the new drug?",
                ),
                Step(
                    f"{len(pushing)} prescriber{'s' if len(pushing) != 1 else ''} give "
                    f"{focus} a share far above the median of their peers."
                    if pushing
                    else "Nobody stands out from their peers right now."
                ),
                *(
                    [
                        Step(
                            "Open one of them: their whole record, every number "
                            "against their peers.",
                            _prescriber_url(pushing[0].subject),
                            f"Prescriber {insights.pseudonym(pushing[0].subject)}",
                        )
                    ]
                    if pushing
                    else []
                ),
                Step(
                    "From there, any prescription opens its public record and its accounts "
                    "on the explorer: the evidence an authority would ask for."
                ),
                Step("A signal for the medical board to look into, not a conclusion."),
            ],
            bool(pushing),
        )
    )

    rates = insights.generic_rates(data)
    avoiding = [r for r in rates.pharmacies if r.stands_out]
    stories.append(
        Story(
            "generics",
            "The pharmacy without generics",
            "A pharmacy always hands out the brand, never the cheaper generic, even when "
            "the prescription allows either. Which one?",
            ICONS["pharmacy"],
            [
                Step(
                    "Compare each pharmacy's share of generics with the network's, only "
                    "where a generic could have been handed out.",
                    reverse("web:insights_generics"),
                    "Which pharmacies avoid generics?",
                ),
                Step(
                    f"{len(avoiding)} pharmacy hands out generics far less than the "
                    f"network's {rates.network:.0%}."
                    if len(avoiding) == 1
                    else f"{len(avoiding)} pharmacies stand out."
                    if avoiding
                    else "No pharmacy stands out right now."
                ),
                *(
                    [
                        Step(
                            "Open it: which manufacturers it favours, and whose "
                            "prescriptions it fills.",
                            _pharmacy_url(avoiding[0].subject),
                            f"Pharmacy {insights.pseudonym(avoiding[0].subject)}",
                        )
                    ]
                    if avoiding
                    else []
                ),
                Step(
                    "Prices are not part of RxTrail: the number shows a behaviour. "
                    "Whether it hurts patients is for the health regulators to judge."
                ),
            ],
            bool(avoiding),
        )
    )

    locks = insights.brand_locks(data)
    locking = [r for r in locks.prescribers if r.stands_out]
    stories.append(
        Story(
            "brand-locks",
            "Always the same brand",
            "A prescriber forbids substitution again and again, always for one "
            "manufacturer's brand. Coincidence?",
            ICONS["brand lock"],
            [
                Step(
                    "See how often each prescriber locks the brand, where a cheaper "
                    "version existed.",
                    reverse("web:insights_brand_locks"),
                    "Who locks the brand?",
                ),
                *(
                    [
                        Step(
                            "Open the one far above their peers, and see which "
                            "manufacturer's brand they lock.",
                            _prescriber_url(locking[0].subject),
                            f"Prescriber {insights.pseudonym(locking[0].subject)}",
                        )
                    ]
                    if locking
                    else [Step("Nobody stands out right now.")]
                ),
            ],
            bool(locking),
        )
    )

    volume = [r for r in insights.unusual_volume(data) if r.stands_out]
    concentrated = sorted(
        (r for r in volume if r.above_limit),
        key=lambda r: (-r.above_limit, -r.top_pharmacy_share),
    )
    # The busiest of the rest: other stories' prescribers stand out on volume too.
    spread = sorted((r for r in volume if r not in concentrated), key=lambda r: -r.prescriptions)
    stories.append(
        Story(
            "volume",
            "Volume: one signal, two stories",
            "Two prescribers write far more of a medication than their peers. Is that "
            "a problem? The volume alone cannot say: the context can.",
            "scale",
            [
                Step(
                    "Rank prescribers by volume, against the peers who prescribe the same.",
                    reverse("web:insights_volume"),
                    "Unusual volume",
                ),
                *(
                    [
                        Step(
                            f"{insights.pseudonym(concentrated[0].prescriber)}: quantities "
                            "above the regulatory limit, dispensed almost all at one "
                            "pharmacy. Worth a closer look.",
                            _prescriber_url(concentrated[0].prescriber),
                            "Open the first prescriber",
                        )
                    ]
                    if concentrated
                    else []
                ),
                *(
                    [
                        Step(
                            f"{insights.pseudonym(spread[0].prescriber)}: as much volume, "
                            "but within the limits and spread across pharmacies, like a "
                            "specialist's practice. The signal alone was not enough.",
                            _prescriber_url(spread[0].prescriber),
                            "Open the second prescriber",
                        )
                    ]
                    if spread
                    else []
                ),
                Step("This is why every page says: a signal, never a finding."),
            ],
            bool(concentrated or spread),
        )
    )
    return stories


def home(request):
    """The case for open auditing, then the ways in."""
    data = _data(request)
    return _page(
        request,
        "home",
        overview=insights.overview(data, datetime.now(UTC)),
        stories=_stories(data),
        signals=_signal_count(data),
    )


def teaser() -> dict | None:
    """What the site's front page shows of the insights: the live numbers and
    the questions. None when the chain is out of reach (the page goes on)."""
    try:
        data = public_data()
    except RxTrailError:
        return None
    return {
        "overview": insights.overview(data, datetime.now(UTC)),
        "signals": _signal_count(data),
        "questions": TABS[1:],
    }


def _signal_count(data: insights.PublicData) -> int:
    return (
        sum(
            r.stands_out
            for c in data.classes
            if len(data.classes[c]) > 1
            for r in insights.class_share(data, c).prescribers
        )
        + sum(r.stands_out for r in insights.generic_rates(data).pharmacies)
        + sum(r.stands_out for r in insights.brand_locks(data).prescribers)
        + sum(r.stands_out for r in insights.unusual_volume(data))
    )


# -- the views ------------------------------------------------------------------------


def overview(request):
    data = _data(request)
    return _page(request, "overview", overview=insights.overview(data, datetime.now(UTC)))


def new_drugs(request):
    data = _data(request)
    classes = {c: m for c, m in data.classes.items() if len(m) > 1}
    chosen = request.GET.get("class", "").upper()
    if chosen not in classes:
        chosen = next(iter(classes), "")
    share = insights.class_share(data, chosen, request.GET.get("focus")) if chosen else None
    return _page(
        request,
        "new_drugs",
        classes=[(c, insights.class_name(c)) for c in classes],
        chosen=chosen,
        class_label=insights.class_name(chosen),
        share=share,
    )


def generics(request):
    return _page(request, "generics", rates=insights.generic_rates(_data(request)))


def brand_locks(request):
    data = _data(request)
    locks = insights.brand_locks(data)
    makers = {r.subject: locks.manufacturers_locked_by(data, r.subject) for r in locks.prescribers}
    return _page(request, "brand_locks", locks=locks, makers=makers)


def volume(request):
    data = _data(request)
    return _page(
        request,
        "volume",
        rows=insights.unusual_volume(data),
        manufacturers=[r for r in insights.manufacturer_concentration(data) if r.sample],
        min_sample=insights.MIN_SAMPLE,
    )


# -- one entity -------------------------------------------------------------------------

LIST_SHOWN = 50  # records listed on an entity's page, newest first


def _prescriber_url(address: str) -> str:
    return reverse("web:insights_prescriber", args=[address])


def _pharmacy_url(address: str) -> str:
    return reverse("web:insights_pharmacy", args=[address])


def prescriber(request, address: str):
    data = _data(request)
    profile = insights.prescriber_profile(data, address)
    if profile is None:
        raise Http404("no prescriptions by this key in the public record")
    now = datetime.now(UTC)
    return _page(
        request,
        "prescriber",
        profile=profile,
        locked_makers=insights.brand_locks(data)
        .manufacturers_locked_by(data, address)
        .most_common(),
        rows=[
            (
                p,
                p.standing(now),
                data.medications.get(p.medication),
                data.products.get(p.prescribed_product),
            )
            for p in profile.prescriptions[:LIST_SHOWN]
        ],
        shown=LIST_SHOWN,
    )


def pharmacy(request, address: str):
    data = _data(request)
    profile = insights.pharmacy_profile(data, address)
    if profile is None:
        raise Http404("no dispensations by this key in the public record")
    rows = []
    for d in profile.dispensations[:LIST_SHOWN]:
        rx = data.prescription_at.get(d.prescription)
        rows.append(
            (d, rx, rx and data.medications.get(rx.medication), data.products.get(d.product))
        )
    return _page(request, "pharmacy", profile=profile, rows=rows, shown=LIST_SHOWN)


def medication(request, address: str):
    data = _data(request)
    profile = insights.medication_profile(data, address)
    if profile is None:
        raise Http404("no such medication in the open catalog")
    return _page(
        request,
        "medication",
        profile=profile,
        class_label=insights.class_name(profile.medication.atc_class),
        in_a_class=len(data.classes.get(profile.medication.atc_class, [])) > 1,
    )


def manufacturer(request, name: str):
    profile = insights.manufacturer_profile(_data(request), name)
    if profile is None:
        raise Http404("no such manufacturer in the open catalog")
    return _page(request, "manufacturer", profile=profile)
