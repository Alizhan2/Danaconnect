"""Create a private deployment template; does not connect to any service."""
import argparse
import base64
import getpass
import os
from pathlib import Path
import secrets
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = args.output.resolve()
    template = Path(__file__).with_name(".env.production.example").read_text(encoding="utf-8")
    replacements = {
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "AUTH_SECRET": secrets.token_hex(48),
        "OUTBOX_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "CRON_SECRET": secrets.token_hex(48),
    }
    content = "\n".join(f"{line.split('=', 1)[0]}={replacements[line.split('=', 1)[0]]}" if line.split("=", 1)[0] in replacements else line for line in template.splitlines()) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == "nt":
            identity = os.environ.get("USERDOMAIN", "") + "\\" + getpass.getuser()
            result = subprocess.run(["icacls", str(target), "/inheritance:r", "/grant:r", identity + ":(F)"], capture_output=True)
            if result.returncode:
                raise RuntimeError("Unable to restrict file permissions")
        else:
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            descriptor = -1
            file.write(content)
    except Exception:
        if descriptor != -1:
            os.close(descriptor)
        target.unlink(missing_ok=True)
        raise
    print("Private configuration created. Complete domain, verified email and private storage settings before launch.")
    print("Secrets were written to the requested file and were not printed.")


if __name__ == "__main__":
    main()
