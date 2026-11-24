"""Local TOTP enrollment rendering; secrets never reach an external QR service."""
import base64
import io
from urllib.parse import quote, urlencode

import qrcode
from qrcode.image.svg import SvgPathFillImage


def totp_uri(email: str, secret: str) -> str:
    return "otpauth://totp/" + quote("DanaConnect:" + email, safe="") + "?" + urlencode({
        "secret": secret, "issuer": "DanaConnect", "algorithm": "SHA1", "digits": 6, "period": 30})


def qr_data_url(uri: str) -> str:
    buffer = io.BytesIO()
    qrcode.make(uri, image_factory=SvgPathFillImage, border=4).save(buffer)
    return "data:image/svg+xml;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
