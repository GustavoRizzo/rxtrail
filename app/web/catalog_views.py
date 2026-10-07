"""Catalog pages: the catalog authority's desk, the public catalog and its
open data, and the medication search behind the prescription form."""

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from records.models import CatalogMedication, CatalogProduct, Participant
from rxtrail.domain import MedicationDetails, ProductDetails, ProductKind, RxTrailError
from web import catalog
from web.chain import with_chain
from web.forms import MedicationForm, ProductForm
from web.views import _fail, _log, role_required

Role = Participant.Role


def _medications():
    return CatalogMedication.objects.prefetch_related("products__manufacturer")


def _form_errors(request, form) -> None:
    for field, errors in form.errors.items():
        messages.error(request, f"{field}: {' '.join(errors)}")


# -- catalog authority -------------------------------------------------------------


@role_required(Role.CATALOG_AUTHORITY)
def catalog_office(request):
    me = request.participant
    try:
        listed = catalog.cards(_medications())
    except RxTrailError as exc:
        _fail(request, exc)
        listed = []
    return render(
        request,
        "web/catalog_office.html",
        {
            "cards": listed,
            "medication_form": MedicationForm(),
            "product_form": ProductForm(),
            "kinds": CatalogProduct.Kind.choices,
            "activities": me.activities.all()[:10],
        },
    )


@require_POST
@role_required(Role.CATALOG_AUTHORITY)
def register_medication(request):
    me = request.participant
    form = MedicationForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
        return redirect("web:catalog_office")
    details = MedicationDetails(**form.cleaned_data)
    try:
        entry = with_chain(lambda app, _l: app.register_medication(me.key_name, details))
    except RxTrailError as exc:
        _fail(request, exc)
    else:
        _log(me, "register", f"Registered {details.name}", signature=entry.receipt.signature)
        messages.success(request, f"{details.name} is in the catalog, pinned on-chain.")
    return redirect("web:catalog_office")


@require_POST
@role_required(Role.CATALOG_AUTHORITY)
def register_product(request):
    me = request.participant
    form = ProductForm(request.POST)
    if not form.is_valid():
        _form_errors(request, form)
        return redirect("web:catalog_office")
    data = form.cleaned_data
    details = ProductDetails(
        data["medication_id"], data["manufacturer"], data["brand_name"], ProductKind(data["kind"])
    )
    try:
        entry = with_chain(lambda app, _l: app.register_product(me.key_name, details))
    except RxTrailError as exc:
        _fail(request, exc)
    else:
        summary = f"Registered {details.brand_name} ({details.manufacturer})"
        _log(me, "register", summary, signature=entry.receipt.signature)
        messages.success(request, f"{details.brand_name} is in the catalog, pinned on-chain.")
    return redirect("web:catalog_office")


@require_POST
@role_required(Role.CATALOG_AUTHORITY)
def set_catalog_status(request):
    """Withdraw (recall) or reinstate a medication or a product."""
    me = request.participant
    kind, verb = request.POST.get("kind"), request.POST.get("verb")
    model, field = {
        "medication": (CatalogMedication, "medication_id"),
        "product": (CatalogProduct, "product_id"),
    }.get(kind, (None, None))
    target = model and model.objects.filter(**{field: request.POST.get("id", "")}).first()
    if target is None or verb not in ("withdraw", "reinstate"):
        messages.error(request, "Unknown catalog record or action.")
        return redirect("web:catalog_office")
    name = target.name if kind == "medication" else target.brand_name
    raw_id = bytes.fromhex(getattr(target, field))
    try:
        receipt = with_chain(lambda app, _l: getattr(app, f"{verb}_{kind}")(me.key_name, raw_id))
    except RxTrailError as exc:
        _fail(request, exc)
    else:
        past = "withdrawn" if verb == "withdraw" else "reinstated"
        _log(me, verb, f"{past.capitalize()} {name}", signature=receipt.signature)
        effect = {
            ("medication", "withdraw"): "No new prescriptions; every existing one is frozen.",
            ("product", "withdraw"): "Pharmacies must hand out another version.",
        }.get((kind, verb), "Dispensable again.")
        messages.success(request, f"{name} {past}, on-chain, for every pharmacy. {effect}")
    return redirect("web:catalog_office")


# -- public ---------------------------------------------------------------------------


def public_catalog(request):
    """The catalog anyone can read and check against the chain."""
    try:
        listed = catalog.cards(_medications())
    except RxTrailError as exc:
        _fail(request, exc)
        listed = []
    return render(request, "web/catalog.html", {"cards": listed})


def catalog_json(request):
    """Open data: download the catalog and cross it with the chain yourself."""
    response = JsonResponse(catalog.open_data(), json_dumps_params={"indent": 2})
    response["Content-Disposition"] = 'inline; filename="rxtrail-catalog.json"'
    return response


# -- prescriber -------------------------------------------------------------------------


@role_required(Role.PRESCRIBER)
def catalog_search(request):
    """Results for the medication picker: a partial page, not a JSON API."""
    query = request.GET.get("q", "")
    found = catalog.search(query, request.participant.key_name)
    try:
        listed = catalog.cards(found)
    except RxTrailError as exc:
        return render(request, "web/_medication_results.html", {"error": str(exc)})
    return render(
        request,
        "web/_medication_results.html",
        {"cards": listed, "query": query, "favourites": not query.strip()},
    )
