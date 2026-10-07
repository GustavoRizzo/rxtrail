"""The design system keeps every text readable, by construction.

Colours live in web/static/web/tokens.css. These checks run on the tokens
themselves, so a new identity (or a new token) that breaks readability fails
here instead of in someone's browser:
- every text colour has enough contrast (WCAG) on every surface;
- the browser is told the theme is dark or light (color-scheme), and the
  surfaces it paints itself are opaque: an open select menu cannot blend a
  translucent colour, and came out white under white text;
- every form control in the templates uses the design system's styling.
"""

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"
TOKENS = (WEB / "static/web/tokens.css").read_text()
COMPONENTS = (WEB / "static/web/rxtrail.css").read_text()
TEMPLATES = sorted((WEB / "templates").rglob("*.html"))

# WCAG 2.2: 4.5 for text (1.4.3), 3 for icons and other UI parts (1.4.11).
TEXT, UI = 4.5, 3.0

type Rgba = tuple[float, float, float, float]


def _parse(value: str) -> Rgba | None:
    value = value.strip()
    if m := re.fullmatch(r"#([0-9a-fA-F]{6})", value):
        h = m.group(1)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    if m := re.fullmatch(
        r"rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*(?:[/,]\s*([\d.]+))?\s*\)", value
    ):
        r, g, b, a = m.groups()
        return (int(r), int(g), int(b), float(a) if a else 1.0)
    return None  # gradients, fonts, references to other tokens


DECLARED = dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", TOKENS))
COLOURS = {name: rgba for name, value in DECLARED.items() if (rgba := _parse(value))}


def colour(name: str, over: str = "surface") -> Rgba:
    """A token as it shows on screen: translucent ones blended over `over`."""
    r, g, b, a = COLOURS[name]
    if a == 1.0:
        return (r, g, b, 1.0)
    base = colour(over)
    return (*(a * c + (1 - a) * bc for c, bc in zip((r, g, b), base[:3], strict=True)), 1.0)


def luminance(rgba: Rgba) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgba[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: str, bg: str) -> float:
    background = colour(bg)
    hi, lo = sorted((luminance(colour(fg, over=bg)), luminance(background)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


SURFACES = ["surface", "surface-card", "surface-raised"]
TEXT_TOKENS = ["text", "brand-accent", "brand-secondary", "danger"]


@pytest.mark.parametrize("bg", SURFACES)
@pytest.mark.parametrize("fg", TEXT_TOKENS)
def test_text_tokens_are_readable_on_every_surface(fg, bg):
    assert contrast(fg, bg) >= TEXT, f"--{fg} on --{bg}: {contrast(fg, bg):.2f}:1"


@pytest.mark.parametrize("bg", ["brand-primary", "brand-secondary", "brand-accent"])
def test_text_on_brand_colours_is_readable(bg):
    assert contrast("on-brand", bg) >= TEXT, (
        f"--on-brand on --{bg}: {contrast('on-brand', bg):.2f}:1"
    )


@pytest.mark.parametrize("bg", SURFACES)
def test_the_primary_brand_colour_is_visible_as_icons_and_accents(bg):
    assert contrast("brand-primary", bg) >= UI


@pytest.mark.parametrize("bg", ["surface-card", "surface-raised"])
def test_placeholders_are_visible_but_fainter_than_values(bg):
    # Deliberately below text contrast (users mistook bright hints for
    # filled-in fields), but never invisible.
    assert 1.8 <= contrast("placeholder", bg) < contrast("text", bg)


def test_the_browser_is_told_the_theme():
    assert re.search(r":root\s*{[^}]*color-scheme\s*:\s*(dark|light)", TOKENS)


@pytest.mark.parametrize("name", ["surface", "surface-raised"])
def test_surfaces_the_browser_paints_are_opaque(name):
    assert COLOURS[name][3] == 1.0, f"--{name} must be opaque: browser menus cannot blend it"


def test_open_select_menus_use_the_opaque_surface():
    rule = re.search(r"select option[^{]*{([^}]*)}", COMPONENTS)
    assert rule, "rxtrail.css must style select options"
    assert "var(--surface-raised)" in rule.group(1) and "var(--text)" in rule.group(1)


def test_every_token_the_styles_use_exists():
    used = set(re.findall(r"var\(--([\w-]+)", COMPONENTS))
    used |= set(re.findall(r"var\(--([\w-]+)", (WEB / "templates/web/_theme.html").read_text()))
    used -= {"i"}  # per-element stagger index, set inline
    assert used <= DECLARED.keys(), f"undefined tokens: {sorted(used - DECLARED.keys())}"


CONTROL = re.compile(r"<(input|select|textarea)\b([^>]*)>", re.DOTALL)
UNSTYLED_TYPES = re.compile(r'\btype="(hidden|checkbox|radio|submit|button)"')


@pytest.mark.parametrize("template", TEMPLATES, ids=lambda p: p.name)
def test_every_form_control_uses_the_design_system(template):
    unstyled = [
        f"<{tag}{attrs[:60]}…"
        for tag, attrs in CONTROL.findall(template.read_text())
        if not UNSTYLED_TYPES.search(attrs) and "rx-input" not in attrs
    ]
    assert not unstyled, f"add class rx-input (or use _field.html): {unstyled}"
