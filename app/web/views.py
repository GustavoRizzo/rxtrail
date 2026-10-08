"""Web pages: one dashboard per role, and a public page to verify a prescription.

Views are synchronous; every chain operation goes through `with_chain`, and
every refusal from the chain is shown as an error (the program decides).
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from config import container
from records.models import (
    Activity,
    CatalogMedication,
    CatalogProduct,
    Participant,
    PrescriptionRecord,
)
from records.repositories import medication_details
from rxtrail import catalog as rules_of_thumb
from rxtrail.domain import (
    AlreadyDispensedError,
    CatalogStatus,
    ClosureReason,
    Prescription,
    PrescriptionDocument,
    RxTrailError,
    Standing,
)
from web import catalog, insights_views, qrcodes
from web.chain import with_chain
from web.context_processors import ROLE_LABELS
from web.forms import (
    CloseForm,
    DispenseForm,
    EnableParticipantForm,
    IssueForm,
    PrescriptionFilterForm,
)
from web.icons import ICONS

Role = Participant.Role

# Which participants each authority manages, and the key it signs with.
AUTHORITY_SCOPE = {
    Role.PROFESSIONAL_AUTHORITY: ("prescriber", Role.PRESCRIBER),
    Role.HEALTH_AUTHORITY: ("dispenser", Role.DISPENSER),
}


def role_required(*roles):
    def decorate(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{settings.LOGIN_URL}?next={request.path}")
            participant = getattr(request.user, "participant", None)
            if participant is None or participant.role not in roles:
                return redirect("web:home")
            request.participant = participant
            return view(request, *args, **kwargs)

        return wrapper

    return decorate


def _names() -> dict[str, str]:
    """On-chain key -> participant name. Names live off-chain; keys are the proof."""
    keys = container.key_store()
    return {
        str(keys.keypair(p.key_name).pubkey()): p.display_name
        for p in Participant.objects.exclude(key_name="")
        if keys.exists(p.key_name)
    }


def _fail(request, exc: Exception) -> None:
    messages.error(request, f"{type(exc).__name__.removesuffix('Error')}: {exc}")


def _log(participant, action, summary, prescription_id="", signature=""):
    Activity.objects.create(
        actor=participant,
        action=action,
        summary=summary,
        prescription_id=prescription_id,
        signature=signature,
    )


# -- public --------------------------------------------------------------------


def landing(request):
    if request.user.is_authenticated:
        return redirect("web:home")
    return render(request, "web/landing.html", {"audit": insights_views.teaser()})


# Demo mode: the login page groups the accounts by role, each with what a
# visitor can try there.
DEMO_ROLES = {
    Role.PRESCRIBER: "Issue a prescription, follow its fills, cancel or discontinue it.",
    Role.DISPENSER: "Scan a patient's prescription and dispense part or all of it.",
    Role.PROFESSIONAL_AUTHORITY: "Register, suspend and reinstate prescribers.",
    Role.HEALTH_AUTHORITY: "Register, suspend and reinstate pharmacies.",
    Role.CATALOG_AUTHORITY: "Add medications and brands; recall one and see the counters stop.",
    Role.AUDITOR: "Read every prescription with its on-chain trail.",
}


class LoginView(auth_views.LoginView):
    template_name = "web/login.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if settings.RXTRAIL_DEMO_MODE:
            accounts = Participant.objects.select_related("user").order_by("display_name")
            context["demo_roles"] = [
                (role, hint, mine)
                for role, hint in DEMO_ROLES.items()
                if (mine := [p for p in accounts if p.role == role])
            ]
            context["demo_password"] = settings.RXTRAIL_DEMO_PASSWORD
        return context


def home(request):
    """Send each participant to their own dashboard."""
    if not request.user.is_authenticated:
        return redirect("web:landing")
    participant = getattr(request.user, "participant", None)
    if participant is None:
        return redirect("admin:index")
    return redirect(
        {
            Role.PRESCRIBER: "web:prescriber",
            Role.DISPENSER: "web:dispenser",
            Role.PROFESSIONAL_AUTHORITY: "web:authority",
            Role.HEALTH_AUTHORITY: "web:authority",
            Role.CATALOG_AUTHORITY: "web:catalog_office",
            Role.AUDITOR: "web:auditor",
        }[participant.role]
    )


def verify(request):
    """Look a prescription up by id (or the link in its QR code), from anywhere."""
    prescription_id = qrcodes.prescription_id_in(request.GET.get("id", ""))
    if prescription_id is None:
        messages.error(request, "A prescription id has 64 hexadecimal characters.")
        return redirect(request.META.get("HTTP_REFERER") or "web:landing")
    return redirect("web:prescription", prescription_id=prescription_id)


def _verification_link(request, prescription_id: str) -> str:
    """What the QR code printed on the prescription holds: its public record."""
    return request.build_absolute_uri(reverse("web:prescription", args=[prescription_id]))


def _verification_qr(request, prescription_id: str):
    return qrcodes.svg(_verification_link(request, prescription_id))


def prescription(request, prescription_id: str):
    """The audit trail of one prescription, rebuilt from the chain."""
    try:
        raw_id = bytes.fromhex(prescription_id)
        trail = with_chain(lambda app, _ledger: app.audit(raw_id))
    except ValueError as exc:
        raise Http404("not a prescription id") from exc
    except RxTrailError as exc:
        _fail(request, exc)
        return redirect("web:home" if request.user.is_authenticated else "web:landing")

    record = (
        PrescriptionRecord.objects.select_related("patient")
        .filter(prescription_id=prescription_id)
        .first()
    )
    rx = trail.prescription
    # The medication is public (its catalog record is open data); who takes it is not.
    named = catalog.by_address(
        [rx.medication, *([rx.prescribed_product] if rx.prescribed_product else [])]
        + [d.product for d in trail.dispensations]
    )
    # The document holds personal data: only the issuing prescriber and
    # dispensers see it. Everyone else sees the on-chain facts and the verdict.
    participant = (
        getattr(request.user, "participant", None) if request.user.is_authenticated else None
    )
    issued_it = (
        participant is not None
        and participant.role == Role.PRESCRIBER
        and record is not None
        and record.prescriber == participant.key_name
    )
    is_pharmacy = participant is not None and participant.role == Role.DISPENSER
    can_read = issued_it or is_pharmacy
    # Only the issuer may close it, and only while it is in force (RN-04d):
    # cancel if nobody dispensed yet, otherwise stop what remains.
    close_kind = None
    if issued_it and rx.standing(datetime.now(UTC)) is Standing.ACTIVE:
        close_kind = "stop" if rx.dispensation_count else "cancel"
    return render(
        request,
        "web/prescription.html",
        {
            "trail": trail,
            "prescription_id": prescription_id,
            "record": record if can_read else None,
            "medication": named.get(rx.medication),
            "locked": named.get(rx.prescribed_product),
            "products": named,
            "activities": Activity.objects.select_related("actor").filter(
                prescription_id=prescription_id
            )[:20],
            "names": _names(),
            "is_pharmacy": is_pharmacy,
            # Only the issuing prescriber hands the patient their copy.
            "patient_link": (
                request.build_absolute_uri(reverse("web:patient_copy", args=[record.patient_token]))
                if issued_it
                else None
            ),
            "qr": _verification_qr(request, prescription_id) if issued_it else None,
            "close_kind": close_kind,
            "reasons": list(ClosureReason),
            "closure_note": record.closure_note if issued_it else "",
        },
    )


@require_POST
@role_required(Role.PRESCRIBER)
def close_prescription(request, prescription_id: str):
    """Cancel or stop, as the prescriber chose. The chain decides; if a pharmacy
    dispensed in the meantime, a cancel is refused, never turned into a stop."""
    me = request.participant
    form = CloseForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
        return redirect("web:prescription", prescription_id=prescription_id)
    data = form.cleaned_data
    reason = ClosureReason(data["reason"])
    try:
        raw_id = bytes.fromhex(prescription_id)
    except ValueError as exc:
        raise Http404("not a prescription id") from exc
    try:
        receipt = with_chain(
            lambda app, _l: getattr(app, data["kind"])(me.key_name, raw_id, reason, data["note"])
        )
    except AlreadyDispensedError:
        messages.error(
            request,
            "A pharmacy filled it in the meantime, so it can no longer be cancelled. "
            "Its fills are listed below; you can still discontinue what remains.",
        )
    except RxTrailError as exc:
        _fail(request, exc)
    else:
        past = "Cancelled" if data["kind"] == "cancel" else "Discontinued"
        _log(me, data["kind"], f"{past}: {reason.label}", prescription_id, receipt.signature)
        messages.success(request, f"{past} on-chain. No pharmacy can dispense it any more.")
    return redirect("web:prescription", prescription_id=prescription_id)


def patient_copy(request, token: str):
    """The patient's copy: everything they need, behind the secret in their link.

    No account: the patient has no login. Whoever holds the link reads it, as
    whoever holds a paper prescription does; the QR code on it holds no
    personal data, only the public verification link.
    """
    record = get_object_or_404(
        PrescriptionRecord.objects.select_related("patient"), patient_token=token
    )
    prescription_id = record.prescription_id
    try:
        trail = with_chain(lambda app, _ledger: app.audit(bytes.fromhex(prescription_id)))
    except RxTrailError as exc:
        _fail(request, exc)
        return redirect("web:landing")
    rx = trail.prescription
    listed = catalog.cards(
        CatalogMedication.objects.prefetch_related("products__manufacturer").filter(
            address=rx.medication
        )
    )
    medication = listed[0] if listed else None
    named = catalog.by_address([d.product for d in trail.dispensations])
    now = datetime.now(UTC)
    response = render(
        request,
        "web/patient.html",
        {
            "record": record,
            "document": record.document,
            "trail": trail,
            "rx": rx,
            "standing": rx.standing(now),
            "days_left": max((rx.expires_at - now).days, 0),
            "medication": medication,
            # Which boxes a pharmacy may hand over: the locked brand only, or
            # any version still on the market (generics are usually cheaper).
            "accepted": [
                p
                for p in (medication.products if medication else [])
                if p.available
                and (rx.prescribed_product is None or p.record.address == rx.prescribed_product)
            ],
            "products": named,
            "names": _names(),
            "prescriber": Participant.objects.filter(key_name=record.prescriber).first(),
            # The prescriber's signature itself: the issuing transaction, when
            # this app sent it; otherwise the prescription's account.
            "issue_signature": Activity.objects.filter(
                prescription_id=prescription_id, action="issue"
            )
            .exclude(signature="")
            .values_list("signature", flat=True)
            .first(),
            "verify_url": _verification_link(request, prescription_id),
            "qr": _verification_qr(request, prescription_id),
        },
    )
    # A secret link: keep it out of caches, search engines and Referer headers.
    response["Cache-Control"] = "private, no-store"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


# -- prescriber ------------------------------------------------------------------


@role_required(Role.PRESCRIBER)
def prescriber(request):
    me = request.participant
    form = IssueForm(request.POST or None)
    chosen = None
    if form.is_bound and form.data.get("medication_id"):
        chosen = CatalogMedication.objects.filter(medication_id=form.data["medication_id"]).first()
        if chosen is None:
            form.add_error("medication_id", "Choose a medication from the catalog.")
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        document = PrescriptionDocument(
            medication_id=chosen.medication_id,
            medication=chosen.name,
            dosage=data["dosage"],
            instructions=data["instructions"],
            quantity=data["quantity"],
            prescriber_name=me.display_name,
            patient_name=data["patient_name"],
            issued_on=datetime.now(UTC).date().isoformat(),
            locked_product_id=data["locked_product_id"],
        )
        try:
            issued = with_chain(
                lambda app, _l: app.issue(
                    me.key_name,
                    data["patient_document"],
                    document,
                    timedelta(days=data["valid_days"]),
                )
            )
        except RxTrailError as exc:
            _fail(request, exc)
        else:
            rx = issued.prescription_id.hex()
            _log(
                me,
                "issue",
                f"Issued {data['quantity']} × {chosen.name}",
                rx,
                issued.receipt.signature,
            )
            messages.success(
                request, "Prescription issued on-chain. Hand the patient their copy below."
            )
            for warning in rules_of_thumb.warnings(
                medication_details(chosen), data["quantity"], data["valid_days"]
            ):
                messages.warning(request, f"Check: {warning}.")
            return redirect("web:prescription", prescription_id=rx)

    filters = PrescriptionFilterForm(request.GET)
    rows, scanned = _prescriber_rows(me, filters.cleaned_data if filters.is_valid() else {})
    return render(
        request,
        "web/prescriber.html",
        {
            "form": form,
            "chosen": catalog.cards([chosen])[0].data() if chosen else None,
            "filters": filters,
            "filters_active": filters.active_count(),
            "rows": rows[:PRESCRIBER_LIST_SHOWN],
            "matches": len(rows),
            "truncated": scanned == PRESCRIBER_LIST_SCANNED or len(rows) > PRESCRIBER_LIST_SHOWN,
            "shown": PRESCRIBER_LIST_SHOWN,
            "total": PrescriptionRecord.objects.filter(prescriber=me.key_name).count(),
        },
    )


# The prescriber's list reads this many records from the chain (two
# getMultipleAccounts calls), filters and sorts them, and shows the first ones.
PRESCRIBER_LIST_SCANNED = 200
PRESCRIBER_LIST_SHOWN = 50

_SORT_KEYS = {
    "expiring": lambda row: (row.rx is None, row.rx and row.rx.expires_at),
    "remaining": lambda row: -(row.rx.remaining if row.rx else -1),
    "patient": lambda row: row.record.patient.name.casefold(),
    "medication": lambda row: row.record.document["medication"].casefold(),
}


@dataclass(frozen=True)
class _Row:
    record: PrescriptionRecord
    rx: Prescription | None  # None: the record points at nothing on this chain
    standing: Standing | None


def _prescriber_rows(me, wanted) -> tuple[list[_Row], int]:
    """Off-chain fields filter in the database; on-chain ones after the read."""
    records = PrescriptionRecord.objects.filter(prescriber=me.key_name).select_related("patient")
    if q := wanted.get("q"):
        records = records.filter(
            Q(patient__name__icontains=q) | Q(document__medication__icontains=q)
        )
    if day := wanted.get("issued_from"):
        records = records.filter(created_at__date__gte=day)
    if day := wanted.get("issued_to"):
        records = records.filter(created_at__date__lte=day)
    sort = wanted.get("sort") or "newest"
    records = list(
        records.order_by("created_at" if sort == "oldest" else "-created_at")[
            :PRESCRIBER_LIST_SCANNED
        ]
    )
    if not records:
        return [], 0

    on_chain = with_chain(
        lambda _app, ledger: ledger.prescriptions_by_id(
            [bytes.fromhex(r.prescription_id) for r in records]
        )
    )
    now = datetime.now(UTC)
    rows = [
        _Row(record, rx, rx.standing(now) if rx else None)
        for record, rx in zip(records, on_chain, strict=True)
    ]
    if standing := wanted.get("standing"):
        rows = [row for row in rows if row.standing == standing]
    if key := _SORT_KEYS.get(sort):
        rows.sort(key=key)
    return rows, len(records)


# -- dispenser ---------------------------------------------------------------------


@role_required(Role.DISPENSER)
def dispenser(request):
    me = request.participant
    # What the counter's scanner read: the QR code's link, or an id typed in.
    scanned = request.GET.get("rx", "").strip()
    prescription_id = qrcodes.prescription_id_in(scanned) or ""
    found = record = medication = None
    if scanned and not prescription_id:
        messages.error(request, "That is not a prescription id or a prescription's QR code.")
    if prescription_id:
        try:
            found = with_chain(
                lambda _a, ledger: ledger.prescription(bytes.fromhex(prescription_id))
            )
        except (ValueError, RxTrailError) as exc:
            _fail(request, exc)
        if found is None and not messages.get_messages(request):
            messages.error(request, "No prescription with that id on this network.")
        record = (
            PrescriptionRecord.objects.select_related("patient")
            .filter(prescription_id=prescription_id)
            .first()
        )
    if found:
        listed = catalog.cards(
            CatalogMedication.objects.prefetch_related("products__manufacturer").filter(
                address=found.medication
            )
        )
        medication = listed[0] if listed else None
    return render(
        request,
        "web/dispenser.html",
        {
            "prescription_id": prescription_id,
            "found": found,
            "medication": medication,
            "frozen": medication is not None and medication.status is CatalogStatus.WITHDRAWN,
            "record": record,
            "names": _names() if found else {},
            "activities": me.activities.all()[:10],
            "samples": _counter_samples() if settings.RXTRAIL_DEMO_MODE else [],
        },
    )


# Demo mode: the counter offers the newest prescription not filled yet, the
# newest partly filled and the newest filled in full, so a visitor can look
# each one up without a patient's QR code. A real pharmacy never lists them.
COUNTER_SAMPLES_SCANNED = 30


def _counter_samples() -> list[tuple[str, _Row]]:
    records = list(
        PrescriptionRecord.objects.select_related("patient").order_by("-created_at")[
            :COUNTER_SAMPLES_SCANNED
        ]
    )
    if not records:
        return []
    try:
        on_chain = with_chain(
            lambda _app, ledger: ledger.prescriptions_by_id(
                [bytes.fromhex(r.prescription_id) for r in records]
            )
        )
    except RxTrailError:
        return []  # only a shortcut: the counter works without it
    now = datetime.now(UTC)
    found: dict[str, _Row] = {}
    for record, rx in zip(records, on_chain, strict=True):
        if rx is None:
            continue
        standing = rx.standing(now)
        if standing is Standing.COMPLETED:
            kind = "Filled in full"
        elif standing is not Standing.ACTIVE:
            continue
        else:
            kind = "Partly filled" if rx.quantity_dispensed else "Not filled yet"
        found.setdefault(kind, _Row(record, rx, standing))
    order = ["Not filled yet", "Partly filled", "Filled in full"]
    return [(kind, found[kind]) for kind in order if kind in found]


@require_POST
@role_required(Role.DISPENSER)
def dispense(request):
    me = request.participant
    form = DispenseForm(request.POST)
    if not form.is_valid():
        for errors in form.errors.values():
            messages.error(request, " ".join(errors))
        return redirect(f"/dispenser/?rx={request.POST.get('prescription_id', '')}")
    data = form.cleaned_data
    rx, quantity = data["prescription_id"], data["quantity"]
    product = bytes.fromhex(data["product_id"])
    try:
        receipt = with_chain(
            lambda app, _l: app.dispense(me.key_name, bytes.fromhex(rx), product, quantity)
        )
    except RxTrailError as exc:
        _fail(request, exc)
    else:
        brand = (
            CatalogProduct.objects.filter(product_id=data["product_id"])
            .values_list("brand_name", flat=True)
            .first()
        )
        _log(me, "dispense", f"Dispensed {quantity} × {brand}", rx, receipt.signature)
        messages.success(request, f"Dispensed {quantity} × {brand}. Recorded on-chain.")
    return redirect(f"/dispenser/?rx={rx}")


# -- authorities -----------------------------------------------------------------


@role_required(Role.PROFESSIONAL_AUTHORITY, Role.HEALTH_AUTHORITY)
def authority(request):
    me = request.participant
    kind, managed_role = AUTHORITY_SCOPE[me.role]
    managed = list(Participant.objects.filter(role=managed_role).order_by("display_name"))

    async def statuses(_app, ledger):
        return await asyncio.gather(*(ledger.participant_status(kind, p.key_name) for p in managed))

    try:
        status = with_chain(statuses) if managed else []
    except RxTrailError as exc:
        _fail(request, exc)
        status = [None] * len(managed)
    label = ROLE_LABELS[managed_role].lower()
    return render(
        request,
        "web/authority.html",
        {
            "kind": kind,
            "label": label,
            "labels": "pharmacies" if label == "pharmacy" else f"{label}s",
            "rows": list(zip(managed, status, strict=True)),
            "form": EnableParticipantForm(),
            "activities": me.activities.all()[:10],
        },
    )


@require_POST
@role_required(Role.PROFESSIONAL_AUTHORITY, Role.HEALTH_AUTHORITY)
def enable_participant(request):
    me = request.participant
    kind, managed_role = AUTHORITY_SCOPE[me.role]
    form = EnableParticipantForm(request.POST)
    if not form.is_valid():
        for field, errors in form.errors.items():
            messages.error(request, f"{field}: {' '.join(errors)}")
        return redirect("web:authority")
    data = form.cleaned_data
    name = data["username"]
    User = get_user_model()
    if User.objects.filter(username=name).exists():
        messages.error(request, f"The username {name} is taken.")
        return redirect("web:authority")

    keys = container.key_store()
    if not keys.exists(name):
        keys.create(name)
    try:
        receipt = with_chain(lambda app, _l: getattr(app, f"enable_{kind}")(me.key_name, name))
    except RxTrailError as exc:
        _fail(request, exc)
        return redirect("web:authority")
    with transaction.atomic():
        user = User.objects.create_user(name, password=data["password"])
        Participant.objects.create(
            user=user,
            role=managed_role,
            key_name=name,
            display_name=data["display_name"],
            license_number=data["license_number"],
        )
    label = ROLE_LABELS[managed_role].lower()
    _log(me, "enable", f"Registered {label} {data['display_name']}", signature=receipt.signature)
    messages.success(
        request, f"{data['display_name']} registered on-chain. They can sign in as {name}."
    )
    return redirect("web:authority")


@require_POST
@role_required(Role.PROFESSIONAL_AUTHORITY, Role.HEALTH_AUTHORITY)
def set_status(request):
    me = request.participant
    kind, managed_role = AUTHORITY_SCOPE[me.role]
    target = Participant.objects.filter(
        role=managed_role, key_name=request.POST.get("key_name")
    ).first()
    verb = request.POST.get("verb")
    if target is None or verb not in ("suspend", "reinstate"):
        messages.error(request, "Unknown participant or action.")
        return redirect("web:authority")
    try:
        receipt = with_chain(
            lambda app, _l: getattr(app, f"{verb}_{kind}")(me.key_name, target.key_name)
        )
    except RxTrailError as exc:
        _fail(request, exc)
    else:
        past = "suspended" if verb == "suspend" else "reinstated"
        _log(me, verb, f"{past.capitalize()} {target.display_name}", signature=receipt.signature)
        messages.success(request, f"{target.display_name} {past}. Effective on-chain, everywhere.")
    return redirect("web:authority")


# -- auditor --------------------------------------------------------------------------


@role_required(Role.AUDITOR)
def auditor(request):
    return render(
        request,
        "web/auditor.html",
        {
            "records": PrescriptionRecord.objects.order_by("-created_at")[:20],
            "activities": Activity.objects.select_related("actor")[:20],
        },
    )


# -- development ------------------------------------------------------------------

STYLE_TOKENS = [
    ("brand-primary", "text-brand-primary · bg-brand-primary/15", "main actions"),
    ("brand-secondary", "text-brand-secondary", "links, information"),
    ("brand-accent", "text-brand-accent · bg-brand-accent/10", "success, live"),
    ("danger", "text-danger · bg-danger/10", "refusals, suspension"),
    ("surface", "bg-surface", "page background"),
    ("surface-raised", "", "opaque: open select menus, autofill"),
    ("on-brand", "", "text on brand colours"),
    ("placeholder", "", "hint text in empty fields"),
]


def styleguide(request):
    """Every token and component on one page. Development only."""
    if not settings.DEBUG:
        raise Http404
    return render(request, "web/styleguide.html", {"tokens": STYLE_TOKENS, "icons": ICONS.items()})
