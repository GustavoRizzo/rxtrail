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
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from config import container
from records.models import Activity, Participant, PrescriptionRecord
from rxtrail.domain import Prescription, PrescriptionDocument, RxTrailError, Standing
from web.chain import with_chain
from web.forms import DispenseForm, EnableParticipantForm, IssueForm, PrescriptionFilterForm

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
    return render(request, "web/landing.html")


class LoginView(auth_views.LoginView):
    template_name = "web/login.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if settings.RXTRAIL_DEMO_MODE:
            order = [
                Role.PRESCRIBER,
                Role.DISPENSER,
                Role.PROFESSIONAL_AUTHORITY,
                Role.HEALTH_AUTHORITY,
                Role.AUDITOR,
            ]
            accounts = Participant.objects.select_related("user").order_by("display_name")
            context["demo_accounts"] = sorted(accounts, key=lambda p: order.index(p.role))
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
            Role.AUDITOR: "web:auditor",
        }[participant.role]
    )


def verify(request):
    """Look a prescription up by id, from anywhere."""
    prescription_id = request.GET.get("id", "").strip().lower()
    if len(prescription_id) != 64:
        messages.error(request, "A prescription id has 64 hexadecimal characters.")
        return redirect(request.META.get("HTTP_REFERER") or "web:landing")
    return redirect("web:prescription", prescription_id=prescription_id)


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
    # The document holds personal data: only the issuing prescriber and
    # dispensers see it. Everyone else sees the on-chain facts and the verdict.
    participant = (
        getattr(request.user, "participant", None) if request.user.is_authenticated else None
    )
    can_read = participant is not None and (
        participant.role == Role.DISPENSER
        or (
            participant.role == Role.PRESCRIBER
            and record
            and record.prescriber == participant.key_name
        )
    )
    return render(
        request,
        "web/prescription.html",
        {
            "trail": trail,
            "prescription_id": prescription_id,
            "record": record if can_read else None,
            "activities": Activity.objects.select_related("actor").filter(
                prescription_id=prescription_id
            )[:20],
            "names": _names(),
        },
    )


# -- prescriber ------------------------------------------------------------------


@role_required(Role.PRESCRIBER)
def prescriber(request):
    me = request.participant
    form = IssueForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        document = PrescriptionDocument(
            medication=data["medication"],
            dosage=data["dosage"],
            instructions=data["instructions"],
            quantity=data["quantity"],
            prescriber_name=me.display_name,
            patient_name=data["patient_name"],
            issued_on=datetime.now(UTC).date().isoformat(),
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
                f"Issued {data['quantity']} × {data['medication']}",
                rx,
                issued.receipt.signature,
            )
            messages.success(
                request, f"Prescription issued on-chain. Share its id with the patient: {rx}"
            )
            return redirect("web:prescription", prescription_id=rx)

    filters = PrescriptionFilterForm(request.GET)
    rows, scanned = _prescriber_rows(me, filters.cleaned_data if filters.is_valid() else {})
    return render(
        request,
        "web/prescriber.html",
        {
            "form": form,
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
    prescription_id = request.GET.get("rx", "").strip().lower()
    found = record = None
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
    return render(
        request,
        "web/dispenser.html",
        {
            "prescription_id": prescription_id,
            "found": found,
            "record": record,
            "names": _names() if found else {},
            "activities": me.activities.all()[:10],
        },
    )


@require_POST
@role_required(Role.DISPENSER)
def dispense(request):
    me = request.participant
    form = DispenseForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Enter a quantity of at least 1.")
        return redirect(f"/dispenser/?rx={request.POST.get('prescription_id', '')}")
    rx, quantity = form.cleaned_data["prescription_id"], form.cleaned_data["quantity"]
    try:
        receipt = with_chain(lambda app, _l: app.dispense(me.key_name, bytes.fromhex(rx), quantity))
    except RxTrailError as exc:
        _fail(request, exc)
    else:
        _log(me, "dispense", f"Dispensed {quantity}", rx, receipt.signature)
        messages.success(request, f"Dispensed {quantity}. Recorded on-chain.")
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
    return render(
        request,
        "web/authority.html",
        {
            "kind": kind,
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
    _log(me, "enable", f"Enabled {kind} {data['display_name']}", signature=receipt.signature)
    messages.success(
        request, f"{data['display_name']} enabled on-chain. They can sign in as {name}."
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

STYLE_ICONS = [
    ("stethoscope", "prescriber"),
    ("pill", "pharmacy"),
    ("landmark", "professional authority"),
    ("building-2", "health authority"),
    ("search-check", "auditor"),
    ("shield-check", "verified"),
    ("scan-search", "verify"),
    ("pen-line", "sign"),
    ("activity", "activity"),
]


def styleguide(request):
    """Every token and component on one page. Development only."""
    if not settings.DEBUG:
        raise Http404
    return render(request, "web/styleguide.html", {"tokens": STYLE_TOKENS, "icons": STYLE_ICONS})
