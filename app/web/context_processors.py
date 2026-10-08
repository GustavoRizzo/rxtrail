from django.conf import settings

from web.icons import ROLE_ICONS

# What each role is called in front of people: the words pharmacies and
# regulators use, not the model's generic names.
ROLE_LABELS = {
    "prescriber": "Prescriber",
    "dispenser": "Pharmacy",
    "professional_authority": "Medical board",
    "health_authority": "Pharmacy board",
    "catalog_authority": "Drug regulator",
    "auditor": "Auditor",
}


def rxtrail(request):
    participant = getattr(getattr(request, "user", None), "participant", None)
    return {
        "settings_network": settings.SOLANA_NETWORK,
        "demo_mode": settings.RXTRAIL_DEMO_MODE,
        "debug_mode": settings.DEBUG,
        "authors": settings.RXTRAIL_AUTHORS,
        "role_icon": ROLE_ICONS.get(getattr(participant, "role", ""), "user"),
    }
