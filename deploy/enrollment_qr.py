"""Export an existing MFA enrollment to an owner-protected local QR image.

No API imports, database access, external QR service or credential rotation.
"""
from __future__ import annotations

import argparse
from io import BytesIO
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def private_path(path: Path, suffix: str) -> Path:
    path = path.absolute()
    path.relative_to(ROOT / "deploy")
    if not path.name.endswith(suffix):
        raise ValueError()
    for ancestor in [path, *path.parents]:
        if ancestor == ROOT:
            break
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError()
    path.resolve().relative_to((ROOT / "deploy").resolve())
    return path


def write_private_image(path: Path, content: bytes) -> None:
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == "nt":
            identity = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
                capture_output=True, text=True, timeout=15,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            sid = identity.stdout.strip()
            if identity.returncode or not re.fullmatch(r"S-1-(?:\d+-)+\d+", sid):
                raise ValueError()
            result = subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", "*" + sid + ":(F)"],
                capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode:
                raise ValueError()
        else:
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            descriptor = -1
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
    except BaseException:
        if descriptor != -1:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def export_qr(enrollment: Path, output: Path | None = None) -> Path:
    enrollment = private_path(enrollment, ".enrollment.json")
    destination = private_path(output or enrollment.with_suffix(".png"), ".enrollment.png")
    if destination.exists() or not enrollment.is_file() or enrollment.stat().st_size > 16384:
        raise ValueError()
    data = json.loads(enrollment.read_text(encoding="utf-8-sig"))
    uri = data["totp_uri"]
    secret, account = data["manual_entry_key"], data["account"]
    if not isinstance(uri, str) or len(uri) > 2048:
        raise ValueError()
    if not isinstance(secret, str) or not re.fullmatch(r"[A-Z2-7]{32}", secret):
        raise ValueError()
    if not isinstance(account, str) or len(account) > 254 or any(ord(c) < 32 for c in account):
        raise ValueError()
    parsed = urlsplit(uri)
    query = parse_qs(parsed.query, strict_parsing=True)
    expected = {"secret": [secret], "issuer": ["DanaConnect"],
                "algorithm": ["SHA1"], "digits": ["6"], "period": ["30"]}
    if (parsed.scheme != "otpauth" or parsed.netloc != "totp" or parsed.fragment
            or unquote(parsed.path) != "/DanaConnect:" + account or query != expected
            or data.get("issuer") != "DanaConnect"):
        raise ValueError()
    import qrcode
    from qrcode.image.pil import PilImage
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    image = qr.make_image(image_factory=PilImage, fill_color="black", back_color="white")
    content = BytesIO()
    image.save(content, format="PNG")
    write_private_image(destination, content.getvalue())
    return destination


def main() -> int:
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            self.exit(2, "Invalid arguments; use --help.\n")
    parser = SafeParser(description=__doc__)
    parser.add_argument("--enrollment", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        export_qr(args.enrollment, args.output)
        print("Private MFA QR created next to the enrollment or at the specified output.")
        print("Scan it in your authenticator. No credential rotation or email performed.")
        return 0
    except Exception:
        print("QR could not be exported. Check operator dependencies, enrollment and new output path.")
        print("Secret values and internal exception details were suppressed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
