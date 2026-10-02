"""Read configuration without displaying secrets; optional explicit HTTPS health read."""
import argparse
import base64
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlparse
if __package__:
    from .vercel_config import blob_credentials_valid
else:
    from vercel_config import blob_credentials_valid


def read_env(path):
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError("Invalid dotenv line; use KEY=value")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()
    if not args.env_file.is_file():
        print("Configuration missing. Create deploy/.env.production first.")
        return 1
    config = read_env(args.env_file)
    domain = config.get("APP_DOMAIN", "")
    email_provider = config.get("EMAIL_PROVIDER", "")
    try:
        encryption_ok = len(base64.b64decode(config.get("OUTBOX_ENCRYPTION_KEY", ""), altchars=b"-_", validate=True)) == 32
    except (ValueError, TypeError):
        encryption_ok = False
    checks = {
        "real_domain": bool(re.fullmatch(r"(?=.{1,253}$)[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", domain)) and "." in domain and not domain.endswith(("example.org", "example.com", ".invalid")),
        "certificate_contact": bool(config.get("ACME_EMAIL")) and not config.get("ACME_EMAIL", "").endswith("@example.org"),
        "production": config.get("ENVIRONMENT") == "production",
        "demo_disabled": config.get("DEMO_MODE", "").lower() == "false",
        "debug_disabled": config.get("AUTH_DEBUG_CODE", "").lower() == "false",
        "database_password": bool(re.fullmatch(r"[0-9a-fA-F]{32,}", config.get("POSTGRES_PASSWORD", ""))),
        "fresh_auth_secret": len(config.get("AUTH_SECRET", "")) >= 32 and config.get("AUTH_SECRET") != "local-development-change-before-deployment",
        "outbox_encryption": encryption_ok,
        "real_email_provider": email_provider in {"resend", "smtp"},
        "sender_configured": bool(config.get("EMAIL_FROM")),
        "email_credentials": bool(config.get("RESEND_API_KEY")) if email_provider == "resend" else bool(config.get("SMTP_HOST")) if email_provider == "smtp" else False,
        "smtp_tls_modes": not (config.get("SMTP_TLS", "false").lower() == "true" and config.get("SMTP_STARTTLS", "true").lower() == "true"),
        "private_storage": (config.get("STORAGE_PROVIDER") == "s3" and bool(config.get("S3_BUCKET")) and bool(config.get("S3_REGION"))) or (config.get("STORAGE_PROVIDER") == "blob" and blob_credentials_valid(config.get("BLOB_STORE_ID", ""), config.get("BLOB_READ_WRITE_TOKEN", ""))),
        "storage_https": config.get("STORAGE_PROVIDER") != "s3" or not config.get("S3_ENDPOINT_URL") or config["S3_ENDPOINT_URL"].startswith("https://"),
        "kms_key": config.get("STORAGE_PROVIDER") != "s3" or config.get("S3_SSE", "AES256") == "AES256" or config.get("S3_SSE") == "aws:kms" and bool(config.get("S3_KMS_KEY_ID")),
        "google_callback": not config.get("GOOGLE_CLIENT_ID") or bool(config.get("GOOGLE_CLIENT_SECRET")) and config.get("GOOGLE_REDIRECT_URI", "").startswith("https://"),
        "cron_secret_if_enabled": not config.get("CRON_SECRET") or len(config["CRON_SECRET"]) >= 32 and config["CRON_SECRET"] != config.get("AUTH_SECRET"),
    }
    if args.base_url:
        parsed = urlparse(args.base_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Provide an HTTPS base URL without credentials, query or fragment")
        for route, expected in (("health", "ok"), ("ready", "ready")):
            try:
                with urllib.request.urlopen(args.base_url.rstrip("/") + "/api/v1/" + route, timeout=10) as response:
                    payload = json.load(response)
                checks["live_" + route] = payload.get("status") == expected
                if route == "health":
                    checks["live_production"] = payload.get("environment") == "production" and payload.get("demo_mode") is False
            except Exception:
                checks["live_" + route] = False
    for label, ready in checks.items():
        print(f"{'READY' if ready else 'MISSING'} {label}")
    print("Static checks do not verify DNS, IAM, sender ownership, MFA provisioning, backup restore or worker freshness.")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
