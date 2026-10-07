"""Reading a prescription id out of whatever the counter's scanner hands over."""

import pytest

from web.qrcodes import prescription_id_in, svg

RX = "0f" * 32


@pytest.mark.parametrize(
    "scanned",
    [
        RX,
        RX.upper(),
        f"  {RX}\n",  # a USB reader types the code, then Enter
        f"https://rxtrail.example/rx/{RX}/",
        f"http://localhost:8142/rx/{RX.upper()}/?from=qr",
    ],
)
def test_the_id_is_found_in_an_id_or_a_link(scanned):
    assert prescription_id_in(scanned) == RX


@pytest.mark.parametrize(
    "scanned",
    [
        "",
        "https://example.com/menu",
        RX[:-1],  # one character short
        RX + "a",  # one too many: not an id
        f"{RX}/{'1' * 64}",  # two ids: ambiguous
    ],
)
def test_anything_else_is_not_a_prescription(scanned):
    assert prescription_id_in(scanned) is None


def test_the_code_is_inline_svg_that_css_colours():
    code = str(svg(f"https://rxtrail.example/rx/{RX}/"))
    assert code.startswith("<svg") and 'class="rx-qr"' in code and "viewBox" in code
    assert "width=" not in code.split(">")[0]  # scales with its container
