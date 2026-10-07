from django.conf import settings

ROLE_ICONS = {
    "prescriber": "stethoscope",
    "dispenser": "pill",
    "professional_authority": "landmark",
    "health_authority": "building-2",
    "catalog_authority": "library-big",
    "auditor": "search-check",
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
