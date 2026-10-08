"""The demo's samples: what a visitor sees first on each login account."""

from web.demo.cast import CAST, Role
from web.demo.plan import PROFILES, SHOWCASE, plan


def kind(item) -> str:
    dispensed = sum(units for _, _, units in item.dispensations)
    if not dispensed:
        return "not filled"
    return "filled in full" if dispensed == item.quantity else "partly filled"


def test_each_login_prescriber_opens_on_one_prescription_of_each_kind():
    logins = [key for _, role, key, _, _ in CAST if role == Role.PRESCRIBER]
    for prescriber in logins:
        mine = [kind(item) for item in SHOWCASE if item.prescriber == prescriber]
        assert mine == ["not filled", "partly filled", "filled in full"], prescriber


def test_every_profile_carries_the_samples_open():
    for profile in PROFILES:
        items = {item.key: item for item in plan(profile)}
        assert all(items[sample.key] == sample for sample in SHOWCASE)
        assert not any(sample.closure for sample in SHOWCASE)
