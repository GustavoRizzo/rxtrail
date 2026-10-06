"""Test-wide setup: point Django at the pre-created test database."""

import pytest
from django.conf import settings
from django.core.management import call_command


def pytest_configure(config):
    # Refuse to touch anything but a database named *_test: tests flush tables.
    name = settings.DATABASES["default"]["NAME"]
    if not name.endswith("_test"):
        raise pytest.UsageError(
            f"database is {name!r}; run tests with `just test-app` (targets the *_test database)"
        )


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    # The test database already exists with its schema and user; the app user
    # cannot create databases on purpose. Use it as-is and migrate.
    settings.DATABASES["default"]["TEST"]["NAME"] = settings.DATABASES["default"]["NAME"]
    with django_db_blocker.unblock():
        call_command("migrate", verbosity=0)
