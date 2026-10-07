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
    from web.context_processors import ROLE_ICONS

    return ROLE_ICONS.get(role, "user")


@register.filter
def who(address: str, names: dict) -> str:
    """The participant's name for an on-chain key, or the short key itself."""
    return (names or {}).get(str(address)) or short(address, 6)
