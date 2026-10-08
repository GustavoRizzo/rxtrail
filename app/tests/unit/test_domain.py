"""Where a prescription stands, derived from its on-chain counters and deadline."""

from datetime import timedelta

import pytest

from rxtrail.domain import PrescriptionStatus, Standing
from tests.fakes import T0, a_prescription


@pytest.mark.parametrize(
    ("dispensed", "now", "expected"),
    [
        (0, T0, Standing.ACTIVE),
        (29, T0 + timedelta(days=29), Standing.ACTIVE),
        (29, T0 + timedelta(days=30), Standing.EXPIRED),  # the deadline itself is past
        (30, T0, Standing.COMPLETED),
        (30, T0 + timedelta(days=90), Standing.COMPLETED),  # finished before it expired
    ],
)
def test_standing(dispensed, now, expected):
    assert a_prescription(granted=30, dispensed=dispensed).standing(now) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (PrescriptionStatus.CANCELLED, Standing.CANCELLED),
        (PrescriptionStatus.STOPPED, Standing.STOPPED),
    ],
)
def test_a_closed_prescription_stands_as_closed_even_once_expired(status, expected):
    prescription = a_prescription(granted=30, dispensed=10, status=status)
    assert prescription.standing(T0) is expected
    assert prescription.standing(T0 + timedelta(days=90)) is expected
