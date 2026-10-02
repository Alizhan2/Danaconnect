"""Plan one production QStash schedule; activation requires explicit operator flags.

No network access occurs without BOTH --apply and --deployment-ready. The default
plan reads no configuration. An explicit --env-file may be validated offline.
This module never imports application Settings, merges ambient credentials,
provisions a resource, probes the destination, or prints provider responses.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from vercel_config import ConfigError, PLACEHOLDER, https_url, read_env, validate_config


SCHEDULE_ID = "danaconnect-production-jobs"
CRON = "*/2 * * * *"
JOBS_PATH = "/api/v1/internal/jobs"
# Exact provider endpoints only; never accept an arbitrary *.upstash.io host.
QSTASH_HOSTS = frozenset({
    "qstash.upstash.io",
    "qstash-eu-central-1.upstash.io",
    "qstash-us-east-1.upstash.io",
})
MAX_RESPONSE_BYTES = 65536
UNKNOWN_RESULT = (
    "Schedule activation was not confirmed. It may already exist; review "
    "danaconnect-production-jobs in the provider console before retrying. "
    "Provider responses and internal exception details were suppressed."
)


class OperatorError(ValueError):
    """Only fixed sanitized messages may be constructed here."""


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid arguments. Use --help for supported options.\n")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OperatorError("Provider redirects are forbidden; activation was not confirmed.")


@dataclass(frozen=True)
class ScheduleConfig:
    base_url: str
    destination: str
    token: str = field(repr=False)
    cron_secret: str = field(repr=False)


def validate(values: dict[str, str]) -> ScheduleConfig:
    """Validate explicit values without DNS, sockets or application imports."""
    if (values.get("ENVIRONMENT") != "production"
            or values.get("VERCEL", "").lower() != "true"
            or values.get("DEMO_MODE", "").lower() != "false"
            or values.get("AUTH_DEBUG_CODE", "").lower() != "false"):
        raise OperatorError("Explicit Vercel production settings with demo and debug disabled are required.")
    if values.get("OPERATOR_SCHEDULER") != "qstash":
        raise OperatorError("OPERATOR_SCHEDULER must explicitly select qstash.")
    frontend = values.get("FRONTEND_URL", "")
    if not https_url(frontend, origin=True) or urlsplit(frontend).port not in {None, 443}:
        raise OperatorError("FRONTEND_URL must be an external HTTPS origin on the standard port.")
    if PLACEHOLDER.search(frontend):
        raise OperatorError("FRONTEND_URL must contain the actual deployed production origin.")
    try:
        origins = json.loads(values.get("TRUSTED_ORIGINS", ""))
    except (TypeError, ValueError):
        raise OperatorError("TRUSTED_ORIGINS must contain the production frontend origin.") from None
    origin = frontend.rstrip("/")
    if not isinstance(origins, list) or origin not in origins:
        raise OperatorError("TRUSTED_ORIGINS must contain the production frontend origin.")
    base_url = values.get("QSTASH_URL", "")
    parsed = urlsplit(base_url)
    if (not https_url(base_url, origin=True)
            or parsed.hostname not in QSTASH_HOSTS
            or parsed.port not in {None, 443}
            or parsed.netloc not in QSTASH_HOSTS):
        raise OperatorError("QSTASH_URL must exactly match an approved HTTPS QStash endpoint.")
    token = values.get("QSTASH_TOKEN", "")
    if (len(token) < 16 or not re.fullmatch(r"[\x21-\x7e]+", token)
            or PLACEHOLDER.search(token)):
        raise OperatorError("A private provider-issued QSTASH_TOKEN is required.")
    cron_secret = values.get("CRON_SECRET", "")
    if (len(cron_secret) < 32 or not re.fullmatch(r"[A-Za-z0-9_-]+", cron_secret)
            or PLACEHOLDER.search(cron_secret)
            or cron_secret in {token, values.get("AUTH_SECRET"), values.get("OUTBOX_ENCRYPTION_KEY")}):
        raise OperatorError("CRON_SECRET must be a unique private key of at least 32 URL-safe characters.")
    return ScheduleConfig(base_url.rstrip("/"), origin + JOBS_PATH, token, cron_secret)


def provider_json(opener, request: Request) -> dict:
    """Bounded provider response, kept private; proxies and redirects are disabled."""
    try:
        with opener.open(request, timeout=15) as response:
            accepted = {200, 201} if request.get_method() == "POST" else {200}
            if response.status not in accepted:
                raise OperatorError(UNKNOWN_RESULT)
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        error.close()
        raise OperatorError(UNKNOWN_RESULT) from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise OperatorError(UNKNOWN_RESULT)
    try:
        result = json.loads(body)
    except (UnicodeError, ValueError):
        raise OperatorError(UNKNOWN_RESULT) from None
    if not isinstance(result, dict):
        raise OperatorError(UNKNOWN_RESULT)
    return result


def apply(config: ScheduleConfig) -> None:
    """Explicit activation/upsert, then inspect only fixed non-secret fields."""
    opener = build_opener(ProxyHandler({}), NoRedirects())
    authorization = "Bearer " + config.token
    headers = {
        "Authorization": authorization,
        "User-Agent": "Codex-DanaConnect-Operator/1.0",
        "Content-Type": "text/plain",
        "Upstash-Schedule-Id": SCHEDULE_ID,
        "Upstash-Cron": CRON,
        "Upstash-Method": "GET",
        "Upstash-Retries": "0",
        "Upstash-Redact-Fields": "header[Authorization]",
        "Upstash-Forward-Authorization": "Bearer " + config.cron_secret,
    }
    result = provider_json(opener, Request(
        # QStash parses the destination from the URL path and requires its
        # http(s) scheme verbatim. The origin has already been validated above.
        config.base_url + "/v2/schedules/" + config.destination,
        data=b"", headers=headers, method="POST",
    ))
    if result.get("scheduleId") != SCHEDULE_ID:
        raise OperatorError(UNKNOWN_RESULT)
    observed = provider_json(opener, Request(
        config.base_url + "/v2/schedules/" + SCHEDULE_ID,
        headers={"Authorization": authorization, "User-Agent": "Codex-DanaConnect-Operator/1.0"},
        method="GET",
    ))
    if (observed.get("scheduleId") != SCHEDULE_ID
            or observed.get("cron") != CRON
            or observed.get("method") != "GET"
            or observed.get("destination") != config.destination
            or type(observed.get("retries")) is not int
            or observed.get("retries") != 0
            or observed.get("isPaused") is not False
            or observed.get("callback") or observed.get("failureCallback")):
        raise OperatorError(UNKNOWN_RESULT)


def print_plan() -> None:
    print("OFFLINE PLAN: no provider or destination connection has been opened.")
    print("Stable schedule: danaconnect-production-jobs (upsert, never a generated second ID).")
    print("Every 2 minutes; GET FRONTEND_URL/api/v1/internal/jobs; retries=0.")
    print("Private CRON_SECRET is forwarded as Bearer authorization; the Authorization header is redacted.")
    print("720 scheduled delivery attempts per day; provider quota is shared with other traffic.")
    print("Activation requires --apply, --deployment-ready and --env-file.")
    print("Deployment acknowledgement is an operator assertion, not a live endpoint check.")


def main() -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="Explicit private production dotenv file; no ambient values are merged.")
    parser.add_argument("--apply", action="store_true", help="Create or update the stable active production schedule.")
    parser.add_argument("--deployment-ready", action="store_true", help="Acknowledge that the exact production endpoint is deployed and ready for jobs.")
    args = parser.parse_args()
    try:
        if args.deployment_ready and not args.apply:
            raise OperatorError("--deployment-ready is only valid together with --apply.")
        if args.apply and (not args.deployment_ready or args.env_file is None):
            raise OperatorError("Activation requires --apply, --deployment-ready and --env-file.")
        print_plan()
        config = None
        if args.env_file is not None:
            values = read_env(args.env_file)
            config = validate(values)
            print("Explicit schedule configuration passed offline checks; values were not printed.")
            if args.apply and validate_config(values):
                raise OperatorError("Complete production configuration, including email credentials, is required before activation.")
        if not args.apply:
            return 0
        apply(config)
        print("Provider confirms the stable active schedule with GET, 2-minute cadence and zero retries.")
        print("Job execution, email delivery and destination availability are separate confirmations.")
        return 0
    except (OperatorError, ConfigError) as error:
        # These classes are only constructed with fixed sanitized messages.
        print(str(error))
        return 1
    except KeyboardInterrupt:
        print(UNKNOWN_RESULT if args.apply else "Operator interrupted; no activation was requested.")
        return 130
    except Exception:
        print(UNKNOWN_RESULT if args.apply else "Offline schedule configuration could not be confirmed; internal details were suppressed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
