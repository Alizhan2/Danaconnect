"""Generate a private Vercel env template or validate an explicit file offline.

This stdlib-only module never imports app.config, reads ambient Settings, executes
an SDK/CLI provider command, connects to a service, or uploads environment values.
read_env and validate_config are safe to import: only main performs CLI actions.
Successful validation means syntax/configuration checks, not production readiness.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
from typing import Mapping
from urllib.parse import parse_qs, unquote, urlsplit


class ConfigError(ValueError):
    """A fixed, sanitized message. Never construct this from input values."""


PLACEHOLDER = re.compile(
    r"replace(?:_|-)|change[-_ ]?me|your[-_ ](?:key|secret|domain|bucket|password)|"
    r"<(?![^<>]*@)[^>]+>|\$\{|local-development-change-before-deployment",
    re.IGNORECASE,
)
RESERVED_DOMAINS = ("example.com", "example.org", "example.net", "localhost")
REQUIRED = {
    "ENVIRONMENT", "VERCEL", "DATABASE_POOL_MODE", "DEMO_MODE", "AUTH_DEBUG_CODE", "DATABASE_URL",
    "TRUSTED_ORIGINS", "FRONTEND_URL", "AUTH_SECRET", "OUTBOX_ENCRYPTION_KEY",
    "OUTBOX_PREVIOUS_ENCRYPTION_KEYS", "CRON_SECRET", "EMAIL_PROVIDER",
    "EMAIL_FROM", "STORAGE_PROVIDER",
    "UPLOAD_MAX_BYTES",
    "AI_ENABLED", "API_BASE_URL", "ADMIN_APP_URL", "ADMIN_BASE_PATH", "NEXT_PUBLIC_WEB_URL",
    "OPERATOR_SCHEDULER",
}
INTEGER_RANGES = {
    "SESSION_DAYS": (1, 30), "OTP_MINUTES": (1, 15),
    "OTP_MAX_ATTEMPTS": (1, 10), "ADMIN_MFA_MINUTES": (1, 10),
    "OUTBOX_MAX_ATTEMPTS": (1, 10), "OUTBOX_LEASE_SECONDS": (60, 600),
    "SMTP_PORT": (1, 65535), "AI_DAILY_USER_LIMIT": (1, 100),
    "AI_DAILY_GLOBAL_LIMIT": (1, 10000), "AI_MAX_INPUT_CHARS": (500, 12000),
    "AI_MAX_OUTPUT_TOKENS": (300, 3000), "UPLOAD_MAX_BYTES": (1024, 3145728),
}


def read_env(path: Path) -> dict[str, str]:
    """Read only the explicit UTF-8 dotenv file, with no expansion or env merge.

    Grammar: KEY=value; optional matching outer quotes; JSON stays unquoted.
    Comments must have their own line. Duplicate keys, shell interpolation,
    control characters, malformed quotes and unknown line formats are rejected.
    Errors never include source lines, values, unknown keys or file paths.
    """
    try:
        if not path.is_file() or path.stat().st_size > 131072:
            raise ConfigError("Configuration must be a regular file of at most 128 KiB.")
        content = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise ConfigError("Configuration cannot be read as UTF-8.") from None
    values: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError("Invalid configuration line; use KEY=value.")
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            raise ConfigError("Configuration keys must use uppercase letters and underscores.")
        if key in values:
            raise ConfigError("Duplicate configuration key.")
        if re.search(r"\s+#", value) and not value.startswith(("'", '"')):
            raise ConfigError("Inline comments are forbidden; use a separate comment line.")
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ConfigError("Unbalanced configuration quotes.")
            value = value[1:-1]
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ConfigError("Control characters are forbidden in configuration values.")
        if "${" in value or "$(" in value or "`" in value:
            raise ConfigError("Configuration expansion and shell substitutions are forbidden.")
        values[key] = value
    return values


def external_host(host: str | None) -> bool:
    """Reject obvious local/reserved addresses without DNS/network resolution."""
    if not host:
        return False
    host = host.lower().rstrip(".")
    if any(host == domain or host.endswith("." + domain) for domain in RESERVED_DOMAINS):
        return False
    if host.endswith((".local", ".localhost", ".invalid", ".test", ".example", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return bool(re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", host))


def https_url(value: str, *, origin: bool = False) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
        return bool(
            parsed.scheme == "https" and external_host(parsed.hostname)
            and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment
            and (port is None or 1 <= port <= 65535)
            and not re.search(r"[\s\\]", value)
            and (not origin or parsed.path in {"", "/"})
        )
    except ValueError:
        return False


def postgres_tls_url(value: str) -> bool:
    """Require psycopg and TLS; private/VPC PostgreSQL hosts are valid topology."""
    try:
        parsed = urlsplit(value)
        query = parse_qs(parsed.query, keep_blank_values=True)
        port = parsed.port
        host = parsed.hostname or ""
        try:
            address = ipaddress.ip_address(host)
            host_valid = not (address.is_unspecified or address.is_loopback or address.is_multicast)
        except ValueError:
            host_valid = bool(re.fullmatch(r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", host)) and host.lower() != "localhost"
            host_valid = host_valid and not re.fullmatch(r"[0-9.]+", host)
            host_valid = host_valid and not any(host.lower() == domain or host.lower().endswith("." + domain) for domain in RESERVED_DOMAINS)
            host_valid = host_valid and not host.lower().endswith((".invalid", ".test", ".example", ".localhost"))
        return bool(
            parsed.scheme == "postgresql+psycopg" and host_valid
            and parsed.username and parsed.password and parsed.path not in {"", "/"}
            and not parsed.fragment and not re.search(r"[\s\\]", value)
            and (port is None or 1 <= port <= 65535)
            and query.get("sslmode") in (["require"], ["verify-ca"], ["verify-full"])
        )
    except ValueError:
        return False


def fernet_key(value: str) -> bool:
    try:
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{43}=", value)) and len(
            base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
        ) == 32
    except (ValueError, UnicodeError, binascii.Error):
        return False


def blob_credentials_valid(store_id: str, token: str) -> bool:
    """Same offline format/binding checks as app.blob_configuration; no imports."""
    identity = store_id.removeprefix("store_")
    match = re.fullmatch(r"vercel_blob_rw_([A-Za-z0-9]{1,63})_([A-Za-z0-9_-]{16,})", token)
    return bool(re.fullmatch(r"[A-Za-z0-9]{1,63}", identity) and match
                and match.group(1).lower() == identity.lower())


def validate_config(values: Mapping[str, str]) -> list[str]:
    """Return fixed safe failure messages only; no I/O and no Settings import.

    This intentionally adds Vercel pilot gates beyond API Settings: provider field
    structure, 3 MiB ceiling and a documented scheduler choice. It cannot confirm
    provider resources, private bucket/IAM policy, budget approval or live readiness.
    """
    issues: list[str] = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            issues.append(message)

    def get(key: str) -> str:
        return values.get(key, "")

    require(all(get(key) for key in REQUIRED), "Required Vercel configuration fields are missing or empty.")
    require(not any(PLACEHOLDER.search(unquote(value)) for value in values.values()), "Unresolved placeholders or development credentials remain.")
    require(not any(re.search(r"(?:^|[.@/])example\.(?:com|org|net)(?:[:/\s]|$)", value, re.IGNORECASE) for value in values.values()), "Reserved example domains remain in configuration.")
    require(not any(key.startswith("NEXT_PUBLIC_") and key != "NEXT_PUBLIC_WEB_URL" for key in values), "Only the non-secret NEXT_PUBLIC_WEB_URL is accepted among public frontend settings.")
    require(get("ENVIRONMENT") == "production", "ENVIRONMENT must be production.")
    require(get("VERCEL").lower() == "true", "VERCEL must be true for this Vercel configuration.")
    require(get("DATABASE_POOL_MODE") == "null", "DATABASE_POOL_MODE must be null to disable the local connection pool for Vercel.")
    require(get("DEMO_MODE").lower() == "false", "DEMO_MODE must be false.")
    require(get("AUTH_DEBUG_CODE").lower() == "false", "AUTH_DEBUG_CODE must be false.")
    require(postgres_tls_url(get("DATABASE_URL")), "DATABASE_URL requires external PostgreSQL via psycopg and explicit TLS sslmode.")
    for key in ("AUTH_SECRET", "CRON_SECRET"):
        secret = get(key)
        require(len(secret) >= 32 and len(set(secret)) >= 12 and not secret.isspace(), f"{key} requires a fresh secret of at least 32 characters.")
    require(get("AUTH_SECRET") != get("CRON_SECRET"), "AUTH_SECRET and CRON_SECRET must be different.")
    require(fernet_key(get("OUTBOX_ENCRYPTION_KEY")), "OUTBOX_ENCRYPTION_KEY must be a valid Fernet key.")
    require(get("OUTBOX_ENCRYPTION_KEY") not in {get("AUTH_SECRET"), get("CRON_SECRET")}, "Outbox, auth and cron keys must be different.")
    try:
        previous = json.loads(get("OUTBOX_PREVIOUS_ENCRYPTION_KEYS"))
        require(isinstance(previous, list) and len(previous) <= 10 and all(isinstance(key, str) and fernet_key(key) for key in previous), "OUTBOX_PREVIOUS_ENCRYPTION_KEYS must be a JSON array of valid Fernet keys (maximum 10).")
        if isinstance(previous, list) and all(isinstance(key, str) for key in previous):
            require(len(previous) == len(set(previous)) and get("OUTBOX_ENCRYPTION_KEY") not in previous, "Previous outbox keys must be distinct from each other and the current key.")
    except (ValueError, TypeError):
        require(False, "OUTBOX_PREVIOUS_ENCRYPTION_KEYS must be a JSON array of valid Fernet keys (maximum 10).")
    frontend = get("FRONTEND_URL").rstrip("/")
    require(https_url(frontend, origin=True), "FRONTEND_URL requires an external HTTPS origin without credentials, query or fragment.")
    require(get("NEXT_PUBLIC_WEB_URL").rstrip("/") == frontend, "NEXT_PUBLIC_WEB_URL must match the non-secret FRONTEND_URL.")
    try:
        origins = json.loads(get("TRUSTED_ORIGINS"))
        require(isinstance(origins, list) and 1 <= len(origins) <= 10 and all(isinstance(origin, str) and https_url(origin, origin=True) for origin in origins), "TRUSTED_ORIGINS requires 1 to 10 external HTTPS origins in a JSON array.")
        require(isinstance(origins, list) and frontend in [origin.rstrip("/") for origin in origins if isinstance(origin, str)], "TRUSTED_ORIGINS must include FRONTEND_URL.")
    except (ValueError, TypeError):
        require(False, "TRUSTED_ORIGINS requires 1 to 10 external HTTPS origins in a JSON array.")
    require(https_url(get("API_BASE_URL"), origin=True), "API_BASE_URL requires a non-secret external HTTPS origin.")
    require(get("ADMIN_BASE_PATH") == "/admin" and get("ADMIN_APP_URL") == frontend + "/admin", "Admin settings must use the same frontend origin and /admin path.")

    email = get("EMAIL_FROM")
    # The transport supports 'Display name <address>'; URL-style and newlines do not.
    match = re.fullmatch(r"(?:[^<>\r\n]+\s*<)?([^<>\s@]+@[^<>\s@]+)(?:>)?", email)
    require(bool(match and external_host(match.group(1).rsplit("@", 1)[1])) and ("<" in email) == (">" in email), "EMAIL_FROM must be a real sender address (optional display name).")
    provider = get("EMAIL_PROVIDER")
    require(provider in {"resend", "smtp"}, "EMAIL_PROVIDER must be resend or smtp; none/console are forbidden.")
    if provider == "resend":
        require(bool(get("RESEND_API_KEY")), "Resend delivery requires RESEND_API_KEY.")
    if provider == "smtp":
        require(external_host(get("SMTP_HOST")) and bool(get("SMTP_USERNAME")) and bool(get("SMTP_PASSWORD")), "SMTP delivery requires an external host and account credentials.")
        require((get("SMTP_STARTTLS").lower(), get("SMTP_TLS").lower()) in {("true", "false"), ("false", "true")}, "SMTP must enable exactly one of STARTTLS or TLS.")
    for key in ("SMTP_STARTTLS", "SMTP_TLS", "AI_ENABLED"):
        require(get(key).lower() in {"true", "false"}, f"{key} must be true or false.")
    require(not (get("SMTP_STARTTLS").lower() == "true" and get("SMTP_TLS").lower() == "true"), "SMTP_STARTTLS and SMTP_TLS cannot both be enabled.")

    storage = get("STORAGE_PROVIDER")
    require(storage in {"s3", "blob"}, "STORAGE_PROVIDER must be s3 or blob; ephemeral/local/no storage is forbidden.")
    if storage == "blob":
        require(blob_credentials_valid(get("BLOB_STORE_ID"), get("BLOB_READ_WRITE_TOKEN")), "Blob requires a valid store ID and matching server read-write token.")
    if storage == "s3":
        bucket = get("S3_BUCKET")
        require(bool(re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket)) and ".." not in bucket and not re.fullmatch(r"\d+\.\d+\.\d+\.\d+", bucket), "S3_BUCKET must be a valid private bucket name.")
        require(bool(re.fullmatch(r"[A-Za-z0-9-]{1,64}", get("S3_REGION"))), "S3_REGION is required.")
        require(not get("S3_ENDPOINT_URL") or https_url(get("S3_ENDPOINT_URL"), origin=True), "Custom S3_ENDPOINT_URL requires an external HTTPS origin.")
        require(get("S3_SSE") in {"AES256", "aws:kms"}, "S3_SSE must be AES256 or aws:kms.")
        require(get("S3_SSE") != "aws:kms" or bool(get("S3_KMS_KEY_ID")), "KMS encryption requires S3_KMS_KEY_ID.")
        require(bool(get("AWS_ACCESS_KEY_ID")) == bool(get("AWS_SECRET_ACCESS_KEY")), "AWS access-key fields must both be set or both empty for a configured native role.")
        require(not get("AWS_SESSION_TOKEN") or bool(get("AWS_ACCESS_KEY_ID")) and bool(get("AWS_SECRET_ACCESS_KEY")), "AWS_SESSION_TOKEN requires the matching access-key pair.")

    google = (get("GOOGLE_CLIENT_ID"), get("GOOGLE_CLIENT_SECRET"), get("GOOGLE_REDIRECT_URI"))
    require(not any(google) or all(google) and get("GOOGLE_REDIRECT_URI") == frontend + "/api/v1/auth/google/callback", "Google configuration must be empty or complete with the same-origin HTTPS callback.")
    require(get("AI_ENABLED").lower() != "true" or bool(get("AI_API_KEY")), "Enabled AI requires AI_API_KEY; choosing a provider and budget remains an operator decision.")
    require(1 <= len(get("AI_MODEL")) <= 100, "AI_MODEL must have 1 to 100 characters.")
    for key, (minimum, maximum) in INTEGER_RANGES.items():
        value = get(key)
        require(bool(re.fullmatch(r"[0-9]{1,10}", value)) and minimum <= int(value or "0") <= maximum, f"{key} is missing or outside its allowed integer range.")
    scheduler = get("OPERATOR_SCHEDULER")
    require(scheduler in {"external_worker", "vercel_cron", "qstash"}, "Select exactly one scheduler: external_worker, vercel_cron or qstash.")
    if scheduler == "qstash":
        try:
            qstash = urlsplit(get("QSTASH_URL"))
            require(https_url(get("QSTASH_URL"), origin=True) and qstash.hostname in {
                "qstash.upstash.io", "qstash-eu-central-1.upstash.io", "qstash-us-east-1.upstash.io",
            }, "QSTASH_URL requires an approved regional Upstash HTTPS origin.")
        except ValueError:
            require(False, "QSTASH_URL requires an approved regional Upstash HTTPS origin.")
        require(len(get("QSTASH_TOKEN")) >= 16 and not any(character.isspace() for character in get("QSTASH_TOKEN")), "QStash scheduler requires a private API token.")
        require(get("QSTASH_TOKEN") not in {get("AUTH_SECRET"), get("CRON_SECRET")}, "QStash, auth and cron keys must be different.")
    return list(dict.fromkeys(issues))


def _private_acl(descriptor: int, target: Path) -> None:
    """Restrict access before writing any secret bytes; never show CLI outputs."""
    if os.name != "nt":
        os.fchmod(descriptor, 0o600)
        return
    # Use the current Windows SID, not a name susceptible to domain ambiguity.
    result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, timeout=15)
    sid_match = re.search(rb"S-1-[0-9-]+", result.stdout)
    if result.returncode or sid_match is None:
        raise ConfigError("Unable to determine the current Windows identity.")
    sid = sid_match.group().decode("ascii")
    result = subprocess.run(["icacls", str(target), "/inheritance:r", "/grant:r", "*" + sid + ":(F)"], capture_output=True, timeout=15)
    if result.returncode:
        raise ConfigError("Unable to restrict configuration file permissions.")


def generate_config(target: Path) -> None:
    """Exclusive file creation. No worker copy; unfinished templates fail validate."""
    # All outputs must use the existing repository-wide .env.*.local ignore rule.
    if not re.fullmatch(r"\.env\.[A-Za-z0-9_-]+\.local", target.name):
        raise ConfigError("Output filename must use .env.<name>.local to keep credentials ignored by Git.")
    target = target.absolute()
    if target.is_symlink() or target.exists():
        raise ConfigError("Output already exists; configuration is never overwritten.")
    if not target.parent.is_dir():
        raise ConfigError("Output parent directory must already exist.")
    # Do not follow a substituted final path; parent directories are operator chosen.
    replacements = {
        "AUTH_SECRET": secrets.token_hex(48),
        "OUTBOX_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
        "CRON_SECRET": secrets.token_hex(48),
    }
    try:
        template = Path(__file__).with_name(".env.vercel.example").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        raise ConfigError("Vercel example template is unavailable.") from None
    content = "\n".join(
        f"{line.split('=', 1)[0]}={replacements[line.split('=', 1)[0]]}"
        if line.split("=", 1)[0] in replacements else line
        for line in template.splitlines()
    ) + "\n"
    descriptor = -1
    created = False
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        created = True
        _private_acl(descriptor, target)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            descriptor = -1
            output.write(content)
    except FileExistsError:
        raise ConfigError("Output already exists; configuration is never overwritten.") from None
    except Exception:
        if descriptor != -1:
            os.close(descriptor)
        if created:
            try:
                target.unlink()
            except OSError:
                pass
        raise ConfigError("Private configuration creation failed; inspect the chosen output directory manually.") from None


def main(argv: list[str] | None = None) -> int:
    class SanitizedParser(argparse.ArgumentParser):
        def error(self, message: str) -> None:
            # argparse's default error embeds unrecognized arguments. Values may
            # have been passed by mistake: show only a fixed message and usage.
            self.print_usage()
            self.exit(2, "Invalid command arguments; use generate --output or validate --env-file.\n")

    parser = SanitizedParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    generate = commands.add_parser("generate", help="Create a NEW private template; never overwrite/upload.")
    generate.add_argument("--output", required=True, type=Path)
    validate = commands.add_parser("validate", help="Check only an explicit file offline; never contact providers.")
    validate.add_argument("--env-file", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.mode == "generate":
            generate_config(args.output)
            print("Private template created. Fresh auth, outbox and cron keys were written only to the private file.")
            print("Fill resource settings. Arrange scheduler budget and private-storage review manually. Reuse the same keys for its external worker; do not generate another set.")
            print("No provider, account, paid resource, deployment, worker or environment upload was created.")
            return 0
        issues = validate_config(read_env(args.env_file))
        if issues:
            for issue in issues:
                print("INVALID: " + issue)
            print("Offline validation failed; no configuration values were printed or sent.")
            return 1
        print("VALID: offline Vercel configuration gates passed; no service was contacted.")
        print("Live DNS, TLS certificates, PostgreSQL access, private IAM, sender verification, budget enforcement, scheduler freshness and MFA enrollment remain manual.")
        print("A scheduler choice is configuration only. Budget approval and private-storage inspection are separate; this command does not authorize publication.")
        return 0
    except ConfigError as error:
        print("INVALID: " + str(error))
        return 1
    except Exception:
        # Includes third-party exceptions if dependencies change later. Never show
        # repr/traceback/Pydantic errors: they may contain URLs or credential values.
        print("INVALID: Unable to process configuration; input values are hidden.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
