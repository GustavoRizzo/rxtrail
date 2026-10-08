"""Template helpers: short ids and links to the Solana explorer."""

from urllib.parse import quote

from django import template
from django.conf import settings

register = template.Library()


@register.filter
def short(value: str, keep: int = 4) -> str:
    """'2b4af0f0…7538' — long ids stay recognizable but compact."""
    value = str(value)
    return value if len(value) <= keep * 2 + 1 else f"{value[:keep]}…{value[-keep:]}"


@register.filter
def explorer(value: str, kind: str = "address") -> str:
    """Link to an address or transaction on the network this app talks to."""
    if settings.SOLANA_NETWORK == "localnet":
        cluster = "custom&customUrl=" + quote(settings.SOLANA_EXPLORER_LOCAL_RPC, safe="")
    else:
        cluster = settings.SOLANA_NETWORK
    return f"https://explorer.solana.com/{kind}/{value}?cluster={cluster}"


@register.filter
def percent(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


@register.filter
def get_item(mapping: dict, key: str):
    """mapping[key] in a template, or None."""
    return (mapping or {}).get(key)


@register.filter
def role_icon(role: str) -> str:
    """The Lucide icon that stands for a participant's role."""
    from web.icons import ROLE_ICONS

    return ROLE_ICONS.get(role, "user")


@register.filter
def icon(meaning: str) -> str:
    """The Lucide icon for an idea in the icon vocabulary (web/icons.py).
    An unknown meaning fails loudly: the vocabulary is the only source."""
    from web.icons import ICONS

    return ICONS[meaning]


@register.filter
def role_label(role: str) -> str:
    """What a participant's role is called on the page."""
    from web.context_processors import ROLE_LABELS

    return ROLE_LABELS.get(role, role)


@register.filter
def who(address: str, names: dict) -> str:
    """The participant's name for an on-chain key, or the short key itself."""
    return (names or {}).get(str(address)) or short(address, 6)


@register.filter
def pseudonym(address: str) -> str:
    """A prescriber or pharmacy on the insights pages: their public key, never a name."""
    from rxtrail.insights import pseudonym as shorten

    return shorten(str(address))


@register.filter
def pct(value: float | None, digits: int = 0) -> str:
    """A 0..1 rate as a percentage; a dash when there is none."""
    return "–" if value is None else f"{value:.{digits}%}"


@register.filter
def bar(value: float | None, scale: float | str = 1.0) -> str:
    """A bar's width, in percent of its track: value / scale (1 if not given), clamped."""
    scale = float(scale or 1.0)
    if not value:
        return "0"
    return f"{max(0.0, min(value / scale, 1.0)) * 100:.1f}"


@register.simple_tag
def insights_link(kind: str, key: str) -> str:
    """Where an entity is studied on the insights pages."""
    from django.urls import reverse

    return reverse(f"web:insights_{kind}", args=[key])
