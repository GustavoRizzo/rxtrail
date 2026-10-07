"""The QR code on a prescription, and reading it back at the counter.

The code holds only the public verification link (/rx/<id>/): no personal
data. A phone camera opens that page; the pharmacy's scanner (a camera in the
page, or a USB reader that types what it reads) hands over the same text, and
the prescription id is taken out of it.
"""

import re

import segno
from django.utils.safestring import SafeString, mark_safe

_PRESCRIPTION_ID = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


def prescription_id_in(scanned: str) -> str | None:
    """The prescription id in a bare id, a verification link, or None."""
    found = _PRESCRIPTION_ID.findall(scanned.strip().lower())
    return found[0] if len(found) == 1 else None


def svg(text: str) -> SafeString:
    """The QR code as inline SVG; CSS colours it (.rx-qr in rxtrail.css).

    Medium error correction survives a creased or smudged printout.
    """
    code = segno.make(text, error="m", micro=False)
    return mark_safe(code.svg_inline(scale=1, border=2, omitsize=True, svgclass="rx-qr"))
