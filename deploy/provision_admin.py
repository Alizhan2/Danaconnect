"""Provision one additional administrator using an explicit private configuration.

Without --apply this command does not read configuration, import the API, connect
to a database or create an enrollment. It never sends an invitation email.
"""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
ENROLLMENTS = ROOT / "deploy" / "enrollments"


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid arguments. Use --help for supported options.\n")


def enrollment_path(value: Path) -> Path:
    path = value.absolute()
    path.relative_to(ENROLLMENTS)
    if not path.name.endswith(".enrollment.json"):
        raise ValueError()
    for ancestor in [path, *path.parents]:
        if ancestor == ROOT:
            break
        if ancestor.is_symlink() or ancestor.is_junction():
            raise ValueError()
    if path.exists():
        raise ValueError()
    path.resolve().relative_to(ENROLLMENTS.resolve())
    return path


def main() -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--email")
    parser.add_argument("--name")
    parser.add_argument("--secret-output", type=Path,
                        help="New *.enrollment.json inside deploy/enrollments")
    parser.add_argument("--no-qr", action="store_true", help="Explicitly use manual MFA enrollment without a QR image")
    args = parser.parse_args()
    if not args.apply:
        print("Additional administrators have full admin permissions and require MFA.")
        print("No configuration read, database access, account creation or email performed.")
        print("Use --apply with --env-file, --email, --name and --secret-output after owner authorization.")
        return 0
    if args.env_file is None or not args.email or not args.name or args.secret_output is None:
        print("Apply requires an explicit private configuration, email, name and enrollment output.")
        return 2
    try:
        output = enrollment_path(args.secret_output)
        if not args.no_qr:
            if not importlib.util.find_spec("qrcode") or not importlib.util.find_spec("PIL"):
                print("Install deploy/requirements.operator.txt before provisioning with QR enrollment.")
                return 2
            if output.with_suffix(".png").exists():
                print("QR output already exists. Choose a new enrollment destination.")
                return 2
        from migrate_external import migration_chain, private_environment
        from vercel_config import read_env
        values = read_env(args.env_file.resolve())
        if (values.get("ENVIRONMENT") != "production"
                or values.get("DEMO_MODE", "").lower() != "false"
                or values.get("AUTH_DEBUG_CODE", "").lower() != "false"):
            raise ValueError()
        environment = private_environment(values, migration_chain())
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="danaconnect-admin-") as isolated:
            result = subprocess.run(
                [sys.executable, "-m", "app.admin_bootstrap", "--email", args.email,
                 "--name", args.name, "--secret-output", str(output)],
                cwd=isolated, env=environment, capture_output=True, timeout=60,
            )
        if result.returncode != 0:
            print("Administrator creation was not confirmed. Review the account and output before retrying.")
            print("Existing participant accounts and administrators with MFA are not overwritten.")
            return 1
        print("Administrator provisioned with MFA. Private enrollment saved at the requested location.")
        if not args.no_qr:
            try:
                from enrollment_qr import export_qr
                export_qr(output)
                print("Private QR enrollment created next to the JSON file.")
            except Exception:
                print("Administrator exists, but QR export was not confirmed. Use the saved enrollment with enrollment_qr.py.")
                return 1
        print("Share it privately with this administrator only; no email was sent.")
        return 0
    except KeyboardInterrupt:
        print("Operator interrupted. Review account state before retrying.")
        return 130
    except Exception:
        print("Operation was not confirmed. Check configuration, account and enrollment destination before retrying.")
        print("Private values and internal exception output were suppressed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
