"""The icon vocabulary: one Lucide icon per idea, everywhere on the site.

Templates ask by meaning (`{{ "pharmacy"|icon }}`), never by icon name, so a
pharmacy looks the same on the login page, the counter and the insights, and
changing an icon is one line here. The style guide shows the whole list.
"""

ICONS = {
    # Who acts (public names; ROLE_ICONS maps the model's roles onto them)
    "prescriber": "stethoscope",
    "pharmacy": "store",
    "medical board": "landmark",
    "pharmacy board": "building-2",
    "drug regulator": "library-big",
    "auditor": "search-check",
    # What the record holds
    "prescription": "file-text",
    "fill": "hand-coins",
    "medication": "pill",
    "product": "package",
    "manufacturer": "factory",
    "therapeutic class": "shapes",
    "brand lock": "lock-keyhole",
    "recall": "snowflake",
    "cancelled": "circle-x",
    "discontinued": "circle-stop",
    # What people do and see
    "signal": "flag",
    "verified": "shield-check",
    "verify": "scan-search",
    "sign": "pen-line",
    "activity": "activity",
}

ROLE_ICONS = {
    "prescriber": ICONS["prescriber"],
    "dispenser": ICONS["pharmacy"],
    "professional_authority": ICONS["medical board"],
    "health_authority": ICONS["pharmacy board"],
    "catalog_authority": ICONS["drug regulator"],
    "auditor": ICONS["auditor"],
}
