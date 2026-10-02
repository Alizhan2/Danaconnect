"""Apply owner-approved directions as an audited offline operator.

Without --apply this reads only the public direction manifest. No config,
database, API login, email, demo seed or legal document publication occurs.
Existing directions with different names are never overwritten.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]

WORKER = '''
import json, sys
from sqlalchemy import select, text
from app.database import SessionLocal
from app.models import Direction, AuditEvent
from app.schemas.identity import DirectionInput
rows = [DirectionInput.model_validate(row) for row in json.load(sys.stdin)]
if any(not row.active for row in rows): raise ValueError()
if len({row.slug for row in rows}) != len(rows): raise ValueError()
result = []
with SessionLocal.begin() as db:
    db.execute(text("SELECT pg_advisory_xact_lock(824310770217)"))
    for row in rows:
        existing = db.scalar(select(Direction).where(Direction.slug == row.slug))
        if existing:
            if any(getattr(existing, key) != getattr(row, key) for key in ("name_ru", "name_kk", "name_en")):
                raise ValueError()
            if existing.active:
                result.append({"slug": row.slug, "status": "already_active"})
                continue
            existing.active = True
            action = "direction.updated"
        else:
            existing = Direction(**row.model_dump())
            db.add(existing)
            db.flush()
            action = "direction.created"
        db.add(AuditEvent(actor_id=None, action=action, entity_type="direction",
            entity_id=existing.id, detail={"source": "offline_operator", "slug": row.slug, "active": True}))
        result.append({"slug": row.slug, "status": "activated"})
print(json.dumps({"committed": True, "directions": result}))
'''


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid arguments; use --help.\n")


def main():
    parser = SafeParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--manifest", type=Path, default=ROOT / "deploy/pilot_directions.json")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    try:
        if args.manifest.stat().st_size > 32768:
            raise ValueError()
        rows = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or not 1 <= len(rows) <= 25 or not all(isinstance(row, dict) for row in rows):
            raise ValueError()
        if not args.apply:
            print("Offline plan: activate the owner-approved direction manifest.")
            print("No configuration, database or external service accessed.")
            return 0
        if args.env_file is None:
            raise ValueError()
        from migrate_external import migration_chain, private_environment
        from vercel_config import read_env
        values = read_env(args.env_file)
        if (values.get("ENVIRONMENT") != "production"
                or values.get("DEMO_MODE", "").lower() != "false"
                or values.get("AUTH_DEBUG_CODE", "").lower() != "false"):
            raise ValueError()
        env = private_environment(values, migration_chain())
        with tempfile.TemporaryDirectory(prefix="danaconnect-directions-") as isolated:
            result = subprocess.run([sys.executable, "-X", "utf8", "-c", WORKER],
                input=json.dumps(rows), text=True, encoding="utf-8", cwd=isolated,
                env=env, capture_output=True, timeout=60)
        if result.returncode:
            raise ValueError()
        summary = json.loads(result.stdout)
        if summary.get("committed") is not True:
            raise ValueError()
        print(json.dumps(summary))
        return 0
    except Exception:
        print("Direction activation unconfirmed. Raw configuration and database diagnostics hidden.")
        print("Inspect current direction state before retrying; no existing names are overwritten.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
