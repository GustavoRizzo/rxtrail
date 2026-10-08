"""Run RxTrail from the command line: set up, issue, dispense, audit."""

import asyncio
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config import container
from records.models import CatalogMedication, CatalogProduct
from rxtrail.domain import ClosureReason, PrescriptionDocument, RxTrailError

AUTHORITIES = ("professional-authority", "health-authority", "catalog-authority")

# Enough for setup plus a demo: each record's rent deposit is ~0.001-0.0015 SOL
# and each transaction fee 0.000005 SOL.
MIN_OPERATOR_LAMPORTS = 50_000_000  # 0.05 SOL


class Command(BaseCommand):
    help = "RxTrail operations against the configured Solana network."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)

        sub.add_parser("setup", help="Create keys, fund the operator (localnet), initialize.")
        demo = sub.add_parser("demo", help="Setup, then demo logins and a planned network.")
        demo.add_argument(
            "--profile",
            default="story",
            help="story (default: every investigation, ~1 SOL) or full (bigger; localnet).",
        )
        demo.add_argument(
            "--estimate", action="store_true", help="Only show what it would create and cost."
        )
        demo.add_argument(
            "--yes", action="store_true", help="Go ahead on a public network (spends SOL)."
        )

        for role in ("prescriber", "dispenser"):
            enable = sub.add_parser(f"enable-{role}", help=f"The authority enables a {role}.")
            enable.add_argument("name")

        for verb in ("suspend", "reinstate"):
            for role in ("prescriber", "dispenser"):
                cmd = sub.add_parser(f"{verb}-{role}", help=f"The authority {verb}s a {role}.")
                cmd.add_argument("name")

        sub.add_parser("catalog", help="List the catalog: medications, products, status.")

        issue = sub.add_parser("issue", help="A prescriber issues a prescription.")
        issue.add_argument("prescriber")
        issue.add_argument("--patient-document", required=True)
        issue.add_argument("--patient-name", required=True)
        issue.add_argument(
            "--medication",
            required=True,
            help="Catalog name (e.g. 'Clonazepam 2 mg tablet') or id.",
        )
        issue.add_argument("--lock-product", default="", help="Brand or id: do not substitute.")
        issue.add_argument("--dosage", default="as directed")
        issue.add_argument("--instructions", default="")
        issue.add_argument("--quantity", type=int, required=True)
        issue.add_argument("--days", type=int, default=30, help="Validity in days.")
        issue.add_argument("--prescriber-name", default=None)

        dispense = sub.add_parser("dispense", help="A dispenser hands out medication.")
        dispense.add_argument("dispenser")
        dispense.add_argument("prescription_id", help="Hex id printed by `issue`.")
        dispense.add_argument("product", help="Brand handed out (e.g. 'Calmazen 2 mg') or id.")
        dispense.add_argument("quantity", type=int)

        for verb, what in (("cancel", "nobody dispensed yet"), ("stop", "partly dispensed")):
            close = sub.add_parser(verb, help=f"The prescriber {verb}s a prescription ({what}).")
            close.add_argument("prescriber")
            close.add_argument("prescription_id")
            close.add_argument("--reason", required=True, choices=[r.value for r in ClosureReason])
            close.add_argument("--note", default="", help="Private: never on-chain.")

        audit = sub.add_parser("audit", help="Verify a prescription's full history.")
        audit.add_argument("prescription_id")

    def handle(self, *args, action, **options):
        try:
            asyncio.run(getattr(self, "_" + action.replace("-", "_"))(**options))
        except (RxTrailError, ValueError) as exc:
            raise CommandError(f"{type(exc).__name__}: {exc}") from exc

    def _key(self, name: str) -> None:
        keys = container.key_store()
        if not keys.exists(name):
            address = keys.create(name).pubkey()
            self.stdout.write(f"  new key {name}: {address}")

    async def _setup(self, **_):
        self.stdout.write(f"network: {settings.SOLANA_NETWORK}")
        for name in (settings.SOLANA_OPERATOR, *AUTHORITIES):
            self._key(name)
        async with container.open_rxtrail() as (_app, chain):
            if await chain.operator_balance() < MIN_OPERATOR_LAMPORTS:
                if settings.SOLANA_NETWORK != "localnet":
                    raise CommandError(
                        f"fund the operator {chain.address_of(settings.SOLANA_OPERATOR)} "
                        "with at least 0.05 SOL (devnet: https://faucet.solana.com), "
                        "then run setup again"
                    )
                await chain.airdrop_to_operator(10_000_000_000)
                self.stdout.write("  operator funded from the local faucet")
            if await chain.initialized():
                self.stdout.write("  program already initialized")
            else:
                receipt = await chain.initialize(*AUTHORITIES)
                self.stdout.write(f"  initialized: {receipt.signature}")
        self.stdout.write(self.style.SUCCESS("ready."))

    async def _demo(self, profile, estimate, yes, **options):
        from web.demo import seed

        await self._setup(**options)
        self.stdout.write("demo data:")
        await seed(self.stdout.write, profile, estimate_only=estimate, confirmed=yes)
        if estimate:
            return
        self.stdout.write(
            self.style.SUCCESS(
                f"demo ready. Every demo password is {settings.RXTRAIL_DEMO_PASSWORD!r}."
            )
        )

    async def _enable(self, role: str, authority: str, name: str):
        self._key(name)
        async with container.open_rxtrail() as (app, _chain):
            enable = getattr(app, f"enable_{role}")
            receipt = await enable(authority, name)
        self.stdout.write(f"{role} {name} enabled at {receipt.address}")

    async def _enable_prescriber(self, name, **_):
        await self._enable("prescriber", "professional-authority", name)

    async def _enable_dispenser(self, name, **_):
        await self._enable("dispenser", "health-authority", name)

    async def _change_status(self, verb: str, role: str, name: str):
        authority = "professional-authority" if role == "prescriber" else "health-authority"
        async with container.open_rxtrail() as (app, _chain):
            receipt = await getattr(app, f"{verb}_{role}")(authority, name)
        self.stdout.write(f"{role} {name} {verb}d ({receipt.signature})")

    async def _suspend_prescriber(self, name, **_):
        await self._change_status("suspend", "prescriber", name)

    async def _reinstate_prescriber(self, name, **_):
        await self._change_status("reinstate", "prescriber", name)

    async def _suspend_dispenser(self, name, **_):
        await self._change_status("suspend", "dispenser", name)

    async def _reinstate_dispenser(self, name, **_):
        await self._change_status("reinstate", "dispenser", name)

    async def _catalog(self, **_):
        medications = [
            m async for m in CatalogMedication.objects.prefetch_related("products__manufacturer")
        ]
        async with container.open_rxtrail() as (_app, chain):
            addresses = [m.address for m in medications] + [
                p.address for m in medications for p in m.products.all()
            ]
            entries = await chain.catalog_entries(addresses)
        status = {a: (e.status if e else "not on chain") for a, e in zip(addresses, entries)}
        for m in medications:
            self.stdout.write(f"{m.name}  [{status[m.address]}]  {m.medication_id}")
            for p in m.products.all():
                self.stdout.write(
                    f"  {p.brand_name} · {p.manufacturer.name} · {p.kind}  "
                    f"[{status[p.address]}]  {p.product_id}"
                )

    async def _issue(self, prescriber, quantity, days, **o):
        name = o["medication"]
        medication = (
            await CatalogMedication.objects.filter(medication_id=name.lower()).afirst()
            or await CatalogMedication.objects.filter(name__iexact=name).afirst()
        )
        if medication is None:
            raise CommandError(f"no medication {name!r} in the catalog (see `rxtrail catalog`)")
        document = PrescriptionDocument(
            medication_id=medication.medication_id,
            medication=medication.name,
            locked_product_id=o["lock_product"] and await _product_id(o["lock_product"]),
            dosage=o["dosage"],
            instructions=o["instructions"],
            quantity=quantity,
            prescriber_name=o["prescriber_name"] or prescriber,
            patient_name=o["patient_name"],
            issued_on=datetime.now(UTC).date().isoformat(),
        )
        async with container.open_rxtrail() as (app, _chain):
            issued = await app.issue(
                prescriber, o["patient_document"], document, timedelta(days=days)
            )
        self.stdout.write(f"prescription id: {issued.prescription_id.hex()}")
        self.stdout.write(f"  on-chain at {issued.receipt.address}")
        self.stdout.write(f"  document hash {issued.document_hash.hex()}")

    async def _dispense(self, dispenser, prescription_id, product, quantity, **_):
        prescription = bytes.fromhex(prescription_id)
        product_id = bytes.fromhex(await _product_id(product))
        async with container.open_rxtrail() as (app, chain):
            receipt = await app.dispense(dispenser, prescription, product_id, quantity)
            remaining = (await chain.prescription(prescription)).remaining
        self.stdout.write(f"dispensed {quantity}; {remaining} remain. record: {receipt.address}")

    async def _close(self, verb, prescriber, prescription_id, reason, note):
        async with container.open_rxtrail() as (app, _chain):
            receipt = await getattr(app, verb)(
                prescriber, bytes.fromhex(prescription_id), ClosureReason(reason), note
            )
        self.stdout.write(f"{verb} recorded at {receipt.address} ({receipt.signature})")

    async def _cancel(self, prescriber, prescription_id, reason, note, **_):
        await self._close("cancel", prescriber, prescription_id, reason, note)

    async def _stop(self, prescriber, prescription_id, reason, note, **_):
        await self._close("stop", prescriber, prescription_id, reason, note)

    async def _audit(self, prescription_id, **_):
        async with container.open_rxtrail() as (app, _chain):
            trail = await app.audit(bytes.fromhex(prescription_id))
        p = trail.prescription
        self.stdout.write(f"prescription {p.address}")
        self.stdout.write(f"  prescriber {p.prescriber}")
        self.stdout.write(
            f"  granted {p.quantity_granted}, dispensed {p.quantity_dispensed}, "
            f"remaining {p.remaining}, expires {p.expires_at:%Y-%m-%d}"
        )
        for d in trail.dispensations:
            self.stdout.write(
                f"  #{d.index} {d.dispensed_at:%Y-%m-%d %H:%M:%S} by {d.dispenser}: "
                f"{d.quantity} (remaining {d.remaining_after})"
            )
        if c := trail.closure:
            self.stdout.write(
                f"  {c.kind} {c.closed_at:%Y-%m-%d %H:%M:%S} by {c.prescriber} "
                f"({c.reason.label}): {c.quantity_voided} voided"
            )
        verdict = {True: "matches", False: "DOES NOT MATCH", None: "not held here"}
        self.stdout.write(f"  document: {verdict[trail.document_verified]}")
        if trail.consistent:
            self.stdout.write(self.style.SUCCESS("history consistent."))
        else:
            for problem in trail.problems:
                self.stdout.write(self.style.ERROR(f"  ! {problem}"))


async def _product_id(brand_or_id: str) -> str:
    product = (
        await CatalogProduct.objects.filter(product_id=brand_or_id.lower()).afirst()
        or await CatalogProduct.objects.filter(brand_name__iexact=brand_or_id).afirst()
    )
    if product is None:
        raise CommandError(f"no product {brand_or_id!r} in the catalog (see `rxtrail catalog`)")
    return product.product_id
