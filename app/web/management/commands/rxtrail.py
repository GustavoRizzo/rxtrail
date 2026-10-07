"""Run RxTrail from the command line: set up, issue, dispense, audit."""

import asyncio
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from config import container
from rxtrail.domain import PrescriptionDocument, RxTrailError

AUTHORITIES = ("professional-authority", "health-authority")

# Enough for setup plus a demo: each record's rent deposit is ~0.001-0.0015 SOL
# and each transaction fee 0.000005 SOL.
MIN_OPERATOR_LAMPORTS = 50_000_000  # 0.05 SOL


class Command(BaseCommand):
    help = "RxTrail operations against the configured Solana network."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="action", required=True)

        sub.add_parser("setup", help="Create keys, fund the operator (localnet), initialize.")
        sub.add_parser("demo", help="Setup, then demo logins and sample prescriptions.")

        for role in ("prescriber", "dispenser"):
            enable = sub.add_parser(f"enable-{role}", help=f"The authority enables a {role}.")
            enable.add_argument("name")

        for verb in ("suspend", "reinstate"):
            for role in ("prescriber", "dispenser"):
                cmd = sub.add_parser(f"{verb}-{role}", help=f"The authority {verb}s a {role}.")
                cmd.add_argument("name")

        issue = sub.add_parser("issue", help="A prescriber issues a prescription.")
        issue.add_argument("prescriber")
        issue.add_argument("--patient-document", required=True)
        issue.add_argument("--patient-name", required=True)
        issue.add_argument("--medication", required=True)
        issue.add_argument("--dosage", default="as directed")
        issue.add_argument("--instructions", default="")
        issue.add_argument("--quantity", type=int, required=True)
        issue.add_argument("--days", type=int, default=30, help="Validity in days.")
        issue.add_argument("--prescriber-name", default=None)

        dispense = sub.add_parser("dispense", help="A dispenser hands out medication.")
        dispense.add_argument("dispenser")
        dispense.add_argument("prescription_id", help="Hex id printed by `issue`.")
        dispense.add_argument("quantity", type=int)

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

    async def _demo(self, **options):
        from web.demo import seed

        await self._setup(**options)
        self.stdout.write("demo data:")
        await seed(self.stdout.write)
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

    async def _issue(self, prescriber, quantity, days, **o):
        document = PrescriptionDocument(
            medication=o["medication"],
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

    async def _dispense(self, dispenser, prescription_id, quantity, **_):
        prescription = bytes.fromhex(prescription_id)
        async with container.open_rxtrail() as (app, chain):
            receipt = await app.dispense(dispenser, prescription, quantity)
            remaining = (await chain.prescription(prescription)).remaining
        self.stdout.write(f"dispensed {quantity}; {remaining} remain. record: {receipt.address}")

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
        verdict = {True: "matches", False: "DOES NOT MATCH", None: "not held here"}
        self.stdout.write(f"  document: {verdict[trail.document_verified]}")
        if trail.consistent:
            self.stdout.write(self.style.SUCCESS("history consistent."))
        else:
            for problem in trail.problems:
                self.stdout.write(self.style.ERROR(f"  ! {problem}"))
