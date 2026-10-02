"""Offline operator-only admin provisioning. Never exposes a public bootstrap API.

Run on the trusted server with its database/encryption configuration. The private
output file must be transferred directly to its owner and removed after enrolling
an authenticator. Rotation revokes all existing sessions for this administrator.
"""
import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote, urlencode

from email_validator import validate_email
from sqlalchemy import delete, select

from app.auth import generate_totp_secret
from app.config import settings
from app.database import SessionLocal
from app.delivery import encrypt_text
from app.models import AuditEvent, SessionToken, User
from app.models_delivery import AdminCredential, MFAChallenge


def write_private_enrollment(path: Path, payload: dict):
    if not path.is_absolute():
        raise ValueError("Enrollment output must be an absolute path")
    # Exclusive creation prevents overwriting or following an existing symlink.
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == "nt":
            # An isolated operator process may deliberately omit USERNAME/USER.
            # Resolve the token SID rather than relying on those environment values.
            identity = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
                capture_output=True, text=True, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            sid = identity.stdout.strip()
            if identity.returncode != 0 or not re.fullmatch(r"S-1-(?:\d+-)+\d+", sid):
                raise RuntimeError("Could not resolve enrollment file owner")
            result = subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", "*" + sid + ":(F)"],
                capture_output=True, check=False, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            if result.returncode != 0:
                raise RuntimeError("Could not restrict enrollment file permissions")
        else:
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            descriptor = -1
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
    except Exception:
        if descriptor != -1:
            os.close(descriptor)
        path.unlink(missing_ok=True)
        raise


def provision_admin(db, *, email: str, name: str, output: Path, rotate_mfa: bool = False):
    email = validate_email(email, check_deliverability=False, test_environment=settings.environment != "production").normalized.lower()
    if not name.strip() or len(name) > 160:
        raise ValueError("Provide an administrator name of 1–160 characters")
    user = db.scalar(select(User).where(User.email == email).with_for_update())
    if user and user.role != "admin":
        raise ValueError("Existing non-admin accounts cannot be promoted by bootstrap")
    if user is None:
        user = User(email=email, full_name=name.strip(), role="admin", account_status="active", profile_completed=True)
        db.add(user)
        db.flush()
    if user.account_status != "active":
        raise ValueError("Suspended administrators cannot be reactivated by bootstrap")
    credential = db.scalar(select(AdminCredential).where(AdminCredential.user_id == user.id))
    if credential and not rotate_mfa:
        raise ValueError("MFA already provisioned; explicit --rotate-mfa is required")
    secret = generate_totp_secret()
    encrypted = encrypt_text(secret)
    if credential:
        credential.encrypted_totp_secret, credential.last_used_step, credential.active = encrypted, -1, True
    else:
        db.add(AdminCredential(user_id=user.id, encrypted_totp_secret=encrypted))
    db.execute(delete(SessionToken).where(SessionToken.user_id == user.id))
    db.execute(delete(MFAChallenge).where(MFAChallenge.user_id == user.id))
    db.add(AuditEvent(actor_id=None, action="admin.mfa_rotated" if credential else "admin.provisioned", entity_type="user", entity_id=user.id, detail={"method": "offline_operator"}))
    uri = "otpauth://totp/" + quote("DanaConnect:" + email, safe="") + "?" + urlencode({"secret": secret, "issuer": "DanaConnect", "algorithm": "SHA1", "digits": "6", "period": "30"})
    write_private_enrollment(output, {
        "account": email, "issuer": "DanaConnect", "totp_uri": uri,
        "manual_entry_key": secret,
        "instructions": "Import the URI or add manual_entry_key as a time-based account in your authenticator, then remove this enrollment file. This file contains a secret.",
    })
    try:
        db.commit()
    except Exception:
        db.rollback()
        output.unlink(missing_ok=True)
        raise
    return user.id


def main():
    parser = argparse.ArgumentParser(description="Provision an administrator and MFA offline; never sends email")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--secret-output", required=True, type=Path)
    parser.add_argument("--rotate-mfa", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        identifier = provision_admin(db, email=args.email, name=args.name, output=args.secret_output, rotate_mfa=args.rotate_mfa)
    print("Administrator provisioned:", identifier)
    print("Private authenticator enrollment saved to the specified file. No email sent.")


if __name__ == "__main__":
    main()
